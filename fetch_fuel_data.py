#!/usr/bin/env python3
"""Live DG-fuel poller and retry runner.

This script keeps the legacy service entry point but routes all provider
collection and persistence through the normalized DG-fuel package.
"""

import logging
import os
import sys
import time
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
from wareApp.dg_fuel.ingestion import record_fuel_alert, record_fuel_level
from wareApp.dg_fuel.sessions import attempt_fetch_for_unit, reconcile_daily_unit_consumption
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
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
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
    variants = [normalized, normalized.upper(), normalized.lower(), normalized.replace(" ", "")]
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
                fuel_liters=(item.get("fuel_in_liters") if isinstance(item, dict) else None),
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


def update_dg_fuel_consumption_data():
    """Retry closed DG runs using the unified session helper."""
    sites = Site.objects.filter(dg_fuel_system_installed=True).only("id").order_by("id")
    for site in sites:
        reconcile_daily_unit_consumption(site)
    pending_units = DgUnitConsumption.objects.filter(fetch_fuel_data=True).order_by("id")
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

    pending_units = DgUnitConsumption.objects.filter(fetch_fuel_data=True).order_by("id")
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
    level_result = run_current_level_cycle()
    alert_result = poll_today_provider_alerts()
    retry_result = retry_closed_dg_runs()
    summary = {
        "level_cycle": level_result,
        "today_provider_alerts": alert_result,
        "closed_run_retry": retry_result,
    }
    logger.info("DG fuel cycle summary=%s", summary)
    print(summary)
    return summary


def main():
    while True:
        run_once()
        if RUN_ONCE:
            break
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()