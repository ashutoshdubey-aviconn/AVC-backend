#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

proj_root = "/home/ashutosh-dubey/django_project"
sys.path.insert(0, proj_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django

django.setup()

from wareApp.models import Site, DgFuelConsumptionData
import requests
from django.utils import timezone

OUT_DIR = Path(proj_root) / "logs" / "third_party"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def probe_loconav(vehicle, start_s, end_s):
    url = "https://marketplace.loconav.com/api/v1/vehicles/fuel"
    headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
    params = {"vehicle_number": vehicle, "start_time": start_s, "end_time": end_s}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    return r


def backfill_site(site):
    vehicle = getattr(site, "partner_dg_fuel_id", None) or getattr(
        site, "partner_dg_vehicle", None
    )
    if not vehicle:
        print("site", site.id, "has no vehicle id; skipping")
        return 0
    now = datetime.utcnow()
    start_s = int((now - timedelta(minutes=30)).timestamp())
    end_s = int(now.timestamp())
    try:
        r = probe_loconav(str(vehicle), start_s, end_s)
    except Exception as e:
        print("Loconav probe failed for", vehicle, e)
        return 0
    fname = (
        OUT_DIR
        / f"loconav_backfill_site{site.id}_{vehicle}_{int(datetime.utcnow().timestamp())}.json"
    )
    with open(fname, "w") as fh:
        json.dump({"status_code": r.status_code, "url": r.url, "text": r.text}, fh)
    print("Saved probe for site", site.id, "->", fname)
    if r.status_code != 200:
        return 0
    j = r.json()
    if not j.get("status"):
        print("Loconav returned status false for", vehicle)
        return 0
    data = j.get("data") or {}
    # prefer explicit sensor value if present
    val = None
    sensors = data.get("fuel_sensors") or []
    if sensors:
        try:
            val = float(sensors[0].get("value"))
        except Exception:
            val = None
    if val is None:
        # try fuel_capacity or fuel_consumption
        if "fuel_capacity" in data and data["fuel_capacity"].get("value") is not None:
            val = float(data["fuel_capacity"]["value"])
        elif (
            "fuel_consumption" in data
            and data["fuel_consumption"].get("value") is not None
        ):
            try:
                val = float(data["fuel_consumption"]["value"])
            except Exception:
                val = None

    if val is None:
        print("No fuel value found for", vehicle)
        return 0

    # insert DgFuelConsumptionData
    now_dt = timezone.now()
    epoch_ms = str(int(now_dt.timestamp() * 1000))
    obj = DgFuelConsumptionData.objects.create(
        site=site,
        vehicle_number=str(vehicle),
        fuel_consumption=val,
        epoch_time=epoch_ms,
        created=now_dt,
        fuel_data_source="loconav",
    )
    print("Inserted DgFuelConsumptionData id=", obj.id, "site=", site.id, "value=", val)
    return 1


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--site",
        type=int,
        help="site id to backfill (default: all sites with partner id)",
    )
    args = parser.parse_args()

    sites = []
    if args.site:
        try:
            sites = [Site.objects.get(id=args.site)]
        except Exception as e:
            print("Site not found", args.site, e)
            return
    else:
        sites = Site.objects.filter(
            partner_dg_fuel_id__isnull=False, dg_fuel_system_installed=True
        )

    total = 0
    for s in sites:
        total += backfill_site(s)

    print("Backfill complete. inserted rows:", total)


if __name__ == "__main__":
    main()
