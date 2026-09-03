"""DG session lifecycle helpers for starting, updating, and closing runs."""

import logging
import time
from datetime import date as date_type
from datetime import datetime, time as datetime_time
from typing import Optional

from django.db import transaction
from django.utils import timezone as dj_timezone

from wareApp.dg_fuel.normalization import as_float
from wareApp.fuel_providers import (
    detect_suspicious_fuel,
    fetch_loconav_fuel,
    fetch_roadcast_fuel,
    fetch_roadcast_report,
)
from wareApp.dg_fuel.ingestion import record_fuel_alert
from wareApp.models import (
    AisleGroup,
    DailySiteReading,
    DGFuelAlertsData,
    DgUnitConsumption,
    NewAlarmsNotifications,
    Site,
)


logger = logging.getLogger(__name__)


def _daily_unit_consumption_for_unit(unit: DgUnitConsumption) -> Optional[float]:
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
        DailySiteReading.objects.filter(
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
    if dj_timezone.is_naive(day_start):
        current_timezone = dj_timezone.get_current_timezone()
        day_start = dj_timezone.make_aware(day_start, current_timezone)
        day_end = dj_timezone.make_aware(day_end, current_timezone)
    return day_start, day_end


def reconcile_daily_unit_consumption(
    site: Site, reading_date: Optional[date_type] = None
) -> dict:
    """Materialize DG unit rows from the daily site readings for one site/day."""
    if site is None:
        return {"created": 0, "updated": 0, "skipped": 0}

    reading_date = reading_date or dj_timezone.now().date()
    logger.info(
        "Reconciling DG unit consumption site_id=%s reading_date=%s",
        site.id,
        reading_date,
    )
    day_start, day_end = _daily_window(reading_date)
    epoch_time = int(day_end.timestamp() * 1000)

    created = 0
    updated = 0
    skipped = 0
    seen_aisles = set()

    with transaction.atomic():
        daily_readings = (
            DailySiteReading.objects.select_for_update()
            .filter(associated_Site=site, reading_for=reading_date)
            .exclude(aisle_group__isnull=True)
            .select_related("aisle_group")
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
                logger.warning(
                    "Skipping DG unit reconciliation site_id=%s aisle_group_id=%s reading_date=%s reason=%s",
                    site.id,
                    aisle_id,
                    reading_date,
                    "invalid_daily_unit_consumption",
                )
                continue

            unit = (
                DgUnitConsumption.objects.select_for_update()
                .filter(site=site, aisle_group=daily_reading.aisle_group, created__date=reading_date)
                .order_by("-id")
                .first()
            )

            if unit:
                update_fields = []
                if unit.unit_consumption != unit_value:
                    unit.unit_consumption = unit_value
                    update_fields.append("unit_consumption")
                if unit.created != day_start:
                    unit.created = day_start
                    update_fields.append("created")
                if unit.dg_start_date != day_start:
                    unit.dg_start_date = day_start
                    update_fields.append("dg_start_date")
                if unit.dg_end_date != day_end:
                    unit.dg_end_date = day_end
                    update_fields.append("dg_end_date")
                if unit.epoch_time != epoch_time:
                    unit.epoch_time = epoch_time
                    update_fields.append("epoch_time")
                if unit.dg_fuel_consumption is None and not unit.fetch_fuel_data:
                    unit.fetch_fuel_data = True
                    update_fields.append("fetch_fuel_data")
                if update_fields:
                    unit.save(update_fields=update_fields)
                    logger.info(
                        "Updated DG unit row site_id=%s aisle_group_id=%s reading_date=%s unit_consumption=%s dg_start_date=%s dg_end_date=%s epoch_time=%s fetch_fuel_data=%s",
                        site.id,
                        aisle_id,
                        reading_date,
                        unit.unit_consumption,
                        unit.dg_start_date,
                        unit.dg_end_date,
                        unit.epoch_time,
                        unit.fetch_fuel_data,
                    )
                updated += 1
            else:
                DgUnitConsumption.objects.create(
                    site=site,
                    aisle_group=daily_reading.aisle_group,
                    unit_consumption=unit_value,
                    dg_fuel_consumption=None,
                    created=day_start,
                    dg_start_date=day_start,
                    dg_end_date=day_end,
                    epoch_time=epoch_time,
                    is_dg_on=False,
                    fetch_fuel_data=True,
                )
                logger.info(
                    "Created DG unit row site_id=%s aisle_group_id=%s reading_date=%s unit_consumption=%s dg_start_date=%s dg_end_date=%s epoch_time=%s fetch_fuel_data=%s",
                    site.id,
                    aisle_id,
                    reading_date,
                    unit_value,
                    day_start,
                    day_end,
                    epoch_time,
                    True,
                )
                created += 1

    logger.info(
        "DG unit reconciliation summary site_id=%s reading_date=%s created=%s updated=%s skipped=%s",
        site.id,
        reading_date,
        created,
        updated,
        skipped,
    )
    return {"created": created, "updated": updated, "skipped": skipped}


def determine_provider(site: Site) -> Optional[str]:
    """Return the configured provider name for a site."""
    provider = (getattr(site, "partner_dg_provider", None) or "").strip().lower()
    if provider in {"loconav", "roadcast"}:
        return provider
    return None


def _fetch_roadcast_fuel(
    vehicle_imei: str, start_dt: datetime, end_dt: datetime
) -> Optional[float]:
    try:
        return fetch_roadcast_fuel(vehicle_imei, start_dt, end_dt)
    except Exception:
        return None


def _fetch_loconav_fuel(
    vehicle_number: str, start_dt: datetime, end_dt: datetime
) -> Optional[float]:
    try:
        return fetch_loconav_fuel(vehicle_number, start_dt, end_dt)
    except Exception:
        return None


def attempt_fetch_for_unit(unit: DgUnitConsumption) -> bool:
    """Fetch consumed fuel for a closed DG run and persist the result."""
    if not unit or not unit.dg_start_date or not unit.dg_end_date:
        return False

    if unit.unit_consumption is None:
        sync_daily_value = _daily_unit_consumption_for_unit(unit)
        if sync_daily_value is not None:
            unit.unit_consumption = sync_daily_value
            unit.save(update_fields=["unit_consumption"])

    if unit.unit_consumption is None:
        unit.fetch_fuel_data = True
        unit.save(update_fields=["fetch_fuel_data"])
        return False

    site = unit.site
    provider = determine_provider(site)
    if provider is None:
        logger.warning(
            "Skipping DG fuel fetch site_id=%s unit_id=%s vehicle_number=%s due to missing or invalid provider configuration",
            getattr(site, "id", None),
            getattr(unit, "id", None),
            getattr(site, "partner_dg_fuel_id", None),
        )
        unit.fetch_fuel_data = True
        unit.save(update_fields=["fetch_fuel_data"])
        return False

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
        logger.warning(
            "DG fuel fetch returned no usable value site_id=%s unit_id=%s vehicle_number=%s provider=%s dg_start_date=%s dg_end_date=%s unit_consumption=%s",
            getattr(site, "id", None),
            getattr(unit, "id", None),
            getattr(site, "partner_dg_fuel_id", None),
            provider,
            unit.dg_start_date,
            unit.dg_end_date,
            unit.unit_consumption,
        )
        unit.fetch_fuel_data = True
        unit.save(update_fields=["fetch_fuel_data"])
        return False

    normalized_value = as_float(value)
    if normalized_value is None:
        logger.warning(
            "DG fuel fetch returned invalid value site_id=%s unit_id=%s vehicle_number=%s provider=%s value=%r dg_start_date=%s dg_end_date=%s",
            getattr(site, "id", None),
            getattr(unit, "id", None),
            getattr(site, "partner_dg_fuel_id", None),
            provider,
            value,
            unit.dg_start_date,
            unit.dg_end_date,
        )
        unit.fetch_fuel_data = True
        unit.save(update_fields=["fetch_fuel_data"])
        return False

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
        return False
    unit.fetch_fuel_data = False
    unit.save(update_fields=["dg_fuel_consumption", "fetch_fuel_data"])

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

    return True
