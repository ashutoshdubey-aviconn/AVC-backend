#!/usr/bin/env python3
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path
import json

OUT_DIR = Path("/home/ashutosh-dubey/django_project/logs/third_party")
OUT_DIR.mkdir(parents=True, exist_ok=True)

vehicle = "PBDN450"
now = datetime.utcnow()
start = now - timedelta(hours=1)
start_s = int(start.timestamp())
end_s = int(now.timestamp())

url = "https://marketplace.loconav.com/api/v1/vehicles/fuel"
headers = {"User-Authentication": "51uKh_YaL72s7zhx6bwZ"}
params = {"vehicle_number": vehicle, "start_time": start_s, "end_time": end_s}

try:
    r = requests.get(url, headers=headers, params=params, timeout=20)
    out = {"status_code": r.status_code, "url": r.url, "text": r.text}
except Exception as e:
    out = {"error": str(e)}

fname = OUT_DIR / f"loconav_seconds_{vehicle}_{int(time.time())}.json"
with open(fname, "w") as fh:
    json.dump(out, fh)
print("Saved", fname)
