"""Build FRONTEND_API_HANDOFF.xlsx: the APIs built in this branch, for the frontend developer.

    virtualwarehouse/bin/python docs/features/build_frontend_api_handoff.py

One workbook with everything needed to call them: login and token, method, URL, who may call it,
request fields, a real request / response (captured on the test server by
capture_frontend_api_samples.py, read-only calls; calls that write show an example from the code),
response fields, errors, how it works, the screen that uses it, and the values to show.
Edit CALLS / VALUES below when an API changes, re-capture the samples, then re-run.
"""

import json
import pathlib

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = pathlib.Path(__file__).resolve().parent
SAMPLES = json.loads((HERE / "frontend_api_samples_test_server.json").read_text())
FE = "src/app/alarm/"
TEST_ONLY = "Test server (branch full-optimization-v2); not on main yet"
TOKEN = "Authorization: Token <token>"

# Every call: request / response come from SAMPLES[sample] when given, else from "request" / "response".
CALLS = [
    dict(
        feature="Login", call="Log in (get the token)", method="POST", url="/api/login/",
        auth="None", who="Everyone", available="Test and main",
        request_fields=[("username", "string", "yes", "Login name"),
                        ("password", "string", "yes", "The password base64-encoded (btoa(password))")],
        request={"username": "AVCadmin", "password": "<base64 of the password>"},
        response={"token": "<40-character token>",
                  "user": {"id": 1, "username": "AVCadmin", "email": "<e-mail>", "UserType": 1,
                           "first_name": "", "last_name": "", "Contact_number": "<number>"}},
        response_fields=[("token", "string", "Send on every call: header Authorization: Token <token>"),
                         ("user.UserType", "number", "1 = Super Admin (needed for spread, sync, baseline, alarm settings); "
                                                     "2 = Aviconn admin; 4 = customer; 5 = site manager")],
        errors="400 wrong username / password; 429 too many attempts (rate limit)",
        how="Returns the user's token (created on first login). Keep it (the frontend stores it in localStorage 'token') "
            "and send it in the Authorization header of every other call.",
        screen="login/login.component.ts",
    ),
    dict(
        feature="Gateway status", call="Gateway list with health (online / offline / Gateway Service issue)",
        method="GET", url="/api/gateway-status/", auth="None (AllowAny)", who="Everyone",
        available="Test (health fields); main has the list without health", sample="gateway-status-health",
        request_fields=[("limit", "number", "no", "Page size, 1-500 (default 100); the panel asks 1000"),
                        ("offset", "number", "no", "Rows to skip (default 0)")],
        response_fields=[
            ("count / limit / offset", "number", "Total gateways and the page"),
            ("results[].gateway_id", "string", "Gateway id, e.g. avc_DHLB500_LuhariSubmeter_000119_1"),
            ("results[].status", "boolean", "Data in the last hour (old field, unchanged)"),
            ("results[].health", "string", "online | offline | modbus_issue - show 'Gateway Service issue' for "
                                           "modbus_issue (pings, but no meter data). Missing on main: use status."),
            ("results[].health_since", "string | null", "ISO time the open gateway alarm started"),
            ("results[].health_detail", "string | null", "Alarm text, e.g. 'Gateway ...: pings OK, no consumption / "
                                                         "recovery / load data for 3.0 h' - use as tooltip"),
            ("results[].site_id / site_name / customer_name", "", "Where the gateway is"),
            ("results[].latitude / longitude", "number | null", "Map position if set"),
        ],
        errors="400 limit / offset not numbers; 500 {message, error}",
        how="Every gateway with its site and customer. health comes from the open gateway alarms: an open Gateway "
            "Service / Modbus Issue alarm (pings arrive, no meter data) gives modbus_issue, an open Gateway Disconnected "
            "alarm (no data, no ping) gives offline; otherwise online / offline follows status. The gateway check runs "
            "every 5 min; an alarm opens after 1 h without data.",
        screen="alarm/gateway-status.component.ts (dashboard Gateway Status panel: filter All / Online / Offline / "
               "Gateway Service issue, badge, tooltip)",
    ),
    dict(
        feature="Catch-up spread", call="Preview the catch-ups of a day (changes nothing)", method="POST",
        url="/api/catchUpSpread/", auth=TOKEN, who="Super Admin (UserType 1)", available=TEST_ONLY,
        sample="catchUpSpread-spread-day",
        request_fields=[("site_id", "number", "yes", "Site"),
                        ("day", "string", "yes", "YYYY/MM/DD - the day of the catch-up hours"),
                        ("legs", "string[]", "no", "Only these aisles (leg ids)"),
                        ("apply", "boolean", "no", "false (default) = preview")],
        response_fields=[
            ("catch_ups[]", "list", "Catch-ups ready to spread. Per item: leg_id, aisle_name, catch_up_at, kwh, "
                                    "gap_from, gap_to, missing_hours, empty_hours (no row), no_data_hours (ERROR404), "
                                    "share_kwh (per hour after), normal_hour_kwh, spread_day_kwh (share x 24), "
                                    "daily_average_kwh, days[] {day, before, after}, manual_required, warnings[]"),
            ("catch_ups[].manual_required", "boolean", "true: a doubt (see warnings) - show 'Manual spread required', "
                                                       "do not tick by default; the night job leaves it"),
            ("waiting[]", "list", "Not offered yet: {leg_id, aisle_name, at, kwh, missing_hours, reason} - aisle not "
                                  "synced, recovery running, or the next hour not in"),
            ("not_spreadable[]", "list", "{leg_id, aisle_name, at, kwh, normal_hour_kwh, reason}: gap start unknown"),
            ("applied_spreads[]", "list", "Spreads of this day: id, aisle_name, catch_up_at, original_kwh, gap_from, "
                                          "hours, share_kwh, mode (manual | automatic), applied_by, applied_at, "
                                          "can_undo, undo_until, empty_hours, no_data_hours"),
        ],
        errors="400 {error}: bad day, unknown site_id / legs; 403 not Super Admin; 401 no token",
        how="A gateway service stops, nothing is saved, and the first hour back carries the gap's energy. The preview "
            "finds those hours: the gap is hours without a row and ERROR404 hours (stored as 0); the first hour after "
            "is > 3 x the aisle's normal hour. Offered only when the aisle is synced again, the next hour is in and "
            "recovery has ended. The share is flat: kWh / (gap hours + 1).",
        screen="alarm/catch-up-spread.component.ts (site page -> Spread catch-up, or Spread... on a Consumption "
               "Spike row)",
    ),
    dict(
        feature="Catch-up spread", call="Spread the ticked catch-ups (manual)", method="POST",
        url="/api/catchUpSpread/", auth=TOKEN, who="Super Admin", available=TEST_ONLY,
        request_fields=[("site_id", "number", "yes", "Site"), ("day", "string", "yes", "YYYY/MM/DD"),
                        ("legs", "string[]", "yes", "The ticked aisles (leg ids)"),
                        ("apply", "boolean", "yes", "true")],
        request={"site_id": 114, "day": "2026/11/16", "legs": ["692"], "apply": True},
        response={"status": 200, "applied": True, "catch_ups": [], "waiting": [], "not_spreadable": [],
                  "applied_spreads": [{"id": 12, "leg_id": "692", "aisle_name": "F1-Outward&Hub area",
                                       "catch_up_at": "2026/11/16 09:00", "original_kwh": 43.6,
                                       "gap_from": "2026/11/14 20:00", "hours": 38, "share_kwh": 1.147,
                                       "mode": "manual", "applied_by": "AVCadmin", "applied_at": "2026/11/17 11:48",
                                       "undone_at": None, "undo_until": "2026/11/22 11:48", "can_undo": True,
                                       "empty_hours": 37, "no_data_hours": 0}],
                  "spreads": [{"id": 12, "leg_id": "692", "catch_up_at": "2026/11/16 09:00", "hours": 38,
                               "share_kwh": 1.147, "mode": "manual"}]},
        response_fields=[("applied", "boolean", "true"),
                         ("spreads[]", "list", "The spreads just made: id, leg_id, catch_up_at, hours, share_kwh, mode"),
                         ("applied_spreads[]", "list", "The day's spreads after the change (as in the preview)")],
        errors="400 {error}: 'no catch-up hour to spread', '<aisle> <hour> changed since the preview' (nothing written); "
               "403; 401",
        how="One transaction per catch-up: every gap hour and the catch-up hour get the share as real readings, hourly "
            "and daily of every touched day are recalculated, the day's Consumption Spike alarm is closed, and a record "
            "keeps every hour (before -> after) and mode manual with the user. Total energy unchanged. Recovery replies "
            "never change spread hours afterwards.",
        screen="alarm/catch-up-spread.component.ts ('Spread N catch-up hour(s)...' -> 'Yes, spread')",
    ),
    dict(
        feature="Catch-up spread", call="Undo a spread (within 5 days)", method="POST", url="/api/catchUpSpread/",
        auth=TOKEN, who="Super Admin", available=TEST_ONLY,
        request_fields=[("undo", "number", "yes", "Spread id (applied_spreads[].id)")],
        request={"undo": 12},
        response={"status": 200, "undone": 12, "hours_reverted": 37, "estimated_hours_removed": 37},
        response_fields=[("undone", "number", "The spread id"),
                         ("hours_reverted", "number", "Gap hours put back (estimated_hours_removed: same, old name)")],
        errors="400 {error}: 'this spread was already undone', 'undo was possible for 5 days, until 22 Nov 2026 11:48', "
               "'unknown spread id'; 403; 401",
        how="Created hours are removed, ERROR404 hours go back to 0, the catch-up hour back to its original kWh, and "
            "the days are recalculated. Only while can_undo is true (5 days after the spread); then show 'closed'.",
        screen="alarm/catch-up-spread.component.ts (Undo -> 'Yes, undo')",
    ),
    dict(
        feature="Catch-up spread", call="Spread history of a site", method="POST", url="/api/catchUpSpread/",
        auth=TOKEN, who="Super Admin", available=TEST_ONLY, sample="catchUpSpread-history",
        request_fields=[("site_id", "number", "yes", "Site"), ("history", "boolean", "yes", "true"),
                        ("from", "string", "no", "YYYY/MM/DD (default: 30 days before to)"),
                        ("to", "string", "no", "YYYY/MM/DD (default today); at most 92 days")],
        response_fields=[("count", "number", "Spreads found"),
                         ("spreads[]", "list", "Newest first: as applied_spreads[] plus undone_at and hours_detail[]"),
                         ("spreads[].mode", "string", "manual (show 'Manual - applied_by') | automatic (night job)"),
                         ("spreads[].hours_detail[]", "list", "One per hour: at (ISO), kind empty | no_data | catch_up, "
                                                              "before (kWh, null = no row), after (kWh)")],
        errors="400 {error}: 'from is after to', 'history covers at most 92 days'; 403; 401",
        how="Every spread of the site whose catch-up hour is in the range, manual and automatic, with its per-hour "
            "record for checking.",
        screen="alarm/catch-up-spread.component.ts (History button: date range, click the hours to expand)",
    ),
    dict(
        feature="Sync & recovery", call="Sync status of every aisle / power source", method="GET",
        url="/api/syncStatus/", auth=TOKEN, who="Super Admin", available=TEST_ONLY, sample="syncStatus-syncing",
        request_fields=[("site_id", "number", "yes", "Site (query parameter)")],
        response_fields=[
            ("total", "number", "Aisles + power sources"),
            ("counts.sync / counts.recovery", "object", "Rows per value (for filter chips / summary)"),
            ("data[].object_type / object_name", "string", "aisle | power_source, and its name"),
            ("data[].home_gateway_id", "string", "Gateway"),
            ("data[].sync / sync_display", "string", "synced | syncing | unknown"),
            ("data[].last_sync_at", "string | null", "ISO time of the last data received"),
            ("data[].recovery / recovery_display", "string", "not_needed | recovered | not_received | received"),
            ("data[].last_recovered_at", "string | null", "ISO time missing data was last recovered (null = never)"),
            ("data[].attempts / max_attempts", "number", "Syncing rows: times the server asked the gateway for this "
                                                         "aisle's missing data (0 = not asked yet), of 3"),
            ("data[].last_requested_at", "string | null", "When it last asked (only when attempts > 0)"),
        ],
        errors="400 'Give a valid site_id.'; 403; 401",
        how="Healthy = Synced / recovery Not needed / last sync time. Gap filled = Synced / Recovered / last recovered "
            "time. No data for 70 min or more = Syncing / Not received / last data time + attempts. The server asks the "
            "gateway for missing hours when a packet reveals a gap, up to 3 times (10 min apart).",
        screen="alarm/sync-status.component.ts (site page -> Data sync)",
    ),
    dict(
        feature="Sync & recovery", call="Recovery requests (history)", method="GET", url="/api/recoveryHistory/",
        auth=TOKEN, who="Super Admin", available=TEST_ONLY, sample="recoveryHistory-syncing",
        request_fields=[("site_id", "number", "yes", "Site"),
                        ("status", "string", "no", "requested | response_received | applied | verified | failed | timeout"),
                        ("recovery_type", "string", "no", "hourly_consumption | daily_consumption | load_runtime"),
                        ("limit / offset", "number", "no", "Page (limit max 500, default 50)")],
        response_fields=[("count / limit / offset", "number", "Paging"),
                         ("results[]", "list", "Newest first: recovery_type(_display), status, gateway_id, object_name, "
                                               "missing_from / missing_to, expected_slots, recovered_slots, error_slots "
                                               "(hours without data on the gateway), attempt, requested_at, "
                                               "response_received_at, applied_at, verified_at, failed_reason, "
                                               "catch_up_at, is_active")],
        errors="400 bad site_id / limit; 403; 401",
        how="One row per gap asked from a gateway. Requests sent from the test server never reach the gateways (they "
            "talk to main), so on test most end 'failed'.",
        screen="alarm/sync-status.component.ts (Recovery requests table: status filter, Newer / Older)",
    ),
    dict(
        feature="Baseline", call="Automatic baseline: preview", method="POST", url="/api/baselineSetup/",
        auth=TOKEN, who="Super Admin", available=TEST_ONLY, sample="baselineSetup",
        request_fields=[("site_id", "number", "yes", "Site"),
                        ("sample_from / sample_to", "string", "yes", "YYYY/MM/DD - complete days before today"),
                        ("effective_from", "string", "no", "YYYY/MM/DD (default: the day after sample_to)"),
                        ("legs", "string[]", "no", "Only these aisles"),
                        ("overrides", "object", "no", "{leg_id: kWh} - a baseline typed by the user"),
                        ("apply", "boolean", "no", "false (default) = preview")],
        response_fields=[("plan.aisles[]", "list", "leg_id, aisle_name, is_active, days {day: kWh}, average, override, "
                                                   "baseline, warnings[]"),
                         ("plan.site_total", "number", "Sum of the baselines (kWh / day)"),
                         ("plan.effective_from", "string", "Applies from; send it back on apply"),
                         ("plan.errors[]", "list", "Block apply (e.g. 'no usable sample day - give an override')")],
        errors="400 {error}: bad dates, 'sample days must be complete days before today', unknown site_id; 403; 401",
        how="Per aisle the average daily consumption of the sample days (days without data or 0 kWh left out and "
            "warned). Changes nothing.",
        screen="baseline/baseline-setup.component.ts (Baseline page -> Automatic baseline -> Calculate)",
    ),
    dict(
        feature="Baseline", call="Automatic baseline: set (apply)", method="POST", url="/api/baselineSetup/",
        auth=TOKEN, who="Super Admin", available=TEST_ONLY,
        request_fields=[("(same as preview)", "", "", ""), ("apply", "boolean", "yes", "true"),
                        ("site_manager", "object", "no", "{name, contact, email}")],
        request={"site_id": 198, "sample_from": "2026/10/29", "sample_to": "2026/10/31",
                 "effective_from": "2026/11/01", "overrides": {"1273": 45.0},
                 "site_manager": {"name": "...", "contact": "...", "email": "..."}, "apply": True},
        response={"status": 200, "applied": True, "plan": {"...": "same as preview"},
                  "result": {"baselines": {"1268": "created", "1273": "updated"},
                             "backfill": {"daily": 30, "hourly": 720},
                             "site": {"is_live": True, "live_date": "2026-09-28T16:18:00",
                                      "baseline_date": "2026-11-01T00:00:00"}}},
        response_fields=[("result.baselines", "object", "{leg_id: created | updated}"),
                         ("result.backfill", "object", "Daily / hourly rows rewritten with the new baseline"),
                         ("result.site", "object", "Site fields after the change")],
        errors="400 {error}: unresolved plan.errors (e.g. '<aisle> (<leg>): no usable sample day - give an override'); "
               "403; 401",
        how="One transaction: closes the open baselines on effective_from, creates the new ones, rewrites daily / hourly "
            "baseline and saving from that day.",
        screen="baseline/baseline-setup.component.ts (Set baseline -> confirmation)",
    ),
    dict(
        feature="Baseline", call="Save one aisle's baseline (older screen)", method="POST", url="/api/saveBaseline/",
        auth=TOKEN, who="Logged-in users of the baseline page", available="Test and main (first-baseline crash fixed "
                                                                          "on test)",
        request_fields=[("siteId", "number", "yes", "Site"), ("legId", "string", "yes", "Aisle leg id"),
                        ("baselineValue", "number", "yes", "kWh / day"), ("date", "string", "yes", "YYYY/MM/DD")],
        request={"siteId": 114, "legId": "671", "baselineValue": 9.21, "date": "2026/11/13"},
        response={"result": 1, "msg": "baseline value set"},
        response_fields=[("result", "number", "1 = saved")],
        errors="500 on bad input",
        how="Sets the baseline of one aisle from a date (baseline page table).",
        screen="baseline/baseline.component.ts",
    ),
    dict(
        feature="Alarm settings", call="Alarm settings of a site", method="GET", url="/api/alarmSettings/",
        auth=TOKEN, who="Super Admin", available=TEST_ONLY, sample="alarmSettings",
        request_fields=[("site_id", "number", "yes", "Site (query parameter)")],
        response_fields=[("data[]", "list", "One per alarm type: alarm_type, alarm_name, group (Power / Consumption / "
                                            "Gateway), raised, unit (null = no manual threshold), mode (default | auto | "
                                            "manual | off), threshold, email_software, email_ground, "
                                            "repeat_tolerance_percent")],
        errors="400 'Give a valid site_id.'; 403; 401",
        how="Default = works as before (site fields); Auto = system thresholds; Manual = your threshold in unit; Off = "
            "not raised on this site.",
        screen="alarm/alarm-settings.component.ts (site page -> Alarms -> settings button)",
    ),
    dict(
        feature="Alarm settings", call="Save one alarm type's setting", method="POST", url="/api/alarmSettings/",
        auth=TOKEN, who="Super Admin", available=TEST_ONLY,
        request_fields=[("site_id", "number", "yes", "Site"), ("alarm_type", "number", "yes", "0-17"),
                        ("mode", "string", "yes", "default (removes the setting) | auto | manual | off"),
                        ("threshold", "number", "manual only", "> 0, in the type's unit"),
                        ("email_software / email_ground", "boolean", "no", "Who gets the e-mail"),
                        ("repeat_tolerance_percent", "number", "no", "Repeat e-mailed only when this much worse")],
        request={"site_id": 114, "alarm_type": 7, "mode": "manual", "threshold": 250, "email_software": True,
                 "email_ground": False},
        response={"status": 200, "site_id": 114, "site_name": "...", "data": ["(same as GET, this type changed)"]},
        response_fields=[("data[]", "list", "The site's settings after the change")],
        errors="400 {msg}: 'Manual needs a threshold above 0 (kWh / day).', '<alarm> has no manual threshold: use auto "
               "or off.', bad mode / type / site; 403; 401",
        how="Saved at once; the alarm code uses it at its next check.",
        screen="alarm/alarm-settings.component.ts (Save / Undo per row)",
    ),
    dict(
        feature="Hourly charts", call="Hourly chart of a saving site (estimated flag)", method="POST",
        url="/api/hourlySavingData/", auth="None (AllowAny)", who="Everyone",
        available="Test (estimated[]); main without it", sample="hourlySavingData",
        request_fields=[("site_id", "number", "yes", "Site"), ("date", "string", "yes", "YYYY/MM/DD")],
        response_fields=[("Hours", "string[24]", "00:00 ... 23:00"),
                         ("Data[] / SavingData[]", "list", "Highcharts series: name, data[24] kWh, type"),
                         ("Data[].estimated", "boolean[24]", "true = hour filled by an older spread (now always false: "
                                                             "spread hours are real readings since 20 Nov). Missing on "
                                                             "main: treat as false")],
        errors="404 unknown site; 400 bad date",
        how="Per aisle 24 hourly values (+ a baseline spline on live sites).",
        screen="warehouse/warehouse.component.ts; shared/estimated-hours.ts",
    ),
    dict(
        feature="Alarm lists", call="Open alarms of one type ('Open for')", method="POST", url="/api/alarmListDetail/",
        auth=TOKEN, who="Logged-in users", available="Test (open_days / open_for); main without them",
        sample="alarmListDetail",
        request_fields=[("siteId", "number", "yes", "Site"), ("alarm_type", "number", "yes", "Alarm type")],
        response_fields=[("data[].issue", "string", "Readable cause"),
                         ("data[].created / last_seen", "string", "First / last seen (ISO)"),
                         ("data[].open_days / open_for", "number / string", "How long it has been open, e.g. "
                                                                             "'2 days 5 h' (orange from 1 day)")],
        errors="500 {status, error}",
        how="Active alarms only, newest first.",
        screen="alarm/alarm.component.ts (site alarm panel, 'Open for' column)",
    ),
]

