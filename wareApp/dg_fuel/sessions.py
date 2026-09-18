"""DG session lifecycle helpers for starting, updating, and closing runs."""

import logging
import time
from datetime import date as date_type
from datetime import datetime, time as datetime_time
from typing import Any

from django.conf import settings
from django.db import connections
from django.utils import timezone as dj_timezone

from wareApp.dg_fuel.normalization import as_float
from wareApp.fuel_providers import (
    detect_suspicious_fuel,
    detect_refuel_from_alerts,
    detect_theft_from_alerts,
    fetch_loconav_fuel,
    fetch_loconav_report,
    fetch_roadcast_fuel,
    fetch_roadcast_report,
)
from wareApp.dg_fuel.ingestion import record_fuel_alert
from wareApp.models import (
    DailySiteReading,
    DGFuelAlertsData,
    DgUnitConsumption,
    HourlySiteReading,
    NewAlarmsNotifications,
    Site,
)

logger = logging.getLogger(__name__)


def _main_database_alias() -> str:
    if "main" in connections.databases:
        return "main"
    return "default"


def _daily_unit_consumption_for_unit(unit: DgUnitConsumption) -> float | None:
    if not unit or not unit.site or not unit.aisle_group:
        return None

    reading_date = None
    if unit.dg_end_date:
        reading_date = unit.dg_end_date.date()
    elif unit.created:
        reading_date = unit.created.date()

    if reading_date is None:
        return None

    daily_reading = (
        DailySiteReading.objects.using(_main_database_alias()).filter(
            associated_Site=unit.site,
            aisle_group=unit.aisle_group,
            reading_for=reading_date,
        )
        .order_by("-id")
        .first()
    )
    if not daily_reading:
        return None

    return as_float(daily_reading.unit_consumption)


def _daily_window(reading_date: date_type) -> tuple[datetime, datetime]:
    day_start = datetime.combine(reading_date, datetime_time.min)
    day_end = datetime.combine(reading_date, datetime_time.max.replace(microsecond=0))
    if settings.USE_TZ and dj_timezone.is_naive(day_start):
        current_timezone = dj_timezone.get_current_timezone()
        day_start = dj_timezone.make_aware(day_start, current_timezone)
        day_end = dj_timezone.make_aware(day_end, current_timezone)
    return day_start, day_end


