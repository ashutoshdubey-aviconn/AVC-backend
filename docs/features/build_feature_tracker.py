"""Build the feature tracker: FEATURE_TRACKER.xlsx and .csv (every feature: done, in progress, waiting, planned),
plus the "Frontend APIs" sheet / FRONTEND_APIS.csv (every API a feature uses, how it works, a real response and how
the frontend handles it) and FRONTEND_API_GUIDE.md for the frontend developer.

    python3 docs/features/build_feature_tracker.py

Edit FEATURES below whenever a feature is planned, started, changed, finished, put on hold or dropped, then
re-run this script. Keep the IDs stable (never reuse one); add new rows at the end of their group.
"""

import csv
import json
import pathlib
from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = pathlib.Path(__file__).resolve().parent
UPDATED = "2026-11-20"

# Status -> (meaning, cell colour). Order = order of the Summary sheet.
STATUSES = {
    "In progress": ("Being built now.", "FFEB9C"),
    "Waiting for input": ("Blocked on an answer or a check by someone (named in 'Waiting on').", "F8CBAD"),
    "Waiting for frontend": ("Backend done and on the test server; the frontend screen is not built yet.", "DDEBF7"),
    "Planned": ("Agreed or proposed; not started.", "E2EFDA"),
    "On hold": ("Stopped by a decision; do not start until it is reopened.", "D9D9D9"),
    "Not started": ("Defined (e.g. an alarm type exists) but nothing raises / uses it.", "EDEDED"),
    "Out of scope": ("Not part of this work, by decision.", "BFBFBF"),
    "Done": ("Built, tested and running on the test server.", "C6EFCE"),
}

COLUMNS = [
    ("ID", 6), ("Feature", 34), ("Area", 14), ("Status", 20), ("What it does / why", 60),
    ("Started", 11), ("Last update", 11), ("Test server", 30), ("Main server", 16),
    ("Next step", 46), ("Waiting on", 18), ("Doc", 40), ("Commit", 30),
]

T = "Not deployed"  # main server column: rollout not permitted yet
F = []


def add(*row):
    assert len(row) == len(COLUMNS), row[:2]
    assert row[3] in STATUSES, row[3]
    F.append(list(row))


# ---- Open: in progress / waiting / planned --------------------------------------------------------
add("F01", "Gateway health report topic", "MQTT / gateway", "Waiting for input",
    "New topic by a colleague: /Acclivate/iOmniControl/{site_id}/{hgw_id}/in/gateway_health/state with temperature, CPU, RAM, "
    "PostgreSQL cluster and service states (e.g. pymodbus.service). Proposed: store the latest report per gateway, count it as "
    "an alive signal (Gateway Disconnected 15 vs Service / Modbus Issue 16), name the failing service in alarm 16, feed "
    "temperature into Gateway Overheat (13).",
    "2026-11-16", "2026-11-16", "-", T,
    "Build the 4 parts once the questions are answered (or with the proposed defaults if told to).",
    "Colleague: payload format (JSON or Python-dict text), send interval, which service states are healthy ('exited' for pymodbus?)",
    "-", "-")
add("F02", "Catch-up spread screen", "Frontend", "Done",
    "Site page: Spread catch-up button and Spread... on Consumption Spike rows; preview, tick aisles, apply (inline "
    "confirmations). Since 20 Nov: 'Manual spread required' tag with the reason, 'Waiting for sync / recovery' list, "
    "each spread shown as Manual (who) or Automatic, Undo for 5 days (then 'closed'), History view (date range, every "
    "spread with its hours before -> after).",
    "2026-11-16", "2026-11-20", "Deployed 20 Nov; checked in Chrome (site 114: 49 automatic + 20 manual in the history)",
    T, "-", "-", "docs/consumption/CATCH_UP_SPREAD.md", "1244b7c9 + frontend")
add("F03", "Baseline setup screen", "Frontend", "Done",
    "Baseline page: Automatic baseline -> sample days -> Calculate (preview, changes nothing) -> edit per aisle -> "
    "Set baseline (inline confirmation). Errors block it; warnings shown; site total follows edits.",
    "2026-11-05", "2026-11-17", "API deployed 5 Nov; screen checked 17 Nov on site 114 (preview, cancelled; nothing set)", T,
    "Push the frontend commit; set a real baseline when a site needs one.", "-",
    "docs/consumption/BASELINE_SETUP_FRONTEND.md", "4bd8744e + frontend")
add("F05", "Alarm e-mails: Gmail login refused", "Alarms / e-mail", "Waiting for input",
    "Gmail has refused the alarm account's SMTP login since 6 Nov 14:55 (test and main share the account). Retries keep "
    "failed e-mails for 24 h; 8 e-mails sent before the retries existed were lost.",
    "2026-11-06", "2026-11-17", "Sending again (e-mails sent 17 Nov 10:26 and 10:46)", "Same account",
    "Login works again; decide whether to re-send the 8 e-mails lost before the retries existed.", "User (Gmail account)",
    "docs/mqtt-flows/EMAIL_RETRIES.md", "807ff4b3")
add("F06", "Midnight check after a day change", "Operations", "Waiting for input",
    "One-time check of the consumption batch at a day change (flush tasks, daily = sum of hourly, day-change alarms). The "
    "21 Oct run never happened (test server off for Diwali).",
    "2026-10-20", "2026-11-06", "Not run", "-",
    "Run it on a coming midnight if wanted.", "User",
    "~/.claude/scheduled-tasks/test-server-midnight-check (disabled)", "-")
add("F07", "Recompute past days with the spike rule", "Consumption", "Planned",
    "Rule 2 (spike hours out of the day total) and the hourly verification apply from now on; past days keep their old "
    "totals. resync_daily_totals can recompute a date range (dry run first).",
    "2026-11-05", "2026-11-16", "Only today's rows resynced after each morning fill", T,
    "Only if asked: choose the date range, dry run, then --apply.", "User",
    "docs/consumption/READING_RULES.md", "-")
add("F08", "DG fuel: alert de-duplication and ON-packet coalescing", "DG fuel", "Planned",
    "From the August roadmap: DGFuelAlertsData de-duplication with normalised epoch strings (partly done); coalescing of "
    "high-rate DG ON packets (design phase).",
    "2026-08-18", "2026-08-18", "-", "-", "Not picked up in this branch.", "-",
    "docs/roadmaps/TODO.md, docs/dg-fuel/DG_FUEL_ROADMAP.md", "-")
add("F09", "Credential clean-up", "Security", "Planned",
    "Remove hard-coded provider tokens from code, rotate them, keep credentials in .env only. The DB password was already "
    "moved out of the setup scripts (26 Oct).",
    "2026-08-18", "2026-10-26", "-", "-", "Agree which credentials to rotate.", "User",
    "docs/roadmaps/TODO.md", "4643371d (DB password)")
add("F11", "Provisioning API: require login, no fixed password", "Security", "Not started",
    "Found 19 Nov in the three-way comparison: CreateCustomerUsingProvisioning (and the other provisioning APIs) need no login "
    "and create customers with one fixed default password. Inherited from main; same on main and ours.",
    "2026-11-19", "2026-11-19", "-", "-", "Check who calls the provisioning script before closing it.", "User",
    "docs/merge/THREE_WAY_COMPARISON.md", "-")