# Values to show (label / colour) per field.
VALUES = [
    ("gateway-status health", "online", "Online", "green", "Data arriving"),
    ("gateway-status health", "offline", "Offline", "red", "No data and no ping (Gateway Disconnected alarm), or no data"),
    ("gateway-status health", "modbus_issue", "Gateway Service issue", "amber", "Pings, but no meter data (Gateway "
                                                                               "Service / Modbus Issue alarm)"),
    ("syncStatus sync", "synced", "Synced", "green", "Data arriving"),
    ("syncStatus sync", "syncing", "Syncing", "amber", "No data for 70 min or more; being asked from the gateway"),
    ("syncStatus recovery", "not_needed", "Not needed", "grey", "Nothing missing"),
    ("syncStatus recovery", "recovered", "Recovered", "green", "Missing data was filled (last_recovered_at)"),
    ("syncStatus recovery", "not_received", "Not received", "red", "Missing data not received yet (see attempts)"),
    ("syncStatus recovery", "received", "Received", "blue", "Answer arrived, being applied (a moment)"),
    ("recoveryHistory status", "requested / response_received / applied / verified / failed / timeout", "as text",
     "verified green, failed red", "Life of one recovery request"),
    ("catchUpSpread mode", "manual", "Manual · <applied_by>", "blue", "Spread by a person"),
    ("catchUpSpread mode", "automatic", "Automatic", "green", "Spread by the night job (19:00-11:00, all Sunday)"),
    ("catchUpSpread hours_detail.kind", "empty / no_data / catch_up", "No row / No data (ERROR404) / Catch-up hour", "",
     "What the hour was before the spread"),
    ("catchUpSpread manual_required", "true", "Manual spread required", "amber", "Show warnings[]; do not tick"),
    ("catchUpSpread can_undo", "true / false", "Undo (until <undo_until>) / closed (5 days passed)", "", "5-day undo"),
    ("alarmSettings mode", "default / auto / manual / off", "Default / Auto / Manual / Off", "", "Manual needs threshold"),
    ("alarmSettings unit", "V / PF / kWh / day / °C / hours / null", "unit next to the threshold", "",
     "null = no manual threshold (disable Manual)"),
]

