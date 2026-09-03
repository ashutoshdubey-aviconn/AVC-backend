"""Centralized persistence helpers for DG-fuel levels and provider alerts."""

import logging
from datetime import datetime
from typing import Optional, Tuple

from django.db import transaction

from wareApp.models import DGFuelAlertsData, DgFuelConsumptionData, Site

from .dedupe import dedupe_dg_consumption
from .normalization import as_float, epoch_milliseconds


logger = logging.getLogger(__name__)


def _created_from_epoch(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000)


def record_fuel_level(
    *,
    site: Site,
    vehicle_number: str,
    fuel_liters: object,
    epoch_value: object,
    source: str,
    created: Optional[datetime] = None,
) -> Tuple[DgFuelConsumptionData, bool]:
    """Create one provider tank-level sample for a site and normalized epoch."""
    normalized_fuel = as_float(fuel_liters)
    normalized_epoch = epoch_milliseconds(epoch_value)
    if normalized_fuel is None or normalized_epoch is None or not vehicle_number:
        logger.warning(
            "Skipping DG fuel level write site_id=%s vehicle_number=%s fuel_liters=%r epoch_value=%r source=%s reason=%s",
            getattr(site, "id", None),
            vehicle_number,
            fuel_liters,
            epoch_value,
            source,
            "missing_vehicle_or_invalid_fuel_or_timestamp",
        )
        raise ValueError("Fuel level requires a vehicle, numeric fuel value, and timestamp")

    created = created or _created_from_epoch(normalized_epoch)
    with transaction.atomic():
        obj, created_flag = DgFuelConsumptionData.objects.get_or_create(
            site=site,
            vehicle_number=str(vehicle_number),
            epoch_time=str(normalized_epoch),
            defaults={
                "fuel_consumption": normalized_fuel,
                "fuel_data_source": source,
                "created": created,
            },
        )
    logger.info(
        "DG fuel level %s site_id=%s vehicle_number=%s fuel_liters=%s epoch_ms=%s created_at=%s source=%s",
        "created" if created_flag else "existing",
        getattr(site, "id", None),
        vehicle_number,
        normalized_fuel,
        normalized_epoch,
        created.isoformat(sep=" "),
        source,
    )
    return obj, created_flag


def record_fuel_alert(
    *,
    site: Site,
    vehicle_number: str,
    alert_name: str,
    fuel_liters: object,
    epoch_value: object,
    created: Optional[datetime] = None,
) -> Tuple[DGFuelAlertsData, bool]:
    """Create one provider refuel or theft event for a normalized timestamp."""
    normalized_fuel = as_float(fuel_liters)
    normalized_epoch = epoch_milliseconds(epoch_value)
    if normalized_fuel is None or normalized_epoch is None or not vehicle_number:
        logger.warning(
            "Skipping DG fuel alert write site_id=%s vehicle_number=%s alert_name=%s fuel_liters=%r epoch_value=%r reason=%s",
            getattr(site, "id", None),
            vehicle_number,
            alert_name,
            fuel_liters,
            epoch_value,
            "missing_vehicle_or_invalid_fuel_or_timestamp",
        )
        raise ValueError("Fuel alert requires a vehicle, numeric fuel value, and timestamp")
    if alert_name not in {"refuel", "theft"}:
        logger.warning(
            "Skipping DG fuel alert write site_id=%s vehicle_number=%s alert_name=%s reason=%s",
            getattr(site, "id", None),
            vehicle_number,
            alert_name,
            "invalid_alert_name",
        )
        raise ValueError("Fuel alert name must be refuel or theft")

    created = created or _created_from_epoch(normalized_epoch)
    with transaction.atomic():
        obj, created_flag = DGFuelAlertsData.objects.get_or_create(
            site=site,
            vehicle_number=str(vehicle_number),
            alert_name=alert_name,
            epoch_time=str(normalized_epoch),
            defaults={"fuel_consumption": normalized_fuel, "created": created},
        )
    logger.info(
        "DG fuel alert %s site_id=%s vehicle_number=%s alert_name=%s fuel_liters=%s epoch_ms=%s created_at=%s",
        "created" if created_flag else "existing",
        getattr(site, "id", None),
        vehicle_number,
        alert_name,
        normalized_fuel,
        normalized_epoch,
        created.isoformat(sep=" "),
    )
    return obj, created_flag