add("F10", "Merge with the colleague's code", "Merge", "Waiting for input",
    "Team lead: merge this branch with the colleague's optimized version of main's code. Prepared 19 Nov: tag "
    "fov2-pre-merge-20261119, code inventory (every feature, alarm, API, model, migration and function with a fingerprint), "
    "function-level overlap check. Main's server = legacy origin/main + our DG fuel / LoadData branches + a few hotfixes "
    "(user type 6, monitoringCustomerSites/ API, Redis CACHES, admin pages, AisleGroup DG fuel fields); migrations "
    "0073-0076 diverged. Colleague's repo Daksh007-batman/New-asem-merger @ 54313d5 reviewed read-only 19 Nov: no common "
    "history, port his features onto ours (docs/merge/COLLEAGUE_CODE_REVIEW.md).",
    "2026-11-19", "2026-11-19", "-", "-",
    "Team lead decides the base (recommended: ours); then port his features one by one with tests.",
    "Team lead: base and who ports; colleague: credentials in his repo rotated",
    "docs/merge/MERGE_GUIDE.md", "-")

# ---- On hold / not started / out of scope ---------------------------------------------------------
add("H01", "Stored readings above 10,000 kWh", "Consumption", "On hold",
    "About 1,155 hourly and 83 daily rows above 10,000 kWh (meter glitches, running totals sent as hours) on test and main. "
    "Left as stored.", "2026-11-03", "2026-11-03", "Unchanged", "Unchanged",
    "Manager decides what to do with them.", "Manager", "docs/consumption/READING_RULES.md", "-")
add("H02", "Main server rollout of this branch", "Deploy", "On hold",
    "Everything on full-optimization-v2 runs on the test server only.", "2026-10-28", "2026-11-16", "-", T,
    "Rollout not permitted yet.", "Permission", "docs/deploy/MAIN_SERVER_ROLLOUT.md", "-")
add("H03", "Location teams for alarm e-mails", "Alarms / e-mail", "On hold",
    "LOCATION_TEAMS in alarm_recipients.py (e-mails by site location) is built but empty.", "2026-10-28", "2026-10-28",
    "Empty", T, "Fill when the teams are given.", "User",
    "docs/alarms/ALARM_CATALOGUE.xlsx (Configuration)", "61cd0fc3")
add("H04", "Low Consumption alarm on sites", "Alarms", "On hold",
    "Alarm 8 is built but opt-in (Site.min_threshold_value or AlarmSetting Auto); no site has it on, a default would flood.",
    "2026-10-23", "2026-11-02", "Off on every site", T, "Switch on per site when wanted.", "User",
    "docs/alarms/ALARM_CATALOGUE.xlsx (type 8)", "-")
add("N01", "Alarms 3, 4, 5 (DG Overtime, DG Fuel Under Level, Mains Higher Consumption)", "Alarms", "Not started",
    "Types exist; no code raises them. Old rows are closed by the alarm closer.", "-", "2026-11-02", "-", "-",
    "Define rules if they are wanted.", "-", "docs/alarms/ALARM_CATALOGUE.xlsx (types 3-5)", "b15b9880")
add("O01", "API view optimization", "API", "Out of scope",
    "Query / N+1 work in wareApp/views is not part of this branch; issues found are only reported.", "2026-10-26", "2026-10-28",
    "-", "-", "-", "-", "-", "-")
add("O02", "Automatic catch-up spreading", "Consumption", "Done",
    "Was out of scope until 20 Nov; now (user decision): the night job spreads clear catch-ups 19:00-11:00 every day and "
    "all day on Sunday (Celery beat every 30 min over the last 3 days). Clear = aisle synced again, next hour in, "
    "recovery ended, share not > 3 x the normal hour, spread day within 0.5-1.5 x the aisle's daily average. Doubtful "
    "ones are left for a manual spread and e-mailed once to the software team.",
    "2026-10-28", "2026-11-20", "Deployed 20 Nov; first run on test 23:52: 49 spread, 4 e-mailed", T, "-", "-",
    "docs/consumption/CATCH_UP_SPREAD.md", "-")

# ---- Done -------------------------------------------------------------------------------------------
add("D27", "Code inventory and merge check", "Docs / merge", "Done",
    "docs/merge/CODE_INVENTORY.xlsx: features, alarms, APIs (new / changed / same), Celery tasks, commands, DB models and "
    "fields, migrations, modules, every function (what it does, origin, tests, fingerprint), tests, why it is better than "
    "the legacy code, overlap with main's code, removed files. scripts/merge/overlap_check.py compares any two code bases "
    "function by function.",
    "2026-11-19", "2026-11-19", "-", "-", "Re-run on the colleague's code before the merge.", "-",
    "docs/merge/MERGE_GUIDE.md", "-")
add("D28", "Colleague's code vs main's code", "Docs / merge", "Done",
    "Static comparison of the colleague's repo (54313d5) with the code running on main's server: function level "
    "(overlap_check.py) and API contract (new scripts/merge/api_contract_check.py: request fields and response keys of "
    "every view, and whether the frontend calls it). 65 of 106 shared views answer differently, 42 of them called by the "
    "frontend; 6 Excel downloads are placeholders; DG fuel v2 and LoadData packages missing; migrations don't fit main's DB; "
    "login has no rate limit and re-activates disabled users.",
    "2026-11-19", "2026-11-19", "-", "-", "Not run: confirm by running his code on a copy of main's DB with the frontend.", "-",
    "docs/merge/COLLEAGUE_VS_MAIN.md", "-")
add("F04", "Estimated hours on the hourly chart", "API / frontend", "Done",
    "hourlySavingData/, submeteringHourlyData/ and getSiteHourlyConsumptionData/ send estimated[24] per series "
    "(HourlySiteReading.is_estimated: hours filled by a catch-up spread). Site, submetering, WH-metering and baseline "
    "hourly charts draw them lighter with a dashed outline, tooltip '(estimated)', and a note under the title.",
    "2026-11-16", "2026-11-20", "Deployed 20 Nov; checked in Chrome (site 114, 15 Nov: 480 estimated bars)", T,
    "-", "-", "docs/CHANGELOG.md (20 Nov)", "-")
add("D31", "Alarm settings screen", "Alarms / frontend", "Done",
    "Site page -> Alarms -> settings button (Super Admin): per alarm type Default / Auto / Manual (threshold with "
    "unit) / Off and the e-mail groups, saved per row. New API GET / POST alarmSettings/ on the AlarmSetting rows "
    "(Super_Admin only, validated; Default removes the row). Was Django admin only.",
    "2026-11-20", "2026-11-20", "Deployed 20 Nov; checked in Chrome (site 114: save Auto, back to Default)", T,
    "-", "-", "docs/CHANGELOG.md (20 Nov)", "-")
add("D32", "'Open for' on the alarm lists", "Alarms / frontend", "Done",
    "Site alarm detail and super-admin alarm list show how long each issue has been open (open_for from the APIs, "
    "orange from 1 day); the super-admin column sorts by days.",
    "2026-11-20", "2026-11-20", "Deployed 20 Nov; checked in Chrome", T,
    "-", "-", "docs/CHANGELOG.md (20 Nov)", "-")