START = [
    ("What", "The APIs built in this branch for the frontend: gateway status (Gateway Service issue), catch-up "
             "spread, sync & recovery status, baseline, alarm settings, hourly estimated flag, alarm 'Open for'."),
    ("Base URL", "/api/ on the server that serves the page. Test: http://43.204.53.81/api/  Main: "
                 "https://asem.aviconncorp.com/api/ (most of these are on test only - column 'Available on')."),
    ("Login", "POST /api/login/ {username, password: base64(password)} -> {token, user{UserType...}}. Keep the token."),
    ("Headers", "Authorization: Token <token>   and   Content-Type: application/json"),
    ("Who", "Super Admin = user.UserType 1. Calls marked Super Admin return 403 for other users: hide those "
            "buttons / panels for them."),
    ("Errors", "401 {detail}: no / bad token -> log in again. 403 {detail}: not allowed. 400 {error} or {msg}: show "
               "the text next to the form. Check the HTTP status first; success flags differ per API (status: 200, "
               "result: 1)."),
    ("Dates", "Send YYYY/MM/DD. Responses: ISO 2026-11-20T15:20:59 (alarms, gateways, sync) or YYYY/MM/DD HH:MM "
              "(catch-up spread)."),
    ("Write calls", "Spread apply / undo, baseline apply, saveBaseline and alarmSettings POST change data: always "
                    "ask an inline confirmation first. Previews (apply false) never change anything."),
    ("Examples", "Responses in 'Examples' are real, captured on the test server; lists are cut to 2 items "
                 "('... N items in total'). Write calls show an example from the code."),
    ("Sheets", "APIs (one row per call) · Request fields · Response fields · Examples (full JSON) · Values (labels "
               "and colours to show)."),
    ("Source", "Generated by docs/features/build_frontend_api_handoff.py; details in docs/features/"
               "FRONTEND_API_GUIDE.md, docs/consumption/CATCH_UP_SPREAD.md, BASELINE_SETUP_FRONTEND.md."),
]

