"""Build the code inventory: CODE_INVENTORY.xlsx, everything this branch has and how it compares with the legacy code.

    virtualwarehouse/bin/python docs/merge/build_code_inventory.py

Sheets: Summary, Why ours is better, Features, Alarms, APIs, Celery tasks, Management commands, DB models,
Migrations, Modules, Functions, Tests, Merge overlap (main), Ours vs colleague, Merge overlap (colleague),
Colleague vs main (APIs), Colleague vs main (functions), Removed files.

Most sheets are read from the code itself (ast), so re-running the script after a change keeps them current.
Hand-written parts: WHY_BETTER and MODULE_NOTES below, and the features / alarms, which come from
docs/features/build_feature_tracker.py and docs/alarms/build_alarm_catalogue.py.

"Legacy" = origin/main (the code before this branch). The Merge overlap sheet is read from
overlap_main_server_*.csv (made by scripts/merge/overlap_check.py against a copy of main's code).
Each function's "Fingerprint" is the hash of its normalized source (same as overlap_check.py): after the merge,
a different fingerprint means the function changed.
"""

import ast
import csv
import importlib.util
import pathlib
import re
import subprocess
import sys
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "merge"))
import overlap_check as oc  # noqa: E402

UPDATED = "2026-11-19"
LEGACY_REF = "origin/main"
TAG = "fov2-pre-merge-20261119"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


# ---- hand-written: why this branch is better (evidence from the docs and measurements) --------------------
# (Area, Legacy code, This branch, Evidence / measurement, Doc)
WHY_BETTER = [
    ("Code structure", "One wareApp/views.py of {legacy_views} lines with every API, and tasks.py of {legacy_tasks} lines "
     "with every MQTT handler inline; many duplicate class definitions (a later one silently replaces an earlier one).",
     "Views split by area into wareApp/views/ ({view_modules} modules); MQTT handling in wareApp/mqtt/ (one module per message "
     "type) and wareApp/mqtt/services/ (alarms, health checks, notifications, idempotency, caching).",
     "Modules sheet: {modules} live modules, {functions} functions / classes listed with what they do.", "docs/mqtt-flows/README.md"),
    ("Tests", "No automated tests ({legacy_tests} test functions).",
     "{tests} backend tests in {test_modules} modules (MQTT handlers, alarms, APIs, DB query counts); frontend 51 specs.",
     "Full suite 520 OK on 17 Nov; query counts pinned with assertNumQueries, so N+1 regressions fail a test.", "Tests sheet"),
    ("MQTT queues", "One listener handled every message type, including high-rate LoadData, so a LoadData burst delayed "
     "consumption and alarms.",
     "Queue 1 (business telemetry) and queue 2 (LoadData only) with narrow broker subscriptions; listener callbacks do no "
     "database work, the processing workers do; stale DB connections closed before / after each task.",
     "Deployed to main 14 Oct (release main-load-dg-fuel-repair-20261014) and running since.",
     "docs/load-data/MQTT_LOAD_DATA_OPTIMIZATION_COMPLETE.md"),
    ("Hourly reading lookup", "Hourly existence check / update on every packet: ~17.12 M calls at ~295 ms mean and ~12.55 M "
     "updates at ~253 ms (main, pg_stat_statements).",
     "Composite index (site, leg, reading_from) + half-open hour range; the planner uses an Index Only Scan.",
     "Index Only Scan, cost 8.46 (test) / 8.58 (main).", "docs/operations/MAIN_SERVER_BEFORE_AFTER_MIGRATION.md"),
    ("Consumption writes", "One Celery task and several queries per consumption packet.",
     "Packets collected and written in bulk every 60 s (MQTT_CONSUMPTION_BATCH_SECONDS), same reading rules as one-by-one.",
     "wareApp/mqtt/consumption_batch.py; tests test_consumption_batch*.", "docs/mqtt-flows/README.md"),
    ("Database load", "Sequential scans on the big tables; 4 redundant single-column indexes (~480 MB); a foreign-key "
     "lookup and row lock on Site / AisleGroup for every telemetry insert.",
     "Every read on the big tables uses an index; redundant indexes dropped; no DB-level FKs on the 5 telemetry tables "
     "(Django still cascades).",
     "3 min of live traffic on test: zero sequential scans on big tables; FK lookups ~860 -> 8; alarm closer probe 198 ms -> "
     "0.085 ms; index space 6,373 MB -> 6,160 MB.", "docs/operations/DB_OPTIMIZATION_2026-11-06.md"),
    ("Duplicate / replayed packets", "A packet resent by the gateway or the broker was processed twice (double counts).",
     "Idempotency keys: a packet already processed is skipped; failed packets go to a dead-letter store and can be replayed "
     "(manage.py replay_dead_letters).", "wareApp/mqtt/services/idempotency.py, failures.py; tests test_idempotency*.",
     "docs/mqtt-flows/README.md"),
    ("Alarms: coverage", "Power / consumption alarms only; no gateway or meter outage alarm (a gateway could be off for days "
     "with no e-mail: site 185 since 6 Nov, site 187 for 82 h).",
     "18 alarm types incl. Meter Disconnected (14), Gateway Disconnected (15), Service / Modbus Issue (16), Consumption "
     "Spike (17); merged sites (virtual aisle groups) covered.", "Alarms sheet; 17 Nov: site 185 gateway alarm raised under "
     "site 183 and e-mailed.", "docs/alarms/ALARM_CATALOGUE.xlsx, docs/alarms/MERGED_SITES.md"),
    ("Alarms: noise", "Every occurrence could e-mail again; Meter Reading Issue closed after 1 h and reopened (14 of 17 "
     "came back within 24 h, each a new e-mail).",
     "One alarm per issue with occurrence count; repeat e-mailed only when > 5 % worse; per-site AlarmSetting Auto / Manual / "
     "Off; Meter Reading Issue fixed only after 24 h; 10-min reconnect grace (no false Service Issue).",
     "wareApp/mqtt/services/alarm_policy.py, alarm_closer.py, gateway_health.py; 2 false alarms on site 130 found and fixed.",
     "docs/alarms/ALARM_CATALOGUE.xlsx"),
    ("Alarm e-mails", "Sent inside the MQTT handler; a mail-server failure lost the e-mail (Gmail refused the login 6 Nov).",
     "Sent from the notifications queue; failures kept in PendingEmail and retried with back-off (5 min ... 8 h) for 24 h.",
     "8 e-mails lost before retries existed; none since.", "docs/mqtt-flows/EMAIL_RETRIES.md"),
    ("Alarm counts in the APIs", "Customer / site page alarm APIs read user_level=4 rows that nothing writes: always 0 / empty.",
     "They count open alarms (is_active); alarmList active_alarms = number of open alarms.",
     "Found in the end-to-end check with the frontend (6 and 17 Nov).", "docs/alarms/ALARM_CATALOGUE.xlsx (Frontend APIs)"),
    ("Reading quality", "A meter glitch (e.g. 2.08 x 10^24 kWh) was stored as consumption; spike hours counted twice.",
     "10,000 kWh glitch limit on saving / submetering sites on every write path; spike hours left out of the day total; "
     "High Consumption / Bypassed verified from hourly rows.", "Reading rules 1 and 2.", "docs/consumption/READING_RULES.md"),
    ("Catch-up hours", "After a data gap the gateway sends the gap's energy in one hour: a fake spike, fixed by hand with "
     "ad-hoc scripts on the server (spike_distribution.py, NewSpikeDistribution.py ...).",
     "POST /api/catchUpSpread/: preview, spread evenly over the missing hours, undo; total energy unchanged; frontend screen.",
     "17 Nov site 114: 43.60 kWh over 38 h, total 82.573 kWh unchanged, spike alarm closed.", "docs/consumption/CATCH_UP_SPREAD.md"),
    ("Baseline setup", "Several manual steps and scripts per site (UpdateBaselineOnly_*.py, ZeroEntryCreate*.py); "
     "saveBaseline/ crashed on an aisle without data.",
     "POST /api/baselineSetup/: preview per-aisle averages, overrides, then one all-or-nothing apply (baselines, aisles "
     "active, site live, backfill of daily + hourly values); frontend screen.", "Checked on site 114 (preview).",
     "docs/consumption/BASELINE_SETUP.md"),
    ("DG fuel", "Provider data stored as received; duplicates and malformed timestamps.",
     "Normalized ingestion: validated timestamps / values, dedupe and uniqueness constraints, multi-unit sessions, "
     "provider credentials from .env.", "Deployed to main Oct; malformed rows skipped with a reason.",
     "docs/dg-fuel/DG_FUEL_ARCHITECTURE.md"),
    ("Configuration and secrets", "Settings partly hard-coded in warehouse/settings.py and in backup copies of it.",
     "Settings from warehouse/.env (python-decouple), template warehouse/.env.example; scripts read credentials from "
     "settings, never print them.", "settings_bck.py and other backup copies removed (Removed files sheet).",
     "warehouse/.env.example"),
    ("Logging", "print() and unstructured log lines.",
     "One log format with site / gateway / message context (wareApp/mqtt/log_format.py, log_context.py); log rotation.",
     "deploy/logrotate", "docs/operations/TEST_SERVER_OPERATIONS.md"),
    ("Dead code", "{removed} files kept in the repo: backup copies (views12_26.py, tasks.py_bck ...), one-off scripts.",
     "Removed ({deleted_lines} lines); history stays in git.", "Removed files sheet.", "-"),
]