add("D34", "Frontend API handoff workbook", "Docs / frontend", "Done",
    "docs/features/FRONTEND_API_HANDOFF.xlsx for the frontend developer: login and token, every API built in this branch "
    "(gateway status with Gateway Service issue, catch-up spread preview / apply / undo / history, sync status, recovery "
    "history, baseline preview / apply / saveBaseline, alarm settings GET / POST, hourly estimated flag, alarm 'Open for'): "
    "method, URL, auth header, who, request and response fields, real responses from test, errors, how it works, screen, "
    "values to show.", "2026-11-21", "2026-11-21", "-", "-", "Hand it to the frontend developer.", "-",
    "docs/features/FRONTEND_API_HANDOFF.xlsx", "-")
add("D33", "Data sync / recovery status screen", "Recovery / frontend", "Done",
    "Site page -> Data sync (Super Admin), per aisle and power source (no gap details, decided 20 Nov): healthy = "
    "Synced / recovery Not needed / last sync time; gap filled = Synced / Recovered / last recovered time; no "
    "data = Syncing / Not received / last data time + Attempts (times asked from the gateway, e.g. 3 of 3, last "
    "asked). Counts and a Synced / Syncing filter; below, the recovery requests (status filter, paging). New "
    "read-only APIs GET syncStatus/ and recoveryHistory/; the data was stored but nothing served it.",
    "2026-11-20", "2026-11-20", "Deployed 20 Nov; checked in Chrome (site 109: 27 synced, 20 syncing, 3 of 3 attempts)", T,
    "-", "-", "docs/features/FRONTEND_API_GUIDE.md", "-")
add("D30", "Gateway Status panel: Gateway Service issue", "Alarms / frontend", "Done",
    "gateway-status/ adds health (online / offline / modbus_issue) with health_since / health_detail, from the open "
    "Gateway Disconnected (15) and Gateway Service / Modbus Issue (16) alarms; status (bool) unchanged. Dashboard panel: "
    "\"Gateway Service issue\" filter + count and an amber badge with the alarm text as tooltip; sorted offline, "
    "Gateway Service issue, online (label renamed from \"Modbus issue\" the same day at the user's request).",
    "2026-11-20", "2026-11-20", "Deployed 20 Nov; checked in Chrome (69 / 3 / 1: site 119)", T,
    "Frontend: commit in Aviconncorp-new-migrated-frontend", "-", "docs/CHANGELOG.md (20 Nov)", "-")
add("D29", "Three-way comparison: main / ours / colleague", "Docs / merge", "Done",
    "Side by side of main's code, ours and the colleague's: API contract for every pair (ours replacing main: 4 frontend "
    "APIs differ, all deliberate fixes; colleague replacing main 42 / ours 40), DB, DG fuel, LoadData, MQTT, alarms, "
    "security, tests. Found in his code: fixed OTP 1234 lets anyone reset any password.",
    "2026-11-19", "2026-11-19", "-", "-", "Static only: not run.", "-",
    "docs/merge/THREE_WAY_COMPARISON.md", "-")
add("D26", "Alarm counts consistent on every page", "Alarms / frontend", "Done",
    "Super-admin, customer and site ALARMS tiles, the customer alarm table / chart and the site panel all read the "
    "alarm server and count open alarms; customer table grouped Gateway / Consumption / Power; sign-in guard.",
    "2026-11-17", "2026-11-17", "Deployed 17 Nov; checked in Chrome (34 / 1 / 1)", T,
    "Frontend: commit in Aviconncorp-new-migrated-frontend", "-", "docs/CHANGELOG.md (17 Nov)", "-")
add("D25", "No false Service / Modbus Issue at gateway reconnect", "Alarms", "Done",
    "A gateway that was Disconnected and pings again gets 10 min for its queued data before it can be called a "
    "Service / Modbus Issue (its first ping arrives before its data is written). Found: site 130, false 16 + e-mail at "
    "06:16 and 10:26 on 17 Nov.", "2026-11-17", "2026-11-17", "Deployed 17 Nov", T, "-", "-",
    "docs/mqtt-flows/GATEWAY_PINGS_FROM_MAIN.md", "-")
add("D24", "Alarms on merged sites (virtual aisle groups)", "Alarms", "Done",
    "A site not live whose aisles show under a live site is still checked (gateway 15 / 16, meter 14, spike 17); "
    "gateway and aisle alarms are stored and e-mailed under the site the customer sees. Found: gateway ..._185_2 "
    "(site 185, shown under 183) silent since 6 Nov without an alarm.", "2026-11-17", "2026-11-17",
    "Deployed 17 Nov; main's 12 newest gateways copied to test; 10:46 alarm raised for ..._185_2 under site 183 and e-mailed", T, "-", "-", "docs/alarms/MERGED_SITES.md", "-")
add("D01", "Catch-up spread API", "Consumption", "Done",
    "POST /api/catchUpSpread/ (Super_Admin): preview / apply / undo / history. Since 20 Nov: gap = hours without a row "
    "and ERROR404 hours (stored as 0; RecoveryMonitor.error_hours), offered only when synced again, the next hour in and "
    "recovery ended; spread hours are real readings (no estimated mark); hourly and daily recalculated; per-hour record "
    "(CatchUpSpread.hours_detail) and mode manual / automatic; undo for 5 days; recovery replies leave spread hours and "
    "days alone.", "2026-11-16", "2026-11-20", "Deployed 20 Nov (migration 0115; 20 old spreads converted)", T,
    "Frontend: F02", "-", "docs/consumption/CATCH_UP_SPREAD.md", "1244b7c9")
add("D02", "Alarms verified from hourly data", "Alarms", "Done",
    "High Consumption / Bypassed are counted from the hourly rows (incl. the 2 days before, to find gaps), never from the "
    "stored daily total. Found by a false Bypassed at site 114.", "2026-11-16", "2026-11-16", "Deployed 16 Nov", T, "-", "-",
    "docs/consumption/READING_RULES.md (Alarms)", "5a6e9331")
add("D03", "DB optimization", "Database", "Done",
    "Redundant indexes dropped, aisle + time index on hourly readings, SSD settings, no FKs on telemetry tables.",
    "2026-11-06", "2026-11-06", "Deployed 6 Nov", T, "-", "-", "docs/operations/DB_OPTIMIZATION_2026-11-06.md",
    "19138914, a80f8474")
add("D04", "Alarm e-mail retries", "Alarms / e-mail", "Done",
    "Failed alarm e-mails kept in PendingEmail and retried with back-off for up to 24 h.", "2026-11-06", "2026-11-06",
    "Deployed 6 Nov", T, "-", "-", "docs/mqtt-flows/EMAIL_RETRIES.md", "807ff4b3")
add("D05", "Gateway pings from main", "MQTT / gateway", "Done",
    "Test reads gateway pings from main's broker log over a restricted read-only SSH key, so it tells 15 from 16.",
    "2026-11-06", "2026-11-06", "Enabled 6 Nov", "Not needed (reads its own log)", "-", "-",
    "docs/mqtt-flows/GATEWAY_PINGS_FROM_MAIN.md", "1d8641c4")
add("D06", "Meter Reading Issue fixed after 24 h", "Alarms", "Done",
    "Counts as fixed only after 24 h without a repeat plus a normal hourly reading (was 1 h).", "2026-11-06", "2026-11-06",
    "Deployed 6 Nov", T, "-", "-", "docs/alarms/ALARM_CATALOGUE.xlsx (type 10)", "0df4ad2e")
add("D07", "Customer / site page alarm APIs", "Alarms / API", "Done",
    "alarmListOnCustomerPage, alarmListOnSitePage, getCustAlarmGraph and the snapshot alarm count read the open alarms "
    "(were always empty).", "2026-11-06", "2026-11-06", "Deployed 6 Nov", T, "-", "-",
    "docs/alarms/ALARM_CATALOGUE.xlsx (Alarm API list)", "f8484404")
