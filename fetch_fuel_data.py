#!/usr/bin/env python3
"""Live DG-fuel poller and retry runner.

This script keeps the legacy service entry point but routes all provider
collection and persistence through the normalized DG-fuel package.
"""

import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

import requests
from django.utils import timezone

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")

import django

django.setup()

from wareApp.dg_fuel.poller import collect_level_cycle
from wareApp.dg_fuel.normalization import epoch_milliseconds
from wareApp.dg_fuel.providers import (
    parse_loconav_current_levels,
    parse_roadcast_current_levels,
)
from wareApp.dg_fuel.ingestion import record_fuel_alert, record_fuel_level
from wareApp.dg_fuel.sessions import (
    attempt_fetch_for_unit,
    reconcile_daily_unit_consumption,
)
from wareApp.fuel_providers import (
    detect_refuel_from_alerts,
    detect_theft_from_alerts,
    fetch_loconav_report,
    fetch_roadcast_report,
)
from wareApp.models import DgUnitConsumption, Site

LOG_DIR = os.path.join(PROJECT_ROOT, "logges")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("wareApp.dg_fuel.fetch_fuel_data")
logger.setLevel(logging.INFO)
logger.propagate = False

for noisy_logger_name in (
    "wareApp.dg_fuel.collection",
    "wareApp.dg_fuel.ingestion",
    "wareApp.dg_fuel.sessions",
    "wareApp.fuel_providers",
):
    logging.getLogger(noisy_logger_name).setLevel(logging.WARNING)

if not logger.handlers:
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "dg_fuel.log"),
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
    )
    console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

LOCONAV_API_KEY = os.environ.get("LOCONAV_API_KEY", "51uKh_YaL72s7zhx6bwZ")
ROADCAST_USERNAME = os.environ.get("ROADCAST_USERNAME", "Aviconn")
ROADCAST_PASSWORD = os.environ.get("ROADCAST_PASSWORD", "Abc@1234")
POLL_INTERVAL_SECONDS = int(os.environ.get("DG_FUEL_POLL_INTERVAL_SECONDS", "300"))
RETRY_BATCH_SIZE = int(os.environ.get("DG_FUEL_RETRY_BATCH_SIZE", "100"))
RETRY_LIMIT_PER_CYCLE = int(os.environ.get("DG_FUEL_RETRY_LIMIT_PER_CYCLE", "500"))
RUN_ONCE = os.environ.get("RUN_ONCE", "").strip().lower() in {"1", "true", "yes", "on"}


