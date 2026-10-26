"""Flow definitions for docs/mqtt-flows (source of the diagrams and README).

Each flow: nodes {id: (label, kind, column, row)}, edges [(from, to, label)],
files [(path, what)], summary and details (Markdown). Kinds: start, end,
process, decision, db, queue, alarm, ext, skip. Run generate.py after editing.
"""

INTRO = """
# MQTT / gateway data flows

How every gateway message travels through the backend: which process receives
it, which queue carries it, which function handles it, which tables it writes,
and what it triggers (recovery requests, sync status, alarms, e-mails).

- Generated from `docs/mqtt-flows/flows.py` by `python docs/mqtt-flows/generate.py`
  (branch `full-optimization-v2`, 2026-10-26). Edit `flows.py`, then regenerate.
- Every flow has a draw.io diagram in `docs/mqtt-flows/drawio/` (open with
  https://app.diagrams.net or the draw.io desktop app) and the same chart below
  as Mermaid.
- Colours: blue = processing step, yellow = decision, green = table,
  purple = queue / topic, red = alarm / e-mail, grey = dropped, dashed = external.

Topic format (all gateway messages):
`/Acclivate/iOmniControl/<site_id>/<gateway_id>/in/<type>/<subtype>` - parsed by
`wareApp/mqtt/topics.py: parse_gateway_topic` into site id, gateway id, type and
subtype (for `recovery` the subtype selects the handler).

| Type | Listener | Processing queue | Handler |
| --- | --- | --- | --- |
| `consumption` | queue 1 | `mqtt.consumption.batch` -> 60 s flush | `consumption_batch.process_consumption_batch` |
| `SupplyTime` | queue 1 | `queue1_processing` | `supply_time.handle_supply_time_message` |
| `load` | queue 1 | `queue1_processing` | `load.handle_load_message` |
| `FIREALARM` | queue 1 | `queue1_processing` | `fire_alarm.handle_fire_alarm_message` |
| `recovery/hourlyConsumption` | queue 1 | `queue1_processing` | `hourly_consumption_recovery.handle_…` |
| `recovery/dailyConsumption` | queue 1 | `queue1_processing` | `daily_consumption_recovery.handle_…` |
| `recovery/loadRuntime` | queue 1 | `queue1_processing` | `load_runtime_recovery.handle_…` |
| `LoadData` | queue 2 | `queue2_processing` | `load_data.handler.handle_load_data_message` |
| `sync`, `remoteAccess` | not subscribed (server -> gateway commands) | - | - |
"""

COMMON_FAILURES = """
**Failure handling (all queue-1 handlers):** the task wrapper
`tasks._with_database_connection_cleanup` gives each packet a fresh DB connection
and retries transient database errors in place (`services/failures.run_with_db_retry`,
0.5 / 1 / 2 s), so the packet keeps its place in the site's order. Any other
error is stored as an `MqttDeadLetter` (`services/failures.record_dead_letter`)
and the handler returns `failed: …`; `manage.py replay_dead_letters` can process
it again.
"""