add("D08", "Automatic baseline setup API", "Consumption", "Done",
    "POST /api/baselineSetup/ previews and applies baselines from sample days; fixes the saveBaseline first-baseline crash.",
    "2026-11-05", "2026-11-06", "Deployed 5 Nov", T, "Frontend: F03", "-", "docs/consumption/BASELINE_SETUP.md",
    "4bd8744e")
add("D09", "Spike hours left out of the day total", "Consumption", "Done",
    "On saving / submetering sites an hour above the aisle's whole daily baseline does not count in the day.",
    "2026-11-05", "2026-11-05", "Deployed 5 Nov", T, "-", "-", "docs/consumption/READING_RULES.md (rule 2)", "b24a6084")
add("D10", "10,000 kWh glitch limit by site type", "Consumption", "Done",
    "Cap only on saving (2) and submetering (5) sites, on every write path; never on WH-metering (1).",
    "2026-11-03", "2026-11-03", "Deployed 3 Nov", T, "-", "-", "docs/consumption/READING_RULES.md (rule 1)", "f63fc814")
add("D11", "Skip sites in the gateway check", "MQTT / gateway", "Done",
    "GATEWAY_HEALTH_SKIP_SITES; test skips site 35 (not forwarded by main).", "2026-11-03", "2026-11-03", "Deployed 3 Nov", T,
    "-", "-", "wareApp/mqtt/services/gateway_health.py", "39451340")
add("D12", "Automatic alarm closing; active alarms only on the frontend", "Alarms", "Done",
    "Alarm closer every 5 min; 'active' means still happening; frontend lists show active alarms only; day-only "
    "High / Low / Bypassed.", "2026-11-02", "2026-11-02", "Deployed 2 Nov", T, "-", "-",
    "docs/alarms/ALARM_CATALOGUE.xlsx (E-mail flow)", "be758d81, 0636779e, b15b9880")
add("D13", "Outage alarms open until solved, daily reminder", "Alarms", "Done",
    "14 / 15 / 16 open since the outage began, open_days in the APIs, e-mail once a day until solved; 15 only with proof "
    "of no pings.", "2026-11-02", "2026-11-02", "Deployed 2 Nov", T, "-", "-",
    "docs/alarms/ALARM_CATALOGUE.xlsx (types 14-16)", "df8001b3, 92420365")
add("D14", "Consumption Spike alarm (17)", "Alarms", "Done",
    "Meter jump / meter reset / catch-up hours with their cause, one e-mail per site per scan. Since 20 Nov a big hour "
    "after a gap is a catch-up even above the whole daily baseline (was called a meter jump), and ERROR404 hours count "
    "as gap.", "2026-10-30", "2026-11-20",
    "Deployed 30 Oct; detection fix 20 Nov", T, "-", "-", "docs/alarms/ALARM_CATALOGUE.xlsx (type 17)", "a323f5d6, 6c2cd379")
add("D15", "Fewer false alarms (our downtime, data spikes)", "Alarms", "Done",
    "Our own listener restarts and data spikes no longer raise alarms.", "2026-10-30", "2026-10-30", "Deployed 30 Oct", T,
    "-", "-", "docs/alarms/ALARM_CATALOGUE.xlsx", "64f7c3f1")
add("D16", "Data-missing alarms 14 / 15 / 16", "Alarms", "Done",
    "Meter Disconnected, Gateway Disconnected, Gateway Service / Modbus Issue (zero-consumption cases 3, 5, 6).",
    "2026-10-28", "2026-11-06", "Deployed 28 Oct (14 waits for a live case: gateways post meter events to main only)", T,
    "-", "-", "docs/alarms/ALARM_CATALOGUE.xlsx (types 14-16)", "e8a3009b, c8c0a0cf")
add("D17", "Bypassed alarm automatic and during the day", "Alarms", "Done",
    "Per aisle at >= 100 % of its daily baseline, raised as soon as today's running total crosses it.", "2026-10-23",
    "2026-11-16", "Deployed 28 Oct", T, "-", "-", "docs/alarms/ALARM_CATALOGUE.xlsx (type 11)", "582f1fee, 33f4cf57")
add("D18", "Alarm recipients and Auto / Manual / Off per site", "Alarms / e-mail", "Done",
    "Software / ground / location teams; AlarmSetting per site and type; no repeat e-mails for near-equal values.",
    "2026-10-27", "2026-10-28", "Deployed 28 Oct (test e-mails go to the override)", T, "-", "-",
    "docs/alarms/ALARM_CATALOGUE.xlsx (Configuration)", "e70d5025, 0ee4c075, 61cd0fc3")
add("D19", "One alarm table", "Alarms", "Done",
    "Power / DG alarms moved into AlarmNotifications; NewAlarmsNotifications dropped.", "2026-10-26", "2026-10-28",
    "Deployed", T, "-", "-", "docs/alarms/ALARM_CATALOGUE.xlsx (Models)", "19c2d009")
add("D20", "LoadData roll-up optimization", "Load data", "Done",
    "Roll up only since the last rolled minute; monthly bounds cached.", "2026-10-27", "2026-10-27", "Deployed", T, "-", "-",
    "docs/load-data/LOAD_DATA_FLOW_AND_OPTIMIZATION.md", "44b4fd43")
add("D21", "Recovery speed-ups", "Recovery", "Done",
    "Stored hours loaded by time range (336 ms -> 0.6 ms); stored hours left unchanged; alarms only for changed days.",
    "2026-10-28", "2026-10-28", "Deployed", T, "-", "-", "docs/mqtt-flows/README.md", "a136576b, dab6a704")
add("D22", "CPU analysis of test and main", "Monitoring", "Done",
    "Per-core CPU use (who uses each core) every minute to local CSVs, with a report.", "2026-11-02", "2026-11-02",
    "Running", "Read only", "-", "-", "docs/monitoring/README.md", "5266567e, b208e6d3")
add("D23", "Alarm catalogue and MQTT flow docs", "Docs", "Done",
    "ALARM_CATALOGUE.xlsx (every alarm, status, APIs, models, logs) and one draw.io flow per MQTT topic / alarm.",
    "2026-10-26", "2026-11-17", "-", "-", "Keep updated with every change.", "-",
    "docs/alarms/, docs/mqtt-flows/", "8a760a89, 9a0877be")


# ---- Frontend APIs: what each feature exposes and how the frontend handles it ----------------------
# Frontend status -> (meaning, colour).
FE_STATUSES = {
    "Done": ("The frontend calls it and shows what the feature needs.", "C6EFCE"),
    "To build": ("The API exists (or needs a small change); the frontend part is not built yet.", "FFEB9C"),
    "To decide": ("No API yet: what to build needs a decision (named in 'Next step').", "F8CBAD"),
    "Not frontend": ("Called by a gateway, a provider or a script, not by the frontend.", "D9D9D9"),
    "Not used": ("The API exists but no frontend screen calls it.", "EDEDED"),
}
API_COLUMNS = [
    ("Feature IDs", 12), ("Endpoint", 30), ("Method", 8), ("Auth", 16), ("Request", 34),
    ("Response (what the frontend reads)", 46), ("Frontend screen / file", 40), ("Frontend status", 14),
    ("Next step for the frontend", 46),
]
A = []
FE = "Aviconncorp-new-migrated-frontend/src/app/"


