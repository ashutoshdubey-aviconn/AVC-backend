"""Process stored MQTT dead letters again (dry run unless --apply).

Each unresolved MqttDeadLetter is sent through the same handler a live packet
uses. Rows whose replay stores (or deliberately skips) the packet are marked
resolved; rows that fail again stay open (the handler logs and, for new
errors, stores a fresh dead letter).

    python manage.py replay_dead_letters --type LoadData --since "2026-10-20 16:40" --until "2026-10-20 16:45"
    python manage.py replay_dead_letters --type LoadData --since ... --apply

Order matters for some types: a late consumption / load / SupplyTime packet
can overwrite a newer total with an older one, so those types are replayed
only with --allow-ordered-types. LoadData (append-only raw readings) and the
recovery replies (idempotent slot upserts) are safe in any order.

LoadData rollups: minute/hour buckets that had no reading at all are built by
the next live packet if the replay happens within LOAD_DATA_ROLLUP_LOOKBACK_MINUTES
(default 6 h); buckets that already exist are not recomputed.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from wareApp.models import MqttDeadLetter
from wareApp.mqtt.services import idempotency

SAFE_TYPES = {
    "LoadData",
    "recovery/hourlyConsumption",
    "recovery/dailyConsumption",
    "recovery/loadRuntime",
}
ORDERED_TYPES = {"consumption", "load", "SupplyTime", "FIREALARM"}


def _parse_time(value, name):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise CommandError(f"--{name}: use YYYY-MM-DD[ HH:MM[:SS]]")


def replay(row):
    """Run one dead letter through its handler; return the outcome text.

    Calls the handlers directly (not the Celery task wrappers, which close the
    database connection after every packet).
    """
    from wareApp.load_data import handle_load_data_message
    from wareApp.mqtt.registry import handler_for
    from wareApp.tasks import _site_for_queued_message

    site = _site_for_queued_message(row.site_id, row.gateway_id, row.message_type)
    if site is None:
        return f"failed: unknown site {row.site_id}"
    if row.message_type == "LoadData":
        return handle_load_data_message(
            None, site, row.site_id, row.gateway_id, row.payload, ["LoadData"]
        )
    message_type, _, subtype = row.message_type.partition("/")
    handler = handler_for(message_type, subtype or None)
    if handler is None:
        return f"failed: no handler for {row.message_type}"
    # A failed packet keeps its duplicate-check key; free it so the replay
    # is not skipped as "already processed".
    idempotency.release(
        idempotency.message_key(handler.name, row.site_id, row.gateway_id, row.payload)
    )
    return handler.handle(site, row.site_id, row.gateway_id, row.payload)


class Command(BaseCommand):
    help = "Replay stored MQTT dead letters (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--type", dest="types", action="append",
                            help="message_type, e.g. LoadData (repeatable)")
        parser.add_argument("--site", type=int, action="append", help="Site id (repeatable)")
        parser.add_argument("--since", help="created at or after (YYYY-MM-DD[ HH:MM[:SS]])")
        parser.add_argument("--until", help="created before")
        parser.add_argument("--id", dest="ids", type=int, action="append", help="Dead letter id")
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--allow-ordered-types", action="store_true",
                            help="Also replay consumption/load/SupplyTime/FIREALARM (see docstring)")
        parser.add_argument("--apply", action="store_true", help="Replay (default: only list)")

    def handle(self, *args, types=None, site=None, since=None, until=None, ids=None,
               limit=5000, allow_ordered_types=False, apply=False, **options):
        rows = MqttDeadLetter.objects.filter(is_resolved=False).order_by("created_at", "id")
        if types:
            rows = rows.filter(message_type__in=types)
        if site:
            rows = rows.filter(site_id__in=site)
        if since:
            rows = rows.filter(created_at__gte=_parse_time(since, "since"))
        if until:
            rows = rows.filter(created_at__lt=_parse_time(until, "until"))
        if ids:
            rows = rows.filter(id__in=ids)
        rows = list(rows[:limit])

        blocked = sorted({r.message_type for r in rows if r.message_type in ORDERED_TYPES})
        if blocked and not allow_ordered_types:
            raise CommandError(
                f"{', '.join(blocked)} dead letters are order-sensitive; filter them out "
                "with --type or pass --allow-ordered-types"
            )
        unknown = sorted({r.message_type for r in rows} - SAFE_TYPES - ORDERED_TYPES)
        if unknown:
            raise CommandError(f"No replay route for: {', '.join(unknown)}")

        by_type = {}
        for row in rows:
            by_type[row.message_type] = by_type.get(row.message_type, 0) + 1
        self.stdout.write(
            f"{len(rows)} unresolved dead letters: "
            + (", ".join(f"{t}={n}" for t, n in sorted(by_type.items())) or "none")
        )
        if not apply:
            for row in rows[:20]:
                self.stdout.write(
                    f"  #{row.id} {row.created_at:%Y-%m-%d %H:%M:%S} {row.message_type} "
                    f"site={row.site_id} gw={row.gateway_id} error={row.error[:80]}"
                )
            self.stdout.write("dry run: nothing replayed (use --apply)")
            return

        resolved = failed = 0
        for row in rows:
            outcome = replay(row)
            text = str(outcome or "")
            if text.startswith(("stored", "skipped")):
                MqttDeadLetter.objects.filter(pk=row.pk).update(is_resolved=True)
                resolved += 1
            else:
                failed += 1
                self.stdout.write(f"  #{row.id} still failing: {text[:120]}")
        self.stdout.write(f"replayed {len(rows)}: resolved {resolved}, still failing {failed}")
