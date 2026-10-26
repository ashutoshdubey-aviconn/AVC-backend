#!/usr/bin/env python3
"""Recover Roadcast DG-fuel history without writing raw fuel-level rows.

This is a DG-only copy of roadcast_monthly_refuel_report.py.
It keeps the same day-by-day, site-by-site recovery flow for one year by
default, but it intentionally skips creating or updating raw fuel-level rows.

The script only reconciles:
- refuel alerts
- theft alerts
- DG unit consumption
- DG fuel consumed
- DG unit per litre
- correcting wrong existing values

Zero-valued refuel, theft, DG fuel, and DG per-litre results are ignored.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta

from django.db.models import Max

import roadcast_monthly_refuel_report as base

DEFAULT_LOOKBACK_DAYS = 365
DAILY_READING_DB_ALIAS = "default"


def _date_range(start_date, end_date):
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def _positive_value(value):
    numeric_value = base.as_float(value)
    if numeric_value is None or numeric_value <= 0:
        return None
    return numeric_value


def _skip_fuel_levels(site, vehicle_imei, report, dry_run):
    return {
        "counts": {
            "created": 0,
            "existing_correct": 0,
            "corrected": 0,
            "failed": 0,
            "skipped_invalid": 0,
            "skipped_zero": 0,
            "ambiguous": 0,
            "fetched": len(report.get("fuel_levels", []) or []),
        },
        "details": [],
    }


def _timestamp_update_fields(existing, *, epoch_ms):
    if existing is None or epoch_ms is None:
        return []

    epoch_time = str(epoch_ms)
    created_value = datetime.fromtimestamp(epoch_ms / 1000)
    current_epoch = str(getattr(existing, "epoch_time", "") or "")
    current_created = getattr(existing, "created", None)
    changes = []

    if current_epoch != epoch_time:
        existing.epoch_time = epoch_time
        changes.append("epoch_time")
    if current_created != created_value:
        existing.created = created_value
        changes.append("created")

    return changes


def _timestamp_fallback_query(
    model, *, site, vehicle_imei, alert_name=None, fuel_liters=None
):
    qs = model.objects.filter(site=site, vehicle_number=str(vehicle_imei))
    if alert_name is not None:
        qs = qs.filter(alert_name=alert_name)
    if fuel_liters is not None:
        qs = qs.filter(fuel_consumption=fuel_liters)
    return qs.order_by("-created", "-id")


def _daily_readings_dg_only(site, reading_date):
    return list(
        base.DailySiteReading.objects.using(DAILY_READING_DB_ALIAS)
        .filter(
            associated_Site=site,
            reading_for=reading_date,
            aisle_group__power_source__gte=1,
        )
        .exclude(aisle_group_id__isnull=True)
        .order_by("aisle_group_id", "id")
    )


def _last_available_daily_reading_date(site, start_date, end_date):
    return (
        base.DailySiteReading.objects.using(DAILY_READING_DB_ALIAS)
        .filter(
            associated_Site=site,
            reading_for__gte=start_date,
            reading_for__lte=end_date,
            aisle_group__power_source__gte=1,
        )
        .exclude(aisle_group_id__isnull=True)
        .aggregate(last_date=Max("reading_for"))
        .get("last_date")
    )


def _reconcile_alerts_dg_only(site, vehicle_imei, report, alert_name, events, dry_run):
    counts = base._init_item_counts(dry_run)
    counts["skipped_zero"] = 0
    details = []
    create_key = base._count_mode_key(dry_run, "created", "would_create")
    correct_key = base._count_mode_key(dry_run, "corrected", "would_correct")

    for event in events:
        counts["fetched"] += 1
        raw_fuel_value = base.as_float(event.get("fuel_liters"))
        fuel_liters = _positive_value(event.get("fuel_liters"))
        epoch_ms = base.epoch_milliseconds(event.get("epoch_ms"))
        if fuel_liters is None or epoch_ms is None:
            if raw_fuel_value == 0:
                counts["skipped_zero"] += 1
                details.append({"epoch_ms": epoch_ms, "status": "SKIPPED_ZERO"})
            else:
                counts["skipped_invalid"] += 1
                details.append({"epoch_ms": epoch_ms, "status": "SKIPPED_INVALID"})
            continue

        epoch_time = str(epoch_ms)
        existing_qs = base.DGFuelAlertsData.objects.filter(
            site=site,
            vehicle_number=str(vehicle_imei),
            alert_name=alert_name,
            epoch_time=epoch_time,
        ).order_by("id")
        if base._existing_exact_count(existing_qs) > 1:
            counts["ambiguous"] += 1
            details.append({"epoch_ms": epoch_ms, "status": "AMBIGUOUS"})
            continue

        existing = existing_qs.first()
        if existing is None:
            fallback_qs = _timestamp_fallback_query(
                base.DGFuelAlertsData,
                site=site,
                vehicle_imei=vehicle_imei,
                alert_name=alert_name,
                fuel_liters=fuel_liters,
            )
            fallback_existing = fallback_qs.first()
            if fallback_existing is not None:
                counts[correct_key] += 1
                details.append({"epoch_ms": epoch_ms, "status": correct_key.upper()})
                if not dry_run:
                    update_fields = []
                    if base.as_float(fallback_existing.fuel_consumption) != fuel_liters:
                        fallback_existing.fuel_consumption = fuel_liters
                        update_fields.append("fuel_consumption")
                    update_fields.extend(
                        field
                        for field in _timestamp_update_fields(
                            fallback_existing, epoch_ms=epoch_ms
                        )
                        if field not in update_fields
                    )
                    if update_fields:
                        fallback_existing.save(update_fields=update_fields)
                continue

            counts[create_key] += 1
            details.append({"epoch_ms": epoch_ms, "status": create_key.upper()})
            if dry_run:
                continue
            base.DGFuelAlertsData.objects.create(
                site=site,
                vehicle_number=str(vehicle_imei),
                alert_name=alert_name,
                fuel_consumption=fuel_liters,
                epoch_time=epoch_time,
                created=datetime.fromtimestamp(epoch_ms / 1000),
            )
            continue

        current_fuel = base.as_float(existing.fuel_consumption)
        identical = (
            current_fuel is not None
            and abs(current_fuel - fuel_liters) < 1e-9
            and str(existing.vehicle_number or "").strip() == str(vehicle_imei)
            and str(existing.alert_name or "").strip().lower() == alert_name
            and str(existing.epoch_time or "") == epoch_time
        )
        if identical:
            counts["existing_correct"] += 1
            details.append({"epoch_ms": epoch_ms, "status": "EXISTING_CORRECT"})
            continue

        counts[correct_key] += 1
        details.append({"epoch_ms": epoch_ms, "status": correct_key.upper()})
        if dry_run:
            continue

        update_fields = []
        if current_fuel != fuel_liters:
            existing.fuel_consumption = fuel_liters
            update_fields.append("fuel_consumption")
        update_fields.extend(
            field
            for field in _timestamp_update_fields(existing, epoch_ms=epoch_ms)
            if field not in update_fields
        )
        if update_fields:
            existing.save(update_fields=update_fields)

    return {"counts": counts, "details": details}


def _reconcile_units_and_fuel_dg_only(site, reading_date, report, dry_run):
    unit_counts = {
        "created": 0,
        "existing_correct": 0,
        "corrected": 0,
        "deferred_no_daily_reading": 0,
        "ignored_below_threshold": 0,
        "failed": 0,
        "unit_source_status": "NO_DAILY_READING",
        "details": [],
    }
    fuel_counts = {
        "updated": 0,
        "existing_correct": 0,
        "corrected": 0,
        "deferred_no_unit_row": 0,
        "skipped_zero": 0,
        "details": [],
    }

    authoritative_daily = _daily_readings_dg_only(site, reading_date)
    if not authoritative_daily:
        unit_counts["deferred_no_daily_reading"] = 1
        unit_counts["unit_source_status"] = "NO_DAILY_READING"
        fuel_counts["deferred_no_unit_row"] = 1
        return {
            "unit_counts": unit_counts,
            "fuel_counts": fuel_counts,
            "unit_rows_touched": [],
        }

    unit_counts["unit_source_status"] = base._unit_source_status_for_day(
        authoritative_daily
    )

    preexisting_units = {
        unit.aisle_group_id: unit for unit in base._daily_unit_rows(site, reading_date)
    }

    if not dry_run:
        base.reconcile_daily_unit_consumption(site, reading_date, return_details=True)

    post_units = {
        unit.aisle_group_id: unit for unit in base._daily_unit_rows(site, reading_date)
    }
    raw_fuel_consumed = base.as_float(report.get("fuel_consumed"))
    fuel_consumed = (
        raw_fuel_consumed
        if raw_fuel_consumed is not None and raw_fuel_consumed > 0
        else None
    )

    unit_rows_touched = []
    seen_aisles = set()

    for daily_row in authoritative_daily:
        aisle_id = daily_row.aisle_group_id
        if aisle_id in seen_aisles:
            continue
        seen_aisles.add(aisle_id)

        daily_value = _positive_value(daily_row.unit_consumption)
        if daily_value is None:
            unit_counts["ignored_below_threshold"] += 1
            unit_counts["details"].append(
                {"aisle_group_id": aisle_id, "status": "SKIPPED_ZERO"}
            )
            continue

        preexisting_unit = preexisting_units.get(aisle_id)
        if preexisting_unit is None:
            unit_counts["created"] += 1
            unit_status = "CREATED"
        else:
            current_value = base.as_float(preexisting_unit.unit_consumption)
            if current_value is not None and abs(current_value - daily_value) < 1e-9:
                unit_counts["existing_correct"] += 1
                unit_status = "EXISTING_CORRECT"
            else:
                unit_counts["corrected"] += 1
                unit_status = "CORRECTED"

        unit_row = post_units.get(aisle_id) if not dry_run else preexisting_unit

        if fuel_consumed is None:
            fuel_counts["skipped_zero"] += 1
            fuel_status = "SKIPPED_ZERO"
        else:
            if unit_row is None:
                fuel_counts["deferred_no_unit_row"] += 1
                fuel_status = "DEFERRED_NO_UNIT_ROW"
            else:
                current_fuel = base.as_float(unit_row.dg_fuel_consumption)
                if (
                    current_fuel is not None
                    and abs(current_fuel - fuel_consumed) < 1e-9
                ):
                    fuel_counts["existing_correct"] += 1
                    fuel_status = "EXISTING_CORRECT"
                elif preexisting_unit is None or current_fuel is None:
                    fuel_counts["updated"] += 1
                    fuel_status = "UPDATED"
                else:
                    fuel_counts["corrected"] += 1
                    fuel_status = "CORRECTED"

                if not dry_run:
                    update_fields = []
                    if current_fuel != fuel_consumed:
                        unit_row.dg_fuel_consumption = fuel_consumed
                        update_fields.append("dg_fuel_consumption")
                    if unit_row.fetch_fuel_data:
                        unit_row.fetch_fuel_data = False
                        update_fields.append("fetch_fuel_data")
                    if getattr(unit_row, "epoch_time", None) is not None:
                        correct_epoch = str(
                            int(
                                datetime.combine(
                                    reading_date, datetime.min.time()
                                ).timestamp()
                                * 1000
                            )
                        )


                    def _last_available_daily_reading_date(site, start_date, end_date):
                        return (
                            base.DailySiteReading.objects.using(DAILY_READING_DB_ALIAS)
                            .filter(
                                associated_Site=site,
                                reading_for__gte=start_date,
                                reading_for__lte=end_date,
                                aisle_group__power_source__gte=1,
                            )
                            .exclude(aisle_group_id__isnull=True)
                            .aggregate(last_date=Max("reading_for"))
                            .get("last_date")
                        )
                        if str(unit_row.epoch_time) != correct_epoch:
                            unit_row.epoch_time = correct_epoch
                            update_fields.append("epoch_time")
                    if (
                        getattr(unit_row, "created", None) is not None
                        and unit_row.created.date() != reading_date
                    ):
                        unit_row.created = datetime.combine(
                            reading_date, datetime.min.time()
                        )
                        update_fields.append("created")
                    if update_fields:
                        unit_row.save(update_fields=update_fields)

        if fuel_consumed is not None and fuel_consumed > 0 and daily_value >= 1:
            per_litre = round(daily_value / fuel_consumed, 2)
        else:
            per_litre = None
            fuel_counts["skipped_zero"] += 1

        unit_row_touched = {
            "aisle_group_id": aisle_id,
            "unit_consumption": daily_value,
            "dg_fuel_consumption": fuel_consumed,
            "dg_unit_per_litre": per_litre,
            "unit_status": unit_status,
            "fuel_status": fuel_status,
        }
        unit_rows_touched.append(unit_row_touched)
        unit_counts["details"].append(unit_row_touched)
        fuel_counts["details"].append(unit_row_touched)

    return {
        "unit_counts": unit_counts,
        "fuel_counts": fuel_counts,
        "unit_rows_touched": unit_rows_touched,
    }


base._reconcile_fuel_levels = _skip_fuel_levels
base._reconcile_alerts = _reconcile_alerts_dg_only
base._reconcile_units_and_fuel = _reconcile_units_and_fuel_dg_only


def build_report(days=DEFAULT_LOOKBACK_DAYS, site_id=None, dry_run=False):
    return base.build_report(days, site_id, dry_run=dry_run)


def build_report_range(start_date, end_date, site_id=None, dry_run=False):
    site_reports = []

    month_summary = {
        "days_requested": (end_date - start_date).days + 1,
        "days_processed": 0,
        "days_unavailable": 0,
        "days_subscription_expired": 0,
        "days_api_error": 0,
        "days_invalid": 0,
        "days_failed": 0,
        "days_with_unit_data": 0,
        "days_missing_unit_data": 0,
        "days_with_ignored_unit_data": 0,
        "missing_unit_dates": [],
        "fuel_levels_created": 0,
        "fuel_levels_existing_correct": 0,
        "fuel_levels_corrected": 0,
        "fuel_levels_failed": 0,
        "refuels_created": 0,
        "refuels_existing_correct": 0,
        "refuels_corrected": 0,
        "refuels_failed": 0,
        "thefts_created": 0,
        "thefts_existing_correct": 0,
        "thefts_corrected": 0,
        "thefts_failed": 0,
        "dg_units_created": 0,
        "dg_units_existing_correct": 0,
        "dg_units_corrected": 0,
        "dg_units_deferred": 0,
        "dg_units_ignored_below_threshold": 0,
        "dg_units_failed": 0,
        "dg_fuel_updated": 0,
        "dg_fuel_existing_correct": 0,
        "dg_fuel_corrected": 0,
        "dg_fuel_deferred": 0,
        "main_database_available": getattr(base, "MAIN_DATABASE_AVAILABLE", False),
    }

    for site in base._site_queryset(site_id):
        site_days = []
        site_status = "unavailable"
        site_last_daily_date = _last_available_daily_reading_date(
            site, start_date, end_date
        )
        site_end_date = min(end_date, site_last_daily_date) if site_last_daily_date else None
        if site_end_date is None or site_end_date < start_date:
            site_reports.append(
                {
                    "site_id": site.id,
                    "site_name": site.site_name,
                    "vehicle_imei": str(site.partner_dg_fuel_id).strip(),
                    "status": "no_daily_readings_in_range",
                    "days": [],
                    "last_available_daily_reading_date": (
                        site_last_daily_date.isoformat() if site_last_daily_date else None
                    ),
                }
            )
            continue

        for reading_date in _date_range(start_date, site_end_date):
            try:
                day_summary = base._process_day(site, reading_date, dry_run=dry_run)
            except Exception as exc:
                month_summary["days_failed"] += 1
                day_summary = {
                    "date": reading_date.isoformat(),
                    "provider_status": "FAILED",
                    "provider_reason": str(exc),
                    "fuel_consumed": None,
                    "fuel_levels": {
                        "fetched": 0,
                        "created": 0,
                        "existing_correct": 0,
                        "corrected": 0,
                        "failed": 0,
                    },
                    "refuels": {
                        "fetched": 0,
                        "created": 0,
                        "existing_correct": 0,
                        "corrected": 0,
                        "failed": 0,
                    },
                    "thefts": {
                        "fetched": 0,
                        "created": 0,
                        "existing_correct": 0,
                        "corrected": 0,
                        "failed": 0,
                    },
                    "dg_unit": {
                        "created": 0,
                        "existing_correct": 0,
                        "corrected": 0,
                        "deferred_no_daily_reading": 0,
                        "ignored_below_threshold": 0,
                        "failed": 0,
                    },
                    "dg_fuel": {
                        "updated": 0,
                        "existing_correct": 0,
                        "corrected": 0,
                        "deferred_no_unit_row": 0,
                        "skipped_zero": 0,
                    },
                    "dg_unit_litre_calculated": 0,
                }
            site_days.append(day_summary)

            provider_status = day_summary["provider_status"]
            if provider_status == "OK":
                site_status = "ok"
                month_summary["days_processed"] += 1
            elif provider_status == "SUBSCRIPTION_EXPIRED":
                month_summary["days_subscription_expired"] += 1
            elif provider_status == "API_ERROR":
                month_summary["days_api_error"] += 1
            elif provider_status == "INVALID_RESPONSE":
                month_summary["days_invalid"] += 1
            else:
                month_summary["days_unavailable"] += 1

            if provider_status == "OK":
                unit_source_status = day_summary.get(
                    "unit_source_status", "NO_DAILY_READING"
                )
                if unit_source_status == "DAILY_READING_FOUND":
                    month_summary["days_with_unit_data"] += 1
                elif unit_source_status == "IGNORED_FLUCTUATION":
                    month_summary["days_with_ignored_unit_data"] += 1
                else:
                    month_summary["days_missing_unit_data"] += 1
                    month_summary["missing_unit_dates"].append(reading_date.isoformat())

            fuel_counts = day_summary.get("fuel_levels", {})
            refuel_counts = day_summary.get("refuels", {})
            theft_counts = day_summary.get("thefts", {})
            unit_counts = day_summary.get("dg_unit", {})
            fuel_update_counts = day_summary.get("dg_fuel", {})

            month_summary["fuel_levels_created"] += fuel_counts.get(
                base._count_mode_key(dry_run, "created", "would_create"), 0
            )
            month_summary["fuel_levels_existing_correct"] += fuel_counts.get(
                "existing_correct", 0
            )
            month_summary["fuel_levels_corrected"] += fuel_counts.get(
                base._count_mode_key(dry_run, "corrected", "would_correct"), 0
            )
            month_summary["fuel_levels_failed"] += fuel_counts.get("failed", 0)

            month_summary["refuels_created"] += refuel_counts.get(
                base._count_mode_key(dry_run, "created", "would_create"), 0
            )
            month_summary["refuels_existing_correct"] += refuel_counts.get(
                "existing_correct", 0
            )
            month_summary["refuels_corrected"] += refuel_counts.get(
                base._count_mode_key(dry_run, "corrected", "would_correct"), 0
            )
            month_summary["refuels_failed"] += refuel_counts.get("failed", 0)

            month_summary["thefts_created"] += theft_counts.get(
                base._count_mode_key(dry_run, "created", "would_create"), 0
            )
            month_summary["thefts_existing_correct"] += theft_counts.get(
                "existing_correct", 0
            )
            month_summary["thefts_corrected"] += theft_counts.get(
                base._count_mode_key(dry_run, "corrected", "would_correct"), 0
            )
            month_summary["thefts_failed"] += theft_counts.get("failed", 0)

            month_summary["dg_units_created"] += unit_counts.get("created", 0)
            month_summary["dg_units_existing_correct"] += unit_counts.get(
                "existing_correct", 0
            )
            month_summary["dg_units_corrected"] += unit_counts.get("corrected", 0)
            month_summary["dg_units_deferred"] += unit_counts.get(
                "deferred_no_daily_reading", 0
            )
            month_summary["dg_units_ignored_below_threshold"] += unit_counts.get(
                "ignored_below_threshold", 0
            )
            month_summary["dg_units_failed"] += unit_counts.get("failed", 0)

            month_summary["dg_fuel_updated"] += fuel_update_counts.get("updated", 0)
            month_summary["dg_fuel_existing_correct"] += fuel_update_counts.get(
                "existing_correct", 0
            )
            month_summary["dg_fuel_corrected"] += fuel_update_counts.get("corrected", 0)
            month_summary["dg_fuel_deferred"] += fuel_update_counts.get(
                "deferred_no_unit_row", 0
            )

        site_reports.append(
            {
                "site_id": site.id,
                "site_name": site.site_name,
                "vehicle_imei": str(site.partner_dg_fuel_id).strip(),
                "status": site_status,
                "days": site_days,
                "last_available_daily_reading_date": (
                    site_last_daily_date.isoformat() if site_last_daily_date else None
                ),
            }
        )

    return {
        "window_start": start_date.isoformat(),
        "window_end": end_date.isoformat(),
        "dry_run": dry_run,
        "site_count": len(site_reports),
        "sites": site_reports,
        "summary": month_summary,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Recover Roadcast DG-fuel history site by site for a date range."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="Look back this many days from today (default: 365).",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--site-id",
        type=int,
        default=None,
        help="Optional site ID filter for a single site.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compare against the DB without saving anything.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full result as JSON instead of a human-readable summary.",
    )
    args = parser.parse_args()

    if args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        report = build_report_range(
            start_date, end_date, args.site_id, dry_run=args.dry_run
        )
    else:
        report = build_report(args.days, args.site_id, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"mode: {'dry-run' if report['dry_run'] else 'save'}")
    print(f"window: {report['window_start']} -> {report['window_end']}")
    print(f"sites: {report['site_count']}")
    for site in report["sites"]:
        print(
            f"site_id={site['site_id']} site_name={site['site_name']} imei={site['vehicle_imei']} status={site['status']}"
        )
        for day in site["days"]:
            base._print_day(day, dry_run=report["dry_run"])
    base._print_month_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