def api(*row):
    assert len(row) == len(API_COLUMNS), row[:2]
    assert row[7] in FE_STATUSES, row[7]
    A.append(list(row))


# Alarm lists
api("D12, D16, D17, D19, D24, N01", "/api/alarmList/", "POST", "Token", '{"siteId": 114}',
    "total_alarm, high_priority, medium_priority, active_alarms (one line per type, active only)",
    FE + "alarm/alarm.component.ts, warehouse/warehouse.component.ts (siteAlarmList)", "Done",
    "N01: types 3 / 4 / 5 will show here once raised; no frontend change.")
api("D12, D14, D16, D24", "/api/alarmListDetail/", "POST", "Token", '{"siteId": 114, "alarm_type": 10}',
    "data[]: type, priority, aisle_group, issue, created, last_seen, occurrences, is_active",
    FE + "alarm/alarm.component.ts (siteAlarmDetail)", "Done", "-")
api("D13, D32", "/api/alarmListDetail/ (open_days, open_for)", "POST", "Token", '{"siteId": 114, "alarm_type": 15}',
    "open_days, open_for of each row", FE + "alarm/alarm.component.ts (detail table: 'Open for' column)",
    "Done", "-")
api("D12, D26", "/api/alarmTypeApi/", "POST", "Token, Super_Admin", "{}",
    "data[]: customer_id, customer_name, alarm_list[] (site, aisle, type, priority, issue)",
    FE + "super-admin/super-admin.component.ts (allAlarmsByCustomer)", "Done", "-")
api("D13, D32", "/api/alarmTypeApi/ (open_days, open_for)", "POST", "Token, Super_Admin", "{}",
    "alarm_list[].open_days, open_for", FE + "super-admin/super-admin.component.ts ('Open for' column, sorts by days)",
    "Done", "-")
api("D26", "/api/alarmapi/", "POST", "Token", "{}", "data[][]: Alarm_priority, site_id__site_name, alarm_count",
    FE + "alarm/alarm-api.service.ts (alarmCounts) - no screen calls it", "Not used",
    "Superseded by alarmTypeApi/ on the super-admin page; drop from the service or keep for later.")
api("D26", "/api/snapshot/", "POST", "Token", '{"user_id": 1, "start_date": "YYYY/MM/DD", "end_date": "YYYY/MM/DD"}',
    "alarms, total_unit_consumed, total_energy_saved, total_saved_percentage",
    FE + "super-admin/super-admin.component.ts (superAdminSnapshot), services/user.service.ts", "Done", "-")
api("D07, D26", "/api/alarmListOnCustomerPage/", "POST", "Token", '{"id": <customer user id>}',
    "data[]: site_id, site_name, alarms {type: count}, total_alarm_count, site_type",
    FE + "customer-dashboard/customer-dashboard.component.ts (customerSiteAlarms)", "Done", "-")
api("D07, D26", "/api/getCustAlarmGraph/", "POST", "Token", '{"id": <customer user id>}',
    "Data[]: name, data [count]; alarm_name_list",
    FE + "customer-dashboard/customer-dashboard.component.ts (customerAlarmGraph)", "Done", "-")
api("D07, D26", "/api/customerSnapShotEnergySavingApi/", "POST", "Token", "(customer snapshot request)",
    "energy figures + alarms (open alarm count)", FE + "services/user.service.ts (customer dashboard)", "Done", "-")
api("D07, D26", "/api/siteSnapShotEnergySavingApi/", "POST", "Token", '{"site_id": 183, "user_type": 1}',
    "energy figures + alarms (open alarm count of the site)", FE + "services/user.service.ts (site page ALARMS tile)",
    "Done", "-")
api("D07", "/api/alarmListOnSitePage/", "POST", "Token", '{"site_id": 114}',
    "data[]: alarm_type, object_type, object_name, alarm_priority, created_date", "- (no screen calls it)", "Not used",
    "The site page uses alarmList/ + alarmListDetail/ instead.")
api("H04", "/api/consumptionAlarms/", "POST", "Token", '{"site_id": 134, "start_date": "...", "end_date": "..."}',
    "data[]: id, alarm_type (High / Low Consumption), priority, aisle_group, created_time",
    FE + "alarm/alarm-api.service.ts (consumptionAlarms) - no screen calls it", "Not used",
    "Low Consumption (H04) is on hold; High / Low already show in alarmList/.")
# Gateway / meter state
api("D16, D30", "/api/gateway-status/", "GET", "None (AllowAny)", "?limit=1000&offset=0",
    "results[]: gateway_id, status, health (online / offline / modbus_issue), health_since, health_detail, site_id, site_name, customer_name",
    FE + "alarm/gateway-status.component.ts (dashboard Gateway Status panel)", "Done",
    "Label 'Gateway Service issue' for health = modbus_issue.")
api("D16", "/api/meter-disconnections/", "GET", "Token", "?site_id=&meter_id=&status=&from=&to=&limit=&offset=",
    "count, limit, offset, results[]: meter_id, meter_number, meter_name, status, last_seen_at",
    FE + "alarm/alarm.component.ts (meterDisconnections)", "Done", "-")
api("F01", "(not designed) latest gateway health report", "GET", "-", "-",
    "Proposed: temperature, CPU, RAM, PostgreSQL / service states (e.g. pymodbus.service) per gateway",
    "Gateway Status panel (extra columns) or gateway detail", "To decide",
    "Waits on the colleague's gateway_health topic; then decide: new endpoint or extra fields in gateway-status/.")
# Catch-up spread, baselines
api("D01, D14, F02, O02", "/api/catchUpSpread/", "POST", "Token, Super_Admin",
    '{"site_id": 114, "day": "2026/11/16", "legs": ["692"], "apply": false} or {"undo": 12} or '
    '{"site_id": 114, "history": true, "from": "2026/11/01", "to": "2026/11/20"}',
    "catch_ups[] (gap, empty / no_data hours, share, days before / after, daily average, manual_required, warnings), "
    "waiting[], not_spreadable[], applied_spreads[] (mode, can_undo, undo_until); history: spreads[] with hours_detail",
    FE + "alarm/catch-up-spread.component.ts (preview, apply, undo, waiting, history); Spread... on Consumption Spike rows",
    "Done", "-")
api("D08, F03", "/api/baselineSetup/", "POST", "Token, Super_Admin", "sample days, aisles, apply flag",
    "per-aisle baselines (preview), errors, warnings, site total", FE + "baseline/baseline-setup.service.ts, baseline-setup.component.ts",
    "Done", "-")
api("D08", "/api/saveBaseline/", "POST", "Token", "baseline values per aisle",
    "status (first baseline no longer crashes)", FE + "baseline/baseline.component.ts, services/data.service.ts", "Done", "-")
# Hourly charts: estimated hours
api("F04", "/api/hourlySavingData/", "POST", "Token", "site, date range",
    "Data[] / SavingData[]: name, data[24], estimated[24]", FE + "warehouse/warehouse.component.ts (hourly consumption + saving charts)", "Done",
    "-")
api("F04", "/api/submeteringHourlyData/", "POST", "Token", "site, date range",
    "Data[]: name, data[24], estimated[24]", FE + "submetering/submetering.component.ts", "Done", "-")
