"""Build the alarm catalogue for presentation: ALARM_CATALOGUE.xlsx and .csv.

    python3 docs/alarms/build_alarm_catalogue.py

Sheets: Alarm catalogue (one row per alarm type), Frontend APIs (with real
responses captured on the test server, api_samples_test_server.json),
Configuration, E-mail flow, Fields. Edit this file when an alarm changes.
"""

import csv
import json
import pathlib

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = pathlib.Path(__file__).resolve().parent
SAMPLES = json.loads((HERE / "api_samples_test_server.json").read_text())

SITE_APIS = "alarmList/ (site summary), alarmListDetail/ (rows of one type), alarmTypeApi/ + alarmapi/ (super-admin active issues), snapshot/ (count)"
REPEAT_POWER = "First occurrence e-mailed. Repeat: counted on the day's row at most every 30 min; e-mailed again only if > 5 % worse than the last e-mailed value (repeat tolerance). Next day with a similar value: no e-mail; after 24 h without the alarm it is new again."
REPEAT_DAILY = "One alarm per aisle per day, e-mailed when raised. If the same alarm fired the day before, e-mailed only when today's consumption is > 5 % worse than the last e-mailed value."
REPEAT_OUTAGE = "One active alarm per outage, e-mailed once when raised; while it lasts only last_seen moves. Cleared automatically (no e-mail) when it recovers; the next e-mail of the same issue shows 'Previous outage ... restored ... (duration)'."
CONFIG_STD = "AlarmSetting (Django admin, per site + type): Auto / Manual (threshold) / Off, e-mail software team on/off, e-mail ground team on/off, repeat tolerance %."
RECIPIENTS = "wareApp/mqtt/services/alarm_recipients.py: SOFTWARE_TEAM (all sites) + GROUND_TEAM_ALL_SITES + LOCATION_TEAMS (by site location) + GROUND_TEAM (per site). Test server: ALARM_EMAIL_OVERRIDE_TO replaces them."

COLUMNS = [
    ("Type", 6), ("Alarm", 22), ("Category", 13), ("Status", 14), ("Priority", 9),
    ("One alarm per", 22), ("Triggered by (input)", 30), ("How it works (rule)", 55),
    ("Default threshold", 28), ("Configurable?", 12), ("How to configure", 45),
    ("Check timing / frequency", 30), ("Repeat & e-mail rule", 45), ("Auto-clear", 22),
    ("E-mail recipients", 32), ("Code path (file -> function)", 48), (".env settings", 32),
    ("Frontend APIs that show it", 40), ("Notes", 40),
]

