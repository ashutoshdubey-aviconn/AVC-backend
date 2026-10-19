# Test-server rollout: `full-optimization-v2`

Target: test server `ubuntu@43.204.53.81`, project `/home/ubuntu/django_project`
(see `TEST_SERVER_OPERATIONS.md`). The test server is **not a Git checkout** and
receives live LoadData from main through the broker bridge, so treat it as
connected infrastructure.

## What this release changes

| Area | Change |
| --- | --- |
| Celery | One app (`-A warehouse`). New units in `deploy/systemd/` replace `root-mqtt-queue1/2`. |
| MQTT listeners | `clean_session=False`, QoS 1, stable client IDs; packets wrapped in `MqttEnvelope`. |
| Processing | DB round trips cut (M4); transient DB errors retried in place; other failures stored as **MQTT dead letters**. |
| Recovery | One request per gap per cooldown window; full recovery status + `RecoveryMonitor` history; 5-minute sweep timer. |
| Consumption | Duplicate packets skipped (6 h window). |
| Alarm email | Sent from the `notifications` queue after the DB commit. |
| DG fuel | `detect_refuel/theft_from_alerts` now also read reports without a `data` wrapper. |
| Migrations | `0085` … `0095` (fields, small-table indexes, `MqttDeadLetter`, recovery status). |

Unchanged: `wareApp/load_data/` logic (queue 2), `dg_fuel/`, `fetch_fuel_data.py`, `celerybeat`.

Tests before release: `python run_tests.py` → 45 unit tests + 243 app tests pass
(SQLite); the 243 app tests also pass on PostgreSQL.

## 0. Build the release bundle (local machine)

```bash
git archive --format=tar.gz -o /tmp/fov2.tar.gz full-optimization-v2
scp /tmp/fov2.tar.gz ubuntu@43.204.53.81:/tmp/
```

The archive contains no `.env`, virtualenv, logs or backups.

## 1. Pre-flight (read-only)

```bash
cd /home/ubuntu/django_project
TS=$(date -u +%Y%m%dT%H%M%SZ); echo $TS
systemctl is-active nginx gunicorn postgresql rabbitmq-server mosquitto root-mqtt-queue1 root-mqtt-queue2 celerybeat
systemctl list-units --all '*mqtt*' '*celery*' --no-pager
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
systemctl cat root-mqtt-queue1 root-mqtt-queue2 | grep -E 'ExecStart|queues|-Q'
```

Write down which queues each legacy unit consumes (`queue1`, `queue1_processing`, …).

### Migration lineage check (must do before `migrate`)

Test has its own migration history (`0080_homegatewaystatus`,
`0081_dg_fuel_aisle_configuration_bridge`), which this repo does not have.

```bash
sudo -u postgres psql -d warehouse -P pager=off -c \
  "select name from django_migrations where app='wareApp' and name >= '0075' order by name;"
```

After unpacking the new code (step 3), run `python manage.py migrate wareApp --plan`.
**Stop and compare** if the plan lists any migration below `0085`, because those
changes may already exist on test under other names:

* For each listed migration, check whether its column/table/index already exists
  (`\d "wareApp_<table>"` in psql).
* Already present → `python manage.py migrate wareApp <name> --fake` for that one only.
* Not present → let it run normally.

`0095_ensure_fuel_data_source_column` checks for the column first, so it is safe either way.

## 2. Backups

```bash
cd /home/ubuntu
tar czf /home/ubuntu/backup-code-$TS.tar.gz --exclude=django_project/virtualwarehouse \
    --exclude=django_project/logs --exclude=django_project/logges django_project
sudo -u postgres pg_dump -Fc -d warehouse -f /home/ubuntu/backup-warehouse-$TS.dump
sudo cp -a /etc/systemd/system/root-mqtt-queue*.service /home/ubuntu/
df -h /     # the dump needs free space; test had ~14 GiB free
```

## 3. Unpack code and dependencies

```bash
cd /home/ubuntu/django_project
tar xzf /tmp/fov2.tar.gz          # overwrites tracked files; keeps .env, venv, logs
virtualwarehouse/bin/pip install -r requirements.txt
virtualwarehouse/bin/python manage.py check
virtualwarehouse/bin/python manage.py migrate wareApp --plan    # see step 1 check
```

## 4. Switch the MQTT services

The legacy workers register tasks as `tasks.process_*`; the new workers expect
`wareApp.tasks.process_*`. **Drain the processing queues before stopping the
legacy workers**, or the leftover messages are rejected by the new workers.

```bash
# 4a. stop only the listeners first if they are separate units; otherwise stop
#     the legacy units and immediately check the queues
sudo systemctl stop root-mqtt-queue1 root-mqtt-queue2
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged
```