api("F04", "/api/getSiteHourlyConsumptionData/", "POST", "Token", "site, date range",
    "Data[]: name, data[24], estimated[24]", FE + "wh-metering/wh-metering.component.ts, baseline/baseline.component.ts",
    "Done", "-")
# Alarm settings: no API yet
api("D18, D31, H04", "/api/alarmSettings/", "GET / POST", "Token, Super_Admin",
    'GET ?site_id=114; POST {"site_id": 114, "alarm_type": 7, "mode": "manual", "threshold": 250, "email_ground": false}',
    "site_id, site_name, data[]: alarm_type, alarm_name, group, raised, unit, mode (default / auto / manual / off), "
    "threshold, email_software, email_ground, repeat_tolerance_percent",
    FE + "alarm/alarm-settings.component.ts (site page -> Alarms -> settings button)", "Done",
    "H04: Low Consumption can now be switched on per site here (Auto or Manual).")
# Data sync / recovery status (read-only)
api("D33", "/api/syncStatus/", "GET", "Token, Super_Admin", "?site_id=114",
    "site_id, site_name, total, counts {sync: {..}, recovery: {..}}, data[]: home_gateway_id, object_type "
    "(aisle / power_source), object_name, leg_id, power_source, sync (synced / syncing / unknown), sync_display, "
    "last_sync_at, recovery (not_needed / recovered / not_received / received), recovery_display, "
    "last_recovered_at, attempts, max_attempts, last_requested_at",
    FE + "alarm/sync-status.component.ts (site page -> Data sync button)", "Done", "-")
api("D33", "/api/recoveryHistory/", "GET", "Token, Super_Admin",
    "?site_id=114&status=failed&recovery_type=hourly_consumption&limit=20&offset=0",
    "count, limit, offset, results[]: recovery_type, status, gateway_id, object_name, missing_from / missing_to, "
    "expected_slots, recovered_slots, error_slots, attempt, requested_at, response_received_at, applied_at, "
    "verified_at, failed_reason, catch_up_at, is_active",
    FE + "alarm/sync-status.component.ts (Recovery requests table, status filter, paging)", "Done", "-")
# Not called by the frontend
api("F11", "/api/createCustomer/, createSite/, createAisleGroups/, createHomeGatewayId/", "POST", "None (open)",
    "provisioning payload", "created ids", "- (provisioning script)", "Not frontend",
    "Backend fix (F11): require login and take the password from the request.")
api("F08", "/api/dgFuelAlerts/, /api/dgFuelPushInterface/", "POST", "None (provider)", "provider payload",
    "status", "- (fuel providers)", "Not frontend", "-")
api("D16", "/api/meter-disconnections/ingest/", "POST", "None (gateway)", "meter events", "saved count",
    "- (gateway)", "Not frontend", "-")
api("D21, D33", "/api/v1/recovery/upload/", "POST", "None (gateway)",
    '{"Recovery Payload": [topic, site id, gateway id, recovery data, ...]}',
    "status, message (400 \"Recovery Payload missing\")", "- (gateways upload recovery data over HTTP)", "Not frontend",
    "Same processing as the MQTT recovery answers: rows applied and the sync status moved (shown by syncStatus/).")


# ---- How each frontend API works, and a real response (FRONTEND_API_GUIDE.md) -------------------
# Responses: frontend_api_samples_test_server.json, captured on the test server by
# capture_frontend_api_samples.py (read-only calls only). APIs that write are not called: their
# example comes from the code (WRITE_EXAMPLES).
SAMPLES_FILE = HERE / "frontend_api_samples_test_server.json"
SAMPLES = json.loads(SAMPLES_FILE.read_text()) if SAMPLES_FILE.exists() else {}

