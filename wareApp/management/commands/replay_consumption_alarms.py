"""Evaluate the daily consumption alarms day by day for a past period.

For every daily reading of the chosen sites and days this runs the same
function the live path runs when a new day starts
(``consumption_alarms.evaluate_daily_alarms``): Bypassed, High / Low
Consumption and Operation Hours Increased, with each site's thresholds and
baselines. An alarm is stored at most once per site, aisle, type and day, so
running it again never duplicates.

Dry run by default (everything is evaluated, then rolled back: nothing stored,
no e-mail). With --apply the alarms are stored, and e-mails are sent only for
the sites given with --email-site (at most --max-emails); alarms of the other
sites are stored without e-mail.

    python manage.py replay_consumption_alarms --from 2026-09-23 --to 2026-10-22
    python manage.py replay_consumption_alarms --from 2026-09-23 --to 2026-10-22 \\
        --email-site 183 --email-site 185 --report reports/alarm_replay.csv --apply
"""

import csv
from collections import Counter, defaultdict
from datetime import datetime
from unittest import mock

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wareApp.models import AisleGroup, DailySiteReading, Site
from wareApp.mqtt.services import consumption_alarms


class _MailGate:
    """Wraps notify(): only the chosen sites e-mail, up to a limit."""

    def __init__(self, real_notify, email_sites, max_emails, apply):
        self.real_notify = real_notify
        self.email_sites = set(email_sites)
        self.max_emails = max_emails
        self.apply = apply
        self.sent = 0
        self.suppressed = 0
        self.decisions = []  # one entry per notify() call, in order

    def __call__(self, send_function, title, site_id, details, *rest):
        wanted = site_id in self.email_sites
        if self.apply and wanted and self.sent < self.max_emails:
            self.sent += 1
            self.decisions.append("e-mail")
            return self.real_notify(send_function, title, site_id, details, *rest)
        if wanted and self.apply:
            self.suppressed += 1
            self.decisions.append("limit reached")
        else:
            self.decisions.append("e-mail (dry run)" if wanted else "no e-mail")
        return None


def _date(value, name):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"--{name}: use YYYY-MM-DD")


class Command(BaseCommand):
    help = "Replay daily consumption alarms day by day (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", required=True)
        parser.add_argument("--to", dest="date_to", required=True, help="inclusive")
        parser.add_argument("--site", type=int, action="append",
                            help="Site id (repeatable); default: all live sites")
        parser.add_argument("--email-site", type=int, action="append", default=[],
                            help="Sites whose alarms send e-mails (repeatable)")
        parser.add_argument("--max-emails", type=int, default=50)
        parser.add_argument("--report", help="Write one CSV row per alarm to this path")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, date_from, date_to, site=None, email_site=(), max_emails=50,
               report=None, apply=False, **options):
        first, last = _date(date_from, "from"), _date(date_to, "to")
        if last < first:
            raise CommandError("--to is before --from")
        sites = Site.objects.filter(id__in=site) if site else Site.objects.filter(is_live=True)
        sites = {s.id: s for s in sites.order_by("id")}
        aisles = {
            (a.site_id, str(a.attached_leg_id)): a
            for a in AisleGroup.objects.filter(site_id__in=sites)
        }
        readings = (
            DailySiteReading.objects.filter(
                associated_Site_id__in=sites, reading_for__gte=first, reading_for__lte=last
            )
            .order_by("reading_for", "associated_Site_id", "leg_id", "id")
        )

        gate = _MailGate(consumption_alarms.notify, email_site, max_emails, apply)
        rows, per_type, per_site = [], Counter(), defaultdict(Counter)
        evaluated = 0
        with transaction.atomic(), mock.patch.object(consumption_alarms, "notify", gate):
            for reading in readings.iterator(chunk_size=2000):
                aisle = aisles.get((reading.associated_Site_id, str(reading.leg_id)))
                if aisle is None:
                    continue
                site_obj = sites[reading.associated_Site_id]
                evaluated += 1
                start = len(gate.decisions)
                titles = consumption_alarms.evaluate_daily_alarms(site_obj, aisle, reading)
                decisions = gate.decisions[start:]
                for index, title in enumerate(titles):
                    per_type[title] += 1
                    per_site[(site_obj.id, site_obj.site_name)][title] += 1
                    rows.append({
                        "date": reading.reading_for,
                        "site_id": site_obj.id,
                        "site_name": site_obj.site_name,
                        "aisle_group": aisle.aisleGroupName,
                        "leg_id": aisle.attached_leg_id,
                        "alarm": title,
                        "consumption_kwh": round(reading.unit_consumption or 0, 2),
                        "daily_baseline_kwh": round(reading.daily_baseline_value or 0, 2),
                        "email": decisions[index] if index < len(decisions) else "-",
                    })
            if not apply:
                transaction.set_rollback(True)

        if report:
            with open(report, "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["date"])
                writer.writeheader()
                writer.writerows(rows)

        mode = "stored" if apply else "would store (dry run, nothing saved, no e-mail)"
        self.stdout.write(
            f"{first} .. {last}: {len(sites)} sites, {evaluated} aisle-days evaluated; "
            f"{mode} {len(rows)} alarms"
        )
        for title, count in per_type.most_common():
            self.stdout.write(f"  {title}: {count}")
        for (site_id, name), counts in sorted(per_site.items()):
            self.stdout.write(
                f"  site {site_id} {name}: "
                + ", ".join(f"{t.replace(' Alarm', '')} {n}" for t, n in counts.most_common())
            )
        if apply:
            self.stdout.write(
                f"e-mails queued: {gate.sent}"
                + (f" (limit {max_emails} reached, {gate.suppressed} not sent)" if gate.suppressed else "")
            )
        if report:
            self.stdout.write(f"report: {report}")
