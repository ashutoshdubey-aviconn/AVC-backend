"""Recompute hourly_baseline_value / energy_saved with the Phase C rule.

Recovered hours were stored with baseline 0. This fills them (and, with
``--all``, re-derives every row) using ``wareApp/mqtt/services/baseline.py``.
Dry run by default: prints what would change per site and leg.

    python manage.py rebuild_hourly_baseline --from 2026-09-01 --to 2026-10-20 [--site 125] [--all] [--apply]
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wareApp.models import AisleGroup, HourlySiteReading, Site
from wareApp.mqtt.services import site_cache
from wareApp.mqtt.services.baseline import BaselineMemo

BATCH = 2000


class Command(BaseCommand):
    help = "Recompute hourly baseline and saving for hourly readings (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
        parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD (inclusive)")
        parser.add_argument("--site", type=int, action="append", help="Site id (repeatable)")
        parser.add_argument(
            "--all", action="store_true", help="All rows, not only rows with baseline 0"
        )
        parser.add_argument("--apply", action="store_true", help="Write the changes")

    def handle(self, *args, date_from, date_to, site=None, all=False, apply=False, **options):
        try:
            start = datetime.strptime(date_from, "%Y-%m-%d")
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        except ValueError as error:
            raise CommandError(str(error)) from error

        sites = Site.objects.all() if not site else Site.objects.filter(id__in=site)
        total_rows = total_changed = 0
        for site_obj in sites.order_by("id"):
            aisles = {
                str(aisle.attached_leg_id): aisle
                for aisle in AisleGroup.objects.filter(site=site_obj)
            }
            # Legs without any baseline row are left alone (nothing to fill).
            no_baseline = sorted(
                leg for leg in aisles if not site_cache.baselines(site_obj.id, leg)
            )
            memos = {
                leg: BaselineMemo(site_obj, aisle)
                for leg, aisle in aisles.items()
                if leg not in no_baseline
            }
            rows = HourlySiteReading.objects.filter(
                associated_Site=site_obj, reading_from__gte=start, reading_from__lt=end
            )
            if not all:
                rows = rows.filter(hourly_baseline_value=0)

            changed, per_leg = [], defaultdict(int)
            seen = 0
            for row in rows.only(
                "id", "leg_id", "reading_from", "unit_consumption",
                "hourly_baseline_value", "energy_saved",
            ).iterator(chunk_size=BATCH):
                seen += 1
                memo = memos.get(str(row.leg_id))
                if memo is None:
                    continue
                hourly, _ = memo.for_day(row.reading_from.date())
                saved = (hourly - row.unit_consumption) if memo.aisle_group.is_active else 0.0
                if row.hourly_baseline_value == hourly and row.energy_saved == saved:
                    continue
                row.hourly_baseline_value = hourly
                row.energy_saved = saved
                changed.append(row)
                per_leg[row.leg_id] += 1

            total_rows += seen
            total_changed += len(changed)
            if no_baseline and seen:
                self.stdout.write(
                    f"site {site_obj.id}: skipped legs without a baseline: {', '.join(no_baseline)}"
                )
            if not changed:
                continue
            legs = ", ".join(
                f"{leg} ({getattr(aisles.get(str(leg)), 'aisleGroupName', '?')}): {count}"
                for leg, count in sorted(per_leg.items(), key=lambda item: str(item[0]))
            )
            self.stdout.write(f"site {site_obj.id} {site_obj.site_name}: {len(changed)} rows -> {legs}")
            if apply:
                started = time.perf_counter()
                with transaction.atomic():
                    HourlySiteReading.objects.bulk_update(
                        changed, ["hourly_baseline_value", "energy_saved"], batch_size=BATCH
                    )
                self.stdout.write(
                    f"BULK UPDATE HourlySiteReading: site={site_obj.id} rows={len(changed)} "
                    f"duration={(time.perf_counter() - started) * 1000:.1f} ms"
                )

        action = "updated" if apply else "would update (dry run, use --apply)"
        self.stdout.write(f"checked {total_rows} rows; {action} {total_changed}")
