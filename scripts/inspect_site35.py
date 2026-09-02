#!/usr/bin/env python3
import os
import sys
import json
import datetime
from pathlib import Path

# project root
proj_root = "/home/ashutosh-dubey/django_project"
sys.path.insert(0, proj_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")

import django

django.setup()

from wareApp.models import Site, DgFuelConsumptionData, DgUnitConsumption
import requests

OUT_DIR = Path(proj_root) / "logs" / "third_party"
OUT_DIR.mkdir(parents=True, exist_ok=True)

site_id = 35
try:
    site = Site.objects.get(id=site_id)
except Exception as e:
    print(f"ERROR: could not load Site {site_id}: {e}")
    raise SystemExit(1)

print("--- Site fields ---")
for f in site._meta.fields:
    try:
        print(f.name, "->", getattr(site, f.name))
    except Exception as e:
        print(f.name, "->", "<error reading>", e)

print("\n--- Recent DgFuelConsumptionData (latest 10) ---")
q = DgFuelConsumptionData.objects.filter(site=site).order_by("-epoch_time")[:10]
for r in q:
    d = {}
    for f in r._meta.fields:
        d[f.name] = getattr(r, f.name)
    print(json.dumps(d, default=str))

print("\n--- Recent DgUnitConsumption (latest 5) ---")
q2 = DgUnitConsumption.objects.filter(site=site).order_by("-epoch_time")[:5]
for r in q2:
    d = {}
    for f in r._meta.fields:
        d[f.name] = getattr(r, f.name)
    print(json.dumps(d, default=str))

# Prepare API probes
now = datetime.datetime.utcnow()
start = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
end = now.strftime("%Y-%m-%dT%H:%M:%S")

# Loconav: try vehicle number from site fields if present
vehicle_candidates = []
for attr in (
    "partner_dg_vehicle",
    "partner_dg_vehicle_number",
    "partner_dg_fuel_vehicle",
    "partner_dg_fuel_id",
    "partner_dg_imei",
):
    if hasattr(site, attr):
        val = getattr(site, attr)
        if val:
            vehicle_candidates.append(str(val))

# Also include common labels
if hasattr(site, "site_name") and site.site_name:
    vehicle_candidates.append(site.site_name)

vehicle_candidates = list(dict.fromkeys(vehicle_candidates))
print("\nVehicle candidates for Loconav probe:", vehicle_candidates)

loc_headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
for veh in vehicle_candidates[:3]:
    url = "https://marketplace.loconav.com/api/v1/vehicles/fuel"
    params = {"vehicle_number": veh, "start_time": start, "end_time": end}
    try:
        r = requests.get(url, headers=loc_headers, params=params, timeout=15)
        fname = (
            OUT_DIR
            / f"loconav_site{site_id}_{veh}_{int(datetime.datetime.utcnow().timestamp())}.json"
        )
        with open(fname, "w") as fh:
            json.dump({"status_code": r.status_code, "url": r.url, "text": r.text}, fh)
        print("Saved Loconav response for", veh, "->", fname)
    except Exception as e:
        print("Loconav probe failed for", veh, e)

# Roadcaste: use partner_dg_fuel_id if exists
rc_device = getattr(site, "partner_dg_fuel_id", None)
if rc_device:
    rc_url = "https://test-track.roadcast.net/api/v1/auth/pull_fuel_report"
    rc_headers = {"Authorization": "Basic QXZpY29ubjpBYmNAMTIzNA=="}
    params = {"device_imei": str(rc_device), "from_time": start, "to_time": end}
    try:
        r = requests.get(rc_url, params=params, headers=rc_headers, timeout=15)
        fname = (
            OUT_DIR
            / f"roadcast_site{site_id}_{rc_device}_{int(datetime.datetime.utcnow().timestamp())}.json"
        )
        with open(fname, "w") as fh:
            json.dump({"status_code": r.status_code, "url": r.url, "text": r.text}, fh)
        print("Saved Roadcaste response ->", fname)
    except Exception as e:
        print("Roadcaste probe failed for", rc_device, e)
else:
    print("No partner_dg_fuel_id present on site; skipping Roadcaste probe")

print("\nDone")