def _best_dg_end_time_for_unit(
    site: Site, aisle_group_id: int, reading_date: date_type
) -> datetime | None:
    hourly_reading = (
        HourlySiteReading.objects.using(_main_database_alias())
        .filter(
            associated_Site_id=site.id,
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


def reconcile_daily_unit_consumption(
    site: Site,
    reading_date: date_type | None = None,
    return_details: bool = False,
) -> dict:
    """Materialize DG unit rows from MAIN DailySiteReading for one site/day."""
    if site is None:
        return {"created": 0, "updated": 0, "skipped": 0}

    reading_date = reading_date or dj_timezone.now().date()

    logger.debug(
        "Reconciling DG unit consumption site_id=%s reading_date=%s",
        site.id,
        reading_date,
    )

    day_start, day_end = _daily_window(reading_date)
    epoch_time = int(day_start.timestamp() * 1000)

    created = 0
    updated = 0
    skipped = 0
    seen_aisles = set()
    row_results = []

    # MAIN DB is authoritative for DailySiteReading.
    daily_readings = (
        DailySiteReading.objects.using(_main_database_alias())
        .filter(
            associated_Site_id=site.id,
            reading_for=reading_date,
            aisle_group__power_source__gte=1,
        )
        .exclude(aisle_group_id__isnull=True)
        .order_by("aisle_group_id", "-id")
    )

    for daily_reading in daily_readings:
        aisle_id = daily_reading.aisle_group_id

        if aisle_id in seen_aisles:
            continue

        seen_aisles.add(aisle_id)

        unit_value = as_float(daily_reading.unit_consumption)

        if unit_value is None:
            skipped += 1
            if return_details:
                row_results.append(
                    {
                        "aisle_group_id": aisle_id,
                        "daily_reading_value": None,
                        "status": "NOT AVAILABLE",
                        "reason": "invalid_daily_unit_consumption",
                    }
                )
            continue

        if unit_value < 1:
            skipped += 1
            if return_details:
                row_results.append(
                    {
                        "aisle_group_id": aisle_id,
                        "daily_reading_value": unit_value,
                        "status": "IGNORED_FLUCTUATION",
                        "reason": "below_threshold",
                    }
                )
            continue

        # TEST DB
        unit = (
            DgUnitConsumption.objects.filter(
                site_id=site.id,
                aisle_group_id=aisle_id,
                created__date=reading_date,
            )
            .order_by("-id")
            .first()
        )

        best_dg_end_time = _best_dg_end_time_for_unit(site, aisle_id, reading_date)
        if unit:
            update_fields = []
            previous_value = unit.unit_consumption

            if unit.unit_consumption != unit_value:
                unit.unit_consumption = unit_value
                update_fields.append("unit_consumption")

            if unit.created != day_start:
                unit.created = day_start
                update_fields.append("created")

            if unit.dg_start_date != day_start:
                unit.dg_start_date = day_start
                update_fields.append("dg_start_date")

            if unit.dg_end_date != best_dg_end_time:
                unit.dg_end_date = best_dg_end_time
                update_fields.append("dg_end_date")

            if unit.epoch_time != epoch_time:
                unit.epoch_time = epoch_time
                update_fields.append("epoch_time")

            if unit.dg_fuel_consumption is None and not unit.fetch_fuel_data:
                unit.fetch_fuel_data = True
                update_fields.append("fetch_fuel_data")

            if update_fields:
                unit.save(update_fields=update_fields)

            if return_details:
                row_results.append(
                    {
                        "aisle_group_id": aisle_id,
                        "unit_id": unit.id,
                        "daily_reading_value": unit_value,
                        "previous_unit_consumption": previous_value,
                        "unit_consumption": unit.unit_consumption,
                        "fetch_fuel_data": unit.fetch_fuel_data,
                        "status": "UPDATED" if update_fields else "EXISTING",
                    }
                )

            updated += 1

        else:
            created_unit = DgUnitConsumption.objects.create(
                site_id=site.id,
                aisle_group_id=aisle_id,
                unit_consumption=unit_value,
                dg_fuel_consumption=None,
                created=day_start,
                dg_start_date=day_start,
                dg_end_date=best_dg_end_time,
                epoch_time=epoch_time,
                is_dg_on=False,
                fetch_fuel_data=True,
            )

            if return_details:
                row_results.append(
                    {
                        "aisle_group_id": aisle_id,
                        "unit_id": created_unit.id,
                        "daily_reading_value": unit_value,
                        "previous_unit_consumption": None,
                        "unit_consumption": created_unit.unit_consumption,
                        "fetch_fuel_data": created_unit.fetch_fuel_data,
                        "status": "CREATED",
                    }
                )

            created += 1

    logger.debug(
        "DG unit reconciliation summary site_id=%s reading_date=%s "
        "created=%s updated=%s skipped=%s",
        site.id,
        reading_date,
        created,
        updated,
        skipped,
    )

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        **({"rows": row_results} if return_details else {}),
    }


def determine_provider(site: Site) -> str | None:
    """Return the configured provider name for a site."""
    provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
    if provider in {"loconav", "roadcast"}:
        return provider
    return None


def _fetch_roadcast_fuel(
    vehicle_imei: str, start_dt: datetime, end_dt: datetime
) -> float | None:
    try:
        return fetch_roadcast_fuel(vehicle_imei, start_dt, end_dt)
    except Exception:
        return None


def _fetch_loconav_fuel(
    vehicle_number: str, start_dt: datetime, end_dt: datetime
) -> float | None:
    try:
        return fetch_loconav_fuel(vehicle_number, start_dt, end_dt)
    except Exception:
        return None


def _fetch_loconav_report(
    vehicle_number: str, start_dt: datetime, end_dt: datetime
) -> dict | None:
    try:
        return fetch_loconav_report(vehicle_number, start_dt, end_dt)
    except Exception:
        return None


def _persist_provider_alerts(
    site: Site, unit: DgUnitConsumption, provider: str
) -> None:
    if provider == "roadcast":
        try:
            report = fetch_roadcast_report(
                site.partner_dg_fuel_id, unit.dg_start_date, unit.dg_end_date
            )
            if isinstance(report, dict):
                for event in report.get("refuels", []) or []:
                    record_fuel_alert(
                        site=site,
                        vehicle_number=site.partner_dg_fuel_id,
                        alert_name="refuel",
                        fuel_liters=event.get("fuel_liters"),
                        epoch_value=event.get("epoch_ms"),
                        created=dj_timezone.now(),
                    )
                for event in report.get("thefts", []) or []:
                    record_fuel_alert(
                        site=site,
                        vehicle_number=site.partner_dg_fuel_id,
                        alert_name="theft",
                        fuel_liters=event.get("fuel_liters"),
                        epoch_value=event.get("epoch_ms"),
                        created=dj_timezone.now(),
                    )
        except Exception:
            pass
    elif provider == "loconav":
        try:
            report = _fetch_loconav_report(
                site.partner_dg_fuel_id, unit.dg_start_date, unit.dg_end_date
            )
            if isinstance(report, dict):
                refuels = detect_refuel_from_alerts(report)
                thefts = detect_theft_from_alerts(report)
                for event in refuels:
                    record_fuel_alert(
                        site=site,
                        vehicle_number=site.partner_dg_fuel_id,
                        alert_name="refuel",
                        fuel_liters=event.get("value"),
                        epoch_value=event.get("timestamp"),
                        created=dj_timezone.now(),
                    )
                for event in thefts:
                    record_fuel_alert(
                        site=site,
                        vehicle_number=site.partner_dg_fuel_id,
                        alert_name="theft",
                        fuel_liters=event.get("value"),
                        epoch_value=event.get("timestamp"),
                        created=dj_timezone.now(),
                    )
        except Exception:
            pass


def attempt_fetch_for_unit(
    unit: DgUnitConsumption, return_details: bool = False
) -> Any:
    """Fetch consumed fuel for a closed DG run and persist the result."""
    result: dict[str, Any] = {
        "site_id": getattr(getattr(unit, "site", None), "id", None),
        "unit_id": getattr(unit, "id", None),
        "vehicle_number": getattr(getattr(unit, "site", None), "partner_dg_fuel_id", None),
        "provider": determine_provider(getattr(unit, "site", None)) if unit else None,
        "success": False,
        "status": "NOT AVAILABLE",
        "reason": None,
        "fuel_value": None,
        "confirmed_zero": False,
        "database_action": None,
        "previous_dg_fuel_consumption": getattr(unit, "dg_fuel_consumption", None),
    }

    if not unit or not unit.dg_start_date or not unit.dg_end_date:
        result["reason"] = "missing_unit_dates"
        return result if return_details else False

    if unit.unit_consumption is None:
        sync_daily_value = _daily_unit_consumption_for_unit(unit)
        if sync_daily_value is not None and sync_daily_value >= 1:
            unit.unit_consumption = sync_daily_value
            unit.save(update_fields=["unit_consumption"])

    if unit.unit_consumption is None or unit.unit_consumption < 1:
        unit.fetch_fuel_data = True
        unit.save(update_fields=["fetch_fuel_data"])
        result["reason"] = (
            "daily_unit_consumption_missing"
            if unit.unit_consumption is None
            else "daily_unit_consumption_below_threshold"
        )
        return result if return_details else False

    site = unit.site
    provider = determine_provider(site)
    result["provider"] = provider
    if provider is None:
        unit.fetch_fuel_data = True
        unit.save(update_fields=["fetch_fuel_data"])
        result["reason"] = "missing_or_invalid_provider"
        return result if return_details else False

    fuel_fetch_success = False
    previous_value = unit.dg_fuel_consumption
    try:
        if provider == "roadcast":
            value = _fetch_roadcast_fuel(
                site.partner_dg_fuel_id, unit.dg_start_date, unit.dg_end_date
            )
        else:
            value = _fetch_loconav_fuel(
                site.partner_dg_fuel_id, unit.dg_start_date, unit.dg_end_date
            )
    except Exception:
        value = None

    if value is None:
        unit.fetch_fuel_data = True
        unit.save(update_fields=["fetch_fuel_data"])
        result.update({"reason": "provider_returned_no_usable_value", "status": "UNAVAILABLE"})
    else:
        normalized_value = as_float(value)
        if normalized_value is None:
            unit.fetch_fuel_data = True
            unit.save(update_fields=["fetch_fuel_data"])
            result.update({"reason": "provider_returned_invalid_value", "status": "INVALID"})
        else:
            try:
                unit.dg_fuel_consumption = normalized_value
            except Exception:
                logger.exception(
                    "Failed to persist DG fuel value site_id=%s unit_id=%s vehicle_number=%s provider=%s",
                    getattr(site, "id", None),
                    getattr(unit, "id", None),
                    getattr(site, "partner_dg_fuel_id", None),
                    provider,
                )
                unit.fetch_fuel_data = True
                unit.save(update_fields=["fetch_fuel_data"])
                result.update({"reason": "failed_to_persist_dg_fuel_value", "status": "ERROR"})
            else:
                unit.fetch_fuel_data = False
                unit.save(update_fields=["dg_fuel_consumption", "fetch_fuel_data"])
                fuel_fetch_success = True

                if previous_value is None:
                    database_action = "CREATED"
                elif previous_value == normalized_value:
                    database_action = "EXISTING"
                else:
                    database_action = "UPDATED"

                result.update(
                    {
                        "success": True,
                        "status": "CONFIRMED ZERO" if normalized_value == 0 else "OK",
                        "fuel_value": normalized_value,
                        "confirmed_zero": normalized_value == 0,
                        "database_action": database_action,
                        "reason": None,
                    }
                )

    if fuel_fetch_success:
        if unit.unit_consumption is not None and unit.unit_consumption <= 0:
            NewAlarmsNotifications.objects.create(
                site_id=site,
                alarm_type=9,
                alarm_priority=0,
                created=dj_timezone.now(),
            )

        try:
            tank_capacity = site.dg_fuel_tank_capacity
            if detect_suspicious_fuel(tank_capacity, unit.dg_fuel_consumption):
                DGFuelAlertsData.objects.create(
                    site=site,
                    vehicle_number=site.partner_dg_fuel_id,
                    alert_name="suspicious_fuel",
                    fuel_consumption=unit.dg_fuel_consumption,
                    epoch_time=str(int(time.time())),
                    created=dj_timezone.now(),
                )
                NewAlarmsNotifications.objects.create(
                    site_id=site,
                    alarm_type=6,
                    alarm_priority=1,
                    created=dj_timezone.now(),
                    fuel_level=unit.dg_fuel_consumption,
                )
        except Exception:
            pass

    _persist_provider_alerts(site, unit, provider)

    if return_details:
        return result
    return fuel_fetch_success