# Side by side with the colleague's code (github.com/Daksh007-batman/New-asem-merger, main = Ashutosh = 54313d5,
# 18 Nov 2026), read only on 19 Nov; his code was not run. (Area, Ours, Colleague, Merge decision)
COLLEAGUE_COMPARISON = [
    ["History / base", "Branch of origin/main (legacy, Dec 2025); 178 commits, each change documented in docs/CHANGELOG.md.",
     "Separate repo, no shared git history: 3 commits (24 Jul 'first commit' + 'optimized backend code' 159k lines; 18 Nov "
     "'feat: complete alarm analysis flow, monitoring dashboard APIs, and notification policy' 82 files).",
     "Git cannot merge them: one code base must be the base and the other's features are ported into it."],
    ["Deployed / verified", "Running on the test server with live gateway data; parts on main since Oct (MQTT queues, LoadData, DG fuel).",
     "Not deployed anywhere we know of; not run here (read-only check).", "Base = the deployed one (ours)."],
    ["Code structure", "wareApp/models.py (one module), wareApp/views/ 18 area modules, wareApp/mqtt/ + mqtt/services/, tasks.py.",
     "wareApp/models/ package (8 modules), wareApp/views/ 7 *_views.py, wareApp/services/, wareApp/tasks/ package, "
     "constants.py with typed Enums, separate mqtt_pipeline/ project.",
     "models/ package and models.py cannot both exist (the package wins, models.py is ignored); same for tasks/ vs "
     "tasks.py. Keep one layout."],
    ["Migrations", "Legacy 0001-0072 + ours up to 0114 (main's DB has 0001-0076: reconciliation planned).",
     "0001_initial same as main, then his own 0002-0032 (different files, same tables).",
     "Two lineages from 0001 = Django 'conflicting migrations'; his 0002-0032 cannot run on main's DB. Port his model "
     "changes as new migrations after ours."],
    ["APIs", "110 routes; new: baselineSetup/, catchUpSpread/, gateway-status/, v1/recovery/, temp/dispatch/mail/; "
     "alarm counts fixed (customer / site pages).",
     "111 routes; new: dashboard/alarms/summary/, live/, acknowledge/, daily-digest/, tokens/. 10 views are placeholders "
     "that return a fixed message (all Excel downloads, e.g. downloadExcelLoadData/, dgFuelDataExcelExport/); 60 views are "
     "less than half the size of ours (simplified); CustomerSnapshotApi returns alarms: 0 (fixed).",
     "Keep our views; port his 4 dashboard alarm APIs + tokens/; do not take his placeholder / simplified views."],
    ["Alarms", "One table (AlarmNotifications), 18 types incl. Meter Disconnected 14, Gateway Disconnected 15, Service / "
     "Modbus Issue 16, Consumption Spike 17; merged sites; auto-close; Auto / Manual / Off per site; 24 h reminders.",
     "Two tables: NewAlarmsNotifications (0-6: voltage, PF, DG overtime, fuel under level, mains higher consumption, fuel "
     "drain) + legacy AlarmNotifications (0-9). Acknowledge, daily digest, live feed. No gateway / meter outage or spike alarms.",
     "Keep our one table; port acknowledge + digest + live feed onto it; port Fuel Drain and Mains Higher Consumption rules "
     "(ours: type 5 not started)."],
    ["Notifications", "notifications queue; PendingEmail retries with back-off 24 h; repeat only when > 5 % worse; per-site "
     "recipients and software / ground team switches.",
     "Notification policy: e-mail immediately only for HIGH priority (DEFAULT_MIN_EMAIL_PRIORITY), 6 h cooldown per site + "
     "type, others in a daily digest.", "Port the priority threshold and the digest as settings on top of our rules."],
    ["MQTT pipeline", "Two listeners (queue 1 business, queue 2 LoadData), processing workers, 60 s consumption batch, "
     "idempotency, dead letters, recovery status; in production since Oct (part).",
     "Standalone bridge MQTT -> Redis list -> dispatcher every 2 s -> 6 queues (consumption, load params, LoadData, fire, "
     "supply time, recovery); handlers rewritten in mqtt_pipeline/handlers.",
     "Same goal, two designs. Keep ours (tested, deployed); his Redis buffer idea can be evaluated later as a separate change."],
    ["Caching", "Django cache for cooldowns / site config / alarm policy (default backend).",
     "Redis (django-redis) used across the pipeline and alarms.", "Port Redis CACHES setting (also on main's server)."],
    ["Database", "Indexes from measured queries, 4 redundant indexes dropped, no FKs on telemetry tables, bulk writes; "
     "measured on test.", "Indexes listed in ARCHITECTURE.md; bulk_create used in places.", "Keep ours; compare his indexes."],
    ["Tests", "514 test functions in 45 modules, query counts pinned.", "44 test functions (test_alarms 34, test_models 5, "
     "test_services 5); not run here.", "Port his alarm tests with the features."],
    ["Deployment", "systemd units, logrotate, rollout docs per server.", "Dockerfile, docker-compose, nginx.conf, start scripts.",
     "Docker files can be added as-is later (no conflict)."],
    ["Security", "Settings and provider credentials from .env (python-decouple); DEBUG off by default when ENV is PROD; "
     "ALLOWED_HOSTS / CORS from .env, but their defaults are open too (* / allow all) - same gap as his.",
     "Live provider credentials written in ARCHITECTURE.md and in settings.py / fetch_fuel*.py / loconav.py / "
     "reset_password.py (GitHub repo); DEBUG = True for PROD too; ALLOWED_HOSTS * and CORS allow all hard-coded; 72 .pyc "
     "files committed.",
     "Do not merge any of these; the exposed credentials should be rotated (F09)."],
]

