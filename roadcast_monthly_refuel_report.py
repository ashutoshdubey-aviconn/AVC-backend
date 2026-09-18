#!/usr/bin/env python3
"""Recover Roadcast DG-fuel history site by site for the last N days.

The script is production-safe and idempotent:
- it fetches Roadcast historical data day by day,
- validates the response belongs to the requested site/device,
- reconciles fuel levels, refuel alerts, theft alerts, DG unit rows, and
  DG fuel consumption against the current DB state,
- never deletes data,
- never invents DG unit consumption when authoritative DailySiteReading data
  is absent.

Dry-run mode performs the same comparisons without saving.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")

import django

django.setup()

from django.conf import settings

MAIN_DATABASE_AVAILABLE = "main" in settings.DATABASES

from django.db import transaction
from django.utils import timezone

from wareApp.dg_fuel.ingestion import record_fuel_alert, record_fuel_level
from wareApp.dg_fuel.normalization import as_float, epoch_milliseconds
from wareApp.dg_fuel.providers import (
    extract_roadcast_subscription_expired_errors,
    parse_roadcast_report,
)
from wareApp.dg_fuel.sessions import reconcile_daily_unit_consumption
from wareApp.models import (
    DailySiteReading,
    DGFuelAlertsData,
    DgFuelConsumptionData,
    DgUnitConsumption,
    Site,
)

ROADCAST_FUEL_URL = "https://test-track.roadcast.net/api/v1/auth/pull_fuel_report"
ROADCAST_USERNAME = os.environ.get("ROADCAST_USERNAME", "Aviconn")
ROADCAST_PASSWORD = os.environ.get("ROADCAST_PASSWORD", "Abc@1234")
ROADCAST_AUTH_HEADERS = {"Authorization": "Basic QXZpY29ubjpBYmNAMTIzNA=="}
PROJECT_ROOT = Path(__file__).resolve().parent
ROADCAST_RESPONSES_DIR = PROJECT_ROOT / "logs" / "roadcast" / "api_responses"


def _current_local_date_window(days: int) -> tuple[date, date]:
    current_time = timezone.now()
    if timezone.is_naive(current_time):
        current_time = timezone.make_aware(
            current_time, timezone.get_current_timezone()
        )
    current_time = timezone.localtime(current_time)
    end_date = current_time.date()
    start_date = end_date - timedelta(days=max(days - 1, 0))
    return start_date, end_date


def _day_window(reading_date: date) -> tuple[datetime, datetime]:
    day_start = datetime.combine(reading_date, datetime.min.time())
    day_end = datetime.combine(reading_date, datetime.max.time().replace(microsecond=0))
    if timezone.is_naive(day_start):
        current_timezone = timezone.get_current_timezone()
        day_start = timezone.make_aware(day_start, current_timezone)
        day_end = timezone.make_aware(day_end, current_timezone)
    return day_start, day_end


def _date_range(start_date: date, end_date: date) -> Iterable[date]:
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def _site_queryset(site_id: int | None = None):
    qs = (
        Site.objects.filter(
            dg_fuel_system_installed=True, partner_dg_provider__iexact="roadcast"
        )
        .exclude(partner_dg_fuel_id__isnull=True)
        .exclude(partner_dg_fuel_id="")
        .order_by("id")
    )
    if site_id is not None:
        qs = qs.filter(id=site_id)
    return qs.only("id", "site_name", "partner_dg_fuel_id")


def _payload_matches_site(
    payload: Dict[str, Any], site: Site, vehicle_imei: str
) -> bool:
    candidates = {
        str(site.id).strip().lower(),
        str(site.site_name or "").strip().lower(),
        str(site.partner_dg_fuel_id or "").strip().lower(),
        str(vehicle_imei or "").strip().lower(),
    }
    candidates = {candidate for candidate in candidates if candidate}
    if not candidates:
        return False

    payload_values = [
        payload.get("device_imei"),
        payload.get("device_id"),
        payload.get("device_name"),
        payload.get("name"),
    ]

    for value in payload_values:
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if not normalized:
            continue
        for candidate in candidates:
            if candidate in normalized or normalized in candidate:
                return True
    return False


def _save_payload_response(
    *,
    site: Site,
    reading_date: date,
    vehicle_imei: str,
    status: str,
    reason: str | None,
    request_params: Dict[str, Any],
    payload: Any,
    response_text: str | None,
) -> None:
    ROADCAST_RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    site_dir = ROADCAST_RESPONSES_DIR / f"site_{site.id}"
    site_dir.mkdir(parents=True, exist_ok=True)
    file_path = site_dir / f"{reading_date.isoformat()}.json"
    body = {
        "site_id": site.id,
        "site_name": getattr(site, "site_name", None),
        "vehicle_number": vehicle_imei,
        "reading_date": reading_date.isoformat(),
        "status": status,
        "reason": reason,
        "request_params": request_params,
        "payload": payload,
        "response_text": response_text,
    }
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, default=str)


def _fetch_roadcast_day_report(
    site: Site, vehicle_imei: str, start_dt: datetime, end_dt: datetime
) -> Dict[str, Any]:
    params = {
        "device_imei": vehicle_imei,
        "from_time": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "to_time": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        response = requests.get(
            ROADCAST_FUEL_URL,
            params=params,
            headers=ROADCAST_AUTH_HEADERS,
            timeout=20,
        )
    except requests.RequestException as exc:
        _save_payload_response(
            site=site,
            reading_date=start_dt.date(),
            vehicle_imei=vehicle_imei,
            status="API_ERROR",
            reason=str(exc),
            request_params=params,
            payload=None,
            response_text=None,
        )
        return {
            "status": "API_ERROR",
            "reason": str(exc),
            "payload": None,
            "report": None,
        }

    if response.status_code != 200:
        _save_payload_response(
            site=site,
            reading_date=start_dt.date(),
            vehicle_imei=vehicle_imei,
            status="API_ERROR",
            reason=f"http_{response.status_code}",
            request_params=params,
            payload=None,
            response_text=response.text,
        )
        return {
            "status": "API_ERROR",
            "reason": f"http_{response.status_code}",
            "payload": None,
            "report": None,
        }

    try:
        payload = response.json()
    except Exception as exc:
        _save_payload_response(
            site=site,
            reading_date=start_dt.date(),
            vehicle_imei=vehicle_imei,
            status="INVALID_RESPONSE",
            reason=f"json_decode_failed: {exc}",
            request_params=params,
            payload=None,
            response_text=response.text,
        )
        return {
            "status": "INVALID_RESPONSE",
            "reason": f"json_decode_failed: {exc}",
            "payload": None,
            "report": None,
        }

    if not isinstance(payload, dict):
        _save_payload_response(
            site=site,
            reading_date=start_dt.date(),
            vehicle_imei=vehicle_imei,
            status="INVALID_RESPONSE",
            reason="response_not_dict",
            request_params=params,
            payload=payload,
            response_text=response.text,
        )
        return {
            "status": "INVALID_RESPONSE",
            "reason": "response_not_dict",
            "payload": payload,
            "report": None,
        }

    expired_errors = extract_roadcast_subscription_expired_errors(
        payload, site=site, vehicle_imei=vehicle_imei
    )
    if expired_errors:
        _save_payload_response(
            site=site,
            reading_date=start_dt.date(),
            vehicle_imei=vehicle_imei,
            status="SUBSCRIPTION_EXPIRED",
            reason="subscription_expired",
            request_params=params,
            payload=payload,
            response_text=response.text,
        )
        return {
            "status": "SUBSCRIPTION_EXPIRED",
            "reason": "subscription_expired",
            "payload": payload,
            "report": None,
        }

    if not _payload_matches_site(payload, site, vehicle_imei):
        _save_payload_response(
            site=site,
            reading_date=start_dt.date(),
            vehicle_imei=vehicle_imei,
            status="INVALID_RESPONSE",
            reason="payload_device_mismatch",
            request_params=params,
            payload=payload,
            response_text=response.text,
        )
        return {
            "status": "INVALID_RESPONSE",
            "reason": "payload_device_mismatch",
            "payload": payload,
            "report": None,
        }

    report = parse_roadcast_report(payload)
    _save_payload_response(
        site=site,
        reading_date=start_dt.date(),
        vehicle_imei=vehicle_imei,
        status="OK",
        reason=None,
        request_params=params,
        payload=payload,
        response_text=response.text,
    )
    return {
        "status": "OK",
        "reason": None,
        "payload": payload,
        "report": report,
    }


def _format_event_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted = []
    for item in items:
        epoch_ms = item.get("epoch_ms")
        when = None
        if epoch_ms is not None:
            when = datetime.fromtimestamp(epoch_ms / 1000).strftime("%Y-%m-%d %H:%M")
        formatted.append({"when": when, "fuel_liters": item.get("fuel_liters")})
    return formatted


def _count_mode_key(dry_run: bool, live_key: str, dry_key: str) -> str:
    return dry_key if dry_run else live_key


def _init_item_counts(dry_run: bool) -> Dict[str, int]:
    counts = {
        _count_mode_key(dry_run, "created", "would_create"): 0,
        "existing_correct": 0,
        _count_mode_key(dry_run, "corrected", "would_correct"): 0,
        "failed": 0,
        "skipped_invalid": 0,
        "ambiguous": 0,
        "fetched": 0,
    }
    return counts


def _existing_exact_count(qs) -> int:
    try:
        return qs.count()
    except Exception:
        return 0


def _reconcile_fuel_levels(
    site: Site,
    vehicle_imei: str,
    report: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    counts = _init_item_counts(dry_run)
    details: List[Dict[str, Any]] = []
    target_key_create = _count_mode_key(dry_run, "created", "would_create")
    target_key_correct = _count_mode_key(dry_run, "corrected", "would_correct")

    for sample in report.get("fuel_levels", []) or []:
        counts["fetched"] += 1
        fuel_liters = as_float(sample.get("fuel_liters"))
        epoch_ms = epoch_milliseconds(sample.get("epoch_ms"))
        if fuel_liters is None or epoch_ms is None:
            counts["skipped_invalid"] += 1
            details.append({"epoch_ms": epoch_ms, "status": "SKIPPED_INVALID"})
            continue

        epoch_time = str(epoch_ms)
        existing_qs = DgFuelConsumptionData.objects.filter(
            site=site,
            vehicle_number=str(vehicle_imei),
            epoch_time=epoch_time,
        ).order_by("id")

        if _existing_exact_count(existing_qs) > 1:
            counts["ambiguous"] += 1
            details.append({"epoch_ms": epoch_ms, "status": "AMBIGUOUS"})
            continue

        existing = existing_qs.first()
        if existing is None:
            counts[target_key_create] += 1
            details.append({"epoch_ms": epoch_ms, "status": target_key_create.upper()})
            if dry_run:
                continue
            DgFuelConsumptionData.objects.create(
                site=site,
                vehicle_number=str(vehicle_imei),
                fuel_consumption=fuel_liters,
                fuel_data_source="roadcast",
                epoch_time=epoch_time,
                created=datetime.fromtimestamp(epoch_ms / 1000),
            )
            continue

        current_fuel = as_float(existing.fuel_consumption)
        current_source = str(existing.fuel_data_source or "").strip().lower()
        current_vehicle = str(existing.vehicle_number or "").strip()
        identical = (
            current_fuel is not None
            and abs(current_fuel - fuel_liters) < 1e-9
            and current_source == "roadcast"
            and current_vehicle == str(vehicle_imei)
            and str(existing.epoch_time or "") == epoch_time
        )

        if identical:
            counts["existing_correct"] += 1
            details.append({"epoch_ms": epoch_ms, "status": "EXISTING_CORRECT"})
            continue

        counts[target_key_correct] += 1
        details.append({"epoch_ms": epoch_ms, "status": target_key_correct.upper()})
        if dry_run:
            continue

        update_fields: List[str] = []
        if current_fuel != fuel_liters:
            existing.fuel_consumption = fuel_liters
            update_fields.append("fuel_consumption")
        if current_source != "roadcast":
            existing.fuel_data_source = "roadcast"
            update_fields.append("fuel_data_source")
        if update_fields:
            existing.save(update_fields=update_fields)

    return {"counts": counts, "details": details}


def _reconcile_alerts(
    site: Site,
    vehicle_imei: str,
    report: Dict[str, Any],
    alert_name: str,
    events: List[Dict[str, Any]],
    dry_run: bool,
) -> Dict[str, Any]:
    counts = _init_item_counts(dry_run)
    details: List[Dict[str, Any]] = []
    create_key = _count_mode_key(dry_run, "created", "would_create")
    correct_key = _count_mode_key(dry_run, "corrected", "would_correct")

    for event in events:
        counts["fetched"] += 1
        fuel_liters = as_float(event.get("fuel_liters"))
        epoch_ms = epoch_milliseconds(event.get("epoch_ms"))
        if fuel_liters is None or epoch_ms is None:
            counts["skipped_invalid"] += 1
            details.append({"epoch_ms": epoch_ms, "status": "SKIPPED_INVALID"})
            continue

        epoch_time = str(epoch_ms)
        existing_qs = DGFuelAlertsData.objects.filter(
            site=site,
            vehicle_number=str(vehicle_imei),
            alert_name=alert_name,
            epoch_time=epoch_time,
        ).order_by("id")
        if _existing_exact_count(existing_qs) > 1:
            counts["ambiguous"] += 1
            details.append({"epoch_ms": epoch_ms, "status": "AMBIGUOUS"})
            continue

        existing = existing_qs.first()
        if existing is None:
            counts[create_key] += 1
            details.append({"epoch_ms": epoch_ms, "status": create_key.upper()})
            if dry_run:
                continue
            DGFuelAlertsData.objects.create(
                site=site,
                vehicle_number=str(vehicle_imei),
                alert_name=alert_name,
                fuel_consumption=fuel_liters,
                epoch_time=epoch_time,
                created=datetime.fromtimestamp(epoch_ms / 1000),
            )
            continue

        current_fuel = as_float(existing.fuel_consumption)
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

        if current_fuel != fuel_liters:
            existing.fuel_consumption = fuel_liters
            existing.save(update_fields=["fuel_consumption"])

    return {"counts": counts, "details": details}


def _daily_unit_rows(site: Site, reading_date: date) -> List[DgUnitConsumption]:
    return list(
        DgUnitConsumption.objects.filter(site=site, created__date=reading_date)
        .select_related("aisle_group")
        .order_by("aisle_group_id", "id")
    )


def _daily_readings(site: Site, reading_date: date) -> List[DailySiteReading]:
    return list(
        DailySiteReading.objects.using("main")
        .filter(
            associated_Site=site,
            reading_for=reading_date,
            aisle_group__power_source__gte=1,
        )
        .exclude(aisle_group_id__isnull=True)
        .order_by("aisle_group_id", "id")
    )


def _unit_source_status_for_day(authoritative_daily: List[DailySiteReading]) -> str:
    if not authoritative_daily:
        return "NO_DAILY_READING"

    valid_values = [
        as_float(daily_row.unit_consumption)
        for daily_row in authoritative_daily
        if as_float(daily_row.unit_consumption) is not None
    ]
    if any(value >= 1 for value in valid_values):
        return "DAILY_READING_FOUND"
    if valid_values:
        return "IGNORED_FLUCTUATION"
    return "NO_DAILY_READING"


def _reconcile_units_and_fuel(
    site: Site,
    reading_date: date,
    report: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
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
        "details": [],
    }

    if not MAIN_DATABASE_AVAILABLE:
        unit_counts["deferred_no_daily_reading"] = 1
        unit_counts["unit_source_status"] = "MAIN_DATABASE_UNAVAILABLE"
        fuel_counts["deferred_no_unit_row"] = 1
        return {
            "unit_counts": unit_counts,
            "fuel_counts": fuel_counts,
            "unit_rows_touched": [],
        }

    authoritative_daily = _daily_readings(site, reading_date)
    if not authoritative_daily:
        unit_counts["deferred_no_daily_reading"] = 1
        unit_counts["unit_source_status"] = "NO_DAILY_READING"
        fuel_counts["deferred_no_unit_row"] = 1
        return {
            "unit_counts": unit_counts,
            "fuel_counts": fuel_counts,
            "unit_rows_touched": [],
        }

    unit_counts["unit_source_status"] = _unit_source_status_for_day(authoritative_daily)

    preexisting_units = {
        unit.aisle_group_id: unit for unit in _daily_unit_rows(site, reading_date)
    }

    if not dry_run:
        reconcile_daily_unit_consumption(site, reading_date, return_details=True)

    post_units = {
        unit.aisle_group_id: unit for unit in _daily_unit_rows(site, reading_date)
    }
    fuel_consumed = as_float(report.get("fuel_consumed"))

    unit_rows_touched: List[Dict[str, Any]] = []
    seen_aisles: set[int] = set()

    for daily_row in authoritative_daily:
        aisle_id = daily_row.aisle_group_id
        if aisle_id in seen_aisles:
            continue
        seen_aisles.add(aisle_id)

        daily_value = as_float(daily_row.unit_consumption)
        if daily_value is None:
            unit_counts["failed"] += 1
            unit_counts["details"].append(
                {"aisle_group_id": aisle_id, "status": "FAILED_INVALID_DAILY_READING"}
            )
            continue

        if daily_value < 1:
            unit_counts["ignored_below_threshold"] += 1
            unit_counts["details"].append(
                {"aisle_group_id": aisle_id, "status": "IGNORED_FLUCTUATION"}
            )
            continue

        preexisting_unit = preexisting_units.get(aisle_id)
        if preexisting_unit is None:
            unit_counts["created"] += 1
            unit_status = "CREATED"
        else:
            current_value = as_float(preexisting_unit.unit_consumption)
            if current_value is not None and abs(current_value - daily_value) < 1e-9:
                unit_counts["existing_correct"] += 1
                unit_status = "EXISTING_CORRECT"
            else:
                unit_counts["corrected"] += 1
                unit_status = "CORRECTED"

        unit_row = post_units.get(aisle_id) if not dry_run else preexisting_unit

        fuel_status = None
        if fuel_consumed is None:
            fuel_counts["deferred_no_unit_row"] += 1
            fuel_status = "DEFERRED_NO_UNIT_ROW"
        else:
            if unit_row is None:
                fuel_counts["deferred_no_unit_row"] += 1
                fuel_status = "DEFERRED_NO_UNIT_ROW"
            else:
                current_fuel = as_float(unit_row.dg_fuel_consumption)
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
                    update_fields: List[str] = []
                    if current_fuel != fuel_consumed:
                        unit_row.dg_fuel_consumption = fuel_consumed
                        update_fields.append("dg_fuel_consumption")
                    if unit_row.fetch_fuel_data:
                        unit_row.fetch_fuel_data = False
                        update_fields.append("fetch_fuel_data")
                    if update_fields:
                        unit_row.save(update_fields=update_fields)

        per_litre = None
        if fuel_consumed is not None and fuel_consumed > 0 and daily_value >= 1:
            per_litre = round(daily_value / fuel_consumed, 2)

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


def _process_day(site: Site, reading_date: date, dry_run: bool) -> Dict[str, Any]:
    vehicle_imei = str(site.partner_dg_fuel_id).strip()
    day_start, day_end = _day_window(reading_date)
    provider_result = _fetch_roadcast_day_report(site, vehicle_imei, day_start, day_end)
    day_summary: Dict[str, Any] = {
        "date": reading_date.isoformat(),
        "provider_status": provider_result["status"],
        "provider_reason": provider_result["reason"],
        "fuel_consumed": None,
        "unit_source_status": "NO_DAILY_READING",
        "fuel_levels": {},
        "refuels": {},
        "thefts": {},
        "dg_unit": {},
        "dg_fuel": {},
        "dg_unit_litre_calculated": 0,
    }

    if provider_result["status"] != "OK":
        return day_summary

    report = provider_result["report"] or {}
    day_summary["fuel_consumed"] = report.get("fuel_consumed")

    if dry_run:
        fuel_summary = _reconcile_fuel_levels(site, vehicle_imei, report, dry_run=True)
        refuel_summary = _reconcile_alerts(
            site, vehicle_imei, report, "refuel", report.get("refuels", []) or [], True
        )
        theft_summary = _reconcile_alerts(
            site, vehicle_imei, report, "theft", report.get("thefts", []) or [], True
        )
        unit_summary = _reconcile_units_and_fuel(site, reading_date, report, True)
    else:
        with transaction.atomic():
            fuel_summary = _reconcile_fuel_levels(
                site, vehicle_imei, report, dry_run=False
            )
            refuel_summary = _reconcile_alerts(
                site,
                vehicle_imei,
                report,
                "refuel",
                report.get("refuels", []) or [],
                False,
            )
            theft_summary = _reconcile_alerts(
                site,
                vehicle_imei,
                report,
                "theft",
                report.get("thefts", []) or [],
                False,
            )
            unit_summary = _reconcile_units_and_fuel(site, reading_date, report, False)

    day_summary["fuel_levels"] = {
        "fetched": len(report.get("fuel_levels", []) or []),
        **fuel_summary["counts"],
    }
    day_summary["refuels"] = {
        "fetched": len(report.get("refuels", []) or []),
        **refuel_summary["counts"],
    }
    day_summary["thefts"] = {
        "fetched": len(report.get("thefts", []) or []),
        **theft_summary["counts"],
    }
    day_summary["dg_unit"] = unit_summary["unit_counts"]
    day_summary["dg_fuel"] = unit_summary["fuel_counts"]
    day_summary["unit_source_status"] = unit_summary["unit_counts"].get(
        "unit_source_status", "NO_DAILY_READING"
    )
    day_summary["dg_unit_litre_calculated"] = len(
        [
            row
            for row in unit_summary["unit_rows_touched"]
            if row.get("dg_unit_per_litre") is not None
        ]
    )
    day_summary["fuel_levels"]["details"] = _format_event_list(
        report.get("fuel_levels", []) or []
    )
    day_summary["refuels"]["details"] = _format_event_list(
        report.get("refuels", []) or []
    )
    day_summary["thefts"]["details"] = _format_event_list(
        report.get("thefts", []) or []
    )
    day_summary["dg_unit"]["details"] = unit_summary["unit_counts"].get("details", [])
    day_summary["dg_fuel"]["details"] = unit_summary["fuel_counts"].get("details", [])
    return day_summary


def build_report(
    days: int, site_id: int | None = None, dry_run: bool = False
) -> Dict[str, Any]:
    start_date, end_date = _current_local_date_window(days)
    site_reports: List[Dict[str, Any]] = []

    month_summary = {
        "days_requested": days,
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
        "main_database_available": MAIN_DATABASE_AVAILABLE,
    }

    for site in _site_queryset(site_id):
        site_days: List[Dict[str, Any]] = []
        site_status = "unavailable"
        for reading_date in _date_range(start_date, end_date):
            try:
                day_summary = _process_day(site, reading_date, dry_run=dry_run)
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
                _count_mode_key(dry_run, "created", "would_create"), 0
            )
            month_summary["fuel_levels_existing_correct"] += fuel_counts.get(
                "existing_correct", 0
            )
            month_summary["fuel_levels_corrected"] += fuel_counts.get(
                _count_mode_key(dry_run, "corrected", "would_correct"), 0
            )
            month_summary["fuel_levels_failed"] += fuel_counts.get("failed", 0)

            month_summary["refuels_created"] += refuel_counts.get(
                _count_mode_key(dry_run, "created", "would_create"), 0
            )
            month_summary["refuels_existing_correct"] += refuel_counts.get(
                "existing_correct", 0
            )
            month_summary["refuels_corrected"] += refuel_counts.get(
                _count_mode_key(dry_run, "corrected", "would_correct"), 0
            )
            month_summary["refuels_failed"] += refuel_counts.get("failed", 0)

            month_summary["thefts_created"] += theft_counts.get(
                _count_mode_key(dry_run, "created", "would_create"), 0
            )
            month_summary["thefts_existing_correct"] += theft_counts.get(
                "existing_correct", 0
            )
            month_summary["thefts_corrected"] += theft_counts.get(
                _count_mode_key(dry_run, "corrected", "would_correct"), 0
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


def _print_day(day: Dict[str, Any], dry_run: bool) -> None:
    print(f"  {day['date']}")
    print(f"    provider={day['provider_status']}")
    if day.get("provider_reason"):
        print(f"    reason={day['provider_reason']}")
    print(f"    fuel_consumed={day.get('fuel_consumed')}")
    print(f"    unit_source_status={day.get('unit_source_status', 'NO_DAILY_READING')}")

    fuel_counts = day.get("fuel_levels", {})
    refuel_counts = day.get("refuels", {})
    theft_counts = day.get("thefts", {})
    unit_counts = day.get("dg_unit", {})
    fuel_update_counts = day.get("dg_fuel", {})

    print("    fuel_levels:")
    print(f"      fetched={fuel_counts.get('fetched', 0)}")
    print(
        f"      {_count_mode_key(dry_run, 'created', 'would_create')}={fuel_counts.get(_count_mode_key(dry_run, 'created', 'would_create'), 0)}"
    )
    print(f"      existing_correct={fuel_counts.get('existing_correct', 0)}")
    print(
        f"      {_count_mode_key(dry_run, 'corrected', 'would_correct')}={fuel_counts.get(_count_mode_key(dry_run, 'corrected', 'would_correct'), 0)}"
    )
    print(f"      failed={fuel_counts.get('failed', 0)}")

    print("    refuels:")
    print(f"      fetched={refuel_counts.get('fetched', 0)}")
    print(
        f"      {_count_mode_key(dry_run, 'created', 'would_create')}={refuel_counts.get(_count_mode_key(dry_run, 'created', 'would_create'), 0)}"
    )
    print(f"      existing_correct={refuel_counts.get('existing_correct', 0)}")
    print(
        f"      {_count_mode_key(dry_run, 'corrected', 'would_correct')}={refuel_counts.get(_count_mode_key(dry_run, 'corrected', 'would_correct'), 0)}"
    )
    print(f"      failed={refuel_counts.get('failed', 0)}")

    print("    thefts:")
    print(f"      fetched={theft_counts.get('fetched', 0)}")
    print(
        f"      {_count_mode_key(dry_run, 'created', 'would_create')}={theft_counts.get(_count_mode_key(dry_run, 'created', 'would_create'), 0)}"
    )
    print(f"      existing_correct={theft_counts.get('existing_correct', 0)}")
    print(
        f"      {_count_mode_key(dry_run, 'corrected', 'would_correct')}={theft_counts.get(_count_mode_key(dry_run, 'corrected', 'would_correct'), 0)}"
    )
    print(f"      failed={theft_counts.get('failed', 0)}")

    print("    dg_unit:")
    print(f"      created={unit_counts.get('created', 0)}")
    print(f"      existing_correct={unit_counts.get('existing_correct', 0)}")
    print(f"      corrected={unit_counts.get('corrected', 0)}")
    print(
        f"      deferred_no_daily_reading={unit_counts.get('deferred_no_daily_reading', 0)}"
    )
    print(
        f"      ignored_below_threshold={unit_counts.get('ignored_below_threshold', 0)}"
    )
    print(f"      failed={unit_counts.get('failed', 0)}")

    print("    dg_fuel:")
    print(f"      updated={fuel_update_counts.get('updated', 0)}")
    print(f"      existing_correct={fuel_update_counts.get('existing_correct', 0)}")
    print(f"      corrected={fuel_update_counts.get('corrected', 0)}")
    print(
        f"      deferred_no_unit_row={fuel_update_counts.get('deferred_no_unit_row', 0)}"
    )
    print(f"    dg_unit_litre_calculated={day.get('dg_unit_litre_calculated', 0)}")


def _print_month_summary(report: Dict[str, Any]) -> None:
    summary = report["summary"]
    print("month_summary:")
    print(f"  main_database_available={summary.get('main_database_available', False)}")
    for key in (
        "days_requested",
        "days_processed",
        "days_unavailable",
        "days_subscription_expired",
        "days_api_error",
        "days_invalid",
        "days_failed",
        "days_with_unit_data",
        "days_missing_unit_data",
        "days_with_ignored_unit_data",
        "fuel_levels_created",
        "fuel_levels_existing_correct",
        "fuel_levels_corrected",
        "fuel_levels_failed",
        "refuels_created",
        "refuels_existing_correct",
        "refuels_corrected",
        "refuels_failed",
        "thefts_created",
        "thefts_existing_correct",
        "thefts_corrected",
        "thefts_failed",
        "dg_units_created",
        "dg_units_existing_correct",
        "dg_units_corrected",
        "dg_units_deferred",
        "dg_units_ignored_below_threshold",
        "dg_units_failed",
        "dg_fuel_updated",
        "dg_fuel_existing_correct",
        "dg_fuel_corrected",
        "dg_fuel_deferred",
    ):
        print(f"  {key}={summary.get(key, 0)}")
    missing_unit_dates = summary.get("missing_unit_dates", [])
    if missing_unit_dates:
        print(f"  missing_unit_dates={','.join(sorted(missing_unit_dates))}")
    else:
        print("  missing_unit_dates=")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover Roadcast DG-fuel history site by site for the last N days."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Look back this many days from today (default: 30).",
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
            _print_day(day, dry_run=report["dry_run"])
    _print_month_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
