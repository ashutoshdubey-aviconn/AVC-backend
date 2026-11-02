"""Build the alarm catalogue for presentation: ALARM_CATALOGUE.xlsx and .csv.

    python3 docs/alarms/build_alarm_catalogue.py

Sheets: Summary, Alarm catalogue (one row per alarm type, with its models), Models, Frontend APIs (with real
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
     "Real time, on every load packet", REPEAT_POWER, "Yes: 60 min after it was last seen", RECIPIENTS,
     "wareApp/mqtt/load.py -> _voltage_thresholds, _record_voltage_alarm; wareApp/mqtt/services/alarms.py -> raise_power_alarm; sendmail.send_alarm_for_high_voltage",
     "ALARM_VOLTAGE_AUTO_HIGH=253, ALARM_REPEAT_TOLERANCE_PERCENT=5", SITE_APIS,
     "Severity value = highest phase voltage."],
    [1, "Low Voltage", "Power", "Active", "High", "site + power source + day",
     "MQTT load packet  .../in/load/state",
     "Same as High Voltage, with ALL of the latest 5 readings having a phase below its minimum.",
     "Site fields r/y/b_phase_voltage_threshold_min (Site.show_voltage_alarms on). Auto mode: 207 V (230 V - 10 %).",
     "Yes", CONFIG_STD, "Real time, on every load packet", REPEAT_POWER, "Yes: 60 min after it was last seen", RECIPIENTS,
     "wareApp/mqtt/load.py -> _voltage_thresholds, _record_voltage_alarm; services/alarms.py -> raise_power_alarm; sendmail.send_alarm_for_low_voltage",
     "ALARM_VOLTAGE_AUTO_LOW=207", SITE_APIS, "Severity value = lowest phase voltage (lower is worse)."],
    [2, "PF Bad Value", "Power", "Active", "Medium", "site + power source + day",
     "MQTT load packet with R/Y/B power factor, status ON",
     "Any phase power factor below its threshold. Low phases are also stored in PowerFactorData.",
     "Site fields r/y/b_phase_pf_threshold (Site.is_pf_visible on). Auto mode: 0.9 on every phase.",
     "Yes", CONFIG_STD + " Manual = one PF for all phases.", "Real time, on every load packet after the first one of a source/meter",
     REPEAT_POWER, "Yes: 60 min after it was last seen", RECIPIENTS,
     "wareApp/mqtt/load.py -> _pf_thresholds, _record_power_factor_alarm; services/alarms.py -> raise_power_alarm; sendmail.send_mail_for_pf_fluctuation",
     "ALARM_PF_AUTO_THRESHOLD=0.9", SITE_APIS, "Sites without PF thresholds are skipped (logged once per hour) unless set to Auto."],
    [3, "DG Overtime", "Power", "Defined, not raised", "-", "-", "-", "Type exists; no current code raises it.", "-", "-", "-", "-", "-", "-", "-", "sendmail.send_alarm_for_dg_overtime (no-op)", "-", "-", "Kept for history / future use."],
    [4, "DG Fuel Under Level", "Power", "Defined, not raised", "-", "-", "-", "Type exists; e-mail template exists; not raised by current code.", "-", "-", "-", "-", "-", "-", "-", "sendmail.send_mail_for_dg_fuel_under_level", "-", "-", "Old Oct 2023 rows only."],
    [5, "Mains Higher Consumption", "Power", "Defined, not raised", "-", "-", "-", "Type exists; not raised by current code.", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", ""],
    [6, "Fuel Drain", "DG fuel", "Active", "Medium", "site + day (count of fetches)",
     "fetch-fuel-data service: fuel used by a DG run, fetched from Roadcast / LocoNav",
     "After a DG run's fuel is fetched: fuel used > 1.2 x Site.dg_fuel_tank_capacity -> also stored as DGFuelAlertsData 'suspicious_fuel'.",
     "1.2 x tank capacity (fixed)", "On / Off", CONFIG_STD + " (threshold not used)", "Every 5 min (fuel service cycle)",
     REPEAT_POWER.replace("at most every 30 min", "each fetch"), "Yes: end of the day after its day", RECIPIENTS,
     "fetch_fuel_data.py -> run_dg_fuel_cycle; wareApp/dg_fuel/sessions.py -> attempt_fetch_for_unit; fuel_providers.detect_suspicious_fuel",
     "DG_FUEL_POLL_INTERVAL_SECONDS=300", SITE_APIS, "Severity = litres used."],
    [7, "High Consumption", "Consumption", "Active", "High", "aisle + day",
     "Daily reading (sum of the aisle's hourly readings)",
     "Day's consumption >= threshold. Not raised when Bypassed fired for that aisle and day (Bypassed covers >= 100 %). Spike hours (meter jump / catch-up, see type 17) are not counted, and it is not raised on a day the aisle has a Meter Reading Issue.",
     "Site.high_consumption_units, else baseline x Site.high_consumption_baseline_percent (default 75 %).",
     "Yes", CONFIG_STD + " Manual = kWh per day; Auto = baseline x percent.",
     "Day end: first reading after midnight; re-checked after recovery rewrites a past day (up to 7 days)",
     REPEAT_DAILY, "Yes: end of the day after its day", RECIPIENTS,
     "wareApp/mqtt/services/consumption_alarms.py -> evaluate_daily_alarms, _record",
     "ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT=75, ALARM_REEVALUATE_DAYS=7", SITE_APIS + ", consumptionAlarms/", ""],
    [8, "Low Consumption", "Consumption", "Active (opt-in)", "Medium", "aisle + day",
     "Daily reading", "Day's consumption < baseline x (1 - percent / 100).",
     "Only for sites with Site.min_threshold_value set (opt-in), or AlarmSetting Auto: baseline less 90 %.",
     "Yes", CONFIG_STD + " Manual = minimum kWh per day.", "Day end (as High Consumption)", REPEAT_DAILY.replace("worse", "lower"), "Yes: end of the day after its day", RECIPIENTS,
     "consumption_alarms.py -> evaluate_daily_alarms", "ALARM_LOW_CONSUMPTION_DEFAULT_PERCENT=90", SITE_APIS + ", consumptionAlarms/",
     "Off by default: most aisle-days use far below baseline, so a default would flood alarms."],
    [9, "DG Running Without Load", "DG fuel", "Active", "High", "site + day (count of fetches)",
     "fetch-fuel-data service after a DG run", "The DG used fuel but its energy for the day is <= 0 kWh.",
     "Fixed rule", "On / Off", CONFIG_STD + " (threshold not used)", "Every 5 min (fuel service cycle)",
     REPEAT_POWER.replace("at most every 30 min", "each fetch"), "Yes: end of the day after its day", RECIPIENTS,
     "dg_fuel/sessions.py -> attempt_fetch_for_unit; services/alarms.py -> raise_power_alarm", "-", SITE_APIS, ""],
    [10, "Meter Reading Issue", "Consumption", "Active", "High", "meter + day (count)",
     "MQTT consumption packet with 'ERROR!!! New meter reading ... smaller than previous meter reading'",
     "Gateway reports a lower cumulative meter reading. Stored at most every 30 min per meter; repeats the same day add to the count.",
     "No threshold (event)", "On / Off", CONFIG_STD + " (threshold not used)", "Real time, on the packet",
     "E-mailed for the first occurrence of the day only.", "Yes: 24 h without a repeat", RECIPIENTS,
     "wareApp/mqtt/consumption.py -> _notify_meter_reading_issue", "-", SITE_APIS, "Zero-consumption case 1."],
    [11, "Bypassed", "Consumption", "Active", "High", "aisle + day",
     "Live consumption (running total of today) and the daily reading",
     "Consumption >= the aisle's own daily baseline x 100 % (no saving). Raised DURING the day as soon as today's running total crosses it, and checked again at day end. Supersedes High Consumption. Spike hours (meter jump / catch-up, see type 17) are not counted, and it is not raised on a day the aisle has a Meter Reading Issue.",
     "Baseline x ALARM_BYPASS_DEFAULT_PERCENT (100 %); Site.bypass_consumption_units overrides.",
     "Yes", CONFIG_STD + " Manual = kWh per day.", "Every consumption batch (~1 min) for today; day end for complete days",
     REPEAT_DAILY, "Yes: end of the day after its day", RECIPIENTS,
     "consumption_alarms.py -> check_intraday_bypass, evaluate_daily_alarms; called from mqtt/consumption_batch.py and mqtt/consumption.py",
     "ALARM_BYPASS_DEFAULT_PERCENT=100", SITE_APIS, "Intra-day raise added 2026-10-28 (manual bypass visible the same day)."],
    [12, "Operation Hours Increased", "Consumption", "Active", "High", "aisle + day",
     "Hourly readings of NL aisles (sites with NL hours and start/end time)",
     "An hour counts as active at >= 0.01 kWh. Raised when an active hour is outside the NL window or there are more active hours than Site.nl_operation_hours. Named as cause on a High Consumption alarm the same day.",
     "Site.nl_operation_hours / nl_operation_start_time / nl_operation_end_time", "On / Off", CONFIG_STD + " (threshold not used)", "Day end",
     REPEAT_DAILY.replace("consumption", "active hours"), "Yes: end of the day after its day", RECIPIENTS,
     "consumption_alarms.py -> operation_hours_check, evaluate_daily_alarms", "ALARM_ACTIVITY_THRESHOLD_KWH=0.01", SITE_APIS, ""],
    [13, "Gateway Overheat", "Gateway", "Active", "Medium", "gateway + day (count)",
     "HTTP POST from the gateway: /api/temp/dispatch/mail/ (CPU temperature, fan)",
     "The gateway posts while its CPU is >= 85 °C. Stored at most every 60 s per gateway.",
     "85 °C", "Yes", CONFIG_STD + " Manual = °C (alerts below it are ignored).",
     "Real time, on the gateway's POST", "E-mail at most once per hour per gateway and only if > 5 % hotter than the last e-mail.", "Yes: 2 h without an overheat post", RECIPIENTS,
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
     "No data AND no ping for >= 1 h. Without fresh ping information (broker log not read in the last 15 min) a gateway silent >= 1 h counts as disconnected. Not checked while no gateway at all sends data (our side down); silence counts from our own listener restart at the earliest (1 h grace), and a restart never clears an open alarm.",
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
    [17, "Consumption Spike", "Consumption", "Active (new)", "High", "aisle + day",
     "Hourly readings (today and yesterday), Meter Reading Issue alarms, gateway alarms, our listener restarts",
     "An hour that is not real use: (a) meter jump - one hour above the aisle's whole daily baseline; (b) catch-up - first hour after a data gap, > 3 x the day's median hour and > 2 x the normal hour. The alarm names the CAUSE: 'meter reset or replaced' (gateway reported a lower reading the same day), 'meter jump', or 'catch-up: carries N missing hours, gap cause: Gateway Disconnected / our server was down / no readings stored'.",
     "Daily baseline (jump); 3 x median and 2 x baseline/24 (catch-up)", "On / Off", CONFIG_STD + " (threshold not used)",
     "Every 5 min (Celery beat check_consumption_spikes) over today and yesterday",
     "One alarm per aisle per day; ONE e-mail per site per scan listing all new spike aisles with their cause; later spikes the same day update the alarm text.",
     "Yes: end of the day after its day", RECIPIENTS,
     "wareApp/mqtt/services/spike_alarms.py -> scan, cause; consumption_alarms.py -> find_spikes",
     "CONSUMPTION_SPIKE_CHECK_SECONDS=300", SITE_APIS, "Spike hours are excluded from Bypassed / High. Added 2026-10-30."],
    ["-", "Fire pump mode / motor on", "Fire", "Active (e-mail only)", "-", "device event",
     "MQTT .../out/FIREALARM/localstate", "Pump mode changes and motor-on events e-mail the customer; no alarm row in AlarmNotifications.",
     "-", "No", "-", "Real time; motor-on at most every 10 min", "Customer e-mail per event", "-", "Customer addresses in sendmail", "wareApp/mqtt/fire_alarm.py; sendmail.send_mail_fire_alarm_user", "-", "fireAlarm/", ""],
]


# Progress per alarm type (checked 2026-10-28 on the test server; main runs older code).
# type -> (progress, unit tests, verified on test server, main server, logs: where + what to search)
L1 = "celerylogs1/celery_logs_of_server.log"
L2 = "celerylogs2/celery_logs_of_server.log"
MAIN_OLD = "Not deployed: main runs the older code (old table / rules); rollout not permitted yet"
STATUS = {
    0: ("Done - waiting for a live case", "test_load_handler, test_alarm_policy (Auto / Manual / Off, repeat rule)",
        "No live High Voltage on test yet (no site above its maximum since the rules went live)", MAIN_OLD,
        f"{L1}: 'Power alarm stored' / 'Power alarm repeated' / 'repeat not e-mailed' + type=0"),
    1: ("Done - waiting for a live case", "test_load_handler (5 low readings), test_alarm_policy",
        "No live Low Voltage on test yet", MAIN_OLD, f"{L1}: 'Power alarm stored' type=1"),
    2: ("Done - working live", "test_load_handler, test_mqtt_services, test_alarm_policy",
        "Live: 78 alarms since 20 Oct (latest 28 Oct 11:43). Repeat rule seen live: site 118 better PF counted, not e-mailed", MAIN_OLD,
        f"{L1}: 'Power alarm stored|repeated' type=2, 'repeat not e-mailed (value ... within tolerance)'"),
    3: ("Not implemented", "-", "-", "-", "-"),
    4: ("Not implemented (old rows only)", "-", "-", "-", "-"),
    5: ("Not implemented", "-", "-", "-", "-"),
    6: ("Done - waiting for a live case", "test_dg_session_integration, test_dg_fuel_cases",
        "No Fuel Drain on test yet (no DG run above 1.2 x tank)", MAIN_OLD,
        "journalctl -u fetch-fuel-data and logges/dg_fuel.log: 'DG fuel cycle summary', 'Power alarm stored' type=6"),
    7: ("Done - working live", "test_consumption_alarms, test_alarm_policy, test_replay_consumption_alarms",
        "Live: 78 alarms since 20 Oct", MAIN_OLD, f"{L1}: 'Consumption alarm stored ... alarm=High Consumption Alarm emailed=True|False'"),
    8: ("Done - opt-in, not enabled for any site", "test_consumption_alarms, test_alarm_policy (Auto low)",
        "None (no site has it switched on)", MAIN_OLD, f"{L1}: 'Consumption alarm stored ... Low Consumption'"),
    9: ("Done - working live", "test_dg_session_integration, test_dg_fuel_cases",
        "Live: 56 alarms (latest 15 Sep 2026)", MAIN_OLD, "journalctl -u fetch-fuel-data, logges/dg_fuel.log: 'Power alarm stored' type=9"),
    10: ("Done - working live", "test_consumption_handler (stored once, throttled, repeats counted)",
         "Live: 53 alarms since 20 Oct (latest 28 Oct 14:30)", MAIN_OLD,
         f"{L1}: 'Meter reading issue stored' / 'Meter reading issue repeated'"),
    11: ("Done - working live (incl. during the day)", "test_consumption_alarms (IntradayBypassTests), test_alarm_policy",
         "Live: 68 alarms since 20 Oct; intra-day raised 28 Oct 21:49 for sites 133 (3 aisles) and 135, e-mailed", MAIN_OLD,
         f"{L1}: 'Consumption alarm stored ... Bypassed', to_do 'Bypassed (during the day, HH:MM)'"),
    12: ("Done - waiting for a live case", "test_consumption_alarms (operation hours)",
         "None on test yet (needs an NL aisle active outside its window)", MAIN_OLD, f"{L1}: 'Operation Hours Increased'"),
    13: ("Done - working live", "test_gateway_overheat, test_alarm_policy (manual °C, Off)",
         "Live: 7 alarms since 20 Oct (latest 28 Oct 11:42)", MAIN_OLD,
         "journalctl -u gunicorn: 'Gateway overheat stored|repeated ... emailed='"),
    14: ("Done - waiting for a live case", "test_gateway_health (MeterDisconnectedTests)",
         "Simulated 28 Oct 17:00: raised, e-mailed, auto-cleared 17:05, restored line on next e-mail. Test gets no real meter events (gateways post them to main only)",
         "Not deployed", f"{L2}: 'Gateway health alarm raised|cleared ... type=14'; task line 'gateway health: raised=.. cleared=..'"),
    15: ("Done - working live", "test_gateway_health (GatewayAlarmTests, CommandTests)",
         "Live: site 94 gw 3 raised 28 Oct 19:05, auto-cleared 19:25; site 127 gw 1 raised 22:55 (active). Simulated full cycle 17:00-17:10",
         "Not deployed", f"{L2}: 'Gateway health alarm raised|cleared ... type=15'"),
    16: ("Done - needs the broker-log cron", "test_gateway_health (pings but no data -> 16)",
         "Dry run with main's broker log (28 Oct): 1 gateway would be 16 (avc_myn_bilaspursvng_000071_1). Not live: test gets data through a bridge, no gateway pings",
         "Not deployed (needs root cron: manage.py gateway_health --broker-log)", f"{L2}: 'Gateway health alarm raised ... type=16'"),
    17: ("Done - working live", "test_spike_alarms (meter reset, jump, catch-up causes, one e-mail per site, Off)",
         "Live 30 Oct: site 138 meter reset (3,290 + 3,162 kWh, ERROR!!! same day); site 114 catch-up at 10:00 on 20 aisles after a gateway gap. 2 tiny false ones before the minimum-size rule, closed",
         "Not deployed", f"{L2}: 'spike scan: raised=.. updated=..'"),
    "-": ("Existing (unchanged)", "test_fire_alarm_handler", "Live (fire pump e-mails)", "Live (old code)", f"{L1}: FIREALARM handler lines"),
}

# type -> models (tables) the alarm reads / writes; every alarm writes AlarmNotifications.
ALARM_ROW = "AlarmNotifications (the alarm)"
SETTING = "AlarmSetting (Auto / Manual / Off)"
MODELS_BY_TYPE = {
    0: f"{ALARM_ROW}; {SETTING}; SiteLoadParameters (voltage readings); Site (thresholds, show_voltage_alarms)",
    1: f"{ALARM_ROW}; {SETTING}; SiteLoadParameters; Site",
    2: f"{ALARM_ROW}; {SETTING}; PowerFactorData (low phases); SiteLoadPower (live load row); Site (PF thresholds, is_pf_visible)",
    3: "AlarmNotifications (type defined only)", 4: "AlarmNotifications (old rows)", 5: "AlarmNotifications (type defined only)",
    6: f"{ALARM_ROW}; {SETTING}; DgUnitConsumption (DG run + fuel); DGFuelAlertsData ('suspicious_fuel'); Site (dg_fuel_tank_capacity)",
    7: f"{ALARM_ROW}; {SETTING}; DailySiteReading; HourlySiteReading; SiteBaseline; AisleGroup; Site",
    8: f"{ALARM_ROW}; {SETTING}; DailySiteReading; SiteBaseline; AisleGroup; Site (min_threshold_value)",
    9: f"{ALARM_ROW}; {SETTING}; DgUnitConsumption; DailySiteReading (DG energy)",
    10: f"{ALARM_ROW}; {SETTING}; AisleGroup (meter / leg)",
    11: f"{ALARM_ROW}; {SETTING}; DailySiteReading (running total); HourlySiteReading; SiteBaseline; AisleGroup; Site (bypass_consumption_units)",
    12: f"{ALARM_ROW}; {SETTING}; HourlySiteReading (active hours); AisleGroup; Site (NL hours / window)",
    13: f"{ALARM_ROW}; {SETTING}; Site; HomeGatewayId (gateway number)",
    14: f"{ALARM_ROW}; {SETTING}; MeterDisconnectionEvent (gateway's meter events); Site (is_live)",
    15: f"{ALARM_ROW}; {SETTING}; HomeGatewayStatus (last_data_at, last_ping_at, status); HomeGatewayId; SiteConsumptionPing; Site (is_live)",
    16: f"{ALARM_ROW}; {SETTING}; HomeGatewayStatus; HomeGatewayId; Site",
    17: f"{ALARM_ROW}; {SETTING}; HourlySiteReading (hours); SiteBaseline; AisleGroup; MonitoringMarker (our restarts); AlarmNotifications 10 / 15 / 16 (cause)",
    "-": "FirePumpAlarm (pump state); Email_History (sent e-mails); no AlarmNotifications row",
}

MODELS = [("Model", 24), ("Table", 30), ("Purpose", 48), ("Fields used by alarms", 60), ("Written by", 40), ("Used by alarms", 18)]
MODEL_ROWS = [
    ["AlarmNotifications", "wareApp_alarmnotifications", "Every alarm of every type: one row per issue per day (outages 14-16: one per outage)",
     "Alarm_type, Alarm_priority, site_id, aisle_group, object_type / object_id (meter, gateway), power_source, to_do (issue), created_time, last_seen, occurrences, is_active, off_time, notified_value, last_notified_at, r/y/b_phase, fuel_level",
     "All alarm handlers and checkers", "0-16"],
    ["AlarmSetting", "wareApp_alarmsetting", "Per site + alarm type configuration (Django admin)",
     "site, alarm_type, mode (Auto / Manual / Off), threshold, email_software, email_ground, repeat_tolerance_percent", "Admin users", "all"],
    ["Site", "wareApp_site", "Site and its alarm fields",
     "is_live, location (location team), show_voltage_alarms, r/y/b voltage max/min, is_pf_visible, r/y/b PF thresholds, high_consumption_units, high_consumption_baseline_percent, bypass_consumption_units, min_threshold_value, nl_operation_hours / start / end, dg_fuel_tank_capacity",
     "Admin users", "all"],
    ["AisleGroup", "wareApp_aislegroup", "Aisle (leg / meter) of a site", "aisleGroupName, attached_leg_id, is_active, power_source", "Admin users", "7, 8, 10, 11, 12"],
    ["SiteBaseline", "wareApp_sitebaseline", "Daily baseline per leg (kWh)", "associated_site_id, leg_id, baseline_value, working_hours, baseline_from", "Admin / baseline tools", "7, 8, 11"],
    ["HourlySiteReading", "wareApp_hourlysitereading", "Hourly consumption per aisle", "associated_Site, leg_id, aisle_group, reading_from, unit_consumption, hourly_baseline_value", "MQTT consumption + recovery", "7, 11, 12"],
    ["DailySiteReading", "wareApp_dailysitereading", "Daily consumption per aisle (= sum of hourly)", "associated_Site, leg_id, reading_for, unit_consumption, daily_baseline_value", "MQTT consumption + recovery", "7, 8, 9, 11"],
    ["SiteLoadParameters", "wareApp_siteloadparameters", "Phase voltages per load packet (high / low check)", "site_id, power_source, parameter_type (0 high, 1 low), r/y/b_phase, created", "MQTT load", "0, 1"],
    ["PowerFactorData", "wareApp_powerfactordata", "Low power-factor readings", "site, supply_source, meter_number, r/y/b_phase_pf, created", "MQTT load", "2"],
    ["SiteLoadPower", "wareApp_siteloadpower", "Live load row per site, source and meter", "Supply_Source, Meter_Number, volts, currents, PF, Status", "MQTT load", "2 (first packet check)"],
    ["DgUnitConsumption", "wareApp_dgunitconsumption", "DG run per aisle and day with fetched fuel", "site, aisle_group, unit_consumption, dg_fuel_consumption, fetch_fuel_data", "fetch-fuel-data service", "6, 9"],
    ["DGFuelAlertsData", "wareApp_dgfuelalertsdata", "Fuel events: refuel, theft, suspicious_fuel", "site, vehicle_number, alert_name, fuel_consumption, epoch_time", "fetch-fuel-data service", "6"],
    ["HomeGatewayId", "wareApp_homegatewayid", "Gateway registry", "hgw_id (…_<number>), connected_to (site)", "Admin users", "13, 15, 16"],
    ["HomeGatewayStatus", "wareApp_homegatewaystatus", "Gateway online state", "home_gateway, status (data in the last hour), last_data_at, last_ping_at (new)", "MQTT listeners (data), gateway_health --broker-log (pings), checker (status)", "15, 16"],
    ["SiteConsumptionPing", "wareApp_siteconsumptionping", "Last consumption packet per site + gateway", "site, home_gateway_id, consumption_ping_time", "MQTT listeners (was: monitoring_dashboard.py cron)", "15 (dashboard)"],
    ["MonitoringMarker", "wareApp_monitoringmarker", "Named times shared by processes (new, 0106)", "name (mqtt_listener_started_at, broker_log_read_at), at", "MQTT listeners (start), gateway_health --broker-log", "15, 16, 17"],
    ["MeterDisconnectionEvent", "wareApp_meterdisconnectionevent", "Meter disconnect / reconnect events reported by gateways", "logged_site_id, meter_id, meter_number, meter_name, status, port_id, detection_window_start / end", "Gateways via meter-disconnections/ingest/", "14"],
    ["FirePumpAlarm", "wareApp_firepumpalarm", "Fire pump state per device", "Site, deviceName, mode, motor status", "MQTT FIREALARM", "fire"],
    ["Email_History", "wareApp_email_history", "Fire e-mails already sent (throttle)", "fire_site, deviceName, email_for, created", "MQTT FIREALARM", "fire"],
]

STATUS_COLUMNS = [
    ("Progress status", 22), ("Unit tests", 34), ("Verified on test server", 48), ("Main server", 30), ("Logs: where to look", 52),
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
    ["warehouse/.env", "GATEWAY_HEALTH_ALL_SILENT_MINUTES", "15", "No gateway at all with data this long: the gateway check is skipped (our side is down)."],
    ["warehouse/.env", "CONSUMPTION_SPIKE_CHECK_SECONDS", "300", "Consumption Spike scan interval (0 = off)."],
    ["warehouse/.env", "ALARM_CLOSE_CHECK_SECONDS / _POWER_MINUTES / _OVERHEAT_HOURS / _EVENT_HOURS", "300 / 60 / 2 / 24", "Closing resolved alarms (alarm_closer.py): voltage / PF after 60 min unseen, overheat after 2 h, meter reading issue after 24 h, daily alarms at the end of the day after their day."],
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


PROGRESS_FILL = [
    ("Done - working live", "C6EFCE"), ("Done - opt-in", "FFF2CC"), ("Done - needs", "FFEB9C"),
    ("Done - waiting", "DDEBF7"), ("Not implemented", "EDEDED"), ("Existing", "C6EFCE"),
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
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        progress = row[2] if title == "Summary" else (row[5] if title == "Alarm catalogue" else "")
        colour = next((fill for key, fill in PROGRESS_FILL if str(progress).startswith(key)), None)
        if colour:
            column = 3 if title == "Summary" else 6
            ws.cell(row=r, column=column).fill = PatternFill("solid", fgColor=colour)
    ws.freeze_panes = "C2" if title in ("Alarm catalogue", "Summary") else "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
    return ws


LOGS = [("Log", 46), ("Server path / command", 62), ("Shows", 70)]
LOG_ROWS = [
    ["Celery queue-1 log (consumption, load, power alarms, e-mails)", "~/django_project/celerylogs1/celery_logs_of_server.log\n grep -a 'Consumption alarm stored\\|Power alarm\\|Meter reading issue' ...",
     "Alarms 0-2, 7, 8, 10, 11, 12 stored / repeated / not e-mailed; e-mail lines 'Alarm email redirected', 'Email sent', 'Email failed'"],
    ["Celery queue-2 log (LoadData, gateway health checker)", "~/django_project/celerylogs2/celery_logs_of_server.log\n grep -a 'Gateway health alarm\\|gateway health:' ...",
     "Alarms 14, 15, 16 raised / cleared; every 5-min check result 'gateway health: raised=.. still_active=.. cleared=..'"],
    ["Fuel service", "journalctl -u fetch-fuel-data --since today\n~/django_project/logges/dg_fuel.log", "DG fuel cycle, alarms 6 and 9"],
    ["Web / API (gunicorn)", "journalctl -u gunicorn --since today", "Gateway overheat (13) and meter-disconnection posts (input of 14)"],
    ["Mosquitto broker (root only)", "/var/log/mosquitto/mosquitto.log", "Gateway pings (PINGREQ) used to tell 15 from 16"],
    ["Recipient check", "cd ~/django_project && virtualwarehouse/bin/python manage.py alarm_recipients [--site ID]", "Who gets each site's alarm e-mails (location team)"],
    ["Gateway health dry run", "virtualwarehouse/bin/python manage.py gateway_health --broker-log FILE --dry-run", "What 14 / 15 / 16 would raise now, without storing or e-mailing"],
    ["Database", "AlarmNotifications (admin: /avcadmin/wareApp/alarmnotifications/)", "Every alarm row: type, site, issue, first / last seen, count, active"],
]

SUMMARY = [("Type", 6), ("Alarm", 30), ("Progress status", 34), ("Verified on test server", 70), ("Main server", 34)]


def main():
    book = Workbook()
    summary_rows = [[row[0], row[1], *[STATUS[row[0]][i] for i in (0, 2, 3)]] for row in ALARMS]
    sheet(book, "Summary", SUMMARY, summary_rows, first=True)
    header = COLUMNS[:5] + STATUS_COLUMNS + COLUMNS[5:16] + [("Models (tables)", 50)] + COLUMNS[16:]
    rows = [row[:5] + list(STATUS[row[0]]) + row[5:16] + [MODELS_BY_TYPE[row[0]]] + row[16:] for row in ALARMS]
    sheet(book, "Alarm catalogue", header, rows)
    sheet(book, "Frontend APIs", APIS, API_ROWS)
    sheet(book, "Configuration", CONFIG, CONFIG_ROWS)
    sheet(book, "E-mail flow", FLOW, FLOW_ROWS)
    sheet(book, "Fields", FIELDS, FIELD_ROWS)
    sheet(book, "Models", MODELS, MODEL_ROWS)
    sheet(book, "Logs", LOGS, LOG_ROWS)
    book.save(HERE / "ALARM_CATALOGUE.xlsx")
    with open(HERE / "ALARM_CATALOGUE.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in header])
        writer.writerows(rows)
    print(f"{len(ALARMS)} alarms, {len(API_ROWS)} APIs -> {HERE / 'ALARM_CATALOGUE.xlsx'}, ALARM_CATALOGUE.csv")


if __name__ == "__main__":
    main()