FLOWS = [
    # ------------------------------------------------------------------ 1
    {
        "slug": "01-overview", "anchor": "overview", "number": 1,
        "title": "Overview: from gateway to database",
        "summary": "Two isolated MQTT listeners receive every gateway packet and only queue it; "
                   "Celery workers process it in order per site and write the tables. "
                   "Timers drive the consumption flush and the recovery-status sweep.",
        "nodes": {
            "gw": ("Gateway\npublishes MQTT\n(QoS 1)", "ext", 2, 0),
            "mosq": ("Mosquitto broker\npersistent sessions", "ext", 2, 1),
            "l1": ("Listener queue 1\nmqtt-listener-queue1\nrun_mqtt_client1", "process", 1, 2),
            "l2": ("Listener queue 2\nmqtt-listener-queue2\nrun_mqtt_client2", "process", 3, 2),
            "kind": ("type =\nconsumption?", "decision", 1, 3),
            "qb": ("mqtt.consumption.batch\n(transient)", "queue", 0, 4),
            "q1": ("queue1_processing\n(transient)", "queue", 2, 4),
            "q2": ("queue2_processing\n(transient)", "queue", 3, 4),
            "beat": ("celerybeat\nevery 60 s", "ext", 0, 5),
            "flush": ("flush_consumption_batch\n(queue-1 worker)", "process", 0, 6),
            "w1": ("process_mqtt_message\n-> registry handler\n(queue-1 worker, 1 at a time)", "process", 2, 6),
            "w2": ("process_load_data_message\n(queue-2 worker)", "process", 3, 6),
            "db": ("PostgreSQL\nreadings, alarms,\nsync status", "db", 2, 7),
            "notif": ("notifications queue\n-> mqtt-notifications\n-> SMTP e-mail", "alarm", 0, 8),
            "pub": ("Recovery request\nMqttPublisher\n-> .../in/sync/...", "queue", 1, 8),
            "sweep": ("recovery-status-sweep.timer\nevery 5 min", "ext", 3, 8),
            "http": ("HTTP from gateways\n/api/v1/recovery/upload/\n/api/temp/dispatch/mail/\n/api/meter-disconnections/ingest/", "ext", 4, 6),
        },
        "edges": [
            ("gw", "mosq"), ("mosq", "l1", "consumption, SupplyTime, load,\nFIREALARM, recovery"),
            ("mosq", "l2", "LoadData"), ("l1", "kind"), ("kind", "qb", "yes"), ("kind", "q1", "no"),
            ("l2", "q2"), ("beat", "flush"), ("qb", "flush"), ("q1", "w1"), ("q2", "w2"),
            ("flush", "db"), ("w1", "db"), ("w2", "db"), ("http", "db"),
            ("db", "notif", "alarm stored"), ("db", "pub", "gap found"), ("pub", "mosq"),
            ("sweep", "db", "late / missing /\ntimeout / failed"),
        ],
        "files": [
            ("wareApp/mqtt/consumers.py", "run_mqtt_client1 / run_mqtt_client2, _queue_one_message_for_processing, _publish_options"),
            ("wareApp/mqtt/routing.py", "QUEUE_ONE/TWO subscriptions, processing_queue_for_site"),
            ("wareApp/mqtt/topics.py, envelope.py", "parse_gateway_topic, MqttEnvelope"),
            ("wareApp/mqtt/registry.py, handlers.py", "handler_for(type, subtype) -> handler class"),
            ("wareApp/tasks.py", "mqtt_client1/2, process_mqtt_message, _dispatch, flush_consumption_batch, process_load_data_message, send_notification"),
            ("warehouse/settings.py", "CELERY_BEAT_SCHEDULE, CELERY_TASK_QUEUES, MQTT_* settings"),
            ("deploy/systemd/*", "listener / processing / notifications units, sweep timer"),
        ],
        "details": """
**Receiving.** `wareApp/tasks.py: mqtt_client1 / mqtt_client2` run the two listeners
(`consumers.run_mqtt_client1 / 2`) inside their own Celery workers. Each Paho
client connects with `clean_session=False` and QoS 1, so Mosquitto keeps the
packets while a listener restarts. The listener only parses the topic
(`MqttEnvelope.from_mqtt`) and queues the packet; it never touches the database.

**Queues.** Packet tasks are published transient (`delivery_mode=1`,
`MQTT_TRANSIENT_MESSAGES`): no disk write per packet; a RabbitMQ restart loses the
few packets in flight and recovery re-requests those hours. Consumption packets go
to `mqtt.consumption.batch` (flow 2); every other queue-1 type to
`queue1_processing` (or `mqtt.site.N` with `MQTT_SITE_PARTITIONS`); LoadData to
`queue2_processing`.

**Processing.** The queue-1 worker runs with concurrency 1, so packets of a site are
handled strictly in order, and the 60 s consumption flush never overlaps a
recovery reply. `process_mqtt_message -> _dispatch` finds the handler with
`registry.handler_for(type, subtype)`, skips duplicate consumption packets
(`services/idempotency`), loads the site (`services/site_cache.site`) and calls
`handler.handle(...)`, which returns an outcome text (`stored: …`, `skipped: …`,
`failed: …`) shown in the Celery log.
""" + COMMON_FAILURES,
    },
    # ------------------------------------------------------------------ 2
    {
        "slug": "02-consumption-live", "anchor": "consumption-live", "number": 2,
        "title": "Consumption (live): batch every 60 s",
        "summary": "Hourly and daily energy per aisle. Packets are parked for up to a minute and "
                   "written in bulk with exactly the per-packet rules: current hour, new hour, first "
                   "reading, gap -> recovery request.",
        "nodes": {
            "in": ("consumption packet\n.../in/consumption/...", "ext", 1, 0),
            "park": ("listener: consumption_batch.enqueue\n-> mqtt.consumption.batch", "queue", 1, 1),
            "beat": ("celerybeat 60 s\nflush_consumption_batch", "ext", 3, 1),
            "drain": ("flush(): drain queue\n(up to 20 000 packets)", "process", 1, 2),
            "dup": ("same packet in\nlast 6 h?", "decision", 1, 3),
            "skipdup": ("skipped: duplicate", "skip", 0, 3),
            "parse": ("parse payload\nERROR!!! -> meter\nreading issue alarm", "process", 1, 4),
            "load": ("load aisles, hourly\nrows (2 days), daily\nrows: 3 queries", "process", 1, 5),
            "cur": ("current hour\nrow exists?", "decision", 1, 6),
            "upd": ("hour = gateway's\nCurrent_hour_total", "process", 0, 7),
            "prev": ("previous hour\nrow exists?", "decision", 2, 7),
            "newh": ("finish previous hour\n(total + saving),\ncreate new hour row", "process", 2, 8),
            "first": ("any reading\never?", "decision", 3, 8),
            "firstrow": ("first reading:\ncreate hour + day rows", "process", 4, 8),
            "gap": ("gap: request\nrecovery (flow 4)\npacket dropped", "skip", 3, 9),
            "day": ("day total = sum of\nthe day's hourly rows\nsaving = baseline - total", "process", 1, 9),
            "newday": ("new day?\n-> yesterday's alarms\n(flow 9)", "alarm", 0, 10),
            "bulk": ("bulk_update / bulk_create\none statement per table\nBULK lines in log", "db", 1, 11),
            "healthy": ("mark_sync_healthy\nack messages", "process", 2, 11),
        },
        "edges": [
            ("in", "park"), ("park", "drain"), ("beat", "drain"), ("drain", "dup"),
            ("dup", "skipdup", "yes"), ("dup", "parse", "no"), ("parse", "load"), ("load", "cur"),
            ("cur", "upd", "yes"), ("cur", "prev", "no"), ("prev", "newh", "yes"),
            ("prev", "first", "no"), ("first", "firstrow", "no"), ("first", "gap", "yes"),
            ("upd", "day"), ("newh", "day"), ("day", "newday"), ("day", "bulk"),
            ("firstrow", "bulk"), ("bulk", "healthy"),
        ],
        "files": [
            ("wareApp/mqtt/consumption_batch.py", "enqueue, flush, process_consumption_batch, _parse, _load_states, _apply, _day_total, _as_saved, _bulk"),
            ("wareApp/mqtt/consumption.py", "per-packet rules (MQTT_CONSUMPTION_BATCH_SECONDS=0): handle_consumption_message, _parse_consumption_message, _notify_meter_reading_issue, _consumption_recovery_request"),
            ("wareApp/mqtt/services/idempotency.py", "claim / release (6 h duplicate check)"),
            ("wareApp/mqtt/services/baseline.py", "BaselineMemo, baseline_info, hourly_baseline"),
            ("wareApp/mqtt/sync_status.py", "mark_sync_healthy"),
            ("wareApp/tasks.py", "flush_consumption_batch"),
            ("Tables", "HourlySiteReading, DailySiteReading, SensorAisleUnitConsumption, AisleSyncRecoveryStatus"),
        ],
        "details": """
**Payload** (`consumption._parse_consumption_message`): consumption time, new units
since the last packet, hour, current-hour total, aisle group (leg) id and the
previous hour's final total. Warehouse-saving sites (`site_type 2`) treat values
over 10 000 as meter glitches (`_cap_warehouse_saving_values`).

**Rules per aisle, in arrival order** (`consumption_batch._apply`, identical to
`consumption.handle_consumption_message`):

1. *Current hour row exists:* set its consumption to the gateway's running total
   for that hour.
2. *New hour (previous hour exists):* set the previous hour to its final total,
   compute its saving (`hourly baseline - consumption`, active aisles only),
   create the new hour row with its baseline.
3. *First reading ever:* create the hour row and today's daily row.
4. *Gap* (neither current nor previous hour, but older data exists): request
   recovery from the gateway (flow 4, once per 10-minute cooldown) and drop the
   packet; live packets keep being dropped until the gap is filled.
5. *Daily row:* consumption = sum of the day's hourly rows, saving = daily
   baseline - total. Creating today's row evaluates yesterday's alarms (flow 9).
6. *Sensor aisles* (`on_sensor_power`) also get a `SensorAisleUnitConsumption` row.

**Writing.** All changes are written in one transaction, one `bulk_update` /
`bulk_create` per table (`_bulk` logs `BULK UPDATE HourlySiteReading (consumption
batch): rows=… aisles=… duration=… ms`). New rows get the same cleaning the
models' `save()` applies (`CleanReadingMixin`: NaN/negative -> 0, > 10 000 -> 0).
RabbitMQ messages are acknowledged only after the commit; on an error they are
re-queued for the next flush. `ERROR!!!` packets raise the Meter Reading Issue
alarm (flow 9). Summary line: `consumption batch: N packets, stored=… skipped=…
failed=… aisles=… in … ms`.
""",
    },
    # ------------------------------------------------------------------ 3
    {
        "slug": "03-supply-time", "anchor": "supply-time", "number": 3,
        "title": "SupplyTime: run time per power source",
        "summary": "Minutes each power source (mains, DG) ran in the hour. Same gap logic as "
                   "consumption, per power source, using the loadRuntime recovery.",
        "nodes": {
            "in": ("SupplyTime packet\nsource, runtime, time", "ext", 1, 0),
            "q": ("queue1_processing\nprocess_mqtt_message", "queue", 1, 1),
            "parse": ("_parse_supply_time_message", "process", 1, 2),
            "cur": ("current hour row\nfor this source?", "decision", 1, 3),
            "add": ("hourly_run_time\n+= runtime", "db", 0, 4),
            "month": ("new month?\n_update_monthly_share_if_due\n-> MonthlyLoadSharePercentage", "db", 2, 4),
            "prev": ("previous hour stored\nor no data at all?", "decision", 2, 5),
            "create": ("create hour row\nSupplyLoadTimeShare", "db", 1, 6),
            "cool": ("recovery requested\nin last 10 min?", "decision", 3, 6),
            "skip": ("skipped (cooldown)", "skip", 4, 6),
            "req": ("request_recovery\nloadRuntime -> publish\n.../in/sync/loadTime/state", "queue", 3, 7),
            "healthy": ("mark_source_healthy", "process", 0, 7),
        },
        "edges": [
            ("in", "q"), ("q", "parse"), ("parse", "cur"), ("cur", "add", "yes"),
            ("cur", "month", "no"), ("month", "prev"), ("prev", "create", "yes"),
            ("prev", "cool", "no (gap)"), ("cool", "skip", "yes"), ("cool", "req", "no"),
            ("add", "healthy"), ("create", "healthy"),
        ],
        "files": [
            ("wareApp/mqtt/supply_time.py", "handle_supply_time_message, _parse_supply_time_message, _previous_hour_exists, _update_monthly_share_if_due"),
            ("wareApp/mqtt/services/cooldown.py", "recovery_request_allowed (scope 'source')"),
            ("wareApp/mqtt/services/recovery_status.py", "RecoveryStatusService.request_recovery (LOAD_RUNTIME)"),
            ("wareApp/mqtt/sync_status.py", "mark_source_healthy"),
            ("Tables", "SupplyLoadTimeShare, MonthlyLoadSharePercentage, AisleSyncRecoveryStatus, RecoveryMonitor"),
        ],
        "details": """
- **Current hour exists:** add the packet's run time to `hourly_run_time` (one UPDATE).
- **New hour:** at a month change first store last month's time share per source
  (`_update_monthly_share_if_due`). Then, if the previous hour is stored (or this
  source has no data yet), create the hour row.
- **Gap:** like consumption, but per power source: one recovery request per 10 min
  (`recovery_request_allowed(site, "source", source)`), recorded in
  `RecoveryMonitor` / `AisleSyncRecoveryStatus` (power_source rows) and published
  to `.../in/sync/loadTime/state` with the last stored hour and the missed seconds.
  The gateway answers on `recovery/loadRuntime` (flow 6).
""" + COMMON_FAILURES,
    },
    # ------------------------------------------------------------------ 4
    {
        "slug": "04-recovery-lifecycle", "anchor": "recovery-lifecycle", "number": 4,
        "title": "Recovery request lifecycle (sync requests)",
        "summary": "What happens after a gap is found: the request, retries, failure and the "
                   "per-aisle sync status, until the gateway's reply fills the gap.",
        "nodes": {
            "gap": ("live packet finds a gap\n(consumption / SupplyTime)", "ext", 1, 0),
            "cool": ("cooldown open?\n(10 min, per aisle/source)", "decision", 1, 1),
            "drop": ("packet dropped\n'already requested'", "skip", 0, 1),
            "open": ("open RecoveryMonitor\nfor this gap?", "decision", 1, 2),
            "max": ("attempts >= 3?", "decision", 2, 3),
            "failed": ("status failed\nno more requests\n(new try after 6 h)", "alarm", 3, 3),
            "new": ("create RecoveryMonitor\nmissing_from..to\nattempt 1", "db", 0, 3),
            "retry": ("attempt + 1", "process", 2, 4),
            "pub": ("publish sync request\nafter commit\nsync_status = recovery_requested", "queue", 1, 5),
            "reply": ("gateway reply\nrecovery/hourlyConsumption\n/ dailyConsumption / loadRuntime", "ext", 1, 6),
            "resp": ("record_response\n(response_received)", "process", 1, 7),
            "apply": ("upsert slots\n(flows 5, 6)\nrecord_applied", "db", 1, 8),
            "all": ("every missing hour\npresent?", "decision", 1, 9),
            "ok": ("recovered ->\nnext packet: healthy", "process", 0, 10),
            "partial": ("stays open:\nretried like no answer", "skip", 2, 10),
            "sweep": ("sweep every 5 min:\nno answer after 10 min\n-> timeout", "ext", 3, 6),
        },
        "edges": [
            ("gap", "cool"), ("cool", "drop", "yes"), ("cool", "open", "no"),
            ("open", "new", "no"), ("open", "max", "yes"), ("max", "failed", "yes"),
            ("max", "retry", "no"), ("new", "pub"), ("retry", "pub"), ("pub", "reply"),
            ("reply", "resp"), ("resp", "apply"), ("apply", "all"), ("all", "ok", "yes"),
            ("all", "partial", "no"), ("sweep", "retry", "timeout"),
        ],
        "files": [
            ("wareApp/mqtt/services/recovery_status.py", "RecoveryScope, RecoveryStatusService.request_recovery / record_response / record_applied / _catch_up_slot"),
            ("wareApp/mqtt/services/cooldown.py", "recovery_request_allowed, release_recovery_request"),
            ("wareApp/mqtt/services/publisher.py", "MqttPublisher, publish_after_commit"),
            ("wareApp/mqtt/sync_status.py", "upsert_status, mark_sync_healthy, mark_source_healthy"),
            ("wareApp/management/commands/recovery_status_sweep.py", "sweep(): timeout / failed / late / missing"),
            ("wareApp/admin.py", "AisleSyncRecoveryStatusAdmin, retry recovery action"),
            ("Tables", "RecoveryMonitor (history), AisleSyncRecoveryStatus (current state)"),
        ],
        "details": """
**States** (`AisleSyncRecoveryStatus.sync_status`, one row per aisle or power source):
`healthy -> recovery_requested -> recovery_received -> recovered -> healthy`;
no answer -> retried; 3 attempts (`MQTT_RECOVERY_MAX_ATTEMPTS`) -> `failed`;
a failed gap may start a fresh request after 6 h (`MQTT_RECOVERY_FAILED_RETRY_SECONDS`).
Independent of requests, the sweep marks an aisle `late` after 70 min and
`missing` after 130 min without a stored reading.

**Request** (`RecoveryStatusService.request_recovery`): records the missing range
in `RecoveryMonitor`, sets the status and decides whether to publish. Topics:
`.../in/sync/consumption/state` (consumption) and `.../in/sync/loadTime/state`
(SupplyTime). The publisher keeps one connected Paho client per worker process
and publishes only after the DB transaction commits.

**Reply:** the gateway answers on `recovery/<subtype>` (or via HTTP, flow 12).
`record_response` and `record_applied` mark what arrived; when every missing hour
is present the gap is `recovered` and the next live packet makes it `healthy`.
`ERROR404` values mean the gateway itself has no data: stored as 0, counted as
resolved, `has_data_loss` set; the first hour with data afterwards
(`catch_up_at`) carries the outage's consumption and is skipped by alarms.

**Manual retry:** admin -> Aisle sync recovery status -> "retry recovery" re-arms
failed requests (the next gap packet publishes again).
""",
    },
    # ------------------------------------------------------------------ 5
    {
        "slug": "05-consumption-recovery", "anchor": "consumption-recovery", "number": 5,
        "title": "Consumption recovery replies (hourly and daily)",
        "summary": "The gateway's answer to a consumption sync request: the missing hours "
                   "(hourlyConsumption) or days (dailyConsumption) of one aisle, written in bulk.",
        "nodes": {
            "in": ("recovery/hourlyConsumption\nor recovery/dailyConsumption", "ext", 1, 0),
            "q": ("queue1_processing", "queue", 1, 1),
            "parse": ("parse: aisle group,\nhours or dates, values\n(ERROR404 -> 0)", "process", 1, 2),
            "aisle": ("aisle group\nexists?", "decision", 1, 3),
            "dead": ("dead letter", "skip", 0, 3),
            "slots": ("per slot: baseline,\nconsumption, saving\n(active aisles)", "process", 1, 4),
            "resp": ("record_response", "process", 1, 5),
            "ups": ("upsert_slots:\nbulk_update existing,\nbulk_create missing", "db", 1, 6),
            "applied": ("record_applied\n(recovered when complete)", "process", 1, 7),
            "log": ("BULK UPDATE / BULK CREATE\nlog line with ms", "process", 2, 7),
            "alarms": ("evaluate_days: alarms\nfor recovered past days\n(last 7 days)", "alarm", 1, 8),
            "note": ("daily total re-summed by the\nnext live packet (flow 2)", "skip", 2, 8),
        },
        "edges": [
            ("in", "q"), ("q", "parse"), ("parse", "aisle"), ("aisle", "dead", "no"),
            ("aisle", "slots", "yes"), ("slots", "resp"), ("resp", "ups"), ("ups", "applied"),
            ("ups", "log"), ("applied", "alarms"), ("applied", "note"),
        ],
        "files": [
            ("wareApp/mqtt/hourly_consumption_recovery.py", "handle_hourly_consumption_recovery_message, _parse_hourly_recovery_message"),
            ("wareApp/mqtt/daily_consumption_recovery.py", "handle_daily_consumption_recovery_message, _parse_daily_recovery_message, _baseline_for_day"),
            ("wareApp/mqtt/slot_writes.py", "upsert_slots -> SlotWriteResult (updated, created, ms)"),
            ("wareApp/mqtt/log_format.py", "log_bulk_write, hour_ranges, day_ranges"),
            ("wareApp/mqtt/services/consumption_alarms.py", "evaluate_days"),
            ("Tables", "HourlySiteReading (hourly), DailySiteReading (daily), RecoveryMonitor, AisleSyncRecoveryStatus"),
        ],
        "details": """
**Payloads:** hourly
`Aisle_group_id : <leg>; Recovery_Hours : [...]; Unit_consumptions : [...]; GW_total_cumulative : …`;
daily `Aisle_group_id : <leg>; Recovery_Dates : [...]; Unit_consumptions : [...]; GW_Total_cumulative : …`.

Each slot (hour or day) gets consumption, baseline (`BaselineMemo.for_day`) and
saving; `ERROR404` slots are stored as 0. Existing rows are updated and missing
ones created in bulk (`upsert_slots`), inside one transaction together with the
recovery status (`record_response` / `record_applied`). Afterwards
`evaluate_days` re-checks the day-end alarms of the recovered days (only the last
`ALARM_REEVALUATE_DAYS` = 7), and a single warning lists days whose baseline is
missing. The daily total of a day changed by an hourly recovery is set to the sum
of its hourly rows by the next live packet of that day.
""" + COMMON_FAILURES,
    },
    # ------------------------------------------------------------------ 6
    {
        "slug": "06-load-runtime-recovery", "anchor": "load-runtime-recovery", "number": 6,
        "title": "Load runtime recovery replies",
        "summary": "The gateway's answer to a SupplyTime sync request: missing hourly run times of "
                   "one power source.",
        "nodes": {
            "in": ("recovery/loadRuntime\nPower_source; hours; runtimes", "ext", 1, 0),
            "q": ("queue1_processing", "queue", 1, 1),
            "parse": ("_parse_load_runtime_\nrecovery_message\n(ERROR404 -> 0)", "process", 1, 2),
            "resp": ("record_response", "process", 1, 3),
            "ups": ("upsert_slots\nSupplyLoadTimeShare\nhourly_run_time", "db", 1, 4),
            "applied": ("record_applied", "process", 1, 5),
            "log": ("BULK lines in log", "process", 2, 5),
        },
        "edges": [("in", "q"), ("q", "parse"), ("parse", "resp"), ("resp", "ups"),
                  ("ups", "applied"), ("ups", "log")],
        "files": [
            ("wareApp/mqtt/load_runtime_recovery.py", "handle_load_runtime_recovery_message, _parse_load_runtime_recovery_message"),
            ("wareApp/mqtt/slot_writes.py", "upsert_slots"),
            ("wareApp/mqtt/services/recovery_status.py", "record_response, record_applied (LOAD_RUNTIME)"),
            ("Tables", "SupplyLoadTimeShare, RecoveryMonitor, AisleSyncRecoveryStatus"),
        ],
        "details": """
Payload `Power_source : <n>; Recovery_hours : [...]; Recovery_load_runtime : [...]`.
Each hour's run time is written to `SupplyLoadTimeShare` (update or create in
bulk); the recovery status of that power source moves to recovered when every
missing hour is present. No alarms are evaluated for run time.
""" + COMMON_FAILURES,
    },
    # ------------------------------------------------------------------ 7
    {
        "slug": "07-load", "anchor": "load", "number": 7,
        "title": "Load: live load, voltage and power-factor alarms",
        "summary": "Real-time load and phase values per meter and power source; updates the live "
                   "table and raises high / low voltage and power-factor alarms.",
        "nodes": {
            "in": ("load packet\nload, R/Y/B volt + current,\nPF, source, status, meter", "ext", 1, 0),
            "q": ("queue1_processing", "queue", 1, 1),
            "parse": ("_parse_load_message", "process", 1, 2),
            "volt": ("show_voltage_alarms\nand all phases > 0?", "decision", 1, 3),
            "vrec": ("_record_voltage_alarm\nhigh (0) and low (1):\nstore SiteLoadParameters", "db", 0, 4),
            "v5": ("last 5 readings all\noutside thresholds\nand none in 30 min?", "decision", 0, 5),
            "valarm": ("NewAlarmsNotifications\ntype 0 / 1 + e-mail", "alarm", 0, 6),
            "exists": ("SiteLoadPower row\nfor source+meter?", "decision", 2, 4),
            "new": ("create SiteLoadPower\n(first packet)", "db", 3, 4),
            "pf": ("_record_power_factor_alarm\n(status ON, PF thresholds set)", "decision", 2, 5),
            "pfrow": ("PowerFactorData +\nNewAlarmsNotifications\ntype 2 (30 min) + e-mail", "alarm", 3, 6),
            "upd": ("update SiteLoadPower\nload, volts, currents, PF", "db", 2, 6),
        },
        "edges": [
            ("in", "q"), ("q", "parse"), ("parse", "volt"), ("volt", "vrec", "yes"),
            ("vrec", "v5"), ("v5", "valarm", "yes"), ("volt", "exists", "no / after"),
            ("exists", "new", "no"), ("exists", "pf", "yes"), ("pf", "pfrow", "below threshold"),
            ("pf", "upd"),
        ],
        "files": [
            ("wareApp/mqtt/load.py", "handle_load_message, _parse_load_message, _record_voltage_alarm, _record_power_factor_alarm"),
            ("wareApp/mqtt/services/notifications.py", "notify (send_alarm_for_high_voltage / low_voltage, send_mail_for_pf_fluctuation)"),
            ("wareApp/sendmail.py", "send_alarm_for_high_voltage, send_alarm_for_low_voltage, send_mail_for_pf_fluctuation"),
            ("Tables", "SiteLoadPower, SiteLoadParameters, PowerFactorData, NewAlarmsNotifications"),
            ("Site settings", "show_voltage_alarms, r/y/b_phase_voltage_threshold_max/min, is_pf_visible, r/y/b_phase_pf_threshold"),
        ],
        "details": """
- **Voltage alarms** (only with `site.show_voltage_alarms` and all phases > 0): every
  packet is stored in `SiteLoadParameters` for high (0) and low (1); an alarm needs
  the last 5 readings all above the max (or below the min) thresholds and no alarm
  of that type and source in the last 30 minutes -> `NewAlarmsNotifications` + e-mail.
- **Power factor** (only with `site.is_pf_visible`, status ON and all three PF
  thresholds set; otherwise skipped and logged once an hour per site): any phase
  below its threshold stores `PowerFactorData`; at most one alarm per source per
  30 minutes -> `NewAlarmsNotifications` type 2 + e-mail.
- The live row `SiteLoadPower` (per site, source, meter) is created by the first
  packet and updated by every later one (load, volts, currents, PF, status).
""" + COMMON_FAILURES,
    },
    # ------------------------------------------------------------------ 8
    {
        "slug": "08-fire-alarm", "anchor": "fire-alarm", "number": 8,
        "title": "FIREALARM: fire pump state",
        "summary": "Fire-pump panel phases and motor status; mode changes and motor-on events are "
                   "e-mailed to the customer.",
        "nodes": {
            "in": ("FIREALARM packet\nmeter, R/Y/B volt,\npower status", "ext", 1, 0),
            "q": ("queue1_processing", "queue", 1, 1),
            "rec": ("FirePumpAlarm row\nfor this meter?", "decision", 1, 2),
            "skip": ("skipped: no fire\npump record", "skip", 0, 2),
            "upd": ("update FirePumpAlarm\n(keep previous volts)", "db", 1, 3),
            "motor": ("motor on in Auto\n(R>200,Y<100,B>200) or\nManual (R<100,Y>200,B>200)?", "decision", 1, 4),
            "thr": ("same e-mail in\nlast 10 min?", "decision", 0, 5),
            "mail1": ("e-mail 'Motor-On in\nAuto/Manual-Mode'\n+ Email_History", "alarm", 0, 6),
            "mode": ("previous vs new phases:\nmode changed\n(Auto/Manual/Off)?", "decision", 2, 5),
            "mail2": ("e-mail mode change\n+ Email_History", "alarm", 2, 6),
        },
        "edges": [
            ("in", "q"), ("q", "rec"), ("rec", "skip", "no"), ("rec", "upd", "yes"),
            ("upd", "motor"), ("motor", "thr", "yes"), ("thr", "mail1", "no"), ("upd", "mode"),
            ("mode", "mail2", "yes"),
        ],
        "files": [
            ("wareApp/mqtt/fire_alarm.py", "handle_fire_alarm_message, _parse_fire_alarm_message, _send_fire_alarm_email, _send_throttled_motor_on_email"),
            ("wareApp/sendmail.py", "send_mail_fire_alarm_user"),
            ("Tables", "FirePumpAlarm, Email_History"),
        ],
        "details": """
The phase pattern encodes the panel mode: R > 200, Y < 100, B > 200 = Auto;
R < 100, Y > 200, B > 200 = Manual. The handler keeps the previous voltages
before updating `FirePumpAlarm`, compares old and new pattern to detect a mode
change (e.g. Off-Mode to Auto-Mode) and e-mails the site's customer. "Motor on"
e-mails are limited to one per device per 10 minutes (`Email_History`,
`email_for=5`).
""" + COMMON_FAILURES,
    },
    # ------------------------------------------------------------------ 9
    {
        "slug": "09-day-end-alarms", "anchor": "day-end-alarms", "number": 9,
        "title": "Day-end consumption alarms (Bypassed / High / Low / Operation hours) and Meter Reading Issue",
        "summary": "Each completed day of each aisle is compared with its own baseline. Bypassed is "
                   "automatic at 100 %, High at 75 %, Low only where configured.",
        "nodes": {
            "t1": ("new day's first packet\n(flow 2)", "ext", 0, 0),
            "t2": ("recovery rewrote past\ndays (flow 5, <= 7 days)", "ext", 1, 0),
            "t3": ("manage.py\nreplay_consumption_alarms", "ext", 2, 0),
            "eval": ("evaluate_daily_alarms\n(site, aisle, daily row)", "process", 1, 1),
            "base": ("baseline for\nthe day?", "decision", 1, 2),
            "none": ("no alarm", "skip", 0, 2),
            "byp": ("consumption >= baseline x 100 %\n(or site bypass kWh)?", "decision", 1, 3),
            "rbyp": ("Bypassed (11)", "alarm", 0, 4),
            "ops": ("NL window set and active\nhours outside / too many?", "decision", 2, 4),
            "rops": ("Operation Hours\nIncreased (12)", "alarm", 3, 4),
            "high": ("consumption >= site high kWh\nor baseline x 75 %?", "decision", 1, 5),
            "rhigh": ("High Consumption (7)", "alarm", 0, 6),
            "low": ("site low % set and\nconsumption < baseline x (1-%)?", "decision", 2, 6),
            "rlow": ("Low Consumption (8)", "alarm", 3, 6),
            "rec": ("_record: one alarm per\naisle/type/day ->\nAlarmNotifications + notify", "db", 1, 7),
            "meter": ("ERROR!!! packet ->\n_notify_meter_reading_issue\n(10): 1 e-mail / meter / day", "alarm", 3, 1),
        },
        "edges": [
            ("t1", "eval"), ("t2", "eval"), ("t3", "eval"), ("eval", "base"),
            ("base", "none", "no"), ("base", "byp", "yes"), ("byp", "rbyp", "yes"),
            ("byp", "ops", "no"), ("ops", "rops", "yes"), ("ops", "high"),
            ("high", "rhigh", "yes"), ("high", "low", "no"), ("low", "rlow", "yes"),
            ("rbyp", "rec"), ("rhigh", "rec"), ("rops", "rec"), ("rlow", "rec"),
        ],
        "files": [
            ("wareApp/mqtt/services/consumption_alarms.py", "evaluate_daily_alarms, evaluate_days, _bypass_threshold, _high_percent, operation_hours_check, _record"),
            ("wareApp/mqtt/consumption.py", "_consumption_alarms, _notify_meter_reading_issue"),
            ("wareApp/mqtt/consumption_batch.py", "alarm_days -> yesterday's alarms after the bulk write"),
            ("wareApp/management/commands/replay_consumption_alarms.py", "day-by-day replay (dry run / --apply / --email-site)"),
            ("wareApp/mqtt/services/baseline.py", "baseline_info"),
            ("Site settings", "bypass_consumption_units, high_consumption_units, high_consumption_baseline_percent, min_threshold_value, nl_operation_hours/start/end"),
            ("Settings", "ALARM_BYPASS_DEFAULT_PERCENT=100, ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT=75, ALARM_ACTIVITY_THRESHOLD_KWH, ALARM_REEVALUATE_DAYS"),
            ("Tables", "AlarmNotifications (Alarm_type 7, 8, 10, 11, 12)"),
        ],
        "details": """
**When:** the first packet of a new day evaluates *yesterday* for that aisle; a
recovery that rewrote past days re-evaluates those days (last 7); the replay
command evaluates any period day by day.

**Order of checks** (`evaluate_daily_alarms`), per aisle and day, against the
aisle's own daily baseline (`SiteBaseline`; no baseline -> no alarm):
1. **Bypassed (11):** consumption >= baseline x `ALARM_BYPASS_DEFAULT_PERCENT` (100 %:
   no saving at all), or >= `site.bypass_consumption_units` when set. Stops here.
2. **Operation Hours Increased (12):** NL aisles of sites with an NL window: an
   hour with >= 0.01 kWh outside the window, or more active hours than allowed.
3. **High Consumption (7):** >= `site.high_consumption_units`, else >= baseline x
   75 % (`high_consumption_baseline_percent` / `ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT`).
   Names Operation Hours as the cause when both fire.
4. **Low Consumption (8):** only where `site.min_threshold_value` is set:
   consumption < baseline x (1 - value %).

**Stored** at most once per site, aisle, type and day (`_record`), with the reason
in `to_do`, then e-mailed (flow 10). **Meter Reading Issue (10)** comes from live
`ERROR!!!` consumption packets: the first per meter and day is stored and
e-mailed; repeats only update `last_seen` / `occurrences`.
""",
    },
    # ------------------------------------------------------------------ 10
    {
        "slug": "10-alarm-email", "anchor": "alarm-email", "number": 10,
        "title": "Alarm e-mail pipeline",
        "summary": "Every alarm e-mail goes through the notifications queue to its own worker, so a "
                   "slow mail server never blocks MQTT processing.",
        "nodes": {
            "alarm": ("alarm stored by a handler\n(flows 7, 8, 9, 12)", "ext", 1, 0),
            "notify": ("notify(send_function, args)", "process", 1, 1),
            "commit": ("after the DB commit:\nqueue available?", "decision", 1, 2),
            "q": ("notifications queue\n(persistent)", "queue", 0, 3),
            "direct": ("send directly\n(fallback, logged)", "process", 2, 3),
            "worker": ("mqtt-notifications\nsend_notification\n(allow-listed functions)", "process", 0, 4),
            "send": ("sendmail.<function>\n-> _send_smtp_email", "process", 1, 5),
            "over": ("ALARM_EMAIL_OVERRIDE_TO\nset?", "decision", 1, 6),
            "test": ("only to override address\n(+ 'TEST REDIRECT' banner)", "alarm", 0, 7),
            "real": ("real recipients /\nALARM_EMAIL_DEFAULT_TO", "alarm", 2, 7),
            "smtp": ("SMTP (EMAIL_* in .env)\n'Email sent' / 'Email failed'", "ext", 1, 8),
        },
        "edges": [
            ("alarm", "notify"), ("notify", "commit"), ("commit", "q", "yes"),
            ("commit", "direct", "no"), ("q", "worker"), ("worker", "send"), ("direct", "send"),
            ("send", "over"), ("over", "test", "yes"), ("over", "real", "no"),
            ("test", "smtp"), ("real", "smtp"),
        ],
        "files": [
            ("wareApp/mqtt/services/notifications.py", "notify, ALLOWED_NOTIFICATIONS, QUEUE_ERRORS fallback"),
            ("wareApp/tasks.py", "send_notification (retries 5x on exceptions)"),
            ("wareApp/sendmail.py", "_send_smtp_email, _smtp_config, send_alarm_email, send_alarm_for_high/low_voltage, send_mail_for_pf_fluctuation, send_mail_fire_alarm_user"),
            ("Settings", "MQTT_ASYNC_NOTIFICATIONS, ALARM_EMAIL_OVERRIDE_TO, ALARM_EMAIL_DEFAULT_TO, EMAIL_HOST / PORT / USE_TLS / HOST_USER / HOST_PASSWORD"),
        ],
        "details": """
`notify()` queues the e-mail after the alarm's transaction commits (an alarm that
is rolled back never e-mails). If RabbitMQ is unavailable, the e-mail is sent
directly instead (`Notification queue unavailable … sending directly`). The
worker accepts only allow-listed function names. `_send_smtp_email` uses the
`EMAIL_*` settings from `.env`; while `ALARM_EMAIL_OVERRIDE_TO` is set (test),
every alarm goes only to that address with the intended recipients shown in a
banner. Each send logs `Email sent: subject=… to=…` or `Email failed: … error=…`.
A failed send (SMTP refused) is not retried today.
""",
    },
    # ------------------------------------------------------------------ 11
    {
        "slug": "11-loaddata", "anchor": "loaddata", "number": 11,
        "title": "LoadData (queue 2): load graph data",
        "summary": "Second-level load readings for the load graphs: raw rows, monthly min/max and "
                   "minute / hour roll-ups. Failures become replayable dead letters.",
        "nodes": {
            "in": ("LoadData packet\nload_value, leg_id,\nmeter, date, epoch", "ext", 1, 0),
            "l2": ("listener queue 2\n-> queue2_processing", "queue", 1, 1),
            "task": ("process_load_data_message\n-> handle_load_data_message", "process", 1, 2),
            "aisle": ("aisle group\nfor leg?", "decision", 1, 3),
            "raw": ("RawLoadData\n(one row per reading)", "db", 1, 4),
            "month": ("load graph visible?\nupdate_monthly_min_max_load\n-> MonthlyMinMaxLoadData", "db", 0, 5),
            "roll": ("roll_up_load_data_if_due\n(once per site per minute)", "process", 2, 5),
            "min": ("finished minutes:\nmin/max -> HourlyLoadData\n+ MainsDgLoadData", "db", 2, 6),
            "hour": ("finished hours:\nmin/max -> DailyLoadData", "db", 2, 7),
            "err": ("error: transient DB -> retry;\nothers -> MqttDeadLetter\n'LoadData'", "skip", 0, 3),
            "replay": ("manage.py\nreplay_dead_letters", "ext", 0, 4),
        },
        "edges": [
            ("in", "l2"), ("l2", "task"), ("task", "aisle"), ("aisle", "raw", "yes"),
            ("aisle", "err", "no"), ("raw", "month"), ("raw", "roll"), ("roll", "min"),
            ("min", "hour"), ("err", "replay"),
        ],
        "files": [
            ("wareApp/mqtt/consumers.py", "run_mqtt_client2"),
            ("wareApp/tasks.py", "process_load_data_message"),
            ("wareApp/load_data/handler.py", "handle_load_data_message (outcome text, dead letters)"),
            ("wareApp/load_data/parser.py", "parse_load_data_message -> LoadReading"),
            ("wareApp/load_data/raw.py, monthly.py", "save_raw_load_reading, update_monthly_min_max_load"),
            ("wareApp/load_data/rollups.py", "roll_up_load_data_if_due, roll_up_completed_load_data, _save_batched_extrema"),
            ("wareApp/management/commands/replay_dead_letters.py", "replay failed packets (dry run / --apply)"),
            ("Tables", "RawLoadData, MonthlyMinMaxLoadData, HourlyLoadData, MainsDgLoadData, DailyLoadData, MqttDeadLetter"),
        ],
        "details": """
Each reading is stored raw (`RawLoadData`). If the site shows the load graph,
the month's minimum / maximum per source is kept in `MonthlyMinMaxLoadData`.
Once per site per minute, `roll_up_load_data_if_due` turns the finished minutes
(looking back `LOAD_DATA_ROLLUP_LOOKBACK_MINUTES`, 6 h) into min/max rows in
`HourlyLoadData` and `MainsDgLoadData`, and once per hour the finished hours into
`DailyLoadData`; buckets that already exist are skipped, so the roll-up is
idempotent (bulk inserts, logged as BULK CREATE).

Errors: transient database errors are re-raised so the task retries; every other
failure is stored as an `MqttDeadLetter` "LoadData" (configuration / payload errors
once per gateway per 10 min, unexpected errors every packet) and can be replayed
with `manage.py replay_dead_letters --type LoadData --apply`.
""",
    },
    # ------------------------------------------------------------------ 12
    {
        "slug": "12-http-from-gateways", "anchor": "http-from-gateways", "number": 12,
        "title": "HTTP calls from gateways",
        "summary": "Three things gateways send over HTTP instead of MQTT: bulk recovery uploads, "
                   "overheat alerts and meter-disconnection events.",
        "nodes": {
            "rec": ("POST /api/v1/recovery/upload/\n'Recovery Payload'", "ext", 0, 0),
            "proc": ("process_http_recovery\nhourly / daily / runtime", "process", 0, 1),
            "recdb": ("same tables and recovery\nstatus as flows 5, 6", "db", 0, 2),
            "heat": ("POST /api/temp/dispatch/mail/\nCPU >= 85 °C (every ~3 s)", "ext", 1, 0),
            "parse": ("parse_alert:\nsite, gateway, temperature", "process", 1, 1),
            "store": ("store once / 60 s:\nAlarmNotifications type 13\n(1 row per gateway per day)", "db", 1, 2),
            "mail": ("e-mail 'Gateway Overheat'\nonce per gateway per hour", "alarm", 1, 3),
            "md": ("POST /api/meter-disconnections/\ningest/", "ext", 2, 0),
            "mde": ("MeterDisconnectionEvent\n(create or update window)", "db", 2, 1),
        },
        "edges": [
            ("rec", "proc"), ("proc", "recdb"), ("heat", "parse"), ("parse", "store"),
            ("store", "mail"), ("md", "mde"),
        ],
        "files": [
            ("wareApp/recovery/views.py, urls.py", "RecoveryUploadAPIView (/api/v1/recovery/upload/)"),
            ("wareApp/recovery/processor.py, service.py", "process_http_recovery, process_hourly, process_runtime, update_daily_from_hourly"),
            ("wareApp/views/gateway_overheat.py", "GatewayOverheatAlertApi (throttle gateway_overheat 60/min)"),
            ("wareApp/gateway_overheat.py", "parse_alert, record_overheat"),
            ("wareApp/views/monitoring.py", "MeterDisconnectionIngestView"),
            ("Tables", "HourlySiteReading, DailySiteReading, SupplyLoadTimeShare, AlarmNotifications, MeterDisconnectionEvent"),
        ],
        "details": """
- **Recovery upload:** large recoveries can come over HTTP; the payload carries the
  original topic, site, gateway and data, and is processed with the same rules and
  recovery status as the MQTT replies.
- **Gateway overheat:** the gateway's temperature monitor posts while the CPU is at
  or above 85 °C. One alarm row per site, gateway and day (repeats update
  `last_seen` / `occurrences`), stored at most once a minute, e-mailed at most once
  an hour (`GATEWAY_OVERHEAT_STORE_SECONDS`, `GATEWAY_OVERHEAT_EMAIL_SECONDS`). Shown in
  the alarm list as a gateway alarm.
- **Meter disconnections:** the gateway's log watcher reports a disconnected meter
  with its detection window; stored as `MeterDisconnectionEvent` (no alarm or e-mail yet).
""",
    },
    # ------------------------------------------------------------------ 13
    {
        "slug": "13-timers-and-checks", "anchor": "timers-and-checks", "number": 13,
        "title": "Timers, sweeps and maintenance commands",
        "summary": "Everything that runs on a schedule or by hand around the MQTT pipeline.",
        "nodes": {
            "beat": ("celerybeat\nevery 60 s", "ext", 0, 0),
            "flush": ("flush_consumption_batch\n(flow 2)", "process", 0, 1),
            "timer": ("recovery-status-sweep.timer\nevery 5 min", "ext", 1, 0),
            "sweep": ("recovery_status_sweep:\ntimeout, failed,\nlate (70 min), missing (130 min)", "db", 1, 1),
            "ffd": ("fetch-fuel-data service\n(DG fuel, Roadcast / Loconav)", "ext", 2, 0),
            "fuel": ("DgFuelConsumptionData,\nDgUnitConsumption", "db", 2, 1),
            "cron": ("main: cron 07:40 UTC\ndb_backup.sh", "ext", 3, 0),
            "s3": ("pg_dump -> S3, keep\nnewest local copy", "db", 3, 1),
            "cmds": ("manual commands", "ext", 1, 3),
            "c1": ("replay_dead_letters", "process", 0, 4),
            "c2": ("replay_consumption_alarms", "process", 1, 4),
            "c3": ("resync_daily_totals", "process", 2, 4),
            "c4": ("rebuild_hourly_baseline", "process", 3, 4),
        },
        "edges": [
            ("beat", "flush"), ("timer", "sweep"), ("ffd", "fuel"), ("cron", "s3"),
            ("cmds", "c1"), ("cmds", "c2"), ("cmds", "c3"), ("cmds", "c4"),
        ],
        "files": [
            ("warehouse/settings.py", "CELERY_BEAT_SCHEDULE (flush-consumption-batch)"),
            ("wareApp/management/commands/recovery_status_sweep.py", "sweep()"),
            ("fetch_fuel_data.py, wareApp/fuel_providers.py", "DG fuel pull (credentials from .env)"),
            ("deploy/main/db_backup.sh", "daily backup on main"),
            ("wareApp/management/commands/replay_dead_letters.py", "process stored failed packets again"),
            ("wareApp/management/commands/replay_consumption_alarms.py", "day-end alarms for a past period"),
            ("wareApp/management/commands/resync_daily_totals.py", "daily total = sum of hourly rows (skips incomplete / glitch days)"),
            ("wareApp/management/commands/rebuild_hourly_baseline.py", "recompute hourly baseline and saving"),
        ],
        "details": """
All manual commands are dry runs unless given `--apply`:

| Command | Use |
| --- | --- |
| `replay_dead_letters --type LoadData --since … --apply` | re-process packets that failed (LoadData and recovery replies any time; consumption / load / SupplyTime / FIREALARM only with `--allow-ordered-types`) |
| `replay_consumption_alarms --from … --to … [--email-site N] --apply` | day-end alarms for a past period; e-mails only for the given sites |
| `resync_daily_totals --from … --to … [--site N] --apply` | set daily rows to the sum of their hourly rows (skips days with missing hours or meter glitches) |
| `rebuild_hourly_baseline --from … --to … [--site N] --apply` | recompute hourly baseline and saving |
""",
    },
]
