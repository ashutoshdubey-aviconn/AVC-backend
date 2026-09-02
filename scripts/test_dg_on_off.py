import os
import sys
from datetime import datetime, timedelta

package_path = os.path.join(os.path.dirname(__file__), "..")
sys.path.append(package_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()
from wareApp.models import Site, AisleGroup, DgUnitConsumption
from wareApp.tasks import DG_fuel_for_Roadcaste


def ensure_test_site():
    site, _ = Site.objects.get_or_create(site_name="DG Test Site")
    aisle, _ = AisleGroup.objects.get_or_create(
        site=site, aisleGroupName="DG Test Aisle"
    )
    # set aisle to DG power source
    aisle.power_source = 1
    aisle.save()
    site.dg_fuel_system_installed = True
    site.partner_dg_fuel_id = "TEST-VEH-01"
    site.save()
    return site, aisle


def run_cycle():
    site, aisle = ensure_test_site()
    now = datetime.now()
    print("Starting DG ON cycle: creating initial ON packet")
    DG_fuel_for_Roadcaste(site.id, aisle, 10.5, now)
    print(
        "Active entries:",
        DgUnitConsumption.objects.filter(site=site, aisle_group=aisle).count(),
    )
    # simulate subsequent packet while DG is on
    later = now + timedelta(minutes=5)
    DG_fuel_for_Roadcaste(site.id, aisle, 5.25, later)
    active = DgUnitConsumption.objects.filter(
        site=site, aisle_group=aisle, is_dg_on=True
    ).last()
    print("After second packet - unit_consumption=", active.unit_consumption)
    # simulate DG turned off by marking aisle as mains and sending an event
    aisle.power_source = 0
    aisle.save()
    off_time = later + timedelta(minutes=2)
    DG_fuel_for_Roadcaste(site.id, aisle, 0, off_time)
    final = (
        DgUnitConsumption.objects.filter(site=site, aisle_group=aisle)
        .order_by("-created")
        .first()
    )
    print(
        "Final entry is_dg_on=",
        final.is_dg_on,
        "dg_end_date=",
        final.dg_end_date,
        "unit_consumption=",
        final.unit_consumption,
    )


if __name__ == "__main__":
    run_cycle()