thin = Side(style="thin", color="BFBFBF")


def sheet(book, title, columns, rows, first=False):
    ws = book.active if first else book.create_sheet()
    ws.title = title
    for index, (name, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=index, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(index)].width = width
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
            if isinstance(value, str) and value.startswith(("{", "[")) and "\n" in value:
                cell.font = Font(name="Consolas", size=9)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
    return ws


# When no gateway is in that state at capture time: the real site 119 row of 20 Nov 2026.
MODBUS_EXAMPLE = {
    "id": 0, "gateway_id": "avc_DHLB500_LuhariSubmeter_000119_1", "latitude": None, "longitude": None,
    "status": False, "health": "modbus_issue", "health_since": "2026-11-19T21:53:00",
    "health_detail": "Gateway avc_DHLB500_LuhariSubmeter_000119_1: pings OK, no consumption / recovery / load data "
                     "for 12.3 h",
    "site_id": 119, "site_name": "DHL B500 Lohari Submetering", "customer_name": "DHL_India",
    "_note": "example from 20 Nov 2026 (no gateway had this state at capture time)",
}


def example(call):
    sample = SAMPLES.get(call.get("sample") or "")
    request = sample["request"] if sample else call.get("request", {})
    response = sample.get("body") if sample else call.get("response")
    if call.get("sample") == "gateway-status-health" and isinstance(response, dict):
        results = [r for r in response.get("results", []) if isinstance(r, dict)]
        if not any(r.get("health") == "modbus_issue" for r in results):
            response = {**response, "results": results + [MODBUS_EXAMPLE]}
    return request, response, bool(sample)