# Modules without a docstring: what they are for.
MODULE_NOTES = {
    "wareApp/admin.py": "Django admin registrations for every model (lists, filters, search).",
    "wareApp/apps.py": "Django app config for wareApp.",
    "wareApp/fuel_providers.py": "DG fuel provider clients (Roadcast, Loconav): auth headers and pull parameters from settings.",
    "wareApp/load_data/__init__.py": "LoadData package (queue 2): parse, store raw, roll up to hourly / daily / monthly.",
    "wareApp/load_data/handler.py": "Entry point for one LoadData MQTT message: validate, store raw, update rollups.",
    "wareApp/load_data/monthly.py": "Monthly min / max load per aisle, updated from new LoadData readings.",
    "wareApp/load_data/parser.py": "Parses a LoadData payload into LoadReading values.",
    "wareApp/load_data/raw.py": "Saves one raw LoadData reading (RawLoadData).",
    "wareApp/load_data/rollups.py": "Hourly and daily min / max rollups of LoadData, run when a bucket is complete.",
    "wareApp/management/commands/simulate_mqtt_gateway_traffic.py": "manage.py command: sends simulated gateway MQTT traffic for tests.",
    "wareApp/management/commands/simulate_mqtt_queue_routing.py": "manage.py command: checks which queue each topic is routed to.",
    "wareApp/models.py": "All database models (sites, aisles, readings, alarms, DG fuel, baselines, catch-up spreads ...).",
    "wareApp/mqtt/consumers.py": "The two MQTT listeners (queue 1 and queue 2): subscribe and hand each message to a processing task.",
    "wareApp/mqtt/consumption.py": "Consumption packets: parse, apply reading rules (glitch cap, spikes), store hourly / daily, raise consumption alarms.",
    "wareApp/mqtt/daily_consumption_recovery.py": "Recovery messages with past daily consumption sent by the gateway after a gap.",
    "wareApp/mqtt/fire_alarm.py": "FIREALARM messages: store the fire pump state and raise / clear the fire alarm.",
    "wareApp/mqtt/hourly_consumption_recovery.py": "Recovery messages with past hourly consumption sent after a gap.",
    "wareApp/mqtt/load.py": "Load packets: phase voltages, current, power factor; High / Low Voltage and power-factor alarms.",
    "wareApp/mqtt/load_runtime_recovery.py": "Recovery messages with past load runtime.",
    "wareApp/mqtt/log_context.py": "Adds site / gateway context to log lines.",
    "wareApp/mqtt/remote_access.py": "Publishes a start / stop / restart remote-access command to a gateway (not called by any API yet).",
    "wareApp/mqtt/routing.py": "Which message types go to queue 1 / queue 2, and the broker subscriptions of each.",
    "wareApp/mqtt/supply_time.py": "SupplyTime messages: mains / DG supply time per site.",
    "wareApp/mqtt/topics.py": "Parses and validates a gateway topic (/Acclivate/iOmniControl/<site>/<gateway>/in/...).",
    "wareApp/recovery/__init__.py": "HTTP recovery package (gateway uploads of missed data).",
    "wareApp/recovery/service.py": "RecoveryService: stores uploaded recovery data in the reading tables.",
    "wareApp/recovery/urls.py": "URL routes of the HTTP recovery API.",
    "wareApp/recovery/views.py": "HTTP recovery API views (upload, status).",
    "wareApp/routers.py": "Database router for the secondary (fuel) database; kept inert on purpose.",
    "wareApp/sendmail.py": "Alarm and report e-mail builders and senders.",
    "wareApp/serializers.py": "DRF serializers used by the APIs.",
    "wareApp/tasks.py": "Celery app tasks: MQTT listeners, processing tasks per message type, scheduled checks (beat).",
    "wareApp/urls.py": "API URL routes (mounted under /api/).",
    "wareApp/utility.py": "Small shared helpers (entry / exit logging decorator).",
    "warehouse/__init__.py": "Loads the Celery app when Django starts.",
    "warehouse/test_settings.py": "Settings for the test run.",
}

