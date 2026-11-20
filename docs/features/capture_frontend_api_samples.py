"""Capture real responses of the frontend APIs on a server, for the frontend API guide.

Read-only: only GETs, list / summary POSTs and previews (catchUpSpread / baselineSetup with
apply=false) are called. APIs that write (saveBaseline/, alarmSettings/ POST, spread apply)
are documented from the code in build_feature_tracker.py, never called here.

Run on the test server (prints JSON between markers), locally:

    ssh ubuntu@43.204.53.81 'cd ~/django_project && virtualwarehouse/bin/python manage.py shell' \\
        < docs/features/capture_frontend_api_samples.py \\
        | sed -n '/^==SAMPLES==$/,/^==END==$/p' | sed '1d;$d' > docs/features/frontend_api_samples_test_server.json

Lists of objects are cut to 2 items (+ a note with the full count); lists of numbers to 24.
"""

import json
from datetime import date, timedelta

from django.conf import settings
from rest_framework.test import APIClient

from wareApp.models import HomeGatewayStatus, Site, User

SITE_ID = 114              # Myntra BGLR Inventory Saving: alarms, spread hours on 15 Nov
WH_SITE_ID = 136           # PPL GGN WHTM (WH-metering)
SPREAD_DAY = "2026/11/15"  # a day with spread (estimated) hours at site 114
TODAY = date.today().strftime("%Y/%m/%d")
WEEK_AGO = (date.today() - timedelta(days=7)).strftime("%Y/%m/%d")
SYNCING_SITE_ID = 109      # Myntra Bhiwandi Inventory Lights: a gateway offline, aisles syncing


def trim(value, depth=0):
    if isinstance(value, dict):
        return {k: trim(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if value and all(not isinstance(v, (dict, list)) for v in value):
            kept = value[:24]
        else:
            kept = [trim(v, depth + 1) for v in value[:2]]
        if len(value) > len(kept):
            kept.append(f"... {len(value)} items in total")
        return kept
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + "..."
    return value


host = next((h for h in settings.ALLOWED_HOSTS if h not in ("*", "")), "127.0.0.1").lstrip(".")
admin = User.objects.filter(UserType=1, is_active=True).order_by("id").first()
site = Site.objects.get(id=SITE_ID)
customer_id = site.customer_id
client = APIClient(HTTP_HOST=host)
client.force_authenticate(admin)

CALLS = [
    ("alarmList", "POST", "alarmList/", {"siteId": SITE_ID}),
    ("alarmListDetail", "POST", "alarmListDetail/", {"siteId": SITE_ID, "alarm_type": 17}),
    ("alarmTypeApi", "POST", "alarmTypeApi/", {}),
    ("alarmapi", "POST", "alarmapi/", {}),
    ("snapshot", "POST", "snapshot/", {"user_id": admin.id}),
    ("alarmListOnCustomerPage", "POST", "alarmListOnCustomerPage/", {"id": customer_id}),
    ("getCustAlarmGraph", "POST", "getCustAlarmGraph/", {"id": customer_id}),
    ("customerSnapShotEnergySavingApi", "POST", "customerSnapShotEnergySavingApi/", {"id": customer_id}),
    ("siteSnapShotEnergySavingApi", "POST", "siteSnapShotEnergySavingApi/", {"site_id": SITE_ID, "user_type": 1}),
    ("alarmListOnSitePage", "POST", "alarmListOnSitePage/", {"site_id": SITE_ID}),
    ("consumptionAlarms", "POST", "consumptionAlarms/", {"site_id": SITE_ID}),
    ("gateway-status", "GET", "gateway-status/", {"limit": 3}),
    ("meter-disconnections", "GET", "meter-disconnections/", {"limit": 2}),
    ("catchUpSpread", "POST", "catchUpSpread/", {"site_id": SITE_ID, "day": TODAY, "apply": False}),
    ("baselineSetup", "POST", "baselineSetup/", {"site_id": SITE_ID, "sample_from": "2026/11/10",
                                                 "sample_to": "2026/11/12", "apply": False}),
    ("hourlySavingData", "POST", "hourlySavingData/", {"site_id": SITE_ID, "date": SPREAD_DAY}),
    ("submeteringHourlyData", "POST", "submeteringHourlyData/", {"site_id": SITE_ID, "date": SPREAD_DAY}),
    ("getSiteHourlyConsumptionData", "POST", "getSiteHourlyConsumptionData/", {"site_id": WH_SITE_ID, "date": SPREAD_DAY}),
    ("alarmSettings", "GET", "alarmSettings/", {"site_id": SITE_ID}),
    ("syncStatus", "GET", "syncStatus/", {"site_id": SITE_ID}),
    ("recoveryHistory", "GET", "recoveryHistory/", {"site_id": SITE_ID, "limit": 2}),
    # Extra examples for the frontend handoff workbook (build_frontend_api_handoff.py).
    ("gateway-status-health", "GET", "gateway-status/", {"limit": 1000}),
    ("syncStatus-syncing", "GET", "syncStatus/", {"site_id": SYNCING_SITE_ID}),
    ("recoveryHistory-syncing", "GET", "recoveryHistory/", {"site_id": SYNCING_SITE_ID, "limit": 2}),
    ("catchUpSpread-spread-day", "POST", "catchUpSpread/", {"site_id": SITE_ID, "day": "2026/11/16", "apply": False}),
    ("catchUpSpread-history", "POST", "catchUpSpread/", {"site_id": SITE_ID, "history": True,
                                                        "from": WEEK_AGO, "to": TODAY}),
]


def _one_of_each(rows, key, values):
    """First row for each value of ``key`` (an example of every state)."""
    picked = []
    for value in values:
        picked += [row for row in rows if row.get(key) == value][:1]
    return picked


# Before trimming: keep one example of every state.
PICK = {
    "gateway-status-health": lambda body: {
        **body, "limit": 1000,
        "results": _one_of_each(body.get("results", []), "health", ["online", "offline", "modbus_issue"]),
    },
    "syncStatus-syncing": lambda body: {
        **body, "data": _one_of_each(body.get("data", []), "sync", ["synced", "syncing"]),
    },
}

out = {
    "_note": f"Captured on the test server ({date.today():%d %b %Y}) as a Super Admin; lists cut to 2 items. "
             f"Site {SITE_ID} ({site.site_name}), WH-metering site {WH_SITE_ID}, spread day {SPREAD_DAY}.",
    "_gateways": HomeGatewayStatus.objects.count(),
}
for name, method, path, body in CALLS:
    url = "/api/" + path
    try:
        if method == "GET":
            response = client.get(url, body)
        else:
            response = client.post(url, body, format="json")
        try:
            data = response.json()
        except ValueError:
            data = response.content.decode(errors="replace")[:300]
        if name in PICK and isinstance(data, dict):
            data = PICK[name](data)
        out[name] = {"method": method, "url": url, "request": body, "http": response.status_code, "body": trim(data)}
    except Exception as error:  # keep going: one failing API must not hide the others
        out[name] = {"method": method, "url": url, "request": body, "error": repr(error)[:300]}

print("==SAMPLES==")
print(json.dumps(out, indent=1, default=str, ensure_ascii=False))
print("==END==")