If `queue1_processing` / `queue2_processing` still hold messages, drain them
with the legacy app before continuing:

```bash
virtualwarehouse/bin/celery -A tasks worker -Q queue1_processing,queue2_processing --concurrency=1 -l INFO
# Ctrl-C once both queues show 0 messages_ready
```

Then:

```bash
virtualwarehouse/bin/python manage.py migrate
sudo systemctl disable root-mqtt-queue1 root-mqtt-queue2

sudo cp deploy/systemd/mqtt-*.service deploy/systemd/recovery-status-sweep.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mqtt-processing-queue1 mqtt-processing-queue2 mqtt-notifications
sudo systemctl enable --now mqtt-listener-queue1 mqtt-listener-queue2
sudo systemctl enable --now recovery-status-sweep.timer
sudo systemctl restart gunicorn          # admin + API pick up the new code
```

Do **not** enable `mqtt-site-worker@N` yet; keep `MQTT_SITE_PARTITIONS=0`. Site partitions
and several workers need `REDIS_URL` set (cooldowns, duplicate check and sync-status
cache are per-process while it is empty).

### Optional: broker persistence (M6)

```bash
grep -n "include_dir\|persistence" /etc/mosquitto/mosquitto.conf   # conf.d must be included; avoid duplicate keys
sudo cp deploy/mosquitto/persistence.conf /etc/mosquitto/conf.d/
sudo systemctl restart mosquitto && systemctl is-active mosquitto
# if it fails to start: sudo rm /etc/mosquitto/conf.d/persistence.conf && sudo systemctl restart mosquitto
```

Restarting Mosquitto drops the main→test LoadData bridge connection for a few seconds.

## 5. Verify

```bash
systemctl is-active mqtt-listener-queue1 mqtt-listener-queue2 mqtt-processing-queue1 \
  mqtt-processing-queue2 mqtt-notifications recovery-status-sweep.timer
sudo rabbitmqctl list_queues name messages_ready consumers   # every queue has ≥1 consumer, ready stays near 0
journalctl -u mqtt-listener-queue1 -n 50 --no-pager          # "Queue1 MQTT connected"
journalctl -u mqtt-processing-queue1 -f                      # tasks succeeding
```

Admin (`/admin/`): **MQTT dead letters**, **Aisle sync recovery statuses**, **Recovery monitors**.

## 6. Real-traffic test checklist

| # | Check | Expected |
| --- | --- | --- |
| 1 | New hourly consumption packet | `HourlySiteReading` row for that hour; daily total grows once |
| 2 | Same packet sent twice | Second one logged `Skipped duplicate consumption packet` |
| 3 | Gap (skip an hour) | Exactly one `sync/consumption` request within 10 min; sync status `recovery_requested`, monitor `requested` |
| 4 | Gateway recovery reply | Rows written; monitor `applied` → `verified`; sync status `recovered` |
| 5 | No reply | After the request timeout the sweep marks it `timeout`; after 3 attempts the status is `failed` |
| 6 | SupplyTime / loadRuntime recovery | `SupplyLoadTimeShare` rows; runtime status rows with `power_source` |
| 7 | `load` packet over threshold | Alarm row + email from the `notifications` worker |
| 8 | FIREALARM packet | `FirePumpAlarm` updated; email sent |
| 9 | Corrupt payload | One **MQTT dead letter** row (not one per packet) |
| 10 | `sudo systemctl restart postgresql` during traffic | Workers log retries, then continue; no dead letters for that window |
| 11 | Restart `mqtt-listener-queue1` | Reconnects; with persistence.conf, packets sent meanwhile are delivered |
| 12 | LoadData (queue 2) | Unchanged behaviour; `queue2_processing` keeps up |

Useful query:

```bash
sudo -u postgres psql -d warehouse -c \
  "select message_type, count(*), max(created_at) from \"wareApp_mqttdeadletter\" group by 1;"
```

## 7. Rollback

Migrations are additive (new columns, tables, indexes; one constraint replaced),
so the old code keeps working with the migrated schema. Do not reverse migrations.

```bash
sudo systemctl disable --now mqtt-listener-queue1 mqtt-listener-queue2 mqtt-processing-queue1 \
  mqtt-processing-queue2 mqtt-notifications recovery-status-sweep.timer
cd /home/ubuntu && tar xzf backup-code-$TS.tar.gz
sudo systemctl enable --now root-mqtt-queue1 root-mqtt-queue2
sudo systemctl restart gunicorn
```

Drain `queue1_processing` / `queue2_processing` with the new app first if they hold
`wareApp.tasks.*` messages (`celery -A warehouse worker -Q queue1_processing,queue2_processing`).