def fetch_loconav(vehicle_number):
    response = requests.get(
        "https://marketplace.loconav.sensorise.net/api/v1/vehicles/fuel/current_levels",
        params={"vehicle_number": vehicle_number},
        headers={"User-Authentication": LOCONAV_API_KEY},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fetch_roadcast():
    response = requests.get(
        "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api",
        params={"username": ROADCAST_USERNAME, "password": ROADCAST_PASSWORD},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def request_json(url, headers=None, params=None, retries=2, timeout=10):
    """Compatibility wrapper for legacy tests and callers."""
    attempt = 0
    while attempt <= retries:
        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=timeout
            )
            try:
                body = response.json()
            except Exception:
                return None, response.text, response.status_code
            return body, response.text, response.status_code
        except Exception as error:
            attempt += 1
            if attempt > retries:
                return None, str(error), None
            time.sleep(0.5)


def epoch_ms_from_value(value):
    """Compatibility wrapper returning milliseconds as a string."""
    epoch_ms = epoch_milliseconds(value)
    return str(epoch_ms) if epoch_ms is not None else None


def vehicle_variants(value):
    if not value:
        return []
    normalized = str(value).strip()
    variants = [
        normalized,
        normalized.upper(),
        normalized.lower(),
        normalized.replace(" ", ""),
    ]
    compact = "".join(character for character in normalized if character.isalnum())
    if compact not in variants:
        variants.append(compact)
    seen = set()
    ordered = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return ordered


def run_current_level_cycle():
    sites = (
        Site.objects.filter(dg_fuel_system_installed=True)
        .only("id", "partner_dg_provider", "partner_dg_fuel_id")
        .order_by("id")
    )
    return collect_level_cycle(sites, fetch_loconav, fetch_roadcast, dry_run=False)


# def _today_provider_window():
#     current_time = timezone.localtime()
#     start_time = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
#     return start_time, current_time


def _today_provider_window():
    current_time = timezone.now()

    if timezone.is_naive(current_time):
        current_time = timezone.make_aware(
            current_time,
            timezone.get_current_timezone(),
        )

    current_time = timezone.localtime(current_time)
    start_time = current_time.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    return start_time, current_time


def _persist_today_provider_alerts(site, provider, fuel_id, report):
    if provider == "loconav":
        refuels = detect_refuel_from_alerts(report or {})
        thefts = detect_theft_from_alerts(report or {})
        for event in refuels:
            record_fuel_alert(
                site=site,
                vehicle_number=fuel_id,
                alert_name="refuel",
                fuel_liters=event.get("value"),
                epoch_value=event.get("timestamp"),
                created=timezone.now(),
            )
        for event in thefts:
            record_fuel_alert(
                site=site,
                vehicle_number=fuel_id,
                alert_name="theft",
                fuel_liters=event.get("value"),
                epoch_value=event.get("timestamp"),
                created=timezone.now(),
            )
        return {"refuels": len(refuels), "thefts": len(thefts)}

    if provider == "roadcast":
        refuels = (report or {}).get("refuels", []) or []
        thefts = (report or {}).get("thefts", []) or []
        for event in refuels:
            record_fuel_alert(
                site=site,
                vehicle_number=fuel_id,
                alert_name="refuel",
                fuel_liters=event.get("fuel_liters"),
                epoch_value=event.get("epoch_ms"),
                created=timezone.now(),
            )
        for event in thefts:
            record_fuel_alert(
                site=site,
                vehicle_number=fuel_id,
                alert_name="theft",
                fuel_liters=event.get("fuel_liters"),
                epoch_value=event.get("epoch_ms"),
                created=timezone.now(),
            )
        return {"refuels": len(refuels), "thefts": len(thefts)}

    return {"refuels": 0, "thefts": 0}


def poll_today_provider_alerts():
    start_time, end_time = _today_provider_window()
    sites = (
        Site.objects.filter(dg_fuel_system_installed=True)
        .only("id", "partner_dg_provider", "partner_dg_fuel_id")
        .order_by("id")
    )
    result = {
        "start_time": start_time,
        "end_time": end_time,
        "attempted": 0,
        "refuels": 0,
        "thefts": 0,
        "failed_site_ids": [],
        "skipped_site_ids": [],
    }

    for site in sites:
        provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
        fuel_id = (getattr(site, "partner_dg_fuel_id", None) or "").strip()
        if provider not in {"loconav", "roadcast"} or not fuel_id:
            result["skipped_site_ids"].append(site.id)
            logger.warning(
                "Skipping provider alert poll site_id=%s provider=%s vehicle_number=%s reason=%s",
                site.id,
                provider,
                fuel_id,
                "missing_or_unsupported_provider",
            )
            continue

        result["attempted"] += 1
        try:
            if provider == "loconav":
                report = fetch_loconav_report(fuel_id, start_time, end_time)
            else:
                report = fetch_roadcast_report(fuel_id, start_time, end_time)

            if not isinstance(report, dict):
                result["failed_site_ids"].append(site.id)
                logger.warning(
                    "Provider alert poll returned no report site_id=%s provider=%s vehicle_number=%s start_time=%s end_time=%s",
                    site.id,
                    provider,
                    fuel_id,
                    start_time,
                    end_time,
                )
                continue

            counts = _persist_today_provider_alerts(site, provider, fuel_id, report)
            result["refuels"] += counts["refuels"]
            result["thefts"] += counts["thefts"]
        except Exception:
            result["failed_site_ids"].append(site.id)
            logger.exception(
                "Provider alert poll failed site_id=%s provider=%s vehicle_number=%s start_time=%s end_time=%s",
                site.id,
                provider,
                fuel_id,
                start_time,
                end_time,
            )

    logger.info("Today provider alert poll result=%s", result)
    return result


def fetch_real_time_data():
    """Legacy compatibility path used by older tests and scripts.

    The live service should use `run_once()`, but this helper preserves the old
    one-shot Loconav ingestion behavior for regression coverage.
    """
    headers = {"User-Authentication": LOCONAV_API_KEY}
    sites = Site.objects.filter(dg_fuel_system_installed=True).order_by("id")
    for site in sites:
        vehicle_number = (site.partner_dg_fuel_id or "").strip()
        if not vehicle_number:
            continue
        response, raw, status = request_json(
            "https://marketplace.loconav.sensorise.net/api/v1/vehicles/fuel/current_levels",
            headers=headers,
            params={"vehicle_number": vehicle_number},
            timeout=20,
        )
        if not isinstance(response, dict) or not response.get("data"):
            continue
        for item in response["data"]:
            epoch_value = None
            if isinstance(item, dict):
                epoch_value = item.get("timestamp") or item.get("time")
            epoch_ms = epoch_ms_from_value(epoch_value)
            if not epoch_ms:
                continue
            record_fuel_level(
                site=site,
                vehicle_number=vehicle_number,
                fuel_liters=(
                    item.get("fuel_in_liters") if isinstance(item, dict) else None
                ),
                epoch_value=epoch_ms,
                source="loconav",
            )


def fetch_interval_data():
    """Legacy compatibility helper retained for older callers."""
    return None


def fetch_alerts_data():
    """Legacy compatibility helper retained for older callers."""
    return None


def fetchDataAndUpdate(site_id):
    """Legacy compatibility helper retained for older callers."""
    site = Site.objects.get(id=site_id)
    return site


def get_fuel_data_roadcaste():
    """Legacy compatibility helper retained for older callers."""
    return run_current_level_cycle()


def _provider_label(provider):
    if provider == "loconav":
        return "LocoNav"
    if provider == "roadcast":
        return "Roadcast"
    return "Unknown"


def _cycle_window():
    current_time = timezone.now()
    if timezone.is_naive(current_time):
        current_time = timezone.make_aware(
            current_time, timezone.get_current_timezone()
        )
    current_time = timezone.localtime(current_time)
    cycle_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
    return cycle_start, current_time


def _display_clock(epoch_value):
    epoch_ms = epoch_milliseconds(epoch_value)
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(
        epoch_ms / 1000, tz=timezone.get_current_timezone()
    ).strftime("%H:%M")


def _log_lines(lines):
    for line in lines:
        logger.info(line)


def _fetch_site_fuel_level(site):
    provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
    vehicle_number = (getattr(site, "partner_dg_fuel_id", None) or "").strip()
    result = {
        "api_status": "FAILED",
        "fuel_liters": None,
        "database_status": "NOT CREATED",
        "created": None,
        "reason": None,
    }

    try:
        if provider == "loconav":
            payload = fetch_loconav(vehicle_number)
            levels = parse_loconav_current_levels(payload)
            if levels:
                sample = max(levels, key=lambda item: item["epoch_ms"])
                result["api_status"] = "SUCCESS"
                result["fuel_liters"] = sample["fuel_liters"]
                _, created = record_fuel_level(
                    site=site,
                    vehicle_number=sample["vehicle_number"],
                    fuel_liters=sample["fuel_liters"],
                    epoch_value=sample["epoch_ms"],
                    source="loconav",
                )
                result["database_status"] = "CREATED" if created else "EXISTING"
                result["created"] = created
            else:
                result["reason"] = "NO USABLE VALUE"
        elif provider == "roadcast":
            payload = fetch_roadcast()
            levels = parse_roadcast_current_levels(payload, [vehicle_number])
            if levels:
                sample = max(levels, key=lambda item: item["epoch_ms"])
                result["api_status"] = "SUCCESS"
                result["fuel_liters"] = sample["fuel_liters"]
                _, created = record_fuel_level(
                    site=site,
                    vehicle_number=sample["vehicle_number"],
                    fuel_liters=sample["fuel_liters"],
                    epoch_value=sample["epoch_ms"],
                    source="roadcast",
                )
                result["database_status"] = "CREATED" if created else "EXISTING"
                result["created"] = created
            else:
                result["reason"] = "DEVICE UNAVAILABLE"
        else:
            result["reason"] = "UNSUPPORTED PROVIDER"
    except Exception as exc:
        result["reason"] = str(exc)
        result["api_status"] = "FAILED"

    return result


def _fetch_site_alerts(site, cycle_start, cycle_end):
    provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
    vehicle_number = (getattr(site, "partner_dg_fuel_id", None) or "").strip()
    result = {
        "api_status": "FAILED",
        "refuels": [],
        "thefts": [],
    }

    try:
        if provider == "loconav":
            report = fetch_loconav_report(vehicle_number, cycle_start, cycle_end)
            if isinstance(report, dict):
                result["api_status"] = "SUCCESS"
                result["refuels"] = detect_refuel_from_alerts(report)
                result["thefts"] = detect_theft_from_alerts(report)
            else:
                result["reason"] = "NO REPORT"
        elif provider == "roadcast":
            report = fetch_roadcast_report(vehicle_number, cycle_start, cycle_end)
            if isinstance(report, dict):
                result["api_status"] = "SUCCESS"
                result["refuels"] = report.get("refuels", []) or []
                result["thefts"] = report.get("thefts", []) or []
            else:
                result["reason"] = "NO REPORT"
        else:
            result["reason"] = "UNSUPPORTED PROVIDER"
    except Exception as exc:
        result["reason"] = str(exc)
        result["api_status"] = "FAILED"

    persisted_refuels = []
    for event in result["refuels"]:
        fuel_value = (
            event.get("value") if "value" in event else event.get("fuel_liters")
        )
        epoch_value = (
            event.get("timestamp") if "timestamp" in event else event.get("epoch_ms")
        )
        _, created = record_fuel_alert(
            site=site,
            vehicle_number=vehicle_number,
            alert_name="refuel",
            fuel_liters=fuel_value,
            epoch_value=epoch_value,
            created=timezone.now(),
        )
        persisted_refuels.append(
            {
                "fuel_liters": fuel_value,
                "epoch_value": epoch_value,
                "created": created,
            }
        )

    persisted_thefts = []
    for event in result["thefts"]:
        fuel_value = (
            event.get("value") if "value" in event else event.get("fuel_liters")
        )
        epoch_value = (
            event.get("timestamp") if "timestamp" in event else event.get("epoch_ms")
        )
        _, created = record_fuel_alert(
            site=site,
            vehicle_number=vehicle_number,
            alert_name="theft",
            fuel_liters=fuel_value,
            epoch_value=epoch_value,
            created=timezone.now(),
        )
        persisted_thefts.append(
            {
                "fuel_liters": fuel_value,
                "epoch_value": epoch_value,
                "created": created,
            }
        )

    result["persisted_refuels"] = persisted_refuels
    result["persisted_thefts"] = persisted_thefts
    return result


def _fetch_site_dg_fuel(site, reading_date, unit_rows):
    results = []
    for row in unit_rows:
        unit_id = row.get("unit_id")
        if not unit_id:
            continue
        unit = DgUnitConsumption.objects.filter(id=unit_id, site=site).first()
        if not unit:
            continue
        if unit.dg_fuel_consumption is not None and not unit.fetch_fuel_data:
            results.append(
                {
                    "unit_id": unit.id,
                    "aisle_group_id": row.get("aisle_group_id"),
                    "status": "EXISTING",
                    "fuel_value": unit.dg_fuel_consumption,
                    "database_action": "EXISTING",
                    "confirmed_zero": unit.dg_fuel_consumption == 0,
                    "unit_consumption": unit.unit_consumption,
                }
            )
            continue

        detail = attempt_fetch_for_unit(unit, return_details=True)
        detail["aisle_group_id"] = row.get("aisle_group_id")
        detail["unit_consumption"] = unit.unit_consumption
        results.append(detail)

    return results


def _run_site_cycle(site, cycle_start, cycle_end):
    provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
    vehicle_number = (getattr(site, "partner_dg_fuel_id", None) or "").strip()
    provider_label = _provider_label(provider)
    site_result = {
        "site_id": site.id,
        "provider": provider,
        "vehicle_number": vehicle_number,
        "fuel_level": None,
        "refuels": [],
        "thefts": [],
        "dg_units": [],
        "dg_fuel": [],
        "dg_per_litre": [],
        "stopped": False,
        "stop_reason": None,
    }

    _log_lines(["", f"SITE {site.id} | {provider_label} | {vehicle_number}"])

    fuel_level_result = _fetch_site_fuel_level(site)
    site_result["fuel_level"] = fuel_level_result
    if (
        fuel_level_result["api_status"] != "SUCCESS"
        or fuel_level_result["fuel_liters"] is None
    ):
        _log_lines(
            [
                "[1] Fuel Level",
                f"    API      : {fuel_level_result['api_status']} / {fuel_level_result.get('reason') or 'DEVICE UNAVAILABLE'}",
                "    Database : NOT CREATED",
                f"  >>> STOP SITE {site.id}",
                "      Reason: no fuel level",
            ]
        )
        site_result["stopped"] = True
        site_result["stop_reason"] = "no fuel level"
        return site_result

    _log_lines(
        [
            "[1] Fuel Level",
            "    API      : SUCCESS",
            f"    Fuel     : {fuel_level_result['fuel_liters']:.2f} L",
            f"    Database : {fuel_level_result['database_status']}",
        ]
    )

    alert_result = _fetch_site_alerts(site, cycle_start, cycle_end)
    refuels = alert_result.get("persisted_refuels", [])
    thefts = alert_result.get("persisted_thefts", [])
    site_result["refuels"] = refuels
    site_result["thefts"] = thefts

    if refuels:
        _log_lines(
            [
                "[2] Refuel",
                f"    Result   : {len(refuels)} event{'s' if len(refuels) != 1 else ''}",
            ]
        )
        for event in refuels:
            timestamp_display = _display_clock(event.get("epoch_value"))
            event_line = f"    {event['fuel_liters']:.2f} L"
            if timestamp_display:
                event_line += f" @ {timestamp_display}"
            event_line += f" | {'CREATED' if event['created'] else 'EXISTING'}"
            _log_lines([event_line])
    else:
        _log_lines(["[2] Refuel", "    Result   : NONE"])

    if thefts:
        _log_lines(
            [
                "[3] Fuel Theft",
                f"    Result   : {len(thefts)} event{'s' if len(thefts) != 1 else ''}",
            ]
        )
        for event in thefts:
            timestamp_display = _display_clock(event.get("epoch_value"))
            event_line = f"    {event['fuel_liters']:.2f} L"
            if timestamp_display:
                event_line += f" @ {timestamp_display}"
            event_line += f" | {'CREATED' if event['created'] else 'EXISTING'}"
            _log_lines([event_line])
    else:
        _log_lines(["[3] Fuel Theft", "    Result   : NONE"])

    unit_result = reconcile_daily_unit_consumption(
        site, reading_date=cycle_start.date(), return_details=True
    )
    dg_rows = unit_result.get("rows", [])
    site_result["dg_units"] = dg_rows
    if dg_rows:
        for index, row in enumerate(dg_rows, start=1):
            step_label = (
                "[4] DG Unit Consumption"
                if index == 1
                else f"[4] DG Unit Consumption #{index}"
            )
            _log_lines(
                [
                    step_label,
                    "    MAIN DailySiteReading",
                    f"    Aisle    : {row.get('aisle_group_id')}",
                    f"    Value    : {row.get('daily_reading_value') if row.get('daily_reading_value') is not None else 'NOT AVAILABLE'}",
                    f"    Database : {row.get('status')}",
                ]
            )
    else:
        _log_lines(
            [
                "[4] DG Unit Consumption",
                "    MAIN DailySiteReading",
                "    Result   : NOT AVAILABLE",
            ]
        )

    dg_fuel_rows = _fetch_site_dg_fuel(site, cycle_start.date(), dg_rows)
    site_result["dg_fuel"] = dg_fuel_rows
    for index, row in enumerate(dg_fuel_rows, start=1):
        step_label = (
            "[5] DG Fuel Consumption"
            if index == 1
            else f"[5] DG Fuel Consumption #{index}"
        )
        _log_lines([step_label])
        if row.get("status") == "UNAVAILABLE":
            _log_lines(["    Provider : UNAVAILABLE - not created"])
        elif row.get("confirmed_zero"):
            _log_lines(
                [
                    "    Provider : CONFIRMED ZERO",
                    f"    Database : {row.get('database_action')}",
                ]
            )
        else:
            fuel_value = row.get("fuel_value")
            _log_lines(
                [
                    (
                        f"    Provider : {fuel_value:.2f} L"
                        if isinstance(fuel_value, (int, float))
                        else "    Provider : NOT AVAILABLE"
                    ),
                    f"    Database : {row.get('database_action') or row.get('status')}",
                ]
            )

        unit_consumption = row.get("unit_consumption")
        fuel_value = row.get("fuel_value")
        if unit_consumption is None:
            _log_lines(
                [
                    "[6] DG Unit Per Litre",
                    "    Result   : NOT CALCULATED - unit unavailable",
                ]
            )
            continue
        if fuel_value is None:
            _log_lines(
                [
                    "[6] DG Unit Per Litre",
                    "    Result   : NOT CALCULATED - fuel unavailable",
                ]
            )
            continue
        if fuel_value == 0:
            _log_lines(
                [
                    "[6] DG Unit Per Litre",
                    "    Result   : NOT CALCULATED - fuel is zero",
                ]
            )
            continue

        dg_per_litre = unit_consumption / fuel_value
        site_result["dg_per_litre"].append(dg_per_litre)
        _log_lines(
            [
                "[6] DG Unit Per Litre",
                f"    Calculation : {unit_consumption} / {fuel_value}",
                f"    Result      : {dg_per_litre:.2f}",
            ]
        )

    return site_result


def run_dg_fuel_cycle():
    cycle_start, cycle_end = _cycle_window()
    sites = (
        Site.objects.filter(dg_fuel_system_installed=True)
        .only("id", "partner_dg_provider", "partner_dg_fuel_id")
        .order_by("id")
    )

    _log_lines(
        [
            "============================================================",
            f"DG FUEL CYCLE START | {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}",
            "============================================================",
        ]
    )

    summary = {
        "sites_processed": 0,
        "fuel_levels": {"created": 0, "existing": 0, "failed": 0},
        "refuels": {"created": 0, "existing": 0},
        "thefts": {"created": 0, "existing": 0},
        "dg_units": {"created": 0, "updated": 0, "existing": 0, "unavailable": 0},
        "dg_fuel": {"created": 0, "updated": 0, "existing": 0, "unavailable": 0},
        "dg_per_litre": {"calculated": 0},
        "sites": [],
    }

    for site in sites:
        summary["sites_processed"] += 1
        site_result = _run_site_cycle(site, cycle_start, cycle_end)
        summary["sites"].append(site_result)

        fuel_level = site_result.get("fuel_level") or {}
        if fuel_level.get("api_status") == "SUCCESS":
            summary["fuel_levels"][
                "created" if fuel_level.get("created") else "existing"
            ] += 1
        else:
            summary["fuel_levels"]["failed"] += 1

        for event in site_result.get("refuels", []):
            summary["refuels"]["created" if event.get("created") else "existing"] += 1

        for event in site_result.get("thefts", []):
            summary["thefts"]["created" if event.get("created") else "existing"] += 1

        for row in site_result.get("dg_units", []):
            status = row.get("status")
            if status == "CREATED":
                summary["dg_units"]["created"] += 1
            elif status == "UPDATED":
                summary["dg_units"]["updated"] += 1
            elif status == "EXISTING":
                summary["dg_units"]["existing"] += 1
            else:
                summary["dg_units"]["unavailable"] += 1

        for row in site_result.get("dg_fuel", []):
            status = row.get("database_action") or row.get("status")
            if status == "CREATED":
                summary["dg_fuel"]["created"] += 1
            elif status == "UPDATED":
                summary["dg_fuel"]["updated"] += 1
            elif status == "EXISTING":
                summary["dg_fuel"]["existing"] += 1
            else:
                summary["dg_fuel"]["unavailable"] += 1

        summary["dg_per_litre"]["calculated"] += len(
            site_result.get("dg_per_litre", [])
        )

    _log_lines(
        [
            "============================================================",
            "DG FUEL CYCLE END",
            "============================================================",
            f"Sites processed : {summary['sites_processed']}",
            f"Fuel levels     : {summary['fuel_levels']['created']} created, {summary['fuel_levels']['existing']} existing, {summary['fuel_levels']['failed']} failed",
            f"Refuels         : {summary['refuels']['created']} created, {summary['refuels']['existing']} existing",
            f"Thefts          : {summary['thefts']['created']} created, {summary['thefts']['existing']} existing",
            f"DG units        : {summary['dg_units']['created']} created, {summary['dg_units']['updated']} updated, {summary['dg_units']['existing']} existing, {summary['dg_units']['unavailable']} unavailable",
            f"DG fuel         : {summary['dg_fuel']['created']} created, {summary['dg_fuel']['updated']} updated, {summary['dg_fuel']['existing']} existing, {summary['dg_fuel']['unavailable']} unavailable",
            f"DG/Litre        : {summary['dg_per_litre']['calculated']} calculated",
            "============================================================",
            "Next cycle in 5 minutes...",
        ]
    )

    return summary


def update_dg_fuel_consumption_data():
    """Retry closed DG runs using the unified session helper."""
    sites = Site.objects.filter(dg_fuel_system_installed=True).only("id").order_by("id")
    for site in sites:
        reconcile_daily_unit_consumption(site)
    pending_units = DgUnitConsumption.objects.filter(fetch_fuel_data=True).order_by(
        "id"
    )
    updated = 0
    attempted = 0
    for unit in pending_units.iterator(chunk_size=RETRY_BATCH_SIZE):
        if attempted >= RETRY_LIMIT_PER_CYCLE:
            break
        attempted += 1
        if attempt_fetch_for_unit(unit):
            updated += 1
    return {"attempted": attempted, "updated": updated}


def retry_closed_dg_runs():
    sites = Site.objects.filter(dg_fuel_system_installed=True).only("id").order_by("id")
    for site in sites:
        reconcile_daily_unit_consumption(site)

    pending_units = DgUnitConsumption.objects.filter(fetch_fuel_data=True).order_by(
        "id"
    )
    updated = 0
    failed = 0
    attempted = 0

    for unit in pending_units.iterator(chunk_size=RETRY_BATCH_SIZE):
        if attempted >= RETRY_LIMIT_PER_CYCLE:
            break
        attempted += 1
        try:
            if attempt_fetch_for_unit(unit):
                updated += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            logger.exception("Closed DG run retry failed for unit_id=%s", unit.id)

    result = {"attempted": attempted, "updated": updated, "failed": failed}
    logger.info("Closed DG run retry result=%s", result)
    return result


def run_once():
    summary = run_dg_fuel_cycle()
    logger.info("DG fuel cycle summary=%s", summary)
    return summary


def main():
    while True:
        run_once()
        if RUN_ONCE:
            break
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