# endpoint (as in A) -> (guide section, sample key, how it works)
FEATURE_API, ALARM_API, OTHER_API = "Feature APIs", "Alarm APIs", "Not called by the frontend"
HOW = {
    "/api/catchUpSpread/": (FEATURE_API, "catchUpSpread",
        "Preview (apply false, changes nothing): the site's catch-up hours on that day - after a gateway service "
        "stopped, the first hour back carries the gap's energy. Gap = hours without a row and ERROR404 hours (stored "
        "as 0); real 0 kWh hours are never taken. Per catch-up: gap, empty_hours / no_data_hours, share per hour, "
        "normal hour, spread day vs the aisle's daily average, day totals before / after, manual_required + warnings "
        "(share > 3 x normal hour, or spread day outside 0.5-1.5 x the daily average). waiting[] = catch-ups not offered "
        "yet (aisle not synced, recovery running, next hour not in); not_spreadable[] = gap start unknown. apply true "
        "(ticked legs) spreads as real readings (manual), recalculates hourly and daily, closes the spike alarm and "
        "keeps a per-hour record. applied_spreads[]: mode manual (applied_by) / automatic (night job), can_undo and "
        "undo_until (5 days). {\"undo\": id} reverses a spread within 5 days. {\"history\": true, from, to} lists "
        "the site's spreads (max 92 days) with hours_detail (at, kind empty / no_data / catch_up, before, after). "
        "Super_Admin only (403 otherwise)."),
    "/api/baselineSetup/": (FEATURE_API, "baselineSetup",
        "Preview (apply false, changes nothing): per aisle the stored consumption of each sample day, the average, an "
        "override if sent, the proposed baseline and warnings (missing hours, alarms, spikes in the sample); errors "
        "block applying. apply true closes the open baselines on effective_from, creates the new SiteBaseline rows "
        "and rewrites daily / hourly baseline and energy_saved from that day. Super_Admin only."),
    "/api/saveBaseline/": (FEATURE_API, None,
        "Old one-aisle baseline save (baseline page table): sets the baseline of legId from date. Fixed: the first "
        "baseline of a site no longer crashes. Writes, so not captured: example from the code."),
    "/api/hourlySavingData/": (FEATURE_API, "hourlySavingData",
        "Hourly chart of a saving site and day: per aisle 24 hourly kWh (Data) and 24 hourly kWh saved (SavingData), "
        "plus a 'baseline' spline (day baseline / 24) on live sites. estimated[i] true = hour i was filled by a "
        "catch-up spread: draw it lighter / dashed. No login needed (AllowAny)."),
    "/api/submeteringHourlyData/": (FEATURE_API, "submeteringHourlyData",
        "Hourly chart of a submetering site: per aisle 24 hourly kWh summed in one query, with estimated[24] as "
        "above. No baseline series."),
    "/api/getSiteHourlyConsumptionData/": (FEATURE_API, "getSiteHourlyConsumptionData",
        "Hourly chart of a WH-metering site (and the baseline page): per meter (Main-Supply, DG, ...) the day's "
        "hourly kWh with estimated[24]. Known issue: values are taken in stored order and padded at the end, so a "
        "missing hour shifts the later hours one place left."),
    "/api/snapshot/": (FEATURE_API, "snapshot",
        "Super-admin tiles: kWh consumed and saved and % saved over all live sites of all customers, this month by "
        "default (start_date / end_date to change it; current_date is the start used), and alarms = the number of "
        "open issues (same count as the super-admin alarm list)."),
    "/api/customerSnapShotEnergySavingApi/": (FEATURE_API, "customerSnapShotEnergySavingApi",
        "Customer page tiles: energy consumed / saved and % saved of the customer's saving sites since each site's "
        "live date up to yesterday, and alarms = open alarms of those sites."),
    "/api/siteSnapShotEnergySavingApi/": (FEATURE_API, "siteSnapShotEnergySavingApi",
        "Site page tiles: energy consumed / saved since the live date up to yesterday (previous_date), % saved, "
        "carbon saved when the site shows it, and alarms = the site's open alarms. Energy values are strings here."),
    "/api/alarmList/": (ALARM_API, "alarmList",
        "Site alarm panel summary: only alarms still happening (is_active). active_alarms = number of open alarms; "
        "total_alarm / high_priority / medium_priority = their occurrences; data = one line per alarm type "
        "(name, count, priority, alarm_type) - use alarm_type to open alarmListDetail/."),
    "/api/alarmListDetail/": (ALARM_API, "alarmListDetail",
        "Open alarms of one site and type, newest first. issue is the readable cause; created = first seen "
        "(outages: when the outage began), last_seen, occurrences; phase / fuel / run-hour values for power and DG "
        "alarms; open_days / open_for = how long it has been open."),
    "/api/alarmListDetail/ (open_days, open_for)": (ALARM_API, "alarmListDetail",
        "Same response as above: open_days (whole days) and open_for (\"2 days 5 h\", \"20.2 h\") count from created."),
    "/api/alarmTypeApi/": (ALARM_API, "alarmTypeApi",
        "Super-admin alarm list: one row per open issue of every live site (last seen within ALARM_FEED_MAX_AGE_DAYS "
        "= 30), grouped by customer. Each row: alarm name / type, priority, site, source (consumption / power / "
        "gateway / meter), aisle or power source or gateway, issue, created_time (first seen), last_seen, "
        "occurrences, open_for."),
    "/api/alarmTypeApi/ (open_days, open_for)": (ALARM_API, "alarmTypeApi",
        "Same response as above: open_days / open_for of each row, counted from the issue's first day."),
    "/api/alarmapi/": (ALARM_API, "alarmapi",
        "Open-issue counts per customer, priority and site (one list per customer, empty for customers without "
        "alarms). No screen uses it."),
    "/api/alarmListOnCustomerPage/": (ALARM_API, "alarmListOnCustomerPage",
        "Customer page table: per site of the customer (id = customer user id) the open alarms by type name, the "
        "total and the site type. Sites without open alarms are left out. result is the string \"1\" here."),
    "/api/getCustAlarmGraph/": (ALARM_API, "getCustAlarmGraph",
        "Customer page bar chart: open alarms per type over the customer's sites, as Highcharts series (one column "
        "series per type) plus alarm_name_list for the x axis."),
    "/api/alarmListOnSitePage/": (ALARM_API, "alarmListOnSitePage",
        "Open alarms of one site, newest first, short form (type, object type / name, priority, date dd-mm-yyyy). "
        "No screen uses it (the site page uses alarmList/ + alarmListDetail/)."),
    "/api/consumptionAlarms/": (ALARM_API, "consumptionAlarms",
        "Open High / Low Consumption alarms (types 7, 8) of a site, optionally created between start_date and "
        "end_date. No screen uses it."),
    "/api/gateway-status/": (ALARM_API, "gateway-status",
        "Every gateway with its site and customer. status (bool) = data in the last hour. health = \"modbus_issue\" "
        "while a Gateway Service / Modbus Issue alarm is open (pings, no meter data; shown as 'Gateway Service "
        "issue'), \"offline\" while a Gateway Disconnected alarm is open, else online / offline from status; "
        "health_since / health_detail = start and text of that alarm. Paged by limit / offset (the panel asks "
        "limit=1000). No login needed."),
    "/api/meter-disconnections/": (ALARM_API, "meter-disconnections",
        "Meter disconnect / reconnect events reported by gateways (input of Meter Disconnected), newest first; "
        "filter by site_id, meter_id, meter_number, status (connected / disconnected), from / to; paged (count, "
        "limit, offset)."),
    "/api/alarmSettings/": (ALARM_API, "alarmSettings",
        "GET ?site_id: every alarm type of the site with its setting: mode default (no setting: works as before) / "
        "auto (system thresholds) / manual (threshold in unit) / off (not raised), the e-mail groups and repeat "
        "tolerance; unit null = no manual threshold; raised false = type exists but nothing raises it. POST saves "
        "one type (validated: manual needs threshold > 0 and a type with a unit; 400 {msg} otherwise) and returns "
        "the whole list; mode default deletes the setting. Applies at the next alarm check. Super_Admin only."),
    "/api/syncStatus/": (FEATURE_API, "syncStatus",
        "Per aisle (consumption) and power source (supply time / load runtime) of the site's gateways, three cases "
        "(no gap details): HEALTHY = sync \"synced\", recovery \"not_needed\", last_sync_at = last data message; "
        "GAP FILLED = sync \"synced\", recovery \"recovered\", last_recovered_at = when the missing data was "
        "recovered; NO DATA (70 min or more) = sync \"syncing\", recovery \"not_received\", last_sync_at = last data "
        "before the gap, attempts = how many times the server asked the gateway for this aisle's missing data "
        "(current gap; 0 = not asked yet; max_attempts = 3), last_requested_at = when it last asked (null when 0). "
        "recovery \"received\" only for the moment between the gateway's answer and its rows being applied. "
        "counts = rows per sync value and per recovery value. Mapped from the stored AisleSyncRecoveryStatus "
        "state: healthy, recovered, then late / missing / recovery_requested / failed = syncing. Read-only; "
        "Super_Admin only."),
    "/api/recoveryHistory/": (FEATURE_API, "recoveryHistory",
        "The site's recovery requests (RecoveryMonitor), newest first: one row per gap asked from a gateway, with "
        "type (hourly / daily consumption, load runtime), status (requested -> response_received -> applied -> "
        "verified, or failed / timeout), the gap, hours asked / got / without data (error_slots), attempt and "
        "failed_reason. Filter by status and recovery_type; paged by limit (max 500) / offset. Raw MQTT payloads are "
        "not returned. Read-only; Super_Admin only."),
}
WRITE_EXAMPLES = {
    "/api/saveBaseline/": {"request": {"siteId": 114, "legId": "671", "baselineValue": 9.21, "date": "2026/11/13"},
                           "body": {"result": 1, "msg": "baseline value set"}},
}
# POST of alarmSettings/ writes: its example is added to the guide next to the captured GET.
ALARM_SETTINGS_POST = {
    "request": {"site_id": 114, "alarm_type": 7, "mode": "manual", "threshold": 250,
                "email_software": True, "email_ground": False},
    "body": "200: the same response as GET, with this type's row changed. "
            "400: {\"status\": 400, \"msg\": \"Manual needs a threshold above 0 (kWh / day).\"}",
}
# Things a frontend developer trips over, shown at the top of the guide.
CONVENTIONS = [
    "Base URL: /api/ on the server that serves the page (test: http://43.204.53.81/api/). Send "
    "'Authorization: Token <token from login>' and 'Content-Type: application/json'. Without a token: 401; "
    "a Super_Admin-only API with another user: 403.",
    "Success flags differ per API: \"status\": 200, \"status\": 1, \"result\": 1 and \"result\": \"1\" (a string) "
    "are all used. Check the HTTP status first; errors are 400 / 404 / 500 with msg, message or error.",
    "Dates differ per API: ISO \"2026-11-20T15:20:59\" (alarms, gateways), \"2026/11/20\" (requests, snapshots), "
    "\"20-11-2026\" (alarmListOnSitePage), \"19-Nov-2026\" (site snapshot). Request dates are YYYY/MM/DD.",
    "Numbers: the site snapshot sends energy as strings (\"541432.6\") and % with a sign (\"78.2 %\"); parse "
    "before maths.",
    "Alarm lists show only alarms still happening (is_active). Daily alarms (High / Low Consumption, Bypassed) "
    "are per day; outage alarms (Meter / Gateway Disconnected, Service / Modbus Issue) stay one row until solved.",
    "Hourly charts: estimated[24] on each series marks spread hours; it is missing on servers without it (main) - "
    "treat missing as all false.",
]


