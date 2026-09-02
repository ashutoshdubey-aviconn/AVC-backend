#!/usr/bin/env python3
"""Live DG-fuel poller and retry runner.

This script keeps the legacy service entry point but routes all provider
collection and persistence through the normalized DG-fuel package.
"""

import logging
import os
import sys
import time

import requests

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")

import django

django.setup()

from wareApp.dg_fuel.poller import collect_level_cycle
from wareApp.dg_fuel.normalization import epoch_milliseconds
from wareApp.dg_fuel.ingestion import record_fuel_level
from wareApp.dg_fuel.sessions import attempt_fetch_for_unit
from wareApp.models import DgUnitConsumption, Site


logger = logging.getLogger("wareApp.dg_fuel.fetch_fuel_data")

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
    retry_result = retry_closed_dg_runs()
    summary = {"level_cycle": level_result, "closed_run_retry": retry_result}
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