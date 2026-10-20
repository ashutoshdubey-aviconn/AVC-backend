#!/usr/bin/env python3
import requests

from _secrets import ROADCAST_PULL_API_URL, roadcast_pull_params
import time
import json
from pathlib import Path

OUT_DIR = Path("/home/ashutosh-dubey/django_project/logs/third_party")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Roadcaste 'pull_api' mapping endpoint (used in tasks.py)
url = ROADCAST_PULL_API_URL

try:
    r = requests.get(url, params=roadcast_pull_params(), timeout=20)
    out = {"status_code": r.status_code, "url": r.url, "text": r.text}
except Exception as e:
    out = {"error": str(e)}

fname = OUT_DIR / f"roadcast_devices_{int(time.time())}.json"
with open(fname, "w") as fh:
    json.dump(out, fh)

print("Saved Roadcaste devices response to", fname)
if out.get("status_code") == 200:
    try:
        j = json.loads(out["text"])
        data = j.get("data") if isinstance(j, dict) else j
        if data:
            print("Found", len(data), "devices (top 10):")
            for dev in data[:10]:
                name = dev.get("name") or dev.get("device_name")
                imei = dev.get("device_imei") or dev.get("uniqueid")
                print("-", name, imei)
        else:
            print("No devices array found in response; saved raw output to file")
    except Exception:
        print("Could not parse JSON body; saved raw output to file")
