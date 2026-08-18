#!/usr/bin/env python3
import requests
import time
import json
from pathlib import Path

OUT_DIR = Path("/home/ashutosh-dubey/django_project/logs/third_party")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Roadcaste 'pull_api' mapping endpoint (used in tasks.py)
url = "https://api-track-py.roadcast.co.in/api/v1/auth/pull_api?username=Aviconn&password=Abc@1234"
headers = {
    "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3MjczMzE2MjIsIm5iZiI6MTcyNzMzMTYyMiwianRpIjoiZGMwODI2YzUtYjA3NS00MDg2LWIyNjUtZGM5ZDI3NWEzYjE4IiwiZXhwIjoxNzI3NTkwODIyLCJpZGVudGl0eSI6eyJpZCI6Nzg0NDYsImRiIjowLCJjbyI6MSwibmFtZSI6IkF2aWNvbm4iLCJ0eXBlIjoiYWRtaW4iLCJyZWFkX29ubHkiOjAsInR6IjotMzMwLCJ0el9zIjoiQXNpYS9Lb2xrYXRhIiwic3NvIjowLCJkZXZpY2UiOiJ3ZWIiLCJhbGlhcyI6IiJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.Fwn08jciwxlm659ZYEfq1LpQBAf2fddUZ9zrjmrzcmU"
}

try:
    r = requests.get(url, headers=headers, timeout=20)
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
