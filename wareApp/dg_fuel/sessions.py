"""DG session lifecycle helpers for starting, updating, and closing runs."""

import time
from datetime import datetime
from typing import Optional

from wareApp.fuel_providers import (
    detect_suspicious_fuel,
    fetch_loconav_fuel,
    fetch_roadcast_fuel,
    fetch_roadcast_report,
)
from wareApp.dg_fuel.ingestion import record_fuel_alert
from wareApp.models import (
    AisleGroup,
    DGFuelAlertsData,
    DgUnitConsumption,
    NewAlarmsNotifications,
    Site,
)


def create_dg_unit_consumption(
    site, aisle_group, unit_consumption, created_time, is_dg_on=True
):
    """Create a DG run row with normalized datetime and epoch."""
    from wareApp.models import AisleGroup, DgUnitConsumption

    ag = None
    try:
        if hasattr(aisle_group, "__iter__") and not isinstance(aisle_group, AisleGroup):
            ag = list(aisle_group)[0] if len(list(aisle_group)) else None
        else:
            ag = aisle_group
    except Exception:
        ag = aisle_group

    epoch_time = int(created_time.timestamp() * 1000) if created_time else None
    return DgUnitConsumption.objects.create(
        site=site,
        aisle_group=ag,
        unit_consumption=unit_consumption,
        created=created_time,
        dg_start_date=created_time,
        dg_end_date=created_time,
        epoch_time=epoch_time,
        is_dg_on=is_dg_on,
    )


def determine_provider(site: Site) -> str:
    """Return the configured provider name for a site."""
    provider = getattr(site, "partner_dg_provider", None)
    if provider:
        return provider.lower()
    pid = (site.partner_dg_fuel_id or "").strip()
    if pid and pid.isdigit():
        return "roadcast"
    return "loconav"


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

    site = unit.site
    provider = determine_provider(site)
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
        return False

    try:
        unit.dg_fuel_consumption = float(value)
    except Exception:
        unit.dg_fuel_consumption = 0
    unit.fetch_fuel_data = False
    unit.save(update_fields=["dg_fuel_consumption", "fetch_fuel_data"])

    if (unit.unit_consumption or 0) <= 0:
        NewAlarmsNotifications.objects.create(
            site_id=site,
            alarm_type=9,
            alarm_priority=0,
            created=datetime.now(),
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
                created=datetime.now(),
            )
            NewAlarmsNotifications.objects.create(
                site_id=site,
                alarm_type=6,
                alarm_priority=1,
                created=datetime.now(),
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
                    )
                for event in report.get("thefts", []) or []:
                    record_fuel_alert(
                        site=site,
                        vehicle_number=site.partner_dg_fuel_id,
                        alert_name="theft",
                        fuel_liters=event.get("fuel_liters"),
                        epoch_value=event.get("epoch_ms"),
                    )
        except Exception:
            pass

    return True


def on_event(site: Site, aisle_group: AisleGroup, entry_time: datetime):
    return create_dg_unit_consumption(
        site=site,
        aisle_group=aisle_group,
        unit_consumption=0,
        created_time=entry_time,
        is_dg_on=True,
    )


def update_event(
    site: Site, aisle_group: AisleGroup, delta_consumption: float, entry_time: datetime
):
    active = DgUnitConsumption.objects.filter(
        site=site, aisle_group=aisle_group, is_dg_on=True
    ).last()
    epoch_time = int(entry_time.timestamp() * 1000)
    if active:
        active.unit_consumption = (active.unit_consumption or 0) + (delta_consumption or 0)
        active.dg_end_date = entry_time
        active.epoch_time = epoch_time
        active.save(update_fields=["unit_consumption", "dg_end_date", "epoch_time"])
        return active

    return create_dg_unit_consumption(
        site=site,
        aisle_group=aisle_group,
        unit_consumption=delta_consumption or 0,
        created_time=entry_time,
        is_dg_on=True,
    )


def off_event(site: Site, aisle_group: AisleGroup, entry_time: datetime):
    active = DgUnitConsumption.objects.filter(
        site=site, aisle_group=aisle_group, is_dg_on=True
    ).last()
    if not active:
        return None

    active.is_dg_on = False
    active.dg_end_date = entry_time
    active.epoch_time = int(entry_time.timestamp() * 1000)
    active.save(update_fields=["is_dg_on", "dg_end_date", "epoch_time"])

    success = attempt_fetch_for_unit(active)
    if not success:
        active.fetch_fuel_data = True
        active.save(update_fields=["fetch_fuel_data"])
    return active