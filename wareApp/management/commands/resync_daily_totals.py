"""Set daily readings to the sum of their hourly readings.

Before the consumption fix the day's total was "previous total + packet
units" and was re-summed only at the hour change, so it drifted away from
the hourly rows. This sets ``unit_consumption`` to the day's hourly sum and
``energy_saved`` to ``daily_baseline_value - total`` (the live rule) for
every daily row that differs. Only days whose hourly rows are complete are
changed (all 24 hours; today: every hour up to the previous one): with
missing hours the sum would undercount, so those days are left alone and
counted as "incomplete" (``--include-incomplete`` changes them too).
Days with an implausible hourly value (meter glitch: over MAX_HOURLY_KWH,
or over GLITCH_FACTOR x the hour's baseline) are never changed; they are
listed so the hourly row can be checked by hand.
Dry run by default: prints what would change per site.

    python manage.py resync_daily_totals --from 2026-10-01 --to 2026-10-20 [--site 125] [--apply]
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate

from wareApp.models import AisleGroup, DailySiteReading, HourlySiteReading, Site

BATCH = 2000
# Differences below this (kWh) are float noise, not drift.
TOLERANCE = 0.001
MAX_HOURLY_KWH = 10000
GLITCH_FACTOR = 100


class Command(BaseCommand):
    help = "Set daily readings to the sum of their hourly readings (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
        parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD (inclusive)")
        parser.add_argument("--site", type=int, action="append", help="Site id (repeatable)")
        parser.add_argument(
            "--include-incomplete",
            action="store_true",
            help="Also change days with missing hourly rows",
        )
        parser.add_argument("--apply", action="store_true", help="Write the changes")

    def handle(
        self, *args, date_from, date_to, site=None, apply=False,
        include_incomplete=False, **options,
    ):
        try:
            first = datetime.strptime(date_from, "%Y-%m-%d").date()
            last = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError as error:
            raise CommandError(str(error)) from error
        start = datetime.combine(first, datetime.min.time())
        end = datetime.combine(last + timedelta(days=1), datetime.min.time())

        now = datetime.now()

        def complete(day, hours):
            if day < now.date():
                return hours >= 24
            return hours >= now.hour  # the current hour may still be open

        sites = Site.objects.all() if not site else Site.objects.filter(id__in=site)
        total_rows = total_changed = total_incomplete = total_glitch = 0
        raised = lowered = 0
        for site_obj in sites.order_by("id"):
            hourly = {
                (str(item["leg_id"]), item["day"]): (item["total"] or 0.0, item["hours"])
                for item in HourlySiteReading.objects.filter(
                    associated_Site=site_obj, reading_from__gte=start, reading_from__lt=end
                )
                .annotate(day=TruncDate("reading_from"))
                .values("leg_id", "day")
                .annotate(
                    total=Sum("unit_consumption"),
                    hours=Count("reading_from", distinct=True),
                )
                .order_by()
            }
            if not hourly:
                continue
            glitches = {}
            for row in HourlySiteReading.objects.filter(
                Q(unit_consumption__gt=MAX_HOURLY_KWH)
                | Q(
                    hourly_baseline_value__gt=0,
                    unit_consumption__gt=F("hourly_baseline_value") * GLITCH_FACTOR,
                ),
                associated_Site=site_obj,
                reading_from__gte=start,
                reading_from__lt=end,
            ).only("id", "leg_id", "reading_from", "unit_consumption"):
                glitches.setdefault((str(row.leg_id), row.reading_from.date()), row)
            changed, per_leg, biggest = [], defaultdict(int), 0.0
            seen = 0
            for row in DailySiteReading.objects.filter(
                associated_Site=site_obj, reading_for__gte=first, reading_for__lte=last
            ).only("id", "leg_id", "reading_for", "unit_consumption", "energy_saved",
                   "daily_baseline_value"):
                seen += 1
                found = hourly.get((str(row.leg_id), row.reading_for))
                if found is None:
                    continue
                total, hours = found
                saved = (row.daily_baseline_value or 0.0) - total
                if (
                    abs((row.unit_consumption or 0.0) - total) <= TOLERANCE
                    and row.energy_saved is not None
                    and abs(row.energy_saved - saved) <= TOLERANCE
                ):
                    continue
                glitch = glitches.get((str(row.leg_id), row.reading_for))
                if glitch is not None:
                    total_glitch += 1
                    self.stdout.write(
                        f"site {site_obj.id} leg {row.leg_id} {row.reading_for}: left alone, "
                        f"implausible hourly value {glitch.unit_consumption:.3f} kWh at "
                        f"{glitch.reading_from:%H:%M} (hourly row id {glitch.id})"
                    )
                    continue
                if not include_incomplete and not complete(row.reading_for, hours):
                    total_incomplete += 1
                    continue
                biggest = max(biggest, abs((row.unit_consumption or 0.0) - total))
                if total > (row.unit_consumption or 0.0) + TOLERANCE:
                    raised += 1
                elif total < (row.unit_consumption or 0.0) - TOLERANCE:
                    lowered += 1
                row.unit_consumption = total
                row.energy_saved = saved
                changed.append(row)
                per_leg[str(row.leg_id)] += 1

            total_rows += seen
            total_changed += len(changed)
            if not changed:
                continue
            names = dict(
                AisleGroup.objects.filter(site=site_obj).values_list(
                    "attached_leg_id", "aisleGroupName"
                )
            )
            legs = ", ".join(
                f"{leg} ({names.get(leg, '?')}): {count}"
                for leg, count in sorted(per_leg.items())
            )
            self.stdout.write(
                f"site {site_obj.id} {site_obj.site_name}: {len(changed)} rows, "
                f"largest change {biggest:.3f} kWh -> {legs}"
            )
            if apply:
                started = time.perf_counter()
                with transaction.atomic():
                    DailySiteReading.objects.bulk_update(
                        changed, ["unit_consumption", "energy_saved"], batch_size=BATCH
                    )
                self.stdout.write(
                    f"BULK UPDATE DailySiteReading: site={site_obj.id} rows={len(changed)} "
                    f"period=[{first} -> {last}] "
                    f"duration={(time.perf_counter() - started) * 1000:.1f} ms"
                )

        action = "updated" if apply else "would update (dry run, use --apply)"
        self.stdout.write(
            f"checked {total_rows} daily rows; {action} {total_changed} "
            f"(total raised {raised}, lowered {lowered}, saving only {total_changed - raised - lowered}); "
            f"left alone {total_incomplete} days with missing hourly rows "
            f"and {total_glitch} days with an implausible hourly value"
        )
