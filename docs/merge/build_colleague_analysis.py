"""Build COLLEAGUE_CODE_ANALYSIS.xlsx: Daksh's code vs ours, point by point.

Read-only analysis of github.com/Daksh007-batman/New-asem-merger @ 54313d5
(cloned in .work/colleague_repo). Nothing was run, nothing was pushed there.
No credential values are written into the workbook.

    python3 docs/merge/build_colleague_analysis.py
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

OUT = Path(__file__).with_name("COLLEAGUE_CODE_ANALYSIS.xlsx")

FONT = "Arial"
HEAD_FILL = PatternFill("solid", fgColor="14213D")
SECTION_FILL = PatternFill("solid", fgColor="DCE3EE")
FILLS = {
    "His": PatternFill("solid", fgColor="FFE6D3"),
    "Ours": PatternFill("solid", fgColor="DDEBD8"),
    "Both": PatternFill("solid", fgColor="FFF4C2"),
}
THIN = Side(style="thin", color="C8CCD2")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

HIS = "Daksh (colleague) @ 54313d5"
OURS = "Ours: full-optimization-v2 (latest, 21 Nov 2026)"

# ---------------------------------------------------------------- data

STACK = [
    # area, his, ours, comment
    ("Framework", "Django 5.2.1, DRF 3.16, Celery 5.5.2, psycopg2", "Django, DRF, Celery (same family)", "Same base stack."),
    ("Message broker for Celery", "Redis (also used as cache and MQTT buffer)", "RabbitMQ (durable queues) for Celery and MQTT batches", "RabbitMQ keeps messages on disk until acknowledged."),
    ("Cache", "django-redis 7.0 + redis 8.1", "Django default cache (main's server has Redis CACHES, to be ported)", "His is better here; port Redis cache."),
    ("MQTT intake", "Standalone bridge.py: paho-mqtt on_message -> Redis list 'asem:mqtt:incoming'", "Celery listener tasks mqtt_client1 / mqtt_client2 (loop_forever) -> processing queues", "His listener is outside Celery; ours occupies a worker slot."),
    ("Routing", "dispatcher.py (Celery Beat every 2 s, up to 1,000 msgs/tick) -> 6 queues", "Broker subscriptions per queue (routing.py): queue1 business, queue2 LoadData only", "Ours filters at the broker, his after receiving everything (topic '#')."),
    ("Queues / workers", "mqtt_consumption x4, mqtt_load_data x4, mqtt_load_params x2, mqtt_supply_time x2, mqtt_recovery x2, mqtt_fire_alarm x1, mqtt_flush, mqtt_dispatcher", "root-mqtt-queue1/2 listeners, mqtt-processing-queue1/2, mqtt-notifications, celerybeat", ""),
    ("DB writes", "Redis row buffers + bulk_create every 5-30 s; hourly/daily totals in a Redis hash, last write wins, UPDATE per key", "Consumption: batched per aisle in one transaction (bulk_create / bulk_update); LoadData raw rows one INSERT each; rollups bulk_create", "Bulk LoadData is his good idea; ours is safer for consumption."),
    ("Code layout", "wareApp/models/ (8), views/ (7 *_views.py), services/ (alarm, email, fuel, baseline), tasks/ package, constants.py, mqtt_pipeline/", "models.py, views/ (21 modules), mqtt/ (39), load_data/, dg_fuel/, recovery/, management/", "Both modular. His models/ and tasks/ packages would hide our models.py and tasks.py."),
    ("Constants", "Typed IntEnums (NewAlarmType, priorities, SiteType)", "Integer constants and choices", "His is cleaner."),
    ("Alarms", "Two tables: NewAlarmsNotifications + legacy AlarmNotifications; AlarmService; NotificationPolicy; digest", "One table AlarmNotifications (one row per issue per day, occurrences), alarm_policy per site, alarm closer every 5 min", ""),
    ("Deployment", "Dockerfile, docker-compose (redis, web, nginx), Kubernetes manifests in bridge/", "systemd services on the servers, deploy docs and backups", "His is more portable for developers."),
    ("Migrations", "0001 (same as main) then his own 0002-0032", "Follows main's history (0059-0115), main's own 0073-0076 to reconcile", "His can't run on main's DB."),
    ("Tests", "44 (test_alarms 34, test_models 5, test_services 5); not run here", "539 tests, run before every deploy", ""),
    ("Docs", "ARCHITECTURE.md, Docker guides, optimization plans, pipeline README", "84 files in docs/, CHANGELOG, trackers, catalogues", ""),
]

# id, area, topic, his approach, his ref, his example, our approach, our ref,
# our example, better, why, risk if his used as-is, action
COMPARE = [
    ("C01", "MQTT pipeline", "Listener separated from DB work",
     "bridge.py only does redis.rpush() in on_message; runs as its own process.",
     "mqtt_pipeline/mqtt_pipeline/bridge.py:129, :99",
     "def on_message(client, userdata, msg):\n    payload = msg.payload.decode(...)\n    _push_to_redis(msg.topic, payload)",
     "Listener is a long-running Celery task that hands packets to processing queues.",
     "wareApp/tasks.py:41, :53; wareApp/mqtt/consumers.py:98",
     "return client.loop_forever(retry_first_connection=True)",
     "His", "The MQTT connection never waits on Celery or the DB, and no Celery worker slot is held by a listener.",
     "Low", "Port idea later (separate process), keeping RabbitMQ durability."),
    ("C02", "MQTT pipeline", "Packets dropped when the buffer is full",
     "When the Redis list holds 50,000 packets the bridge refuses new ones (comment says 'drop oldest', code drops newest).",
     "mqtt_pipeline/mqtt_pipeline/bridge.py:83; config.py REDIS_MAX_QUEUE",
     "if queue_len >= REDIS_MAX_QUEUE:\n    _stats['dropped'] += 1\n    return False",
     "RabbitMQ queues have no drop limit; messages stay until acknowledged after the DB commit.",
     "wareApp/mqtt/consumption_batch.py:129",
     "message.ack()  # only after the transaction commits",
     "Ours", "A DB slowdown or outage on his side silently loses gateway data; ours queues it.",
     "High", "Keep ours."),
    ("C03", "MQTT pipeline", "Packets lost on bridge restart",
     "MQTT client connects with clean_session=True: the broker forgets the subscription, packets sent while the bridge is down are lost.",
     "mqtt_pipeline/mqtt_pipeline/bridge.py:176",
     "mqtt.Client(client_id=MQTT_CLIENT_ID_BRIDGE, clean_session=True)",
     "clean_session=False: the broker keeps subscriptions and queues QoS 1 packets while the listener restarts.",
     "wareApp/mqtt/consumers.py:79-81",
     "client = mqtt.Client(client_id, clean_session=False)",
     "Ours", "Every deploy or crash of his bridge loses the packets of that moment.",
     "High", "Keep ours."),
    ("C04", "MQTT pipeline", "Packets lost between pop and route",
     "Dispatcher removes up to 100 packets (lrange + ltrim) before routing them; a crash in between loses them. acks_late doesn't help: the Redis list has no acknowledgement.",
     "mqtt_pipeline/mqtt_pipeline/dispatcher.py:110-118",
     "pipe.lrange(REDIS_QUEUE_KEY, 0, DISPATCHER_BATCH_SIZE - 1)\npipe.ltrim(REDIS_QUEUE_KEY, DISPATCHER_BATCH_SIZE, -1)",
     "Messages acknowledged only after processing; failures become dead letters.",
     "wareApp/mqtt/services/failures.py:29",
     "def record_dead_letter(message_type, site_id, gateway_id, payload, error, dedupe=True):",
     "Ours", "No replay possible for packets lost in a worker crash.",
     "High", "Keep ours."),
    ("C05", "MQTT pipeline", "Throughput ceiling",
     "Dispatcher runs every 2 s and routes at most 1,000 packets per tick (500 packets/s). Above that the list grows until C02 drops data.",
     "mqtt_pipeline/mqtt_pipeline/dispatcher.py:110; celery_beat_schedule.py:19",
     "MAX_PER_TICK = 1000\n\"schedule\": 2.0,",
     "Listener pushes directly to RabbitMQ; workers consume continuously.",
     "wareApp/mqtt/routing.py",
     "queue1: business types; queue2: /+/+/in/LoadData/#",
     "Ours", "Fixed tick plus extra hop adds up to 2 s latency and a hard ceiling.",
     "Medium", "Keep ours."),
    ("C06", "MQTT pipeline", "Subscribing to everything",
     "Subscribes to /Acclivate/iOmniControl/# (all topics, both directions) and filters by substring in the dispatcher.",
     "mqtt_pipeline/mqtt_pipeline/config.py MQTT_TOPIC; dispatcher.py _route",
     "if \"load\" in msg_type_parts or \"load\" in msg_type_lower:",
     "Narrow subscriptions per queue; validated topic parser.",
     "wareApp/mqtt/routing.py, wareApp/mqtt/topics.py",
     "Queue 1 excludes LoadData; queue 2 receives only LoadData",
     "Ours", "Substring matching is fragile (order-dependent: 'LoadData' must be tested before 'load').",
     "Medium", "Keep ours."),
    ("C07", "DB writes", "Bulk INSERT of LoadData rows",
     "Raw / hourly / daily LoadData, PF and voltage rows buffered in Redis and written with one bulk_create every 5-30 s.",
     "mqtt_pipeline/mqtt_pipeline/buffer.py:151; tasks/flush_task.py",
     "Model.objects.bulk_create(objects, ignore_conflicts=True)",
     "RawLoadData saved one row per packet (rollups already bulk).",
     "wareApp/load_data/raw.py:7; wareApp/load_data/rollups.py:113",
     "return RawLoadData.objects.create(...)",
     "His", "Fewer DB round trips for the highest-volume table. Listed as 'not done' in our 6 Nov DB doc.",
     "Low", "Port idea: batch RawLoadData from a RabbitMQ batch queue like consumption, with dead letters (not Redis drop buffers)."),
    ("C08", "DB writes", "Row buffer overflow deletes oldest rows",
     "Each row buffer keeps max 5,000 rows; on overflow the oldest is deleted. A failed bulk_create re-pushes rows, which can push others out.",
     "mqtt_pipeline/mqtt_pipeline/buffer.py:53-63, :159",
     "if current_len > BUFFER_MAX_SIZE:\n    _redis.lpop(buf_key)   # drop oldest",
     "Batch written in one transaction; on failure the aisle's packets become dead letters, others still written.",
     "wareApp/mqtt/consumption_batch.py (docstring steps 3-4)",
     "If one aisle fails, its packets become dead letters and the other aisles are still written.",
     "Ours", "A DB outage of a few minutes deletes measured data on his side.",
     "High", "Keep ours."),
    ("C09", "Consumption", "Hourly update lost before the row exists",
     "First packet of an hour: row put in BUF_HOURLY_READ (flushed every 10 s) and the hour marked 'exists' in cache at once. Later packets become UPDATEs flushed every 5 s; if the row isn't created yet, UPDATE hits 0 rows and the value is deleted from Redis.",
     "handlers/consumption_handler.py:423-434; buffer.py:204-254; celery_beat_schedule.py:45, :55",
     "push_row(BUF_HOURLY_READ, {...})\nmark_hourly_bucket(*hour_bucket_key)\n...\n).update(**update_fields)   # 0 rows -> value gone",
     "Hourly row created and updated in the same transaction, in arrival order per aisle.",
     "wareApp/mqtt/consumption_batch.py",
     "applies every packet in arrival order per aisle in memory ... writes all changes ... inside one transaction",
     "Ours", "Hour totals can be wrong when the last packets of an hour fall in that window.",
     "High", "Keep ours."),
    ("C10", "Consumption", "Duplicate hourly rows under parallel workers",
     "4 consumption workers; two first-packets of the same meter/hour can both see 'not exists' and both create a row. HourlySiteReading has no unique constraint, so ignore_conflicts does nothing.",
     "wareApp/models/metering.py:38-47; README (mqtt_consumption x4)",
     "indexes = [Index(fields=['associated_Site','leg_id','reading_from','reading_to'], ...)]  # no unique",
     "Aisle rows locked with select_for_update before applying packets.",
     "wareApp/mqtt/consumption_batch.py:244; wareApp/mqtt/consumption.py:361",
     "for aisle in AisleGroup.objects.select_for_update().filter(site_filter).order_by(\"id\"):",
     "Ours", "Duplicate hours double the reported consumption.",
     "High", "Keep ours."),
    ("C11", "Consumption", "Hour range boundary",
     "Hour filter uses reading_from <= hh:59:59 (closed range).",
     "buffer.py:240-254; consumption_handler.py:277-278",
     "reading_from__gte=hour_lower,\nreading_from__lte=hour_upper,",
     "Half-open range: >= hour start and < next hour.",
     "docs/operations/MAIN_SERVER_BEFORE_AFTER_MIGRATION.md (Application Query Improvements)",
     "reading_from__gte=lower, reading_from__lt=upper",
     "Ours", "A reading at hh:59:59.5 belongs to no hour in his code.",
     "Low", "Keep ours."),
    ("C12", "Consumption", "Readings above 10,000 kWh",
     "Model save() sets unit_consumption > 10000 to 0. But his pipeline writes with bulk_create / update(), which skip save(), so the rule doesn't even run there.",
     "wareApp/models/metering.py:32, :79",
     "if self.unit_consumption > 10000:\n    self.unit_consumption = 0",
     "Values stay as stored until the manager decides (team decision).",
     "docs/consumption/READING_RULES.md",
     "Impossible readings on hold",
     "Ours", "Silently zeroes data, and inconsistently.",
     "Medium", "Keep ours."),
    ("C13", "Consumption", "Catch-up after a data gap, spikes",
     "No catch-up spread, no spike detection, no recovery status.",
     "-", "-",
     "Catch-up spread (night auto + manual, 5-day undo, history), spike vs meter-jump alarms, sync / recovery status APIs.",
     "wareApp/catch_up_spread.py; wareApp/views/catch_up.py; wareApp/views/sync_status.py",
     "auto_spread() 19:00-11:00 and Sundays, clear cases only",
     "Ours", "Without it a gateway catch-up shows as one huge hour.",
     "Medium", "Keep ours."),
    ("C14", "Database", "Hourly index",
     "Two identical 4-column indexes (one partial on is_visible) on site, leg, reading_from, reading_to.",
     "wareApp/models/metering.py:40-47",
     "name='idx_site_leg_time' and name='idx_site_leg_time_visible' (same columns)",
     "One 3-column index (site, leg, reading_from), built CONCURRENTLY, proven on main (index-only scan, cost 8.58); aisle + time index; redundant indexes dropped.",
     "docs/operations/MAIN_SERVER_BEFORE_AFTER_MIGRATION.md; docs/operations/DB_OPTIMIZATION_2026-11-06.md",
     "CREATE INDEX CONCURRENTLY idx_hourlysitereading_site_leg_reading_from ON ... (\"associated_Site_id\", leg_id, reading_from);",
     "Ours", "Two indexes double the write cost for the same reads.",
     "Low", "Keep ours."),
    ("C15", "Database", "Migrations",
     "0001 equals main's, then his own 0002-0032; main's DB has 0001-0076.",
     "wareApp/migrations/",
     "0002 ... 0032 (own lineage)",
     "Follows main's lineage; main's 0073-0076 reconciled in the rollout plan.",
     "docs/deploy/MAIN_SERVER_ROLLOUT.md section 3",
     "",
     "Ours", "Django refuses to migrate (two leaf nodes); his can't be applied to main.",
     "High", "Keep ours; never apply his migrations."),
    ("C16", "Caching", "Redis cache for lookups",
     "django-redis; site / aisle / baseline cached (10 min / 1 h); hourly 'exists' flags.",
     "mqtt_pipeline/mqtt_pipeline/cache_layer.py; config.py CACHE_TTL_*",
     "CACHE_TTL_SITE = 600\nCACHE_TTL_BASELINE = 3600",
     "Site cache with the default Django cache; main's server already has Redis CACHES.",
     "wareApp/mqtt/services/site_cache.py",
     "",
     "His", "A shared Redis cache works across all worker processes.",
     "Low", "Port: Redis CACHES setting (as on main's server)."),
    ("C17", "Alarms", "Alarm table design",
     "Two tables: NewAlarmsNotifications (power) and legacy AlarmNotifications (consumption).",
     "wareApp/models/alerts.py:8, :42",
     "class AlarmNotifications(models.Model)\nclass NewAlarmsNotifications(models.Model)",
     "One table for every alarm since Oct 2026.",
     "wareApp/models.py:551",
     "One row per issue per day: a repeat updates last_seen / occurrences",
     "Ours", "Two tables caused our old 'tile shows 0 alarms' bug; counts differ between screens.",
     "Medium", "Keep ours."),
    ("C18", "Alarms", "Duplicate rows for long issues",
     "Deduplicates only inside a time window; after it a still-open issue gets a new row.",
     "wareApp/services/alarm_service.py:66-73, :138-145",
     "existing = ...filter(is_active=True, created__gte=dedup_window).first()\nif existing: return existing\nalarm = NewAlarmsNotifications.objects.create(...)",
     "Repeat increments occurrences on the same row; closed by the alarm closer when the issue stops.",
     "wareApp/mqtt/services/alarms.py:84-91",
     "occurrences=F(\"occurrences\") + 1,",
     "Ours", "A 2-day outage becomes many alarm rows.",
     "Medium", "Keep ours."),
    ("C19", "Alarms", "Outage alarms",
     "No Gateway Disconnected, Gateway Service issue (Modbus), Meter Disconnected or Consumption Spike.",
     "-", "-",
     "All four live on test, plus Gateway Status panel (Super Admin).",
     "wareApp/mqtt/services/gateway_health.py; spike_alarms.py; views/monitoring.py",
     "types 15 -> offline, 16 -> modbus_issue",
     "Ours", "Outages go unnoticed.",
     "Medium", "Keep ours."),
    ("C20", "Alarms", "Fuel Drain and Mains Higher Consumption",
     "raise_fuel_drain_alarm and raise_mains_higher_consumption_alarm implemented.",
     "wareApp/services/alarm_service.py:270, :294",
     "def raise_mains_higher_consumption_alarm(cls, site, load_val, power_source='MAINS SUPPLY', ...)",
     "Fuel Drain active; Mains Higher Consumption, DG Overtime, Fuel Under Level defined but not raised.",
     "docs/alarms/ALARM_CATALOGUE.xlsx",
     "",
     "His", "He has the rule for Mains Higher Consumption.",
     "Low", "Port the rule into our single table (agree the threshold first)."),
    ("C21", "Alarms", "Dashboard APIs: summary, live feed, acknowledge, daily digest",
     "get_dashboard_summary, get_live_alarms_feed, acknowledge_alarm, generate_daily_digest_data + views.",
     "wareApp/services/alarm_service.py:454, :509, :573, :609; views/alert_views.py",
     "def acknowledge_alarm(...)",
     "Not built (alarm list, counts and settings exist).",
     "-", "-",
     "His", "Acknowledge and a live feed are useful for the monitoring team.",
     "Low", "Port onto our AlarmNotifications (add acknowledged_by / acknowledged_at), Super Admin only."),
    ("C22", "Alarms", "Notification policy",
     "Immediate e-mail only for HIGH priority; 6 h cooldown per site and type; rest in a daily digest; emergencies bypass.",
     "wareApp/services/email_service.py:31-105",
     "if priority is not None and priority > cls.min_email_priority:\n    return False, 'Route to Dashboard only.'",
     "Per-site / per-type settings (off, recipients), repeat e-mailed only when > 5% worse, retries for 24 h.",
     "wareApp/mqtt/services/alarm_policy.py, cooldown.py, notifications.py",
     "",
     "Both", "His priority + digest reduces e-mail noise; ours has per-site control and never loses an e-mail. Note his cooldown check and record are not atomic, and the in-memory fallback is per process.",
     "Low", "Port priority + digest as settings on top of ours."),
    ("C23", "Code quality", "Typed constants",
     "IntEnums with display names.",
     "wareApp/constants.py:10",
     "class NewAlarmType(IntEnum):\n    HIGH_VOLTAGE = 0\n    ...\n    FUEL_DRAIN = 6",
     "Integer constants / choices.",
     "wareApp/models.py",
     "alarm_type=16",
     "His", "Self-documenting, fewer magic numbers.",
     "Low", "Optional: add Enums for our alarm types 0-17."),
    ("C24", "APIs", "Placeholder APIs",
     "10 APIs return a fixed message: every Excel download, DemoApi.",
     "wareApp/views/load_views.py:400; views/alert_views.py:169; urls.py:33-109",
     "def post(self, request):\n    return Response({'message': 'Excel export ready'})",
     "Real exports with data.",
     "wareApp/views/",
     "",
     "Ours", "Every Excel button on the frontend would break.",
     "High", "Keep ours."),
    ("C25", "APIs", "Simplified views",
     "60 of 103 shared views are less than half the size of ours; e.g. CustomerSnapshotApi returns alarms: 0; SiteCeleryPingApi 114 -> 8 lines.",
     "wareApp/views/*_views.py; docs/merge/colleague_vs_ours_apis_20261119.csv",
     "'alarms': 0",
     "Full views; frontend contract checked (4 deliberate fixes vs main).",
     "docs/merge/THREE_WAY_COMPARISON.md",
     "",
     "Ours", "40-42 frontend APIs answer differently from main / ours.",
     "High", "Keep ours."),
    ("C26", "Security", "Password reset with a fixed OTP",
     "forgot/ stores the fixed OTP 1234 for any username and sends nothing; reset/ accepts it. Never expires, never used up.",
     "wareApp/views/auth_views.py:108 (ForgetPassword), :113 (ResetPasswordApi)",
     "otp_val = \"1234\"",
     "forgot/ no longer returns the OTP; reset/ checks username + OTP.",
     "wareApp/views/auth.py",
     "",
     "Ours", "Anyone can take over any account.",
     "High", "Never deploy his forgot/ reset/ login/."),
    ("C27", "Security", "Credentials in the repo",
     "Live DB password and public DB host in docker-compose.yml; provider credentials in ARCHITECTURE.md and 5 code files; weak fixed Redis password. Values deliberately not copied here.",
     "docker-compose.yml; ARCHITECTURE.md; warehouse/settings.py; fetch_fuel_data.py; fetch_fuel.py; loconav.py; reset_password.py",
     "(values withheld)",
     "Secrets read from .env; no hardcoded password in settings.",
     "warehouse/settings.py",
     "DEBUG = config(\"DEBUG\", default=not IS_PROD, cast=bool)",
     "Ours", "Anyone with repo access has production DB and provider access.",
     "High", "Rotate the exposed credentials and remove them from his repo history (F09)."),
    ("C28", "Security", "Settings",
     "DEBUG = True in both branches of the ENV check; ALLOWED_HOSTS = ['*']; CORS_ALLOW_ALL_ORIGINS = True hardcoded.",
     "warehouse/settings.py:34-41",
     "DEBUG = True\nALLOWED_HOSTS = ['*']\nCORS_ALLOW_ALL_ORIGINS = True",
     "Read from .env (our defaults are open too, to tighten).",
     "warehouse/settings.py",
     "",
     "Ours", "DEBUG in production leaks stack traces and settings.",
     "High", "Keep ours; tighten our defaults too."),
    ("C29", "Deployment", "Docker and Kubernetes",
     "Dockerfile, docker-compose (Redis, web, nginx), Kubernetes manifests (generated on Windows: file names contain Windows paths).",
     "Dockerfile; docker-compose.yml; bridge/",
     "command: gunicorn --bind 0.0.0.0:8000 --workers 3 --timeout 300 warehouse.wsgi:application",
     "systemd services on the servers.",
     "monitoring/*.service; docs/deploy/",
     "",
     "His", "One-command dev setup.",
     "Low", "Port Dockerfile / compose for local dev, with env_file instead of inline secrets."),
    ("C30", "Testing", "Tests and verification",
     "44 tests; never run here; no record of a run.",
     "wareApp/tests/",
     "test_alarms.py (34)",
     "539 tests, run before each deploy; live on test, partly on main since 9 Oct with measured CPU.",
     "wareApp/tests/",
     "",
     "Ours", "His code has never been proven on real traffic.",
     "Medium", "Port his 34 alarm tests along with the features."),
    ("C31", "Repo hygiene", "History and files",
     "One large commit for the whole project; 72 .pyc / __pycache__ files committed; celerybeat-schedule.dat committed.",
     "git log; mqtt_pipeline/mqtt_pipeline/celerybeat-schedule.dat",
     "6ea3c2f 'optimized backend code' (159k lines)",
     "189 commits with messages; CHANGELOG row per change.",
     "docs/CHANGELOG.md",
     "",
     "Ours", "No way to see what changed and why.",
     "Low", "-"),
]

PORT = [
    # item, from (his), into (ours), how, depends on, effort, priority
    ("Alarm acknowledge", "services/alarm_service.py:573 acknowledge_alarm; views/alert_views.py", "AlarmNotifications + new fields acknowledged_by / acknowledged_at; views/alarms.py", "Migration (2 nullable fields), POST API Super Admin only, button in the alarm list", "-", "Small", "High"),
    ("Live alarm feed", "alarm_service.py:509 get_live_alarms_feed", "views/alarms.py", "Read from our single table, newest first, paging", "-", "Small", "Medium"),
    ("Alarm dashboard summary", "alarm_service.py:454 get_dashboard_summary", "views/alarms.py", "Counts by type / priority / site from AlarmNotifications", "-", "Small", "Medium"),
    ("Daily digest e-mail", "alarm_service.py:609, email_service.py:151 / :255, tasks/alarm_tasks.py:96", "mqtt/services/notifications.py + Celery beat", "Digest of non-urgent alarms once a day to the software team", "Notification priority", "Medium", "Medium"),
    ("Notification priority", "email_service.py:31-105 NotificationPolicy", "mqtt/services/alarm_policy.py, AlarmSetting", "Priority per alarm type; immediate e-mail only above a level; rest to digest; emergencies always", "Team agrees priorities", "Medium", "Medium"),
    ("Mains Higher Consumption alarm", "alarm_service.py:294", "mqtt/services/alarms.py (type 5)", "Raise into the single table with our repeat rule; threshold in AlarmSetting", "Rule / threshold agreed", "Small", "Medium"),
    ("Redis cache", "settings.py CACHES (django-redis)", "warehouse/settings.py (as on main's server)", "CACHES from .env; site cache / cooldown / idempotency then shared", "Redis on test", "Small", "High"),
    ("Bulk RawLoadData writes (idea)", "buffer.py:151 + flush_task.py", "wareApp/load_data/raw.py", "Batch queue on RabbitMQ like consumption_batch, one transaction, dead letters; no drop limits", "-", "Medium", "Medium"),
    ("Listener outside Celery (idea)", "bridge.py", "wareApp/mqtt/consumers.py", "Run the listener as its own systemd process publishing to RabbitMQ; keep clean_session=False", "Load test", "Medium", "Low"),
    ("Typed Enums", "constants.py", "wareApp/constants.py (new)", "IntEnum for alarm types 0-17 and site types; use in new code", "-", "Small", "Low"),
    ("Docker for local dev", "Dockerfile, docker-compose.yml", "repo root", "Use env_file, no inline secrets; Postgres + RabbitMQ + Redis services", "-", "Small", "Low"),
    ("His alarm tests", "tests/test_alarms.py (34)", "wareApp/tests/", "Port with each feature above", "Each feature", "Small", "Medium"),
]

DO_NOT = [
    ("Redis list pipeline as-is (bridge + dispatcher + drop buffers)", "C02, C03, C04, C05, C08", "Loses data on overflow, restart and crash."),
    ("His consumption handler", "C09, C10, C11, C12", "Lost hourly updates, duplicate hours, closed hour range, zeroes > 10,000 kWh."),
    ("forgot/ reset/ login/", "C26", "Account takeover with OTP 1234; login has no rate limit and re-activates deactivated users."),
    ("Placeholder and simplified views", "C24, C25", "Excel downloads and 40-42 frontend APIs break."),
    ("Migrations 0002-0032", "C15", "Don't fit main's DB; two leaf nodes."),
    ("models/ and tasks/ packages", "-", "Would hide our models.py and tasks.py without any error."),
    ("Second alarm table", "C17", "Counts differ between screens."),
    ("settings.py, docker-compose.yml as they are", "C27, C28", "Credentials in plain text; DEBUG on in PROD."),
]

FLOW = [
    # step, his, ours
    ("1. Gateway publishes", "MQTT broker (Mosquitto)", "MQTT broker (Mosquitto)"),
    ("2. Subscription", "One bridge subscribes to /Acclivate/iOmniControl/# (everything), clean_session=True", "Queue 1 and queue 2 listeners with narrow subscriptions, clean_session=False"),
    ("3. First hand-off", "rpush to Redis list (max 50,000, then dropped)", "Published to RabbitMQ queues (durable)"),
    ("4. Routing", "Celery Beat dispatcher every 2 s, max 1,000 per tick, substring match on message type", "Already routed by subscription; validated topic parser"),
    ("5. Processing", "6 Celery queues, several parallel workers per type", "Processing workers; consumption in batches per aisle with row locks"),
    ("6. Duplicate guard", "ignore_conflicts (needs unique constraints, most tables have none)", "Idempotency keys (claim / release) per message"),
    ("7. Writing", "Redis row buffers (max 5,000, oldest dropped) + hash of last values, flushed every 5-30 s", "One transaction per batch: bulk_create / bulk_update"),
    ("8. Failure", "Re-push to buffer or log; lost on overflow", "Dead letter row with payload and error; DB retry with back-off"),
    ("9. Acknowledge", "None (Redis list)", "message.ack() after commit"),
    ("10. Alarms", "Raised in handlers into two tables, dedup by time window", "One table, one row per issue per day, closer every 5 min"),
]


# ---------------------------------------------------------------- helpers

def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = BORDER


def write_table(ws, start_row, headers, rows, widths):
    for i, h in enumerate(headers, 1):
        ws.cell(row=start_row, column=i, value=h)
    style_header(ws, start_row, len(headers))
    for r, data in enumerate(rows, start_row + 1):
        for c, v in enumerate(data, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = Font(name=FONT, size=10)
            cell.alignment = WRAP
            cell.border = BORDER
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    end_row = start_row + len(rows)
    ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{end_row}"
    return end_row


def title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, bold=True, size=14, color="14213D")
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(name=FONT, italic=True, size=10, color="4E5A6B")


# ---------------------------------------------------------------- sheets

def build():
    wb = Workbook()

    # Start here
    ws = wb.active
    ws.title = "Start here"
    title(ws, "Daksh's code vs ours: detailed analysis", "Read-only review, 21 Nov 2026. Kept in our repo only; nothing is uploaded to the colleague's repo.")
    info = [
        ("His repo", "github.com/Daksh007-batman/New-asem-merger, branches main = Ashutosh = 54313d5 (18 Nov 2026); no newer commits on 21 Nov"),
        ("Our code", OURS),
        ("How reviewed", "Cloned into .work/colleague_repo and read. His code was not run (no manage.py check, no tests). Nothing pushed or changed there."),
        ("Secrets", "His repo contains live credentials. Their values are deliberately not copied into this workbook."),
        ("Earlier review", "docs/merge/COLLEAGUE_CODE_REVIEW.md, THREE_WAY_COMPARISON.md, COLLEAGUE_VS_MAIN.md, CODE_INVENTORY.xlsx"),
        ("Rebuild", "python3 docs/merge/build_colleague_analysis.py"),
    ]
    for i, (k, v) in enumerate(info, 4):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT, bold=True)
        c = ws.cell(row=i, column=2, value=v)
        c.font = Font(name=FONT)
        c.alignment = WRAP

    r = 4 + len(info) + 1
    ws.cell(row=r, column=1, value="Sheets").font = Font(name=FONT, bold=True, size=12)
    sheets = [
        ("Tech stack", "What each side uses, area by area."),
        ("Comparison", "31 points: his approach and ours, file:line references, code examples, which is better and why, risk, action."),
        ("Pipeline flow", "The MQTT path step by step, his vs ours."),
        ("Port list", "His good parts to bring into our code, with where and how."),
        ("Do not use", "Parts of his code that must not be deployed, and why."),
    ]
    for i, (k, v) in enumerate(sheets, r + 1):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT)
        ws.cell(row=i, column=2, value=v).font = Font(name=FONT)

    r = r + len(sheets) + 2
    ws.cell(row=r, column=1, value="Summary (formulas over the Comparison sheet)").font = Font(name=FONT, bold=True, size=12)
    n = len(COMPARE)
    rng_b = f"Comparison!$J$4:$J${3 + n}"
    rng_r = f"Comparison!$L$4:$L${3 + n}"
    summary = [
        ("Points compared", f"=COUNTA(Comparison!$A$4:$A${3 + n})"),
        ("Ours better", f'=COUNTIF({rng_b},"Ours")'),
        ("His better", f'=COUNTIF({rng_b},"His")'),
        ("Both have value", f'=COUNTIF({rng_b},"Both")'),
        ("High risk if his used as-is", f'=COUNTIF({rng_r},"High")'),
        ("Items to port", f"=COUNTA('Port list'!$A$4:$A${3 + len(PORT)})"),
    ]
    for i, (k, f) in enumerate(summary, r + 1):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT)
        c = ws.cell(row=i, column=2, value=f)
        c.font = Font(name=FONT, bold=True)
        c.alignment = Alignment(horizontal="left")

    r = r + len(summary) + 2
    ws.cell(row=r, column=1, value="Verdict").font = Font(name=FONT, bold=True, size=12)
    verdict = ("Keep our code as the base and port his good parts onto it: alarm acknowledge, live feed, "
               "dashboard summary, daily digest, notification priority, Mains Higher Consumption, Redis cache, "
               "typed Enums, Docker. Take his bulk LoadData writes as an idea and build it on RabbitMQ with dead "
               "letters. Do not deploy his pipeline, consumption handler, auth views, placeholder views, "
               "migrations or settings as they are.")
    c = ws.cell(row=r + 1, column=1, value=verdict)
    c.font = Font(name=FONT)
    c.alignment = WRAP
    ws.merge_cells(start_row=r + 1, start_column=1, end_row=r + 1, end_column=2)
    ws.row_dimensions[r + 1].height = 75

    r = r + 3
    ws.cell(row=r, column=1, value="Colours in Comparison").font = Font(name=FONT, bold=True)
    for i, (k, label) in enumerate([("Ours", "Ours is better"), ("His", "His is better"), ("Both", "Both have value")], r + 1):
        c = ws.cell(row=i, column=1, value=label)
        c.font = Font(name=FONT)
        c.fill = FILLS[k]
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 120

    # Tech stack
    ws = wb.create_sheet("Tech stack")
    title(ws, "What each side uses", f"His: {HIS} · Ours: {OURS}")
    write_table(ws, 3, ["Area", "His code", "Our code", "Comment"], STACK, [26, 60, 60, 50])

    # Comparison
    ws = wb.create_sheet("Comparison")
    title(ws, "Point-by-point comparison with examples", "File references: his are relative to his repo, ours to our repo. Line numbers as of 21 Nov 2026.")
    headers = ["ID", "Area", "Topic", "His approach", "His file:line", "His code example",
               "Our approach", "Our file:line", "Our code example", "Better", "Why", "Risk if his used as-is", "Action"]
    end = write_table(ws, 3, headers, COMPARE, [6, 14, 26, 48, 32, 46, 44, 32, 44, 9, 44, 12, 38])
    for r in range(4, end + 1):
        better = ws.cell(row=r, column=10).value
        fill = FILLS.get(better)
        if fill:
            for c in (1, 3, 10):
                ws.cell(row=r, column=c).fill = fill
        for c in (6, 9):
            ws.cell(row=r, column=c).font = Font(name="Courier New", size=9)
    dv = DataValidation(type="list", formula1='"His,Ours,Both"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"J4:J{end}")
    dv2 = DataValidation(type="list", formula1='"High,Medium,Low"', allow_blank=True)
    ws.add_data_validation(dv2)
    dv2.add(f"L4:L{end}")

    # Pipeline flow
    ws = wb.create_sheet("Pipeline flow")
    title(ws, "MQTT path, step by step")
    write_table(ws, 3, ["Step", "His pipeline", "Our pipeline"], FLOW, [24, 70, 70])

    # Port list
    ws = wb.create_sheet("Port list")
    title(ws, "His good parts to bring into our code", "Each as its own change with tests and docs. Status column is for tracking.")
    rows = [p + ("Not started",) for p in PORT]
    end = write_table(ws, 3, ["Item", "From (his code)", "Into (our code)", "How", "Depends on", "Effort", "Priority", "Status"],
                      rows, [30, 46, 40, 52, 22, 10, 10, 14])
    dv3 = DataValidation(type="list", formula1='"Not started,In progress,Done,Dropped"', allow_blank=True)
    ws.add_data_validation(dv3)
    dv3.add(f"H4:H{end}")

    # Do not use
    ws = wb.create_sheet("Do not use")
    title(ws, "Parts of his code that must not be deployed as they are")
    write_table(ws, 3, ["Part", "Comparison IDs", "Why"], DO_NOT, [50, 22, 80])

    # Views merge (21 Nov): one row per API view, decision and reason
    decisions = Path(__file__).with_name("views_merge_decisions_20261121.csv")
    if decisions.exists():
        import csv

        with decisions.open() as fh:
            reader = csv.reader(fh)
            header = next(reader)
            drows = list(reader)
        ws = wb.create_sheet("Views merge")
        title(ws, "Views merge, 21 Nov 2026: his view or ours, one row per API view",
              "Rule: keep ours for alarms, features, LoadData, DG fuel and anything we built or reworked; "
              "take his only where it returns the same answer. Source: views_merge_decisions_20261121.csv")
        end = write_table(ws, 3, header, drows, [34, 30, 30, 10, 16, 10, 16, 30, 14, 26, 22, 70])
        dcol = header.index("Decision") + 1
        for r in range(4, end + 1):
            d = ws.cell(row=r, column=dcol).value or ""
            fill = FILLS["His"] if d.startswith("Merged") else FILLS["Both"] if d.startswith("Already") else None
            if fill:
                for c in (1, dcol):
                    ws.cell(row=r, column=c).fill = fill
        start = wb["Start here"]
        last = start.max_row + 2
        start.cell(row=last, column=1, value="Views merge (formulas)").font = Font(name=FONT, bold=True, size=12)
        rng = f"'Views merge'!${get_column_letter(dcol)}$4:${get_column_letter(dcol)}${end}"
        for i, (label, crit) in enumerate([
            ("API views reviewed", None),
            ("Merged from his code", "Merged*"),
            ("Already the same code", "Already*"),
            ("Kept ours: our area or new in ours", "Keep ours (*"),
            ("Kept ours: his changes the API / is missing / placeholder / security", "Keep ours"),
        ], last + 1):
            start.cell(row=i, column=1, value=label).font = Font(name=FONT)
            f = f"=COUNTA({rng})" if crit is None else f'=COUNTIF({rng},"{crit}")'
            c = start.cell(row=i, column=2, value=f)
            c.font = Font(name=FONT, bold=True)
            c.alignment = Alignment(horizontal="left")

    for sheet in wb.worksheets:
        sheet.sheet_view.zoomScale = 100
    wb.save(OUT)
    print(f"Wrote {OUT} ({len(COMPARE)} comparison points, {len(PORT)} port items)")


if __name__ == "__main__":
    build()