def pretty(value, limit=30000):
    text = json.dumps(value, indent=1, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "\n..."


def main():
    book = Workbook()
    sheet(book, "Start here", [("Topic", 16), ("", 140)], START, first=True)
    api_rows, req_rows, resp_rows, ex_rows = [], [], [], []
    for n, call in enumerate(CALLS, start=1):
        request, response, captured = example(call)
        name = f"{n}. {call['call']}"
        query = call["method"] == "GET"
        api_rows.append([
            n, call["feature"], call["call"], call["method"], call["url"], call["auth"], call["who"],
            ("Query: " if query else "JSON body: ") + json.dumps(request, ensure_ascii=False),
            call["errors"], call["how"], call["screen"], call["available"],
            "captured on test" if captured else "example from the code",
        ])
        req_rows += [[name, field, kind, required, meaning] for field, kind, required, meaning in call["request_fields"]]
        resp_rows += [[name, field, kind, meaning] for field, kind, meaning in call["response_fields"]]
        ex_rows.append([name, f"{call['method']} {call['url']}" + (" (query)" if query else ""), pretty(request),
                        pretty(response)])
    sheet(book, "APIs", [("#", 4), ("Feature", 14), ("Call", 30), ("Method", 8), ("URL", 24), ("Auth header", 22),
                         ("Who", 16), ("Request example", 46), ("Errors", 40), ("How it works", 70),
                         ("Frontend screen / file", 40), ("Available on", 24), ("Example", 16)], api_rows)
    sheet(book, "Request fields", [("Call", 36), ("Field", 26), ("Type", 12), ("Required", 10), ("Meaning", 80)],
          req_rows)
    sheet(book, "Response fields", [("Call", 36), ("Field", 34), ("Type", 14), ("Meaning", 90)], resp_rows)
    ws = sheet(book, "Examples", [("Call", 30), ("Method / URL", 26), ("Request", 50), ("Response", 110)], ex_rows)
    for row in range(2, len(ex_rows) + 2):
        ws.row_dimensions[row].height = 300
    sheet(book, "Values", [("Field", 30), ("Value", 34), ("Show as", 34), ("Colour", 18), ("Meaning", 70)],
          [list(v) for v in VALUES])
    out = HERE / "FRONTEND_API_HANDOFF.xlsx"
    book.save(out)
    print(f"{len(CALLS)} calls, {len(req_rows)} request fields, {len(resp_rows)} response fields -> {out}")


if __name__ == "__main__":
    main()
