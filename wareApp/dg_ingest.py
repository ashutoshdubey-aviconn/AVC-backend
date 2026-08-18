"""DG ingestion helpers: create DG unit consumption rows and ingest fuel rows.

Conservative helpers centralize normalization and small safety checks so callers
can be simplified and behavior is consistent across the codebase.
"""

from typing import Optional
from datetime import datetime

from wareApp.models import DgFuelConsumptionData, DgUnitConsumption, Site, AisleGroup
from wareApp.dg_dedupe import dedupe_dg_consumption
from django.db import transaction
import logging

logger = logging.getLogger(__name__)


def ingest_fuel_row(
    site: Site,
    vehicle_number: str,
    epoch_ms: str,
    fuel_liters: float,
    source: str = None,
    created: Optional[datetime] = None,
) -> DgFuelConsumptionData:
    """Create a DgFuelConsumptionData row, normalize epoch to string, dedupe afterwards.

    Keeps insertion deterministic: creates the row then calls dedupe helper to
    remove duplicates for the same site/vehicle/epoch_time.
    Returns the created (or kept) DgFuelConsumptionData instance.
    """
    # normalize epoch to string
    if isinstance(epoch_ms, int):
        epoch_str = str(epoch_ms)
    else:
        epoch_str = str(epoch_ms) if epoch_ms is not None else None

    if created is None:
        created = datetime.now()

    # create + dedupe inside a transaction so race windows are smaller
    with transaction.atomic():
        obj = DgFuelConsumptionData.objects.create(
            site=site,
            vehicle_number=vehicle_number,
            fuel_consumption=(fuel_liters or 0),
            epoch_time=epoch_str,
            fuel_data_source=source,
            created=created,
        )
        try:
            removed = dedupe_dg_consumption(site, vehicle_number, epoch_str)
            if removed:
                logger.info(
                    "dedupe_dg_consumption removed %d duplicates for %s@%s",
                    removed,
                    vehicle_number,
                    epoch_str,
                )
        except Exception:
            logger.exception(
                "dedupe_dg_consumption failed for %s@%s", vehicle_number, epoch_str
            )

        # return the canonical (earliest) row for this key
        qs = DgFuelConsumptionData.objects.filter(
            site=site, vehicle_number=vehicle_number, epoch_time=epoch_str
        ).order_by("id")
        return qs.first()


def create_dg_unit_consumption(
    site, aisle_group, unit_consumption, created_time, is_dg_on=True
):
    """Create a DgUnitConsumption row with normalized epoch_time and defaults.

    `aisle_group` may be an AisleGroup instance or an iterable containing one.
    Returns the created DgUnitConsumption instance.
    """
    # normalize aisle_group argument
    ag = None
    try:
        if hasattr(aisle_group, "__iter__") and not isinstance(aisle_group, AisleGroup):
            ag = list(aisle_group)[0] if len(list(aisle_group)) else None
        else:
            ag = aisle_group
    except Exception:
        ag = aisle_group

    epoch_time = int(created_time.timestamp() * 1000) if created_time else None

    obj = DgUnitConsumption.objects.create(
        site=site,
        aisle_group=ag,
        unit_consumption=unit_consumption,
        created=created_time,
        dg_start_date=created_time,
        dg_end_date=created_time,
        epoch_time=epoch_time,
        is_dg_on=is_dg_on,
    )
    return obj
