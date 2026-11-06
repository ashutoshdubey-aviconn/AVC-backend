#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proj_root = "/home/ashutosh-dubey/django_project"
sys.path.insert(0, proj_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()

from wareApp.models import DgFuelConsumptionData

# Simple heuristic: numeric vehicle_number -> 'roadcast', otherwise 'loconav'


def infer_source(vehicle):
    if not vehicle:
        return None
    v = str(vehicle).strip()
    if v.isdigit():
        return "roadcast"
    # common pattern 'PBDN' etc -> loconav
    return "loconav"


def main(limit=10000):
    qs = DgFuelConsumptionData.objects.filter(fuel_data_source__isnull=True).order_by(
        "-created"
    )[:limit]
    updated = 0
    for r in qs:
        src = infer_source(r.vehicle_number)
        if src:
            r.fuel_data_source = src
            r.save(update_fields=["fuel_data_source"])
            updated += 1
    print("Updated", updated, "rows")


if __name__ == "__main__":
    main()