def api_samples(endpoint):
    """(request, body) for an endpoint: captured on test, else the code example, else (None, None)."""
    _, key, _ = HOW.get(endpoint, (None, None, None))
    sample = SAMPLES.get(key) if key else None
    if sample:
        return sample.get("request"), sample.get("body", sample.get("error"))
    example = WRITE_EXAMPLES.get(endpoint)
    return (example["request"], example["body"]) if example else (None, None)


def short_json(value, limit=1500):
    if value is None:
        return "-"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " ..."


def _json_block(value):
    return value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False)


def write_guide(path):
    """FRONTEND_API_GUIDE.md: every frontend API with how it works and a real response."""
    note = SAMPLES.get("_note", "No samples captured yet.")
    lines = [
        "# Frontend API guide", "",
        "For the frontend developer: every API the frontend calls (features and alarms), how it works and a real "
        "response. Generated by `docs/features/build_feature_tracker.py` (same data as the \"Frontend APIs\" sheet "
        "of `FEATURE_TRACKER.xlsx`); do not edit by hand.", "",
        f"Responses: {note} Re-capture with `docs/features/capture_frontend_api_samples.py` (read-only calls). "
        "APIs that write are shown with an example from the code.", "",
        "## Conventions", "",
    ]
    lines += [f"- {c}" for c in CONVENTIONS]
    for section in (FEATURE_API, ALARM_API):
        lines += ["", f"## {section}", ""]
        for row in A:
            endpoint = row[1]
            if endpoint not in HOW or HOW[endpoint][0] != section or "(open_days" in endpoint:
                continue
            request, body = api_samples(endpoint)
            shown = json.dumps(request, ensure_ascii=False) if request is not None else row[4]
            lines += [
                f"### `{row[2]} {endpoint}`", "",
                f"- **Features:** {row[0]} | **Auth:** {row[3]} | **Frontend:** {row[7]} - {row[6]}",
                f"- **Request:** `{shown}`",
                f"- **How it works:** {HOW[endpoint][2]}",
            ]
            if row[8] not in ("-", ""):
                lines.append(f"- **Note:** {row[8]}")
            lines += ["", "<details><summary>Response</summary>", "", "```json", _json_block(body), "```", "",
                      "</details>", ""]
            if endpoint == "/api/alarmSettings/":
                lines += [f"- **POST request:** `{json.dumps(ALARM_SETTINGS_POST['request'])}`",
                          f"- **POST response:** {ALARM_SETTINGS_POST['body']}", ""]
    others = [r for r in A if r[1] not in HOW]
    lines += ["", f"## {OTHER_API}", ""]
    lines += [f"- `{r[1]}` ({r[2]}, {r[3]}): {r[5]} - {r[8]}" for r in others]
    path.write_text("\n".join(lines) + "\n")


def write_sheet(book, title, columns, rows, status_col=None, first=False, colours=None):
    colours = colours or STATUSES
    ws = book.active if first else book.create_sheet()
    ws.title = title
    thin = Side(style="thin", color="BFBFBF")
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
        if status_col is not None and row[status_col] in colours:
            ws.cell(row=r, column=status_col + 1).fill = PatternFill("solid", fgColor=colours[row[status_col]][1])
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"


def main():
    book = Workbook()
    counts = Counter(row[3] for row in F)
    summary = [[status, counts.get(status, 0), meaning,
                ", ".join(row[0] for row in F if row[3] == status)] for status, (meaning, _) in STATUSES.items()]
    summary.append(["Total", len(F), f"Updated {UPDATED}", ""])
    write_sheet(book, "Summary", [("Status", 20), ("Count", 8), ("Meaning", 60), ("IDs", 60)], summary, status_col=0, first=True)
    order = list(STATUSES)
    # "Frontend APIs" column (after "Main server"), from the Frontend APIs sheet.
    known = {row[0] for row in F}
    for row in A:
        assert {i.strip() for i in row[0].split(",")} <= known, row[:2]
    columns = COLUMNS[:9] + [("Frontend APIs", 40)] + COLUMNS[9:]
    rows = []
    for row in sorted(F, key=lambda row: order.index(row[3])):
        apis = [f"{a[1]} ({a[7]})" for a in A if row[0] in {i.strip() for i in a[0].split(",")}]
        rows.append(row[:9] + ["; ".join(apis) or "-"] + row[9:])
    write_sheet(book, "Features", columns, rows, status_col=3)
    api_columns = API_COLUMNS + [("How it works", 70), ("Example response (test server, trimmed)", 80)]
    api_rows = [row + [HOW.get(row[1], ("", "", "-"))[2], short_json(api_samples(row[1])[1])] for row in A]
    write_sheet(book, "Frontend APIs", api_columns, api_rows, status_col=7, colours=FE_STATUSES)
    write_guide(HERE / "FRONTEND_API_GUIDE.md")
    fe_counts = Counter(row[7] for row in A)
    write_sheet(book, "Frontend API status", [("Frontend status", 16), ("APIs", 8), ("Meaning", 70)],
                [[status, fe_counts.get(status, 0), meaning] for status, (meaning, _) in FE_STATUSES.items()],
                status_col=0, colours=FE_STATUSES)
    write_sheet(book, "How to update", [("Step", 6), ("What to do", 110)], [
        [1, "Edit FEATURES in docs/features/build_feature_tracker.py (one add(...) per feature) and set UPDATED."],
        [2, "New idea / request: add a row (F = open, H = on hold, N = not started, O = out of scope, D = done) with status Planned."],
        [3, "When it moves on: change Status, Last update, Test server / Main server, Next step and Waiting on; keep the ID."],
        [4, "When it is done: status Done, link its doc and commit, and add a row to docs/CHANGELOG.md."],
        [5, "API added / changed / built in the frontend: edit A (one api(...) per endpoint, with the feature IDs) - the "
            "Features sheet's 'Frontend APIs' column is filled from it."],
        [6, "API response changed: re-capture the samples on test with docs/features/capture_frontend_api_samples.py "
            "(read-only calls; command in its docstring) and update HOW (how it works)."],
        [7, "Run: python3 docs/features/build_feature_tracker.py (writes FEATURE_TRACKER.xlsx, .csv, FRONTEND_APIS.csv "
            "and FRONTEND_API_GUIDE.md)."],
    ])
    book.save(HERE / "FEATURE_TRACKER.xlsx")
    with open(HERE / "FEATURE_TRACKER.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in columns])
        writer.writerows(rows)
    with open(HERE / "FRONTEND_APIS.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in api_columns])
        writer.writerows(api_rows)
    print(f"{len(F)} features ({', '.join(f'{s} {n}' for s, n in counts.items())}); "
          f"{len(A)} APIs ({', '.join(f'{s} {n}' for s, n in fe_counts.items())}) -> {HERE / 'FEATURE_TRACKER.xlsx'}")


if __name__ == "__main__":
    main()
