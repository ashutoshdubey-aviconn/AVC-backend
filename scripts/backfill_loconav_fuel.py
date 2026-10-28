#!/usr/bin/env python3
"""Day-by-day historical recovery for LocoNav DG fuel data."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from django.db import connections, transaction
from django.utils import timezone as dj_timezone

proj_root = Path(__file__).resolve().parents[1]
if str(proj_root) not in sys.path:
    sys.path.insert(0, str(proj_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")

import django

django.setup()

from wareApp.dg_fuel.ingestion import record_fuel_alert, record_fuel_level
from wareApp.dg_fuel.normalization import as_float, epoch_milliseconds
from wareApp.dg_fuel.providers import extract_loconav_subscription_expired_errors
from wareApp.fuel_providers import (
    detect_refuel_from_alerts,
    detect_theft_from_alerts,
    fetch_loconav_report,
)
from wareApp.models import (
    DailySiteReading,
    DGFuelAlertsData,
    DgFuelConsumptionData,
    DgUnitConsumption,
    HourlySiteReading,
    Site,
)

DEFAULT_PROVIDER = "loconav"
DEFAULT_DAYS = 30
DEFAULT_SITE_IDS = (35, 76, 92)
RESPONSES_DIR = proj_root / "logs" / "loconav" / "api_responses"


def _current_local_date_window(days: int) -> tuple[date, date]:
    today = dj_timezone.now().date()
    start_date = today - timedelta(days=max(days - 1, 0))
    return start_date, today


def _day_window(reading_date: date) -> tuple[datetime, datetime]:
    day_start = datetime.combine(reading_date, datetime.min.time())
    day_end = datetime.combine(reading_date, datetime.max.time().replace(microsecond=0))
    current_timezone = dj_timezone.get_current_timezone()
    if dj_timezone.is_naive(day_start):
        day_start = dj_timezone.make_aware(day_start, current_timezone)
    if dj_timezone.is_naive(day_end):
        day_end = dj_timezone.make_aware(day_end, current_timezone)
    return day_start, day_end


def _vehicle_number_for_site(site: Site) -> str | None:
    for attr in (
        "partner_dg_fuel_id",
        "partner_dg_vehicle",
        "partner_dg_vehicle_number",
        "partner_dg_fuel_vehicle",
    ):
        value = getattr(site, attr, None)
        if value:
            return str(value).strip()
    return None


def _main_database_alias() -> str:
    if "main" not in connections.databases:
        available = ", ".join(sorted(connections.databases)) or "<none>"
        raise RuntimeError(
            "DailySiteReading recovery requires the 'main' database alias; "
            f"available aliases: {available}"
        )
    return "main"


def _database_identity(alias: str) -> str:
    config = connections.databases.get(alias, {})
    engine = str(config.get("ENGINE") or "<unknown>").rsplit(".", 1)[-1]
    name = str(config.get("NAME") or "<unknown>")
    return f"{alias}:{engine}:{name}"


def _day_epoch_ms(reading_date: date) -> int:
    day_start, _ = _day_window(reading_date)
    return epoch_milliseconds(day_start) or 0


def _loconav_payload_data(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _loconav_fuel_level_sample(
    payload: Any, default_vehicle: str, reading_date: date
) -> dict[str, Any] | None:
    data = _loconav_payload_data(payload)
    if data is None:
        return None

    fuel_sensors = data.get("fuel_sensors")
    if not isinstance(fuel_sensors, list):
        return None

    for sensor in fuel_sensors:
        if not isinstance(sensor, dict):
            continue
        fuel_liters = as_float(sensor.get("value"))
        if fuel_liters is None:
            continue
        return {
            "epoch_ms": _day_epoch_ms(reading_date),
            "fuel_liters": fuel_liters,
            "vehicle_number": str(default_vehicle).strip(),
            "source": DEFAULT_PROVIDER,
        }
    return None


def _loconav_daily_fuel_consumed(payload: Any) -> float | None:
    data = _loconav_payload_data(payload)
    if data is None:
        return None

    fuel_consumption = data.get("fuel_consumption")
    if not isinstance(fuel_consumption, dict):
        return None
    return as_float(fuel_consumption.get("value"))


def _loconav_daily_refuel_total(payload: Any) -> float | None:
    data = _loconav_payload_data(payload)
    if data is None:
        return None

    refuel = data.get("refuel")
    if not isinstance(refuel, dict):
        return None
    return as_float(refuel.get("value"))


def _loconav_daily_theft_total(payload: Any) -> float | None:
    data = _loconav_payload_data(payload)
    if data is None:
        return None

    fuel_theft = data.get("fuel_theft")
    if not isinstance(fuel_theft, dict):
        return None
    return as_float(fuel_theft.get("value"))


def _save_payload_response(
    *, site: Site, reading_date: date, payload: Any, status: str
) -> None:
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    site_dir = RESPONSES_DIR / f"site_{site.id}"
    site_dir.mkdir(parents=True, exist_ok=True)
    file_path = site_dir / f"{reading_date.isoformat()}.json"
    body = {
        "site_id": site.id,
        "site_name": getattr(site, "site_name", None),
        "vehicle_number": _vehicle_number_for_site(site),
        "reading_date": reading_date.isoformat(),
        "status": status,
        "payload": payload,
    }
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, default=str)


def _loconav_alerts_from_payload(
    payload: Any, default_vehicle: str
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for alert_name, rows in (
        ("refuel", detect_refuel_from_alerts(payload)),
        ("theft", detect_theft_from_alerts(payload)),
    ):
        for row in rows:
            epoch_ms = epoch_milliseconds(row.get("timestamp") or row.get("epoch_ms"))
            fuel_liters = as_float(row.get("value") or row.get("fuel_liters"))
            if epoch_ms is None or fuel_liters is None:
                continue
            alerts.append(
                {
                    "alert_name": alert_name,
                    "epoch_ms": epoch_ms,
                    "fuel_liters": fuel_liters,
                    "vehicle_number": default_vehicle,
                }
            )
    alerts.sort(key=lambda item: (item["epoch_ms"], item["alert_name"]))
    return alerts


def _daily_unit_readings(site: Site, reading_date: date) -> list[DailySiteReading]:
    return list(
        DailySiteReading.objects.using(_main_database_alias())
        .filter(
            associated_Site=site,
            reading_for=reading_date,
            aisle_group__power_source__gte=1,
        )
        .exclude(aisle_group_id__isnull=True)
        .order_by("aisle_group_id", "id")
    )


def _unit_source_status_for_day(authoritative_daily: list[DailySiteReading]) -> str:
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


def _best_dg_end_time_for_unit(
    site: Site, aisle_group_id: int, reading_date: date
) -> datetime | None:
    hourly_reading = (
        HourlySiteReading.objects.using(_main_database_alias())
        .filter(
            associated_Site=site,
            aisle_group_id=aisle_group_id,
            reading_from__date=reading_date,
        )
        .exclude(reading_to__isnull=True)
        .order_by("-reading_to", "-id")
        .first()
    )
    if hourly_reading and hourly_reading.reading_to:
        return hourly_reading.reading_to
    return None


def _existing_unit_row(
    site: Site, reading_date: date, aisle_group_id: int
) -> DgUnitConsumption | None:
    epoch_time = str(_day_epoch_ms(reading_date))
    search_order = (
        {"epoch_time": epoch_time},
        {"created__date": reading_date},
        {"dg_start_date__date": reading_date},
        {"dg_end_date__date": reading_date},
    )
    for filters in search_order:
        row = (
            DgUnitConsumption.objects.filter(
                site=site,
                aisle_group_id=aisle_group_id,
                **filters,
            )
            .order_by("id")
            .first()
        )
        if row is not None:
            return row
    return None


def _reconcile_units_and_fuel(
    site: Site,
    reading_date: date,
    payload: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
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

    authoritative_daily = _daily_unit_readings(site, reading_date)
    if not authoritative_daily:
        unit_counts["deferred_no_daily_reading"] = 1
        fuel_counts["deferred_no_unit_row"] = 1
        return {
            "unit_counts": unit_counts,
            "fuel_counts": fuel_counts,
            "unit_rows_touched": [],
        }

    unit_counts["unit_source_status"] = _unit_source_status_for_day(authoritative_daily)
    fuel_consumed = _loconav_daily_fuel_consumed(payload)
    day_start, _ = _day_window(reading_date)
    epoch_time = str(_day_epoch_ms(reading_date))
    unit_rows_touched: list[dict[str, Any]] = []
    seen_aisles: set[int] = set()

    for daily_row in authoritative_daily:
        aisle_id = daily_row.aisle_group_id
        if aisle_id is None or aisle_id in seen_aisles:
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

        preexisting_unit = _existing_unit_row(site, reading_date, aisle_id)
        if dry_run:
            unit_row = preexisting_unit
            if unit_row is None:
                unit_counts["created"] += 1
                unit_status = "CREATED"
            else:
                current_value = as_float(unit_row.unit_consumption)
                if (
                    current_value is not None
                    and abs(current_value - daily_value) < 1e-9
                ):
                    unit_counts["existing_correct"] += 1
                    unit_status = "EXISTING_CORRECT"
                else:
                    unit_counts["corrected"] += 1
                    unit_status = "CORRECTED"
        else:
            unit_row = preexisting_unit
            best_dg_end_time = _best_dg_end_time_for_unit(site, aisle_id, reading_date)
            if unit_row is None:
                unit_row = DgUnitConsumption.objects.create(
                    site=site,
                    aisle_group_id=aisle_id,
                    unit_consumption=daily_value,
                    dg_fuel_consumption=None,
                    created=day_start,
                    dg_start_date=day_start,
                    dg_end_date=best_dg_end_time,
                    epoch_time=epoch_time,
                    is_dg_on=False,
                    fetch_fuel_data=True,
                )
                unit_counts["created"] += 1
                unit_status = "CREATED"
            else:
                update_fields: list[str] = []
                previous_value = as_float(unit_row.unit_consumption)
                if previous_value != daily_value:
                    unit_row.unit_consumption = daily_value
                    update_fields.append("unit_consumption")
                if unit_row.created != day_start:
                    unit_row.created = day_start
                    update_fields.append("created")
                if unit_row.dg_start_date != day_start:
                    unit_row.dg_start_date = day_start
                    update_fields.append("dg_start_date")
                if unit_row.dg_end_date != best_dg_end_time:
                    unit_row.dg_end_date = best_dg_end_time
                    update_fields.append("dg_end_date")
                if unit_row.epoch_time != epoch_time:
                    unit_row.epoch_time = epoch_time
                    update_fields.append("epoch_time")
                if (
                    unit_row.dg_fuel_consumption is None
                    and not unit_row.fetch_fuel_data
                ):
                    unit_row.fetch_fuel_data = True
                    update_fields.append("fetch_fuel_data")
                if update_fields:
                    unit_row.save(update_fields=update_fields)
                if previous_value == daily_value and not update_fields:
                    unit_counts["existing_correct"] += 1
                    unit_status = "EXISTING_CORRECT"
                else:
                    unit_counts["corrected"] += 1
                    unit_status = "CORRECTED"

        if unit_row is None:
            fuel_counts["deferred_no_unit_row"] += 1
            fuel_status = "DEFERRED_NO_UNIT_ROW"
        else:
            current_fuel = as_float(unit_row.dg_fuel_consumption)
            if fuel_consumed is None:
                fuel_counts["deferred_no_unit_row"] += 1
                fuel_status = "DEFERRED_NO_UNIT_ROW"
            elif current_fuel is not None and abs(current_fuel - fuel_consumed) < 1e-9:
                fuel_counts["existing_correct"] += 1
                fuel_status = "EXISTING_CORRECT"
            elif current_fuel is None:
                fuel_counts["updated"] += 1
                fuel_status = "UPDATED"
            else:
                fuel_counts["corrected"] += 1
                fuel_status = "CORRECTED"

            if (
                not dry_run
                and fuel_consumed is not None
                and current_fuel != fuel_consumed
            ):
                unit_row.dg_fuel_consumption = fuel_consumed
                unit_row.fetch_fuel_data = False
                unit_row.save(update_fields=["dg_fuel_consumption", "fetch_fuel_data"])

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


def _level_row_matches(row: DgFuelConsumptionData, fuel_liters: float) -> bool:
    existing_value = as_float(getattr(row, "fuel_consumption", None))
    if existing_value is None:
        return False
    return abs(existing_value - fuel_liters) < 1e-9


def _alert_row_matches(row: DGFuelAlertsData, fuel_liters: float) -> bool:
    existing_value = as_float(getattr(row, "fuel_consumption", None))
    if existing_value is None:
        return False
    return abs(existing_value - fuel_liters) < 1e-9


def _save_level(site: Site, sample: dict[str, Any]) -> str:
    row = (
        DgFuelConsumptionData.objects.filter(
            site=site,
            vehicle_number=str(sample["vehicle_number"]),
            epoch_time=str(sample["epoch_ms"]),
        )
        .order_by("id")
        .first()
    )
    if row is None:
        record_fuel_level(
            site=site,
            vehicle_number=sample["vehicle_number"],
            fuel_liters=sample["fuel_liters"],
            epoch_value=sample["epoch_ms"],
            source=sample["source"],
        )
        return "created"

    if _level_row_matches(row, sample["fuel_liters"]):
        return "existing"

    row.fuel_consumption = sample["fuel_liters"]
    row.fuel_data_source = sample["source"]
    row.save(update_fields=["fuel_consumption", "fuel_data_source"])
    return "corrected"


def _save_alert(site: Site, alert: dict[str, Any]) -> str:
    row = (
        DGFuelAlertsData.objects.filter(
            site=site,
            vehicle_number=str(alert["vehicle_number"]),
            alert_name=alert["alert_name"],
            epoch_time=str(alert["epoch_ms"]),
        )
        .order_by("id")
        .first()
    )
    if row is None:
        record_fuel_alert(
            site=site,
            vehicle_number=alert["vehicle_number"],
            alert_name=alert["alert_name"],
            fuel_liters=alert["fuel_liters"],
            epoch_value=alert["epoch_ms"],
        )
        return "created"

    if _alert_row_matches(row, alert["fuel_liters"]):
        return "existing"

    row.fuel_consumption = alert["fuel_liters"]
    row.save(update_fields=["fuel_consumption"])
    return "corrected"


def _process_day(site: Site, reading_date: date, save: bool) -> dict[str, Any]:
    day_start, day_end = _day_window(reading_date)
    vehicle_number = _vehicle_number_for_site(site)
    if not vehicle_number:
        return {
            "date": reading_date.isoformat(),
            "status": "NO_VEHICLE",
            "fuel_level_samples": 0,
            "fuel_level_value": None,
            "fuel_consumed": None,
            "refuel_total": None,
            "theft_total": None,
            "refuel_events": 0,
            "theft_events": 0,
            "alert_samples": 0,
            "created": 0,
            "existing": 0,
            "corrected": 0,
            "alerts_created": 0,
            "alerts_existing": 0,
            "alerts_corrected": 0,
            "dg_unit": {},
            "dg_fuel": {},
        }

    payload = fetch_loconav_report(vehicle_number, day_start, day_end)
    if payload is None:
        _save_payload_response(
            site=site, reading_date=reading_date, payload=None, status="NO_DATA"
        )
        return {
            "date": reading_date.isoformat(),
            "status": "NO_DATA",
            "fuel_level_samples": 0,
            "fuel_level_value": None,
            "fuel_consumed": None,
            "refuel_total": None,
            "theft_total": None,
            "refuel_events": 0,
            "theft_events": 0,
            "alert_samples": 0,
            "created": 0,
            "existing": 0,
            "corrected": 0,
            "alerts_created": 0,
            "alerts_existing": 0,
            "alerts_corrected": 0,
            "dg_unit": {},
            "dg_fuel": {},
        }

    if not isinstance(payload, dict):
        _save_payload_response(
            site=site, reading_date=reading_date, payload=payload, status="NON_DICT"
        )
        return {
            "date": reading_date.isoformat(),
            "status": "NO_DATA",
            "fuel_level_samples": 0,
            "fuel_level_value": None,
            "fuel_consumed": None,
            "refuel_total": None,
            "theft_total": None,
            "refuel_events": 0,
            "theft_events": 0,
            "alert_samples": 0,
            "created": 0,
            "existing": 0,
            "corrected": 0,
            "alerts_created": 0,
            "alerts_existing": 0,
            "alerts_corrected": 0,
            "dg_unit": {},
            "dg_fuel": {},
        }

    if extract_loconav_subscription_expired_errors(payload):
        _save_payload_response(
            site=site,
            reading_date=reading_date,
            payload=payload,
            status="SUBSCRIPTION_EXPIRED",
        )
        return {
            "date": reading_date.isoformat(),
            "status": "SUBSCRIPTION_EXPIRED",
            "fuel_level_samples": 0,
            "fuel_level_value": None,
            "fuel_consumed": None,
            "refuel_total": None,
            "theft_total": None,
            "refuel_events": 0,
            "theft_events": 0,
            "alert_samples": 0,
            "created": 0,
            "existing": 0,
            "corrected": 0,
            "alerts_created": 0,
            "alerts_existing": 0,
            "alerts_corrected": 0,
            "dg_unit": {},
            "dg_fuel": {},
        }

    fuel_level_sample = _loconav_fuel_level_sample(
        payload, vehicle_number, reading_date
    )
    samples = [fuel_level_sample] if fuel_level_sample is not None else []
    alerts = _loconav_alerts_from_payload(payload, vehicle_number)
    fuel_consumed = _loconav_daily_fuel_consumed(payload)
    refuel_total = _loconav_daily_refuel_total(payload)
    theft_total = _loconav_daily_theft_total(payload)
    _save_payload_response(
        site=site, reading_date=reading_date, payload=payload, status="OK"
    )

    created = existing = corrected = 0
    alerts_created = alerts_existing = alerts_corrected = 0
    unit_summary: dict[str, Any] = {
        "unit_counts": {},
        "fuel_counts": {},
        "unit_rows_touched": [],
    }

    if save:
        with transaction.atomic():
            for sample in samples:
                result = _save_level(site, sample)
                if result == "created":
                    created += 1
                elif result == "existing":
                    existing += 1
                else:
                    corrected += 1
            for alert in alerts:
                result = _save_alert(site, alert)
                if result == "created":
                    alerts_created += 1
                elif result == "existing":
                    alerts_existing += 1
                else:
                    alerts_corrected += 1
            unit_summary = _reconcile_units_and_fuel(
                site, reading_date, payload, dry_run=False
            )
    else:
        for sample in samples:
            row = (
                DgFuelConsumptionData.objects.filter(
                    site=site,
                    vehicle_number=sample["vehicle_number"],
                    epoch_time=str(sample["epoch_ms"]),
                )
                .order_by("id")
                .first()
            )
            if row is None:
                created += 1
            elif _level_row_matches(row, sample["fuel_liters"]):
                existing += 1
            else:
                corrected += 1
        for alert in alerts:
            row = (
                DGFuelAlertsData.objects.filter(
                    site=site,
                    vehicle_number=alert["vehicle_number"],
                    alert_name=alert["alert_name"],
                    epoch_time=str(alert["epoch_ms"]),
                )
                .order_by("id")
                .first()
            )
            if row is None:
                alerts_created += 1
            elif _alert_row_matches(row, alert["fuel_liters"]):
                alerts_existing += 1
            else:
                alerts_corrected += 1

        unit_summary = _reconcile_units_and_fuel(
            site, reading_date, payload, dry_run=True
        )

    unit_counts = unit_summary.get("unit_counts", {})
    fuel_counts = unit_summary.get("fuel_counts", {})
    fuel_level_value = fuel_level_sample["fuel_liters"] if fuel_level_sample else None
    refuel_events = len(detect_refuel_from_alerts(payload))
    theft_events = len(detect_theft_from_alerts(payload))
    return {
        "date": reading_date.isoformat(),
        "status": "OK" if (samples or alerts or unit_counts) else "NO_DATA",
        "fuel_level_samples": len(samples),
        "fuel_level_value": fuel_level_value,
        "fuel_consumed": fuel_consumed,
        "refuel_total": refuel_total,
        "theft_total": theft_total,
        "refuel_events": refuel_events,
        "theft_events": theft_events,
        "alert_samples": len(alerts),
        "created": created,
        "existing": existing,
        "corrected": corrected,
        "alerts_created": alerts_created,
        "alerts_existing": alerts_existing,
        "alerts_corrected": alerts_corrected,
        "dg_unit": unit_counts,
        "dg_fuel": fuel_counts,
    }


def build_report(site: Site, days: int, save: bool) -> dict[str, Any]:
    start_date, end_date = _current_local_date_window(days)
    days_out: list[dict[str, Any]] = []
    totals: dict[str, int] = {
        "fuel_level_samples": 0,
        "alert_samples": 0,
        "created": 0,
        "existing": 0,
        "corrected": 0,
        "alerts_created": 0,
        "alerts_existing": 0,
        "alerts_corrected": 0,
        "dg_unit_created": 0,
        "dg_unit_existing_correct": 0,
        "dg_unit_corrected": 0,
        "dg_unit_deferred_no_daily_reading": 0,
        "dg_unit_ignored_below_threshold": 0,
        "dg_unit_failed": 0,
        "dg_fuel_updated": 0,
        "dg_fuel_existing_correct": 0,
        "dg_fuel_corrected": 0,
        "dg_fuel_deferred_no_unit_row": 0,
    }

    current_date = start_date
    while current_date <= end_date:
        day_result = _process_day(site, current_date, save=save)
        days_out.append(day_result)
        for key in (
            "fuel_level_samples",
            "alert_samples",
            "created",
            "existing",
            "corrected",
            "alerts_created",
            "alerts_existing",
            "alerts_corrected",
        ):
            totals[key] += int(day_result.get(key, 0) or 0)
        unit_counts = day_result.get("dg_unit", {}) or {}
        fuel_counts = day_result.get("dg_fuel", {}) or {}
        for key in (
            "created",
            "existing_correct",
            "corrected",
            "deferred_no_daily_reading",
            "ignored_below_threshold",
            "failed",
        ):
            totals[f"dg_unit_{key}"] += int(unit_counts.get(key, 0) or 0)
        for key in (
            "updated",
            "existing_correct",
            "corrected",
            "deferred_no_unit_row",
        ):
            totals[f"dg_fuel_{key}"] += int(fuel_counts.get(key, 0) or 0)
        current_date += timedelta(days=1)

    return {
        "site_id": site.id,
        "site_name": getattr(site, "site_name", None),
        "provider": DEFAULT_PROVIDER,
        "vehicle_number": _vehicle_number_for_site(site),
        "save": save,
        "database_default": _database_identity("default"),
        "database_main": _database_identity(_main_database_alias()),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": days_out,
        "totals": totals,
    }


def _print_day(day_result: dict[str, Any]) -> None:
    parts = [
        day_result.get("date"),
        day_result.get("status"),
        f"fuel_level={day_result.get('fuel_level_value')}",
        f"fuel_consumed={day_result.get('fuel_consumed')}",
        f"refuel={day_result.get('refuel_total')}",
        f"theft={day_result.get('theft_total')}",
        f"fuel_level_samples={day_result.get('fuel_level_samples', 0)}",
        f"alerts={day_result.get('alert_samples', 0)}",
        f"created={day_result.get('created', 0)}",
        f"existing={day_result.get('existing', 0)}",
        f"corrected={day_result.get('corrected', 0)}",
        f"alerts_created={day_result.get('alerts_created', 0)}",
        f"alerts_existing={day_result.get('alerts_existing', 0)}",
        f"alerts_corrected={day_result.get('alerts_corrected', 0)}",
        f"unit_source={((day_result.get('dg_unit') or {}).get('unit_source_status'))}",
        (
            f"dg_unit={(day_result.get('dg_unit') or {}).get('created', 0)}/"
            f"{(day_result.get('dg_unit') or {}).get('existing_correct', 0)}/"
            f"{(day_result.get('dg_unit') or {}).get('corrected', 0)}"
        ),
        (
            f"dg_fuel={(day_result.get('dg_fuel') or {}).get('updated', 0)}/"
            f"{(day_result.get('dg_fuel') or {}).get('existing_correct', 0)}/"
            f"{(day_result.get('dg_fuel') or {}).get('corrected', 0)}"
        ),
    ]
    print(" | ".join(str(part) for part in parts))


def _print_summary(report: dict[str, Any]) -> None:
    print(
        f"site={report['site_id']} provider={report['provider']} vehicle={report['vehicle_number']} "
        f"range={report['start_date']}..{report['end_date']} save={report['save']}"
    )
    print(
        f"databases | default={report['database_default']} | main={report['database_main']}"
    )
    for day_result in report["days"]:
        _print_day(day_result)
    totals = report["totals"]
    print(
        "totals | "
        f"fuel_level={totals['fuel_level_samples']} | alerts={totals['alert_samples']} | "
        f"created={totals['created']} | existing={totals['existing']} | corrected={totals['corrected']} | "
        f"alerts_created={totals['alerts_created']} | alerts_existing={totals['alerts_existing']} | "
        f"alerts_corrected={totals['alerts_corrected']} | "
        f"dg_unit_created={totals['dg_unit_created']} | dg_unit_existing_correct={totals['dg_unit_existing_correct']} | "
        f"dg_unit_corrected={totals['dg_unit_corrected']} | dg_unit_deferred_no_daily_reading={totals['dg_unit_deferred_no_daily_reading']} | "
        f"dg_fuel_updated={totals['dg_fuel_updated']} | dg_fuel_existing_correct={totals['dg_fuel_existing_correct']} | "
        f"dg_fuel_corrected={totals['dg_fuel_corrected']} | dg_fuel_deferred_no_unit_row={totals['dg_fuel_deferred_no_unit_row']}"
    )


def _load_sites(site_id: int | None) -> Sequence[Site]:
    if site_id is not None:
        try:
            return [Site.objects.get(id=site_id)]
        except Site.DoesNotExist as exc:
            raise RuntimeError(f"Site {site_id} not found") from exc
    return Site.objects.filter(id__in=DEFAULT_SITE_IDS).order_by("id")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover historical LocoNav DG fuel rows"
    )
    parser.add_argument("--site", type=int, help="Recover one site only")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="Number of trailing days to recover",
    )
    parser.add_argument(
        "--save", action="store_true", help="Persist rows instead of running dry-run"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly run without persisting rows (default behavior)",
    )
    args = parser.parse_args()

    if args.save and args.dry_run:
        raise SystemExit("Choose only one of --save or --dry-run")

    sites = _load_sites(args.site)
    if not sites:
        print("No LocoNav sites found")
        return

    for site in sites:
        report = build_report(site, args.days, args.save)
        _print_summary(report)


if __name__ == "__main__":
    main()