# Key entry points without a docstring (qualname: text).
FUNCTION_NOTES = {
    "mqtt_client1": "Celery task on queue1: runs the queue-1 MQTT listener (all business message types except LoadData); "
                    "retried with back-off if it exits.",
    "mqtt_client2": "Celery task on queue2: runs the queue-2 MQTT listener (LoadData only); retried with back-off if it exits.",
    "start_queue_one_mqtt_client": "When the queue-1 worker is ready, starts mqtt_client1 once (not if already running).",
    "start_queue_two_mqtt_client": "When the queue-2 worker is ready, starts mqtt_client2 once (not if already running).",
    "_run_handler": "Runs one message handler for a queued packet: resolves the site (cached), logs and skips unknown sites.",
    "process_load_data_message": "Celery task on queue2_processing: stores one LoadData packet (raw row + rollups).",
    "run_mqtt_client1": "Connects the queue-1 listener, subscribes to the queue-1 topics, hands each packet to a processing task.",
    "run_mqtt_client2": "Connects the queue-2 listener, subscribes to LoadData only, hands each packet to a processing task.",
    "evaluate_gateways": "Gateway check (every 5 min): per monitored site / gateway decides Disconnected (15), Service / Modbus "
                         "Issue (16) or OK from last data and pings; raises, reminds or clears the alarms (merged sites incl.).",
    "evaluate_meters": "Meter check: raises / clears Meter Disconnected (14) from the gateways' meter disconnection events.",
    "_record": "Stores (or repeats) one consumption alarm for an aisle and day under the aisle's display site, with the "
               "repeat / e-mail rule (> 5 % worse), and e-mails it.",
    "meter_issue_on": "True when the aisle had a Meter Reading Issue alarm on that day.",
    "setting": "The site's AlarmSetting for an alarm type (cached, cache cleared when a setting is saved), or None.",
    "is_off": "True when the alarm type is switched Off for the site.",
}

# ---- workbook helpers ------------------------------------------------------------------------------------
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
THIN = Side(style="thin", color="BFBFBF")
RISK_FILL = {"HIGH": "F8CBAD", "MEDIUM": "FFEB9C", "LOW": "E2EFDA"}
ORIGIN_FILL = {"New": "C6EFCE", "Changed": "FFEB9C", "Moved, unchanged": "DDEBF7", "Unchanged": "EDEDED"}


def sheet(book, title, columns, rows, first=False, fill_col=None, fills=None, freeze="B2"):
    ws = book.active if first else book.create_sheet()
    ws.title = title
    for c, (name, width) in enumerate(columns, 1):
        cell = ws.cell(1, c, name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(c)].width = width
    for r, row in enumerate(rows, 2):
        for c, value in enumerate(row, 1):
            cell = ws.cell(r, c, value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
        if fill_col is not None and fills and row[fill_col] in fills:
            ws.cell(r, fill_col + 1).fill = PatternFill("solid", fgColor=fills[row[fill_col]])
    ws.freeze_panes = freeze
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
    return ws


# ---- reading the code ------------------------------------------------------------------------------------
def changed_files():
    out = {}
    for line in git("diff", "--name-status", f"{LEGACY_REF}...HEAD").splitlines():
        parts = line.split("\t")
        out[parts[-1]] = parts[0][0]
    return out


def parse(path):
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, FileNotFoundError):
        return None


def first_sentence(text, limit=400):
    text = " ".join((text or "").split("\n\n")[0].split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def comment_above(lines, lineno):
    out = []
    i = lineno - 2
    while i >= 0 and lines[i].strip().startswith(("#", "@")):
        if lines[i].strip().startswith("#"):
            out.insert(0, lines[i].strip().lstrip("#").strip())
        i -= 1
    return " ".join(out)


def words(name):
    name = name.strip("_")
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ")
    return name.lower()


def defs(tree):
    """[(qualname, node, class_node_or_None)] for every function / class, nested ones qualified."""
    out = []

    def visit(body, prefix, cls):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((prefix + n.name, n, cls))
            elif isinstance(n, ast.ClassDef):
                out.append((prefix + n.name, n, cls))
                visit(n.body, prefix + n.name + ".", n)

    visit(tree.body, "", None)
    return out


def legacy_index(root):
    idx = defaultdict(set)
    for rel, f in oc.live_files(root):
        t = parse(f)
        if t is None:
            continue
        for q, n, _ in defs(t):
            idx[q].add((rel, oc.h(ast.unparse(n))))
    return idx


def url_routes(tree):
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("path", "re_path", "url")
                and n.args and isinstance(n.args[0], ast.Constant) and len(n.args) > 1):
            view = ast.unparse(n.args[1])
            name = re.sub(r"^views\.|\.as_view\(.*\)$", "", view)
            name = re.sub(r"\.as_view\(.*\)$", "", name)
            yield n.args[0].value, name, view, n.lineno


VIEW_BASES = ("APIView", "GenericAPIView", "ViewSet", "ModelViewSet", "View", "ListAPIView", "CreateAPIView",
              "RetrieveAPIView", "ListCreateAPIView")
HTTP = ("get", "post", "put", "patch", "delete")


