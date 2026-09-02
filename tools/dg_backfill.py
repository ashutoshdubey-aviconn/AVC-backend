#!/usr/bin/env python3
"""DG backfill / reconciliation runner (dry-run by default).

Usage examples:
  # dry-run, scan site 35 and write audit files
  ./virtualwarehouse/bin/python3 tools/dg_backfill.py --site 35

  # actually apply deletions (requires --apply)
  ./virtualwarehouse/bin/python3 tools/dg_backfill.py --site 35 --apply --chunk-size 500

Notes:
- This script is intentionally conservative: do not run with --apply unless you
  have backups and have run a dry-run first. Audit files will be written to
  `logs/dg_backfill/` by default.
"""

import os
import sys
import json
import argparse
from datetime import datetime

# bootstrap django
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()

from django.db import transaction
from django.db.models import Count
from wareApp.models import DgFuelConsumptionData, Site
from wareApp.dg_fuel.dedupe import dedupe_dg_consumption


def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def run_backfill(
    site_id=None,
    vehicle=None,
    start_epoch=None,
    end_epoch=None,
    chunk_size=500,
    limit=None,
    apply=False,
    audit_dir="logs/dg_backfill",
):
    ensure_dir(audit_dir)

    qs = DgFuelConsumptionData.objects.all()
    if site_id:
        qs = qs.filter(site_id=site_id)
    if vehicle:
        qs = qs.filter(vehicle_number=vehicle)

    groups_qs = (
        qs.values("site_id", "vehicle_number", "epoch_time")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1)
    )

    groups = list(groups_qs)
    if start_epoch or end_epoch:
        # filter by numeric epoch bounds if provided
        def epoch_in_range(g):
            try:
                e = int(g.get("epoch_time") or 0)
            except Exception:
                return False
            if start_epoch and e < int(start_epoch):
                return False
            if end_epoch and e > int(end_epoch):
                return False
            return True

        groups = [g for g in groups if epoch_in_range(g)]

    total_groups = len(groups)
    print(f"Found {total_groups} duplicate groups to inspect")
    if total_groups == 0:
        return {"scanned": 0, "removed": 0}

    processed = 0
    removed_total = 0
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    for chunk_idx, grp_chunk in enumerate(chunked(groups, chunk_size)):
        print(
            f"Processing chunk {chunk_idx+1}/{(total_groups+chunk_size-1)//chunk_size} ({len(grp_chunk)} groups)"
        )
        for g in grp_chunk:
            if limit and processed >= limit:
                break
            site_id = g.get("site_id")
            vehicle_number = g.get("vehicle_number")
            epoch_time = g.get("epoch_time")

            # load rows (ordered by id to keep the earliest)
            rows_qs = DgFuelConsumptionData.objects.filter(
                site_id=site_id, vehicle_number=vehicle_number, epoch_time=epoch_time
            ).order_by("id")
            rows = list(rows_qs)
            if len(rows) <= 1:
                processed += 1
                continue

            pre = [
                {
                    "id": r.id,
                    "site_id": r.site_id,
                    "vehicle_number": r.vehicle_number,
                    "epoch_time": r.epoch_time,
                    "fuel_consumption": r.fuel_consumption,
                    "fuel_data_source": r.fuel_data_source,
                    "created": r.created.isoformat() if r.created else None,
                }
                for r in rows
            ]

            audit_file_pre = os.path.join(
                audit_dir,
                f"pre_site{site_id}_veh{vehicle_number}_epoch{epoch_time}_{ts}.json",
            )
            with open(audit_file_pre, "w") as fh:
                json.dump({"group": g, "rows": pre}, fh, default=str, indent=2)

            deleted_count = 0
            kept_id = None
            if apply:
                # wrap each group's deletion in a transaction for safety
                try:
                    with transaction.atomic():
                        site_obj = None
                        try:
                            site_obj = Site.objects.get(pk=site_id) if site_id else None
                        except Site.DoesNotExist:
                            site_obj = None
                        # use the conservative dedupe helper
                        deleted_count = dedupe_dg_consumption(
                            site_obj, vehicle_number, epoch_time
                        )
                except Exception as exc:
                    print(f"Error while deduping group {g}: {exc}")
                    deleted_count = 0
                # refresh rows to capture post-state
                remaining = list(
                    DgFuelConsumptionData.objects.filter(
                        site_id=site_id,
                        vehicle_number=vehicle_number,
                        epoch_time=epoch_time,
                    ).order_by("id")
                )
                kept_id = remaining[0].id if remaining else None
            else:
                # dry-run: don't change DB, only report
                deleted_count = max(0, len(rows) - 1)
                kept_id = rows[0].id if rows else None

            post = {
                "kept_id": kept_id,
                "deleted_count": deleted_count,
            }
            audit_file_post = os.path.join(
                audit_dir,
                f"post_site{site_id}_veh{vehicle_number}_epoch{epoch_time}_{ts}.json",
            )
            with open(audit_file_post, "w") as fh:
                json.dump({"group": g, "result": post}, fh, default=str, indent=2)

            processed += 1
            removed_total += deleted_count

        if limit and processed >= limit:
            break

    print(f"Finished. groups_scanned={processed} duplicates_removed={removed_total}")
    return {"scanned": processed, "removed": removed_total}


def parse_args_and_run():
    parser = argparse.ArgumentParser(
        description="DG fuel duplicate backfill/reconciliation runner"
    )
    parser.add_argument("--site", type=int, help="Site id to scope the run (optional)")
    parser.add_argument(
        "--vehicle", type=str, help="Vehicle number to scope the run (optional)"
    )
    parser.add_argument(
        "--start-epoch", type=int, help="Start epoch (inclusive), in ms"
    )
    parser.add_argument("--end-epoch", type=int, help="End epoch (inclusive), in ms")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Number of groups to process per chunk",
    )
    parser.add_argument(
        "--limit", type=int, help="Limit number of groups to process (optional)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete duplicates. Without this flag the run is a dry-run",
    )
    parser.add_argument(
        "--audit-dir",
        type=str,
        default="logs/dg_backfill",
        help="Directory to write audit JSON files",
    )
    args = parser.parse_args()

    print("Starting DG backfill (dry-run unless --apply specified)")
    if args.apply:
        print(
            "WARNING: running with --apply will delete duplicate rows. Ensure you have backups."
        )

    res = run_backfill(
        site_id=args.site,
        vehicle=args.vehicle,
        start_epoch=args.start_epoch,
        end_epoch=args.end_epoch,
        chunk_size=args.chunk_size,
        limit=args.limit,
        apply=args.apply,
        audit_dir=args.audit_dir,
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    parse_args_and_run()
