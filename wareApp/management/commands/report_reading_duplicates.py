"""Report duplicate reading rows before unique constraints are added (M7).

Read-only. Lists, per table, how many (site, leg/source, slot) keys have more
than one row, with a few examples. Unique constraints on these keys can only
be added once the count is zero; how duplicates are merged (keep newest row?
keep the larger value?) is a business decision made from this report.

    python manage.py report_reading_duplicates [--since 2026-01-01] [--examples 5]
"""

from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models import Count

from wareApp.models import DailySiteReading, HourlySiteReading, SupplyLoadTimeShare

CHECKS = (
    ("HourlySiteReading", HourlySiteReading, ("associated_Site", "leg_id", "reading_from"), "reading_from"),
    ("DailySiteReading", DailySiteReading, ("associated_Site", "leg_id", "reading_for"), "reading_for"),
    ("SupplyLoadTimeShare", SupplyLoadTimeShare, ("site", "power_source", "reading_from"), "reading_from"),
)


class Command(BaseCommand):
    help = "Report duplicate hourly/daily/runtime reading keys (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--since", help="Only rows on/after this date (YYYY-MM-DD)")
        parser.add_argument("--examples", type=int, default=5)

    def handle(self, *args, since=None, examples=5, **options):
        since_value = datetime.strptime(since, "%Y-%m-%d") if since else None
        for label, model, key, slot_field in CHECKS:
            rows = model.objects.all()
            if since_value is not None:
                rows = rows.filter(**{f"{slot_field}__gte": since_value})
            duplicates = (
                rows.values(*key)
                .annotate(rows=Count("id"))
                .filter(rows__gt=1)
                .order_by("-rows")
            )
            total = duplicates.count()
            self.stdout.write(f"{label}: {total} duplicated key(s) on {', '.join(key)}")
            for item in duplicates[:examples]:
                self.stdout.write(f"    {item}")