def describe(qual, node, cls, lines, routes_by_view, models, rel):
    """(description, source)."""
    doc = ast.get_docstring(node) if not isinstance(node, ast.Module) else None
    if doc:
        return first_sentence(doc), "docstring"
    above = comment_above(lines, node.lineno)
    if above:
        return first_sentence(above), "comment"
    name = qual.split(".")[-1]
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(b) for b in node.bases]
        if any(b.split(".")[-1] in VIEW_BASES for b in bases):
            methods = [m.name.upper() for m in node.body if isinstance(m, ast.FunctionDef) and m.name in HTTP]
            r = routes_by_view.get(node.name, [])
            where = ", ".join(f"/api/{x}" for x in r) or "no route"
            return f"API view: {'/'.join(methods) or '-'} {where}.", "derived (route)"
        if any("Model" in b for b in bases) and "models.py" in rel:
            return f"Database model {node.name} (table wareApp_{node.name.lower()}).", "derived (model)"
        if any("Serializer" in b for b in bases):
            return f"DRF serializer: {words(name)}.", "derived (base class)"
        if any("ModelAdmin" in b or "admin." in b for b in bases):
            return f"Django admin page: {words(name)}.", "derived (base class)"
        if name == "Command":
            helptext = next((ast.literal_eval(s.value) for s in node.body if isinstance(s, ast.Assign)
                             and getattr(s.targets[0], "id", "") == "help" and isinstance(s.value, ast.Constant)), "")
            return f"manage.py {pathlib.Path(rel).stem}: {first_sentence(helptext) or 'management command'}.", "help text"
        if name == "Meta":
            return "Model / serializer options (table, ordering, indexes, fields).", "derived (Meta)"
        return f"Class: {words(name)} ({', '.join(bases) or 'object'}).", "derived (name)"
    if cls is not None and name in HTTP:
        r = routes_by_view.get(cls.name, [])
        where = ", ".join(f"/api/{x}" for x in r) or cls.name
        return f"Handles {name.upper()} {where}.", "derived (route)"
    if qual in FUNCTION_NOTES:
        return FUNCTION_NOTES[qual], "hand-written"
    body = ast.unparse(node)
    used = sorted({m for m in models if re.search(rf"\b{m}\.objects\b", body)})
    deco = [ast.unparse(d) for d in node.decorator_list]
    args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    calls = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = ast.unparse(n.func).split(".")[-1]
            if fn in PROJECT_FUNCS and fn != name and fn not in calls:
                calls.append(fn)
    reads = sorted(set(re.findall(r"settings\.([A-Z][A-Z0-9_]+)", body)
                       + re.findall(r"getattr\(settings, '([A-Z][A-Z0-9_]+)'", body)))
    stmts = [s for s in node.body if not isinstance(s, ast.Expr) or not isinstance(s.value, ast.Constant)]
    parts = []
    if any("task" in d for d in deco):
        q = re.search(r"queue=['\"]([\w-]+)", " ".join(deco))
        parts.append(f"Celery task{' on ' + q.group(1) if q else ''}")
    if any("receiver" in d or ".connect" in d for d in deco):
        parts.append("signal handler (" + ", ".join(deco)[:80] + ")")
    if name == "handle" and cls is not None and cls.name == "Command":
        parts.append("runs the management command")
    parts.append(f"{words(name).capitalize()} ({', '.join(args) or 'no arguments'})")
    if len(stmts) == 1 and isinstance(stmts[0], ast.Return) and stmts[0].value is not None:
        parts.append("returns " + ast.unparse(stmts[0].value)[:140])
    if calls:
        parts.append("calls " + ", ".join(calls[:6]) + (" ..." if len(calls) > 6 else ""))
    if used:
        parts.append("uses " + ", ".join(used[:6]) + (" ..." if len(used) > 6 else ""))
    if reads:
        parts.append("settings " + ", ".join(reads[:5]))
    return "; ".join(parts) + ".", "derived from code"


def tests_index():
    idx = {}
    for f in sorted((ROOT / "wareApp" / "tests").glob("test_*.py")):
        idx[f.name] = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", f.read_text(errors="replace")))
    return idx


PROJECT_FUNCS = set()
COMMON = {"get", "post", "put", "delete", "patch", "save", "handle", "__init__", "__str__", "Meta", "setUp", "main",
          "run", "parse", "process", "close", "send", "notify", "record", "flush", "clean", "update", "create"}


def tests_for(qual, idx):
    names = [p for p in qual.split(".") if p not in COMMON and len(p) >= 5]
    if not names:
        return ""
    key = names[-1]
    return ", ".join(t for t, ids in idx.items() if key in ids)[:300]


