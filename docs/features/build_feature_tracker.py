"""Build the feature tracker: FEATURE_TRACKER.xlsx and .csv (every feature: done, in progress, waiting, planned).

    python3 docs/features/build_feature_tracker.py

Edit FEATURES below whenever a feature is planned, started, changed, finished, put on hold or dropped, then
re-run this script. Keep the IDs stable (never reuse one); add new rows at the end of their group.
"""

import csv
import pathlib
from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = pathlib.Path(__file__).resolve().parent
UPDATED = "2026-11-19"

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
    "Site page: Spread catch-up button and Spread... on Consumption Spike rows; preview, tick aisles, apply, undo "
    "(inline confirmations). First real spread 17 Nov: site 114 F1-Outward&Hub area, 43.60 kWh over 38 h, total energy unchanged, "
    "spike alarm closed (proof: .work/spread_114_20261117/).",
    "2026-11-16", "2026-11-17", "Used on test 17 Nov (site 114 hours 9-15 Nov copied from main first); 19 more site-114 catch-ups spreadable",
    T, "Push the frontend commit; spread the other 19 when wanted.", "User", "docs/consumption/CATCH_UP_SPREAD.md", "1244b7c9 + frontend")
add("F03", "Baseline setup screen", "Frontend", "Done",
    "Baseline page: Automatic baseline -> sample days -> Calculate (preview, changes nothing) -> edit per aisle -> "
    "Set baseline (inline confirmation). Errors block it; warnings shown; site total follows edits.",
    "2026-11-05", "2026-11-17", "API deployed 5 Nov; screen checked 17 Nov on site 114 (preview, cancelled; nothing set)", T,
    "Push the frontend commit; set a real baseline when a site needs one.", "-",
    "docs/consumption/BASELINE_SETUP_FRONTEND.md", "4bd8744e + frontend")
add("F04", "Estimated hours on the hourly chart", "API / frontend", "Planned",
    "Hourly API returns HourlySiteReading.is_estimated so charts can show spread hours differently (e.g. hatched).",
    "2026-11-16", "2026-11-16", "-", T,
    "Needs approval first: API views are out of scope for this branch.", "User",
    "docs/consumption/CATCH_UP_SPREAD.md", "-")
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
add("F10", "Merge with the colleague's code", "Merge", "Waiting for input",
    "Team lead: merge this branch with the colleague's optimized version of main's code. Prepared 19 Nov: tag "
    "fov2-pre-merge-20261119, code inventory (every feature, alarm, API, model, migration and function with a fingerprint), "
    "function-level overlap check. Main's server = legacy origin/main + our DG fuel / LoadData branches + a few hotfixes "
    "(user type 6, monitoringCustomerSites/ API, Redis CACHES, admin pages, AisleGroup DG fuel fields); migrations "
    "0073-0076 diverged. The colleague's code is not on origin/main yet.",
    "2026-11-19", "2026-11-19", "-", "-",
    "Colleague pushes his code (to main or a branch); run overlap_check.py on it; merge on an integration branch.",
    "Colleague: his code (repo / branch); team lead: who merges",
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
add("O02", "Automatic catch-up spreading", "Consumption", "Out of scope",
    "Catch-ups are spread only when someone triggers it from the frontend (F02), never automatically.", "2026-10-28",
    "2026-11-16", "-", "-", "-", "-", "docs/consumption/CATCH_UP_SPREAD.md", "-")

# ---- Done -------------------------------------------------------------------------------------------
add("D27", "Code inventory and merge check", "Docs / merge", "Done",
    "docs/merge/CODE_INVENTORY.xlsx: features, alarms, APIs (new / changed / same), Celery tasks, commands, DB models and "
    "fields, migrations, modules, every function (what it does, origin, tests, fingerprint), tests, why it is better than "
    "the legacy code, overlap with main's code, removed files. scripts/merge/overlap_check.py compares any two code bases "
    "function by function.",
    "2026-11-19", "2026-11-19", "-", "-", "Re-run on the colleague's code before the merge.", "-",
    "docs/merge/MERGE_GUIDE.md", "-")
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
    "POST /api/catchUpSpread/ (Super_Admin): preview / apply / undo; spread hours marked is_estimated; days recomputed; "
    "spike alarm closed; CatchUpSpread log.", "2026-11-16", "2026-11-16", "Deployed 16 Nov (migration 0114)", T, "Frontend: F02", "-",
    "docs/consumption/CATCH_UP_SPREAD.md", "1244b7c9")
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
    "Meter jump / meter reset / catch-up hours with their cause, one e-mail per site per scan.", "2026-10-30", "2026-11-02",
    "Deployed 30 Oct", T, "-", "-", "docs/alarms/ALARM_CATALOGUE.xlsx (type 17)", "a323f5d6, 6c2cd379")
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


def write_sheet(book, title, columns, rows, status_col=None, first=False):
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
        if status_col is not None and row[status_col] in STATUSES:
            ws.cell(row=r, column=status_col + 1).fill = PatternFill("solid", fgColor=STATUSES[row[status_col]][1])
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
    rows = sorted(F, key=lambda row: order.index(row[3]))
    write_sheet(book, "Features", COLUMNS, rows, status_col=3)
    write_sheet(book, "How to update", [("Step", 6), ("What to do", 110)], [
        [1, "Edit FEATURES in docs/features/build_feature_tracker.py (one add(...) per feature) and set UPDATED."],
        [2, "New idea / request: add a row (F = open, H = on hold, N = not started, O = out of scope, D = done) with status Planned."],
        [3, "When it moves on: change Status, Last update, Test server / Main server, Next step and Waiting on; keep the ID."],
        [4, "When it is done: status Done, link its doc and commit, and add a row to docs/CHANGELOG.md."],
        [5, "Run: python3 docs/features/build_feature_tracker.py (writes FEATURE_TRACKER.xlsx and .csv)."],
    ])
    book.save(HERE / "FEATURE_TRACKER.xlsx")
    with open(HERE / "FEATURE_TRACKER.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in COLUMNS])
        writer.writerows(rows)
    print(f"{len(F)} features ({', '.join(f'{s} {n}' for s, n in counts.items())}) -> {HERE / 'FEATURE_TRACKER.xlsx'}")


if __name__ == "__main__":
    main()
