#!/usr/bin/env python3
import os
import sys
import time
from datetime import datetime

# bootstrap django environment (same pattern used in fetch_fuel_data.py)
package_path = os.path.join("..", "django_project")
sys.path.append(package_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()

from wareApp.models import DgUnitConsumption
from wareApp.dg_fuel.sessions import attempt_fetch_for_unit


def main(limit=200):
    qs = DgUnitConsumption.objects.filter(fetch_fuel_data=True).order_by("created")[
        :limit
    ]
    if not qs:
        print("No runs pending fetch_fuel_data")
        return
    total = qs.count()
    print(f"Attempting retry for {total} runs")
    success = 0
    for u in qs:
        try:
            ok = attempt_fetch_for_unit(u)
            if ok:
                success += 1
                print(f"Fetched for run {u.id}")
            else:
                print(f"Still failed for run {u.id}")
        except Exception as e:
            print("Exception while retrying run", u.id, e)
        # small pause to avoid hammering providers
        time.sleep(0.2)
    print(f"Completed: {success}/{total} succeeded at {datetime.now()}")


if __name__ == "__main__":
    main()