def main():
    status = changed_files()
    legacy_root = oc.tree(LEGACY_REF)
    legacy = legacy_index(legacy_root)
    tidx = tests_index()

    # models (for "uses ..." descriptions)
    models_tree = parse(ROOT / "wareApp" / "models.py")
    model_names = [n.name for n in models_tree.body if isinstance(n, ast.ClassDef)]

    # routes
    url_tree = parse(ROOT / "wareApp" / "urls.py")
    routes = list(url_routes(url_tree))
    routes_by_view = defaultdict(list)
    for r, name, _, _ in routes:
        routes_by_view[name.split(".")[-1]].append(r)

    # ---- modules and functions ----
    py = sorted(p for p, s in status.items() if s in "AM" and p.endswith(".py")
                and "/migrations/" not in p and "/tests/" not in p and not p.startswith("unit_tests/")
                and not p.startswith("docs/"))
    module_rows, func_rows = [], []
    view_classes = {}
    origin_count = Counter()
    for rel in py:
        t = parse(ROOT / rel)
        if t is not None:
            PROJECT_FUNCS.update(n.name for n in ast.walk(t) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    PROJECT_FUNCS.difference_update(COMMON)
    for rel in py:
        f = ROOT / rel
        t = parse(f)
        if t is None:
            continue
        lines = f.read_text(errors="replace").splitlines()
        area = "/".join(rel.split("/")[:2]) if rel.count("/") >= 2 else rel.split("/")[0]
        mstatus = "New" if status[rel] == "A" else "Changed"
        if rel.startswith("wareApp/views/"):
            mstatus = "New (split from legacy views.py)"
        purpose = first_sentence(ast.get_docstring(t)) or MODULE_NOTES.get(rel, "")
        items = defs(t)
        module_rows.append([rel, area, mstatus, len(lines), len(items), purpose])
        for qual, node, cls in items:
            src = ast.unparse(node)
            fp = oc.h(src)
            if isinstance(node, ast.ClassDef):
                kind = "class"
                if any(ast.unparse(b).split(".")[-1] in VIEW_BASES for b in node.bases):
                    kind = "API view"
                    view_classes[node.name] = (rel, node)
            elif any("task" in ast.unparse(d) for d in node.decorator_list):
                kind = "Celery task"
            else:
                kind = "method" if cls is not None else "function"
            leg = legacy.get(qual, set())
            if not leg:
                origin = "New"
            elif any(h == fp for _, h in leg):
                origin = "Unchanged" if any(p == rel and h == fp for p, h in leg) else "Moved, unchanged"
            else:
                origin = "Changed"
            origin_count[origin] += 1
            desc, src_kind = describe(qual, node, cls, lines, routes_by_view, model_names, rel)
            legacy_file = ", ".join(sorted({p for p, _ in leg}))
            n_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            func_rows.append([rel, qual, kind, node.lineno, n_lines, origin, legacy_file, desc, src_kind,
                              tests_for(qual, tidx), fp])

    # ---- APIs ----
    legacy_url_tree = parse(legacy_root / "wareApp" / "urls.py")
    legacy_routes = {r: name for r, name, _, _ in url_routes(legacy_url_tree)}
    api_rows = []
    for r, name, view, line in routes:
        cname = name.split(".")[-1]
        rel, node = view_classes.get(cname, ("", None))
        if node is None:  # view defined in a file this branch did not change
            for f in (ROOT / "wareApp").rglob("*.py"):
                if "migrations" in f.parts or "tests" in f.parts:
                    continue
                tt = parse(f)
                if tt is None:
                    continue
                found = [n for n in tt.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == cname]
                if found:
                    rel, node = f.relative_to(ROOT).as_posix(), found[-1]
                    break
        methods, perms, desc = "-", "-", ""
        if isinstance(node, ast.ClassDef):
            methods = "/".join(m.name.upper() for m in node.body if isinstance(m, ast.FunctionDef) and m.name in HTTP) or "-"
            for s in node.body:
                if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", "") in ("permission_classes",):
                    perms = ast.unparse(s.value)
            desc = first_sentence(ast.get_docstring(node) or "") or next(
                (first_sentence(ast.get_docstring(m)) for m in node.body
                 if isinstance(m, ast.FunctionDef) and m.name in HTTP and ast.get_docstring(m)), "")
        if r not in legacy_routes:
            st = "New API"
        else:
            leg = legacy.get(cname, set())
            if node is not None and any(h == oc.h(ast.unparse(node)) for _, h in leg):
                st = "Same as legacy"
            else:
                st = "Changed (fixed / optimized)"
        api_rows.append([f"/api/{r}", cname, methods, st, perms, rel, desc])
    for r, name in sorted(legacy_routes.items()):
        if r not in {x[0] for x in routes}:
            api_rows.append([f"/api/{r}", name.split(".")[-1], "-", "Removed (legacy route)", "-", "", ""])
    api_order = {"New API": 0, "Changed (fixed / optimized)": 1, "Same as legacy": 2, "Removed (legacy route)": 3}
    api_rows.sort(key=lambda x: (api_order[x[3]], x[0]))

    # ---- Celery ----
    settings_tree = parse(ROOT / "warehouse" / "settings.py")
    beat = {}
    for n in ast.walk(settings_tree):
        if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript)
                and ast.unparse(n.targets[0].value) == "CELERY_BEAT_SCHEDULE" and isinstance(n.value, ast.Dict)):
            d = {ast.literal_eval(k): v for k, v in zip(n.value.keys, n.value.values)}
            task = ast.literal_eval(d["task"]).split(".")[-1]
            beat[task] = f"{ast.literal_eval(n.targets[0].slice)}: every {ast.unparse(d['schedule'])} s"
    celery_rows = []
    tasks_tree = parse(ROOT / "wareApp" / "tasks.py")
    tlines = (ROOT / "wareApp" / "tasks.py").read_text().splitlines()
    for n in tasks_tree.body:
        if isinstance(n, ast.FunctionDef) and any("task" in ast.unparse(d) for d in n.decorator_list):
            deco = " ".join(ast.unparse(d) for d in n.decorator_list)
            q = re.search(r"queue=['\"]([\w-]+)", deco)
            desc, _ = describe(n.name, n, None, tlines, routes_by_view, model_names, "wareApp/tasks.py")
            origin = "New" if n.name not in legacy else "Changed"
            celery_rows.append([n.name, q.group(1) if q else "celery (default)", beat.get(n.name, "on demand / per message"),
                                origin, desc])

    # ---- management commands ----
    cmd_rows = []
    for f in sorted((ROOT / "wareApp" / "management" / "commands").glob("*.py")):
        if f.name.startswith("_"):
            continue
        t = parse(f)
        cmd = next((n for n in t.body if isinstance(n, ast.ClassDef) and n.name == "Command"), None)
        helptext = ""
        if cmd:
            for s in cmd.body:
                if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", "") == "help":
                    try:
                        helptext = ast.literal_eval(s.value)
                    except ValueError:
                        helptext = ast.unparse(s.value)
        cmd_rows.append([f"manage.py {f.stem}", first_sentence(helptext or ast.get_docstring(t) or ""),
                         f.relative_to(ROOT).as_posix()])

    # ---- DB models ----
    def fields(cls):
        out = {}
        for s in cls.body:
            if isinstance(s, ast.Assign) and isinstance(s.value, ast.Call) and isinstance(s.targets[0], ast.Name):
                fn = ast.unparse(s.value.func)
                if fn.startswith("models."):
                    out[s.targets[0].id] = (fn.replace("models.", ""), oc.h(ast.unparse(s.value)))
        return out

    def meta_info(cls):
        meta = next((s for s in cls.body if isinstance(s, ast.ClassDef) and s.name == "Meta"), None)
        if not meta:
            return 0, 0
        src = ast.unparse(meta)
        return src.count("models.Index("), src.count("Constraint(")

    legacy_models = {n.name: n for n in parse(legacy_root / "wareApp" / "models.py").body if isinstance(n, ast.ClassDef)}
    model_rows = []
    for n in models_tree.body:
        if not isinstance(n, ast.ClassDef):
            continue
        ours_f = fields(n)
        idx_n, con_n = meta_info(n)
        doc = first_sentence(ast.get_docstring(n) or "")
        if "abstract = True" in ast.unparse(n):
            table = "(abstract: no table, fields added to the models using it)"
        else:
            table = f"wareApp_{n.name.lower()}"
        if not any("Model" in ast.unparse(b) or "Mixin" in ast.unparse(b) for b in n.bases):
            continue  # helper class, not a model
        if n.name not in legacy_models:
            model_rows.append([n.name, table, "New model", len(ours_f), idx_n, con_n,
                               ", ".join(ours_f), "", "", doc])
            continue
        lf = fields(legacy_models[n.name])
        added = [k for k in ours_f if k not in lf]
        removed = [k for k in lf if k not in ours_f]
        changed = [k for k in ours_f if k in lf and ours_f[k][1] != lf[k][1]]
        li, lc = meta_info(legacy_models[n.name])
        st = "Changed" if (added or removed or changed or (idx_n, con_n) != (li, lc)) else "Same fields"
        model_rows.append([n.name, table, st, len(ours_f), idx_n, con_n, ", ".join(added),
                           ", ".join(removed), ", ".join(changed), doc])
    model_rows.sort(key=lambda r: ({"New model": 0, "Changed": 1, "Same fields": 2}[r[2]], r[0]))

    # ---- migrations ----
    legacy_migs = {p.name for p in (legacy_root / "wareApp" / "migrations").glob("0*.py")} if (
        legacy_root / "wareApp" / "migrations").exists() else set()
    mig_rows = []
    for f in sorted((ROOT / "wareApp" / "migrations").glob("0*.py")):
        if f.name in legacy_migs:
            continue
        t = parse(f)
        ops = []
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and ast.unparse(n.func).startswith("migrations."):
                op = ast.unparse(n.func).replace("migrations.", "")
                kw = {k.arg: k.value for k in n.keywords}
                target = kw.get("model_name") or kw.get("name")
                tgt = ast.literal_eval(target) if isinstance(target, ast.Constant) else ""
                field = ast.literal_eval(kw["name"]) if "model_name" in kw and isinstance(kw.get("name"), ast.Constant) else ""
                ops.append(f"{op} {tgt}{'.' + field if field else ''}".strip())
        doc = first_sentence(ast.get_docstring(t) or "")
        mig_rows.append([f.name[:4], f.stem, "; ".join(dict.fromkeys(ops))[:600], doc])

    # ---- tests ----
    test_rows = []
    total_tests = 0
    for f in sorted((ROOT / "wareApp" / "tests").glob("test_*.py")):
        t = parse(f)
        n_tests = sum(1 for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name.startswith("test"))
        total_tests += n_tests
        test_rows.append([f.name, n_tests, first_sentence(ast.get_docstring(t) or "")])

    # ---- merge overlap ----
    def read_overlap(pattern, skip=("Ours only",)):
        files = sorted(HERE.glob(pattern))
        rows = []
        if files:
            with files[-1].open() as fh:
                for r in csv.DictReader(fh):
                    if r["Status"] in skip:
                        continue  # "Ours only" of this branch: listed in the Functions sheet
                    rows.append([r["Risk"], r["Status"], r["Kind"], r["Name"], r["Their file"], r["Their line"],
                                 r["Our file"], r["Our line"], r["Action"]])
        return rows, files

    overlap_rows, overlap_files = read_overlap("overlap_main_server_*.csv")
    colleague_rows, colleague_files = read_overlap("overlap_colleague_2*.csv")
    cvm_rows, cvm_files = read_overlap("overlap_colleague_vs_main_*.csv", skip=())
    cvm_api_rows, cvm_api_files = [], sorted(HERE.glob("colleague_vs_main_apis_*.csv"))
    if cvm_api_files:
        with cvm_api_files[-1].open() as fh:
            for r in csv.DictReader(fh):
                cvm_api_rows.append([r["View"], r["Route"], r["Frontend calls it"], r["Verdict"], r["Contract differs"],
                                     r["Our lines"], r["Their lines"], r["Response keys only ours"],
                                     r["Response keys only theirs"], r["Request fields only ours"],
                                     r["Request fields only theirs"], r["Our file"], r["Their file"]])
        cvm_api_rows.sort(key=lambda r: (not r[4], not r[2], r[0]))

    # ---- removed ----
    removed_rows = []
    for p, s in sorted(status.items()):
        if s != "D":
            continue
        name = pathlib.Path(p).name
        if p == "wareApp/views.py":
            why = "Split by area into wareApp/views/ (every view class kept, see Functions sheet: 'Moved')."
        elif re.search(r"bck|backup|_before|\.save$|\d{2,}", name, re.I) or "/backups/" in p:
            why = "Backup copy of another file."
        elif "/migrations/" in p:
            why = "Migration replaced by this branch's migration history."
        elif p.startswith(("wareApp/", "warehouse/")):
            why = "Unused module (not imported by live code)."
        else:
            why = "One-off script / old tool outside the app."
        removed_rows.append([p, why])

    # ---- numbers for the summary / why sheet ----
    legacy_views = len((legacy_root / "wareApp" / "views.py").read_text(errors="replace").splitlines())
    legacy_tasks = len((legacy_root / "wareApp" / "tasks.py").read_text(errors="replace").splitlines())
    legacy_tests = 0
    if (legacy_root / "wareApp" / "tests.py").exists():
        legacy_tests = (legacy_root / "wareApp" / "tests.py").read_text().count("def test")
    shortstat = git("diff", "--shortstat", f"{LEGACY_REF}...HEAD").strip()
    deleted_lines = re.search(r"(\d+) deletions", shortstat)
    nums = dict(
        legacy_views=f"{legacy_views:,}", legacy_tasks=f"{legacy_tasks:,}",
        view_modules=len([p for p in py if p.startswith("wareApp/views/") and not p.endswith("__init__.py")]),
        modules=len(module_rows), functions=len(func_rows), legacy_tests=legacy_tests, tests=total_tests,
        test_modules=len(test_rows), removed=len(removed_rows),
        deleted_lines=f"{int(deleted_lines.group(1)):,}" if deleted_lines else "?",
    )
    why_rows = [[a, b.format(**nums), c.format(**nums), d.format(**nums), e] for a, b, c, d, e in WHY_BETTER]

    feats = load(ROOT / "docs/features/build_feature_tracker.py", "feature_tracker")
    alarms = load(ROOT / "docs/alarms/build_alarm_catalogue.py", "alarm_catalogue")

    head = git("rev-parse", "--short", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    risk = Counter(r[0] for r in overlap_rows)
    summary = [
        ["Branch / tag", f"{branch}, tag {TAG} (workbook built on top of commit {head})"],
        ["Compared with", f"{LEGACY_REF} (legacy code before this branch)"],
        ["Updated", UPDATED],
        ["Files changed vs legacy", shortstat],
        ["Live modules (new / changed)", f"{len(module_rows)}"],
        ["Functions + classes", f"{len(func_rows)}: " + ", ".join(f"{k} {v}" for k, v in origin_count.most_common())],
        ["APIs", ", ".join(f"{k} {v}" for k, v in Counter(r[3] for r in api_rows).most_common())],
        ["Alarm types", f"{len(alarms.ALARMS)}"],
        ["Features tracked", ", ".join(f"{k} {v}" for k, v in Counter(r[3] for r in feats.F).most_common())],
        ["Celery tasks", f"{len(celery_rows)} ({len(beat)} on a schedule)"],
        ["Management commands", f"{len(cmd_rows)}"],
        ["DB models", ", ".join(f"{k} {v}" for k, v in Counter(r[2] for r in model_rows).most_common())],
        ["Migrations of this branch", f"{len(mig_rows)} ({mig_rows[0][1] if mig_rows else '-'} ... "
                                      f"{mig_rows[-1][1] if mig_rows else '-'})"],
        ["Backend tests", f"{total_tests} in {len(test_rows)} modules (legacy: {legacy_tests})"],
        ["Merge overlap with main's code", ", ".join(f"{k} {v}" for k, v in sorted(risk.items())) +
         (f" (from {overlap_files[-1].name})" if overlap_files else " (no overlap CSV yet)")],
        ["Merge overlap with the colleague's code", ", ".join(
            f"{k} {v}" for k, v in sorted(Counter(r[0] for r in colleague_rows).items())) +
         (f" (from {colleague_files[-1].name}; repo Daksh007-batman/New-asem-merger @ 54313d5)" if colleague_files else "")],
        ["Colleague's code vs main's code", (
            f"{sum(1 for r in cvm_api_rows if r[3] not in ('Only ours', 'Only theirs'))} API views on both sides, "
            f"{sum(1 for r in cvm_api_rows if r[4] and r[3] not in ('Only ours', 'Only theirs'))} answer differently; "
            f"{sum(1 for r in cvm_api_rows if r[2] and r[4] and r[3] not in ('Only ours', 'Only theirs'))} of them are called by the frontend. "
            "Functions: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r[0] for r in cvm_rows).items())) +
            f" (from {cvm_api_files[-1].name if cvm_api_files else '-'}, {cvm_files[-1].name if cvm_files else '-'}; "
            "see docs/merge/COLLEAGUE_VS_MAIN.md)")],
        ["How to read", "Functions sheet: Origin New = written in this branch; Changed = exists in legacy, rewritten; "
                        "Moved, unchanged = same code in a new file. 'Description source' says whether the text is the "
                        "code's own docstring / comment or derived from its name, route and the models it uses."],
        ["Merge guide", "docs/merge/MERGE_GUIDE.md"],
    ]

    book = Workbook()
    sheet(book, "Summary", [("Item", 30), ("Value", 120)], summary, first=True)
    sheet(book, "Why ours is better", [("Area", 20), ("Legacy code", 55), ("This branch", 60), ("Evidence", 55), ("Doc", 38)],
          why_rows)
    sheet(book, "Features", feats.COLUMNS, feats.F, fill_col=3, fills={k: v[1] for k, v in feats.STATUSES.items()}, freeze="C2")
    sheet(book, "Alarms", alarms.COLUMNS, alarms.ALARMS, freeze="C2")
    sheet(book, "APIs", [("Endpoint", 40), ("View", 38), ("Methods", 10), ("Status vs legacy", 22), ("Permissions", 30),
                         ("File", 32), ("What it does", 70)], api_rows,
          fill_col=3, fills={"New API": "C6EFCE", "Changed (fixed / optimized)": "FFEB9C", "Removed (legacy route)": "D9D9D9"})
    sheet(book, "Celery tasks", [("Task", 40), ("Queue", 20), ("Schedule", 40), ("Origin", 10), ("What it does", 80)],
          celery_rows)
    sheet(book, "Management commands", [("Command", 36), ("What it does", 90), ("File", 50)], cmd_rows)
    sheet(book, "DB models", [("Model", 28), ("Table", 32), ("Status vs legacy", 14), ("Fields", 8), ("Indexes", 8),
                              ("Constraints", 11), ("Fields added (new model: all)", 50), ("Fields removed", 30),
                              ("Fields changed", 40), ("What it stores", 60)], model_rows,
          fill_col=2, fills={"New model": "C6EFCE", "Changed": "FFEB9C"})
    sheet(book, "Migrations", [("No.", 6), ("Migration", 50), ("Operations", 90), ("Note", 50)], mig_rows)
    sheet(book, "Modules", [("File", 52), ("Area", 24), ("Status", 18), ("Lines", 7), ("Functions + classes", 10),
                            ("Purpose", 90)], module_rows)
    sheet(book, "Functions", [("File", 44), ("Function / class", 46), ("Kind", 11), ("Line", 6), ("Lines", 6),
                              ("Origin", 15), ("Legacy file", 24), ("What it does", 80), ("Description source", 18),
                              ("Tests that use it", 40), ("Fingerprint", 13)], func_rows,
          fill_col=5, fills=ORIGIN_FILL, freeze="C2")
    sheet(book, "Tests", [("Test module", 44), ("Tests", 7), ("What it covers", 100)], test_rows)
    sheet(book, "Merge overlap (main)", [("Risk", 8), ("Status", 20), ("Kind", 10), ("Name", 50), ("Their file", 32),
                                         ("Their line", 8), ("Our file", 36), ("Our line", 8), ("Action", 60)],
          overlap_rows, fill_col=0, fills=RISK_FILL)
    sheet(book, "Ours vs colleague", [("Area", 22), ("Ours (full-optimization-v2)", 60), ("Colleague (New-asem-merger)", 60),
                                      ("Merge decision", 50)], COLLEAGUE_COMPARISON)
    sheet(book, "Merge overlap (colleague)", [("Risk", 8), ("Status", 20), ("Kind", 10), ("Name", 50), ("Their file", 32),
                                              ("Their line", 8), ("Our file", 36), ("Our line", 8), ("Action", 60)],
          colleague_rows, fill_col=0, fills=RISK_FILL)
    sheet(book, "Colleague vs main (APIs)", [("View", 40), ("Route", 36), ("Frontend calls it", 9), ("Verdict", 26),
                                             ("Contract differs", 9), ("Main lines", 7), ("His lines", 7),
                                             ("Response keys only main", 40), ("Response keys only his", 30),
                                             ("Request fields only main", 30), ("Request fields only his", 30),
                                             ("Main file", 28), ("His file", 28)],
          cvm_api_rows, fill_col=4, fills={"yes": "FFC7CE"})
    sheet(book, "Colleague vs main (functions)", [("Risk", 8), ("Status", 20), ("Kind", 10), ("Name", 50), ("His file", 32),
                                                  ("His line", 8), ("Main file", 36), ("Main line", 8), ("Action", 60)],
          cvm_rows, fill_col=0, fills=RISK_FILL)
    sheet(book, "Removed files", [("File", 70), ("Why", 70)], removed_rows)
    out = HERE / "CODE_INVENTORY.xlsx"
    book.save(out)
    print(f"{len(module_rows)} modules, {len(func_rows)} functions, {len(api_rows)} APIs, {len(model_rows)} models, "
          f"{len(mig_rows)} migrations, {total_tests} tests, {len(overlap_rows)} overlap rows -> {out}")


if __name__ == "__main__":
    main()