ALARMS = [
    [0, "High Voltage", "Power", "Active", "High", "site + power source + day",
     "MQTT load packet  /Acclivate/iOmniControl/<site>/<gateway>/in/load/state (R/Y/B volts)",
     "Every load packet's phase voltages are stored (SiteLoadParameters). When at least 7 readings exist and ALL of the latest 5 have a phase above its maximum, the alarm is raised.",
     "Site fields r/y/b_phase_voltage_threshold_max (only when Site.show_voltage_alarms is on). Auto mode: 253 V (230 V + 10 %).",
     "Yes", CONFIG_STD + " Manual = one voltage for all phases; empty = site phase fields.",
     "Real time, on every load packet", REPEAT_POWER, "No (one row per day)", RECIPIENTS,
     "wareApp/mqtt/load.py -> _voltage_thresholds, _record_voltage_alarm; wareApp/mqtt/services/alarms.py -> raise_power_alarm; sendmail.send_alarm_for_high_voltage",
     "ALARM_VOLTAGE_AUTO_HIGH=253, ALARM_REPEAT_TOLERANCE_PERCENT=5", SITE_APIS,
     "Severity value = highest phase voltage."],
    [1, "Low Voltage", "Power", "Active", "High", "site + power source + day",
     "MQTT load packet  .../in/load/state",
     "Same as High Voltage, with ALL of the latest 5 readings having a phase below its minimum.",
     "Site fields r/y/b_phase_voltage_threshold_min (Site.show_voltage_alarms on). Auto mode: 207 V (230 V - 10 %).",
     "Yes", CONFIG_STD, "Real time, on every load packet", REPEAT_POWER, "No (one row per day)", RECIPIENTS,
     "wareApp/mqtt/load.py -> _voltage_thresholds, _record_voltage_alarm; services/alarms.py -> raise_power_alarm; sendmail.send_alarm_for_low_voltage",
     "ALARM_VOLTAGE_AUTO_LOW=207", SITE_APIS, "Severity value = lowest phase voltage (lower is worse)."],
    [2, "PF Bad Value", "Power", "Active", "Medium", "site + power source + day",
     "MQTT load packet with R/Y/B power factor, status ON",
     "Any phase power factor below its threshold. Low phases are also stored in PowerFactorData.",
     "Site fields r/y/b_phase_pf_threshold (Site.is_pf_visible on). Auto mode: 0.9 on every phase.",
     "Yes", CONFIG_STD + " Manual = one PF for all phases.", "Real time, on every load packet after the first one of a source/meter",
     REPEAT_POWER, "No (one row per day)", RECIPIENTS,
     "wareApp/mqtt/load.py -> _pf_thresholds, _record_power_factor_alarm; services/alarms.py -> raise_power_alarm; sendmail.send_mail_for_pf_fluctuation",
     "ALARM_PF_AUTO_THRESHOLD=0.9", SITE_APIS, "Sites without PF thresholds are skipped (logged once per hour) unless set to Auto."],
    [3, "DG Overtime", "Power", "Defined, not raised", "-", "-", "-", "Type exists; no current code raises it.", "-", "-", "-", "-", "-", "-", "-", "sendmail.send_alarm_for_dg_overtime (no-op)", "-", "-", "Kept for history / future use."],
    [4, "DG Fuel Under Level", "Power", "Defined, not raised", "-", "-", "-", "Type exists; e-mail template exists; not raised by current code.", "-", "-", "-", "-", "-", "-", "-", "sendmail.send_mail_for_dg_fuel_under_level", "-", "-", "Old Oct 2023 rows only."],
    [5, "Mains Higher Consumption", "Power", "Defined, not raised", "-", "-", "-", "Type exists; not raised by current code.", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", ""],
    [6, "Fuel Drain", "DG fuel", "Active", "Medium", "site + day (count of fetches)",
     "fetch-fuel-data service: fuel used by a DG run, fetched from Roadcast / LocoNav",
     "After a DG run's fuel is fetched: fuel used > 1.2 x Site.dg_fuel_tank_capacity -> also stored as DGFuelAlertsData 'suspicious_fuel'.",
     "1.2 x tank capacity (fixed)", "On / Off", CONFIG_STD + " (threshold not used)", "Every 5 min (fuel service cycle)",
     REPEAT_POWER.replace("at most every 30 min", "each fetch"), "No", RECIPIENTS,
     "fetch_fuel_data.py -> run_dg_fuel_cycle; wareApp/dg_fuel/sessions.py -> attempt_fetch_for_unit; fuel_providers.detect_suspicious_fuel",
     "DG_FUEL_POLL_INTERVAL_SECONDS=300", SITE_APIS, "Severity = litres used."],
    [7, "High Consumption", "Consumption", "Active", "Medium", "aisle + day",
     "Daily reading (sum of the aisle's hourly readings)",
     "Day's consumption >= threshold. Not raised when Bypassed fired for that aisle and day (Bypassed covers >= 100 %).",
     "Site.high_consumption_units, else baseline x Site.high_consumption_baseline_percent (default 75 %).",
     "Yes", CONFIG_STD + " Manual = kWh per day; Auto = baseline x percent.",
     "Day end: first reading after midnight; re-checked after recovery rewrites a past day (up to 7 days)",
     REPEAT_DAILY, "No", RECIPIENTS,
     "wareApp/mqtt/services/consumption_alarms.py -> evaluate_daily_alarms, _record",
     "ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT=75, ALARM_REEVALUATE_DAYS=7", SITE_APIS + ", consumptionAlarms/", ""],
    [8, "Low Consumption", "Consumption", "Active (opt-in)", "Medium", "aisle + day",
     "Daily reading", "Day's consumption < baseline x (1 - percent / 100).",
     "Only for sites with Site.min_threshold_value set (opt-in), or AlarmSetting Auto: baseline less 90 %.",
     "Yes", CONFIG_STD + " Manual = minimum kWh per day.", "Day end (as High Consumption)", REPEAT_DAILY.replace("worse", "lower"), "No", RECIPIENTS,
     "consumption_alarms.py -> evaluate_daily_alarms", "ALARM_LOW_CONSUMPTION_DEFAULT_PERCENT=90", SITE_APIS + ", consumptionAlarms/",
     "Off by default: most aisle-days use far below baseline, so a default would flood alarms."],
    [9, "DG Running Without Load", "DG fuel", "Active", "High", "site + day (count of fetches)",
     "fetch-fuel-data service after a DG run", "The DG used fuel but its energy for the day is <= 0 kWh.",
     "Fixed rule", "On / Off", CONFIG_STD + " (threshold not used)", "Every 5 min (fuel service cycle)",
     REPEAT_POWER.replace("at most every 30 min", "each fetch"), "No", RECIPIENTS,
     "dg_fuel/sessions.py -> attempt_fetch_for_unit; services/alarms.py -> raise_power_alarm", "-", SITE_APIS, ""],
    [10, "Meter Reading Issue", "Consumption", "Active", "Medium", "meter + day (count)",
     "MQTT consumption packet with 'ERROR!!! New meter reading ... smaller than previous meter reading'",
     "Gateway reports a lower cumulative meter reading. Stored at most every 30 min per meter; repeats the same day add to the count.",
     "No threshold (event)", "On / Off", CONFIG_STD + " (threshold not used)", "Real time, on the packet",
     "E-mailed for the first occurrence of the day only.", "No", RECIPIENTS,
     "wareApp/mqtt/consumption.py -> _notify_meter_reading_issue", "-", SITE_APIS, "Zero-consumption case 1."],
    [11, "Bypassed", "Consumption", "Active", "Medium", "aisle + day",
     "Live consumption (running total of today) and the daily reading",
     "Consumption >= the aisle's own daily baseline x 100 % (no saving). Raised DURING the day as soon as today's running total crosses it, and checked again at day end. Supersedes High Consumption.",
     "Baseline x ALARM_BYPASS_DEFAULT_PERCENT (100 %); Site.bypass_consumption_units overrides.",
     "Yes", CONFIG_STD + " Manual = kWh per day.", "Every consumption batch (~1 min) for today; day end for complete days",
     REPEAT_DAILY, "No", RECIPIENTS,
     "consumption_alarms.py -> check_intraday_bypass, evaluate_daily_alarms; called from mqtt/consumption_batch.py and mqtt/consumption.py",
     "ALARM_BYPASS_DEFAULT_PERCENT=100", SITE_APIS, "Intra-day raise added 2026-10-28 (manual bypass visible the same day)."],
    [12, "Operation Hours Increased", "Consumption", "Active", "Medium", "aisle + day",
     "Hourly readings of NL aisles (sites with NL hours and start/end time)",
     "An hour counts as active at >= 0.01 kWh. Raised when an active hour is outside the NL window or there are more active hours than Site.nl_operation_hours. Named as cause on a High Consumption alarm the same day.",
     "Site.nl_operation_hours / nl_operation_start_time / nl_operation_end_time", "On / Off", CONFIG_STD + " (threshold not used)", "Day end",
     REPEAT_DAILY.replace("consumption", "active hours"), "No", RECIPIENTS,
     "consumption_alarms.py -> operation_hours_check, evaluate_daily_alarms", "ALARM_ACTIVITY_THRESHOLD_KWH=0.01", SITE_APIS, ""],
    [13, "Gateway Overheat", "Gateway", "Active", "Medium", "gateway + day (count)",
     "HTTP POST from the gateway: /api/temp/dispatch/mail/ (CPU temperature, fan)",
     "The gateway posts while its CPU is >= 85 °C. Stored at most every 60 s per gateway.",
     "85 °C", "Yes", CONFIG_STD + " Manual = °C (alerts below it are ignored).",
     "Real time, on the gateway's POST", "E-mail at most once per hour per gateway and only if > 5 % hotter than the last e-mail.", "No", RECIPIENTS,
     "wareApp/gateway_overheat.py -> parse_alert, record_overheat; views/gateway_overheat.py",
     "GATEWAY_OVERHEAT_STORE_SECONDS=60, GATEWAY_OVERHEAT_EMAIL_SECONDS=3600", SITE_APIS, ""],
    [14, "Meter Disconnected", "Data missing", "Active (new)", "Medium", "meter outage",
     "Gateway's own meter event posted to /api/meter-disconnections/ingest/ (MeterDisconnectionEvent: disconnected / connected)",
     "The meter's latest event is 'disconnected' since >= 1 h -> alarm. Its 'connected' event clears it.",
     "1 hour", "Yes", CONFIG_STD + " Manual = hours.", "Every 5 min (Celery beat check_gateway_health)",
     REPEAT_OUTAGE, "Yes, on 'connected' event", RECIPIENTS,
     "wareApp/mqtt/services/gateway_health.py -> evaluate_meters; views/monitoring.py -> MeterDisconnectionIngestView",
     "GATEWAY_HEALTH_DOWN_MINUTES=60, GATEWAY_HEALTH_CHECK_SECONDS=300", SITE_APIS + ", meter-disconnections/",
     "Zero-consumption case 3. Live sites only."],
    [15, "Gateway Disconnected", "Data missing", "Active (new)", "High", "gateway outage",
     "Last data packet per gateway (our MQTT listeners -> HomeGatewayStatus.last_data_at) and last ping (Mosquitto log -> last_ping_at)",
     "No data AND no ping for >= 1 h. Without fresh ping information (broker log not read in the last 15 min) a gateway silent >= 1 h counts as disconnected.",
     "1 hour", "Yes", CONFIG_STD + " Manual = hours.", "Every 5 min (Celery beat check_gateway_health)",
     REPEAT_OUTAGE, "Yes, when data returns", RECIPIENTS,
     "services/gateway_activity.py -> seen, flush; services/gateway_health.py -> evaluate_gateways; manage.py gateway_health --broker-log (root cron)",
     "GATEWAY_HEALTH_DOWN_MINUTES=60, GATEWAY_HEALTH_PING_FRESH_MINUTES=15", SITE_APIS + ", gateway-status/",
     "Zero-consumption case 5. A gateway must have been seen once before it can raise."],
    [16, "Gateway Service / Modbus Issue", "Data missing", "Active (new)", "High", "gateway outage",
     "Same inputs as 15", "Pings arrive (gateway online) but no consumption / recovery / load data for >= 1 h: service stopped or meters not read over Modbus.",
     "1 hour", "Yes", CONFIG_STD + " Manual = hours.", "Every 5 min (Celery beat)", REPEAT_OUTAGE, "Yes, when data returns", RECIPIENTS,
     "services/gateway_health.py -> evaluate_gateways", "Needs the broker log read (root cron) to tell it from 15", SITE_APIS + ", gateway-status/",
     "Zero-consumption case 6. On test (bridge, no gateway pings) only 15 can be raised."],
    ["-", "Fire pump mode / motor on", "Fire", "Active (e-mail only)", "-", "device event",
     "MQTT .../out/FIREALARM/localstate", "Pump mode changes and motor-on events e-mail the customer; no alarm row in AlarmNotifications.",
     "-", "No", "-", "Real time; motor-on at most every 10 min", "Customer e-mail per event", "-", "Customer addresses in sendmail", "wareApp/mqtt/fire_alarm.py; sendmail.send_mail_fire_alarm_user", "-", "fireAlarm/", ""],
]


def sample(name):
    return json.dumps(SAMPLES.get(name, {}).get("body", {}), indent=1, default=str)


APIS = [
    ("Endpoint", 26), ("Method", 8), ("Auth", 20), ("Used for", 34), ("Request", 36), ("Response fields", 50), ("Example response (test server, trimmed)", 80),
]
API_ROWS = [
    ["/api/alarmList/", "POST", "Token", "Site alarm page: totals and one line per alarm type",
     '{"siteId": 134}', "status, total_alarm (sum of occurrences), high_priority, medium_priority, active_alarms, data[]: name, count, priority, alarm_type", sample("alarmList")],
    ["/api/alarmListDetail/", "POST", "Token", "Site alarm page: rows of one type, newest first",
     '{"siteId": 134, "alarm_type": 11}', "data[]: get_alarm_type_display, get_alarm_priority_display, power_source, r_phase, y_phase, b_phase, fuel_level, run_hours, created, is_active, aisle_group, issue, occurrences, last_seen", sample("alarmListDetail")],
    ["/api/alarmTypeApi/", "POST", "Token, Super_Admin only", "Super-admin alarm list: active issues of every live site (last 30 days), grouped by customer",
     "{}", "data[]: customer_id, customer_name, alarm_list[] (see 'Fields' sheet: alarm, priority, site, source, aisle / leg / power source / gateway, issue, created_time = first seen, last_seen, occurrences, alarm_type)", sample("alarmTypeApi")],
    ["/api/alarmapi/", "POST", "Token", "Super-admin: active issue counts per customer, priority and site",
     "{}", "data[][]: Alarm_priority, site_id__site_name, alarm_count (one list per customer)", sample("alarmapi")],
    ["/api/snapshot/", "POST", "Token", "Super-admin snapshot tiles",
     '{"user_id": 1, "start_date": "YYYY/MM/DD", "end_date": "YYYY/MM/DD"} (dates optional: current month)', "alarms (same count as the alarm list), total_unit_consumed, total_energy_saved, total_saved_percentage, current_date", sample("snapshot")],
    ["/api/consumptionAlarms/", "POST", "Token", "Active High / Low Consumption alarms of a site",
     '{"site_id": 134, "start_date": "YYYY/MM/DD", "end_date": "YYYY/MM/DD"} (dates optional)', "data[]: id, alarm_type, priority, aisle_group, created_time", sample("consumptionAlarms")],
    ["/api/gateway-status/", "GET", "None (AllowAny)", "Gateway online map / list (status = data in the last hour)",
     "?limit=100&offset=0", "count, limit, offset, results[]: id, gateway_id, latitude, longitude, status, site_id, site_name, customer_name", sample("gateway-status")],
    ["/api/meter-disconnections/", "GET", "Token", "Meter disconnect / reconnect events (input of alarm 14)",
     "?site_id=102&meter_number=&meter_id=&status=disconnected&from=&to=", "count, limit, offset, results[]: id, logged_site_id, meter_id, meter_number, meter_name, status, port_id, detection_window_start/end, last_seen_at, ...", sample("meter-disconnections")],
    ["/api/meter-disconnections/ingest/", "POST", "None (gateway)", "Gateways report meter disconnects (device side, not frontend)",
     '[{"meter_id": 790, "meter_number": 79, "meter_name": "meter790", "status": "disconnected", "port_id": "/dev/ttyUSB1", "site": 102, "logged_site_id": 102, "detection_window_start": "...", "detection_window_end": "...", "last_seen_at": "..."}]',
     "status, saved count", "-"],
    ["/api/temp/dispatch/mail/", "POST", "None (gateway)", "Gateway overheat alert (device side, input of alarm 13)",
     '{"Site Id": 183, "Site Name": "...", "Site Type": "...", "Gateway No": "2", "Gateway Info": {"Temperature": 87.3, "CPU Status": {"cpu0": "1.2 GHz"}, "Fan PWM": 255}}',
     'status: "stored" | "repeated" | "throttled" | "off" | "below threshold"; 400 {"status": "rejected", "error": ...}', '{"status": "stored"}'],
]

CONFIG = [
    ("Where", 34), ("Setting", 34), ("Default", 16), ("What it does", 70),
]
CONFIG_ROWS = [
    ["Django admin -> Alarm settings", "mode", "Auto", "Per site + alarm type: Auto (system threshold) / Manual (typed threshold) / Off (not raised). No row = the alarm works from the site fields as before."],
    ["Django admin -> Alarm settings", "threshold", "-", "Manual mode: V (voltage), PF, kWh/day (High, Low, Bypassed), °C (overheat), hours (14 / 15 / 16)."],
    ["Django admin -> Alarm settings", "email_software / email_ground", "on / on", "Switch the software team or the ground team off for this site and type."],
    ["Django admin -> Alarm settings", "repeat_tolerance_percent", "5", "A repeat is e-mailed again only when this much worse than the last e-mail."],
    ["wareApp/mqtt/services/alarm_recipients.py", "SOFTWARE_TEAM", "ashutosh.dubey@aviconncorp.com", "Receives every site's alarms."],
    ["wareApp/mqtt/services/alarm_recipients.py", "GROUND_TEAM_ALL_SITES", "rakesh.kumar@aviconncorp.com", "Ground-team members for every site."],
    ["wareApp/mqtt/services/alarm_recipients.py", "LOCATION_TEAMS", "7 locations, e-mails empty", "Ground team per location (Gurgaon, Delhi, Mumbai / Bhiwandi, Pune, Bangalore, Kolkata, Lucknow); site matched by keywords in its location / name. Check: python manage.py alarm_recipients"],
    ["wareApp/mqtt/services/alarm_recipients.py", "GROUND_TEAM", "{}", "Extra ground-team members for one site id."],
    ["Site fields (admin -> Sites)", "show_voltage_alarms, r/y/b_phase_voltage_threshold_max/min", "-", "Voltage alarms when no AlarmSetting row exists."],
    ["Site fields", "is_pf_visible, r/y/b_phase_pf_threshold", "-", "PF alarm when no AlarmSetting row exists."],
    ["Site fields", "high_consumption_units, high_consumption_baseline_percent, bypass_consumption_units, min_threshold_value", "-", "Consumption alarm overrides when no AlarmSetting row exists."],
    ["Site fields", "nl_operation_hours, nl_operation_start_time, nl_operation_end_time", "-", "Operation Hours Increased window."],
    ["Site fields", "dg_fuel_tank_capacity", "-", "Fuel Drain threshold (1.2 x)."],
    ["warehouse/.env", "ALARM_EMAIL_OVERRIDE_TO", "test: you + Rakesh", "Test servers: every alarm e-mail goes only to these addresses (intended recipients shown in the e-mail)."],
    ["warehouse/.env", "ALARM_REPEAT_TOLERANCE_PERCENT / ALARM_REPEAT_CLEAR_HOURS", "5 / 24", "Repeat e-mail rule."],
    ["warehouse/.env", "ALARM_BYPASS_DEFAULT_PERCENT / ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT / ALARM_LOW_CONSUMPTION_DEFAULT_PERCENT", "100 / 75 / 90", "Consumption Auto thresholds."],
    ["warehouse/.env", "ALARM_VOLTAGE_AUTO_HIGH / _LOW / ALARM_PF_AUTO_THRESHOLD", "253 / 207 / 0.9", "Power Auto thresholds."],
    ["warehouse/.env", "GATEWAY_HEALTH_DOWN_MINUTES / _CHECK_SECONDS / _PING_FRESH_MINUTES", "60 / 300 / 15", "Alarms 14 / 15 / 16."],
    ["warehouse/.env", "ALARM_FEED_MAX_AGE_DAYS", "30", "The super-admin list shows issues seen in the last 30 days."],
]

FLOW = [("Step", 6), ("What happens", 110)]
FLOW_ROWS = [
    [1, "A handler / checker decides an alarm is due (rules in the catalogue) and stores or updates its AlarmNotifications row."],
    [2, "Repeat rule (wareApp/mqtt/services/alarm_policy.py -> should_email): first occurrence or > 5 % worse -> e-mail; otherwise only counted."],
    [3, "Recipients (alarm_policy.recipients): software team + all-sites ground team + the site's location team + per-site ground team, minus groups switched off in AlarmSetting."],
    [4, "notify() queues the e-mail on the 'notifications' RabbitMQ queue after the database commit; if the queue is down it is sent directly."],
    [5, "mqtt-notifications worker -> sendmail -> SMTP (EMAIL_* in .env). On test servers ALARM_EMAIL_OVERRIDE_TO replaces the recipients (banner shows the intended ones)."],
    [6, "Logs: 'Alarm email redirected' (test), 'Email sent: subject=... to=...' or 'Email failed: ...' in the Celery log."],
]

FIELDS = [("Field", 22), ("Meaning", 90)]
FIELD_ROWS = [
    ["alarm", "Alarm name (e.g. 'Bypassed')."],
    ["alarm_type", "Type number 0-16 (catalogue sheet)."],
    ["Alarm_priority / priority", "0 High, 1 Medium, 2 Low / label."],
    ["source", "power | consumption | gateway."],
    ["site_id, site_id__site_name", "Site."],
    ["customer_id, customer_name", "Customer of the site."],
    ["aisle_group_id, aisle_group_name, leg_id", "Aisle (consumption alarms)."],
    ["power_source", "Mains Supply / DG_n (power alarms)."],
    ["home_gateway_id", "Gateway of the aisle / the alarm (gateway alarms: matched by the gateway number)."],
    ["issue", "Reason with values, e.g. 'Bypassed: consumption=220.00, threshold=200.00 (100 % of baseline)'."],
    ["created_time", "First time the issue was seen."],
    ["last_seen", "Last time it was seen (repeats)."],
    ["occurrences", "How many times it happened (one row per issue per day)."],
    ["is_active", "False when an outage alarm (14 / 15 / 16) has cleared."],
    ["r_phase, y_phase, b_phase, fuel_level, run_hours", "Measured values of power / DG alarms."],
]


def sheet(book, title, columns, rows, first=False):
    ws = book.active if first else book.create_sheet()
    ws.title = title
    header_fill = PatternFill("solid", fgColor="1F4E78")
    thin = Side(style="thin", color="BFBFBF")
    for index, (name, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=index, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(index)].width = width
    status_fill = {
        "Active (new)": "E2EFDA", "Defined, not raised": "EDEDED", "Active (opt-in)": "FFF2CC",
    }
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        if title == "Alarm catalogue" and row[3] in status_fill:
            for c in range(1, len(columns) + 1):
                ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=status_fill[row[3]])
    ws.freeze_panes = "C2" if title == "Alarm catalogue" else "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
    return ws


def main():
    book = Workbook()
    sheet(book, "Alarm catalogue", COLUMNS, ALARMS, first=True)
    sheet(book, "Frontend APIs", APIS, API_ROWS)
    sheet(book, "Configuration", CONFIG, CONFIG_ROWS)
    sheet(book, "E-mail flow", FLOW, FLOW_ROWS)
    sheet(book, "Fields", FIELDS, FIELD_ROWS)
    book.save(HERE / "ALARM_CATALOGUE.xlsx")
    with open(HERE / "ALARM_CATALOGUE.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in COLUMNS])
        writer.writerows(ALARMS)
    print(f"{len(ALARMS)} alarms, {len(API_ROWS)} APIs -> {HERE / 'ALARM_CATALOGUE.xlsx'}, ALARM_CATALOGUE.csv")


if __name__ == "__main__":
    main()
