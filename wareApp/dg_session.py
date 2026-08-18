import requests
import time
from datetime import datetime
from typing import Optional

from wareApp.models import (
    Site,
    AisleGroup,
    DgUnitConsumption,
    DgFuelConsumptionData,
    DGFuelAlertsData,
    NewAlarmsNotifications,
)
from wareApp.fuel_providers import (
    fetch_roadcast_fuel,
    fetch_loconav_fuel,
    detect_suspicious_fuel,
)


def determine_provider(site: Site) -> str:
    """Return provider string: 'roadcast' or 'loconav'.
    Future-proof: if Site gains `partner_dg_provider`, prefer that.
    """
    # explicit provider field (not yet present) — fall back to heuristic
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
    """Delegate to provider helper for Roadcaste fetch."""
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
    """Try to fetch fuel for a closed `DgUnitConsumption` run.
    Returns True if fuel was filled successfully (even if zero), False on failure.
    """
    if not unit or not unit.dg_start_date or not unit.dg_end_date:
        return False
    site = unit.site
    provider = determine_provider(site)
    try:
        if provider == "roadcast":
            val = _fetch_roadcast_fuel(
                site.partner_dg_fuel_id, unit.dg_start_date, unit.dg_end_date
            )
        else:
            val = _fetch_loconav_fuel(
                site.partner_dg_fuel_id, unit.dg_start_date, unit.dg_end_date
            )
    except Exception:
        val = None

    if val is None:
        unit.fetch_fuel_data = True
        unit.save()
        return False

    # set fuel value (allow zero)
    try:
        unit.dg_fuel_consumption = float(val)
    except Exception:
        unit.dg_fuel_consumption = 0
    unit.fetch_fuel_data = False
    unit.save()

    # Basic validations and alerts
    # 1) Production validation: DG run with zero unit consumption -> raise 'No DG Run' alarm
    if (unit.unit_consumption or 0) <= 0:
        NewAlarmsNotifications.objects.create(
            site_id=site,
            alarm_type=9,  # No DG Run
            alarm_priority=0,
            created=datetime.now(),
        )

    # 2) Fuel drain/theft validation: nonsensical fuel numbers
    # Respect an explicit `None` tank capacity so detectors can opt-out.
    tank = site.dg_fuel_tank_capacity
    # if reported consumed fuel exceeds tank capacity, create an alert
    try:
        if detect_suspicious_fuel(tank, unit.dg_fuel_consumption):
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
                alarm_type=6,  # Fuel Drain (approx)
                alarm_priority=1,
                created=datetime.now(),
                fuel_level=unit.dg_fuel_consumption,
            )
    except Exception:
        pass

    return True


def on_event(site: Site, aisle_group: AisleGroup, entry_time: datetime):
    epoch_time = int(entry_time.timestamp() * 1000)
    # start a new run via central helper
    from wareApp.dg_ingest import create_dg_unit_consumption

    create_dg_unit_consumption(
        site=site,
        aisle_group=aisle_group,
        unit_consumption=0,
        created_time=entry_time,
        is_dg_on=True,
    )


def update_event(
    site: Site, aisle_group: AisleGroup, delta_consumption: float, entry_time: datetime
):
    # update existing active run or start a new one
    active = DgUnitConsumption.objects.filter(
        site=site, aisle_group=aisle_group, is_dg_on=True
    ).last()
    epoch_time = int(entry_time.timestamp() * 1000)
    if active:
        active.unit_consumption = (active.unit_consumption or 0) + (
            delta_consumption or 0
        )
        active.dg_end_date = entry_time
        active.epoch_time = epoch_time
        active.save()
    else:
        from wareApp.dg_ingest import create_dg_unit_consumption

        create_dg_unit_consumption(
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
    # attempt immediate fetch; if fails leave fetch_fuel_data=True for retry worker
    success = attempt_fetch_for_unit(active)
    if not success:
        active.fetch_fuel_data = True
        active.save()
    return active
