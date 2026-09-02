#!/usr/bin/env python3
import requests
import time
import json
from pathlib import Path
from datetime import datetime

OUT_DIR = Path("/home/ashutosh-dubey/django_project/logs/third_party")
OUT_DIR.mkdir(parents=True, exist_ok=True)

url = "https://marketplace.loconav.com/api/v1/vehicles"
headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}

try:
    r = requests.get(url, headers=headers, timeout=20)
    out = {"status_code": r.status_code, "url": r.url, "text": r.text}
except Exception as e:
    out = {"error": str(e)}

fname = OUT_DIR / f"loconav_devices_{int(time.time())}.json"
with open(fname, "w") as fh:
    json.dump(out, fh)

print("Saved Loconav devices response to", fname)
if out.get("status_code") == 200:
    try:
        j = json.loads(out["text"])
        # If API returns list of vehicles under 'data' or directly
        vehicles = j.get("data") if isinstance(j, dict) else j
        if vehicles:
            print("Found", len(vehicles), "vehicles (top 10):")
            for v in vehicles[:10]:
                # best-effort display
                name = (
                    v.get("display_number") or v.get("vehicle_number") or v.get("name")
                )
                imei = v.get("uniqueid") or v.get("imei") or v.get("device_imei")
                print("-", name, imei)
        else:
            print("No vehicles array found in response; saved raw output to file")
    except Exception:
        print("Could not parse JSON body; saved raw output to file")
