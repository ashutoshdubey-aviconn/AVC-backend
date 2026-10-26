# Test-server rollout: `full-optimization-v2`

Target: test server `ubuntu@43.204.53.81`, project `/home/ubuntu/django_project`
(see `docs/operations/TEST_SERVER_OPERATIONS.md`). The test server is **not a Git checkout** and
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
| Settings | `warehouse/settings.py` reorganised; no credentials in code (`main` DB, Roadcast now from `.env`); `SECRET_KEY` required with `ENV=PROD`; `DEBUG`, SSL/cookie flags, `ALLOWED_HOSTS`, CORS configurable; `EMAIL_USE_TLS`/`EMAIL_PORT` typed; log folders created on start. Effective values on test are unchanged. |
| Dependencies | Security updates: Django 5.2.18, DRF 3.17.2, urllib3 2.8.0, requests 2.33.0, sqlparse 0.6.0, idna 3.15, PyNaCl 1.6.2 (+ cffi 2.0.0). `pip-audit` clean for app packages. |
| Migrations | Repo `0073` … `0095`; on test applied via `deploy/test_server_migrate.sh` (see 1). |

Unchanged: `wareApp/load_data/` logic (queue 2), `dg_fuel/`, `fetch_fuel_data.py`, `celerybeat`.

Tests before release: `python run_tests.py` → 45 unit tests + 243 app tests pass
(SQLite); the 243 app tests also pass on PostgreSQL.

## 0. Build the release bundle (local machine)

```bash
git archive --format=tar.gz -o /tmp/fov2.tar.gz full-optimization-v2
scp /tmp/fov2.tar.gz ubuntu@43.204.53.81:/tmp/
```

The archive contains no `.env`, virtualenv, logs or backups.

## 1. Pre-flight (read-only) — done 2026-10-19

| Item | Found on test |
| --- | --- |
| Legacy units | `root-mqtt-queue1`, `root-mqtt-queue1-processing`, `root-mqtt-queue2`, `root-mqtt-queue2-processing`, `celerybeat` — all active. A drop-in (`*.service.d/release-celery-app.conf`) already runs them as `celery -A warehouse` with `wareApp.tasks.*` names, so no task-name change on the queues. |
| Listener start | Legacy listener units also run `ExecStartPost ... call wareApp.tasks.mqtt_client1/2`; `queue1` held 12 and `queue2` 3 waiting listener-start messages. The new units do not have `ExecStartPost`. |
| Redis | `redis-server` active; `REDIS_URL` not set in `warehouse/.env`. |
| Mosquitto | 2.0.18. `/etc/mosquitto/mosquitto.conf` sets `persistence false` and has **no** `include_dir`, so `conf.d/` is not read. |
| Versions | Django 5.2.1, Celery 5.5.2, kombu 5.5.3, paho 1.6.1, django-redis 6.0.0 (same as repo); PostgreSQL 16.15. |
| Disk / memory | 13 GB free (75 % used); 12 GiB RAM available. |
| Migrations | History diverged after `0072` — see `deploy/test_server_migrate.sh`. |

Re-check right before the switch:

```bash
cd /home/ubuntu/django_project
TS=$(date -u +%Y%m%dT%H%M%SZ); echo $TS
systemctl is-active root-mqtt-queue1 root-mqtt-queue1-processing root-mqtt-queue2 root-mqtt-queue2-processing celerybeat
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

### Migration lineage (why a script)

Test applied its own `0076`–`0081` (and old `0002`–`0004 alter_*` files). Their schema
matches this repo's `0073`–`0085` under other names. A plain `migrate` would stop with
`InconsistentMigrationHistory` (test has `0074`/`0075` applied but not this repo's `0073`)
and the leftover test-only files would also give "conflicting migrations".

`deploy/test_server_migrate.sh` (checked against the server schema and simulated against
its `django_migrations` rows):

| Repo migration | On test | Script |
| --- | --- | --- |
| `0073`–`0083`, `0085` | schema already present | record as applied (`--fake`) |
| `0084` | raw-load index exists as `idx_live_rawload_site_created`; two rollup indexes missing (`hourlyloaddata` is 14 M rows / 2.2 GB) | rename; `CREATE INDEX CONCURRENTLY` the two new ones; fake |
| `0088`, `0089` | same index as `idx_live_dailyload_site_created` / `idx_monthlyminmax_site_source_created` | rename; fake |
| `0086`, `0087`, `0090`–`0095` | missing; tables ≤ 50 MB | run normally |

Without `--apply` the script only prints the steps.

## 2. Backups

```bash
cd /home/ubuntu
tar czf /home/ubuntu/backup-code-$TS.tar.gz --exclude=django_project/virtualwarehouse \
    --exclude=django_project/logs --exclude=django_project/logges django_project
sudo -u postgres pg_dump -Fc -d warehouse -f /home/ubuntu/backup-warehouse-$TS.dump
sudo cp -a /etc/systemd/system/root-mqtt-queue* /home/ubuntu/   # units + drop-in dirs
sudo cp -a /etc/mosquitto/mosquitto.conf /home/ubuntu/mosquitto.conf.$TS
df -h /     # the dump of ~10 GB of tables needs room; 13 GB was free
```

## 3. Unpack code and dependencies

```bash
cd /home/ubuntu/django_project
source virtualwarehouse/bin/activate   # same environment name locally and on test
tar xzf /tmp/fov2.tar.gz          # overwrites tracked files; keeps .env, venv, logs
virtualwarehouse/bin/pip install --upgrade pip setuptools   # venv tooling also had advisories
virtualwarehouse/bin/pip install -r requirements.txt
virtualwarehouse/bin/python manage.py check
bash deploy/test_server_migrate.sh          # dry run: read the steps
```

Add to `warehouse/.env` (settings no longer contain credentials):

| Variable | Needed for |
| --- | --- |
| `ROADCAST_PULL_USERNAME`, `ROADCAST_PULL_PASSWORD` | Roadcast pull API in the DG graph (skipped, with a warning, when unset) |
| `MAIN_DB_PASSWORD` (+ optional `MAIN_DB_HOST/NAME/USER/PORT`) | `main` DB alias, used only by `roadcast_monthly_refuel_report.py` |
| `REDIS_URL=redis://127.0.0.1:6379/1` | recommended: shared cooldowns, duplicate check and sync-status cache |
| `ALARM_EMAIL_OVERRIDE_TO` | every alarm email goes only here; defaults to ashutosh.dubey@aviconncorp.com while alarm emails are in testing. Set it empty to send to the real recipients (then `ALARM_EMAIL_DEFAULT_TO` for PF/consumption/meter/DG alarms). |

`SECRET_KEY`, `EMAIL_*` and `ALLOWED_HOSTS` are already in the test `.env` and are now
read from it (`EMAIL_USE_TLS`/`EMAIL_PORT` as bool/int). Move the old settings copies
out of the package, they hold credentials and are no longer in the repo:

```bash
mkdir -p ~/settings-snapshots && mv warehouse/settings_bck.py warehouse/settings_main_server.py \
  warehouse/settings_test_sserver.py warehouse/settings.py_before_full_optimization ~/settings-snapshots/
```

## 4. Switch the MQTT services

```bash
# 4a. stop the legacy listeners, let the processing workers finish what is queued
sudo systemctl stop root-mqtt-queue1 root-mqtt-queue2
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged
# wait until queue1_processing and queue2_processing show 0 / 0, then:
sudo systemctl stop root-mqtt-queue1-processing root-mqtt-queue2-processing
sudo systemctl disable root-mqtt-queue1 root-mqtt-queue1-processing root-mqtt-queue2 root-mqtt-queue2-processing

# 4b. drop the stale listener-start messages (queue1/queue2 carry nothing else)
virtualwarehouse/bin/celery -A warehouse purge -Q queue1,queue2 -f

# 4c. migrations
bash deploy/test_server_migrate.sh --apply

# 4d. new units
sudo cp deploy/systemd/mqtt-*.service deploy/systemd/recovery-status-sweep.* /etc/systemd/system/
sudo cp deploy/logrotate/celerylogs1 /etc/logrotate.d/celerylogs1   # celerylogs2 already rotated
sudo systemctl daemon-reload
sudo systemctl enable --now mqtt-processing-queue1 mqtt-processing-queue2 mqtt-notifications
sudo systemctl enable --now mqtt-listener-queue1 mqtt-listener-queue2
sudo systemctl enable --now recovery-status-sweep.timer
sudo systemctl restart gunicorn celerybeat      # admin/API and beat pick up the new code
```

Logs: queue-1 units (listener, processing, notifications, sweep) append to
`celerylogs1/celery_logs_of_server.log`, queue-2 units to `celerylogs2/celery_logs_of_server.log`
(as the legacy units did).

The listener is started once by the `worker_ready` signal; check that `queue1` and
`queue2` stay at 0–1 messages after the restart.

Do **not** enable `mqtt-site-worker@N` yet; keep `MQTT_SITE_PARTITIONS=0`. Site partitions
need `REDIS_URL` set.

### Optional: broker persistence (M6)

The test `mosquitto.conf` does not read `conf.d/` and sets `persistence false`, so edit
the main file instead of copying `persistence.conf`:

```bash
sudo sed -i 's/^persistence false/persistence true/; s/^autosave_interval 1800/autosave_interval 60/' /etc/mosquitto/mosquitto.conf
printf '%s\n' 'persistence_location /var/lib/mosquitto/' 'persistent_client_expiration 7d' \
  'max_queued_messages 200000' 'queue_qos0_messages true' | sudo tee -a /etc/mosquitto/mosquitto.conf
sudo systemctl restart mosquitto && systemctl is-active mosquitto
# if it fails: sudo cp /home/ubuntu/mosquitto.conf.$TS /etc/mosquitto/mosquitto.conf && sudo systemctl restart mosquitto
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

Admin (`/avcadmin/`): **MQTT dead letters**, **Aisle sync recovery statuses**, **Recovery monitors**.

## 6. Real-traffic test checklist

Requests published **by the test server** do not reach the gateways, but gateways still
answer the recovery requests sent by **main**, and those replies arrive on test. So:

* test the **recovery replies** (writing rows, status, history) with that traffic;
* do not expect test's own requests to be answered or verified from a reply to them.

A reply that matches an open request on test is linked to it; any other reply is stored
as its own `RecoveryMonitor` row ("unsolicited") and its rows are written the same way.
Once a reply fills an aisle's gap, its consumption packets are stored again.

| # | Check | Expected |
| --- | --- | --- |
| 1 | New hourly consumption packet (aisle without a gap) | `HourlySiteReading` row for that hour; daily total grows once |
| 2 | Same packet sent twice | Second one logged `Skipped duplicate consumption packet` |
| 3 | Gap packet | Packet not stored; one `recovery requested` log and one `RecoveryMonitor` `requested` row per gap per 10 min (not per packet); sync status `recovery_requested` |
| 4 | `hourlyConsumption` reply (from main's request) | Hourly rows written / `ERROR404` slots set to 0; monitor `response_received` → `applied` → `verified` when the gap is covered; sync status `recovered`, or `missing` with the remaining slot count |
| 5 | `dailyConsumption` reply | `DailySiteReading` rows written; history row only (the hourly reply decides the status) |
| 6 | `loadRuntime` reply / SupplyTime packet | `SupplyLoadTimeShare` rows; runtime status rows carry `power_source` |
| 7 | Test's own request never answered | After the timeout the sweep marks it `timeout`; after 3 attempts `failed` (expected on test) |
| 8 | `load` packet over threshold | Alarm row + email from the `notifications` worker |
| 9 | FIREALARM packet | `FirePumpAlarm` updated; email sent |
| 10 | Corrupt payload | One **MQTT dead letter** row (not one per packet) |
| 11 | `sudo systemctl restart postgresql` during traffic | Workers log retries, then continue; no dead letters for that window |
| 12 | Restart `mqtt-listener-queue1` | Reconnects; with broker persistence on, packets sent meanwhile are delivered |
| 13 | LoadData (queue 2) | Unchanged behaviour; `queue2_processing` keeps up |
| 14 | Admin and API | `/avcadmin/` loads; dashboard APIs answer as before |
| 15 | DG fuel | Graph APIs return data; Roadcast pull works once `ROADCAST_PULL_*` is set |

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
sudo systemctl enable --now root-mqtt-queue1-processing root-mqtt-queue2-processing root-mqtt-queue1 root-mqtt-queue2
sudo systemctl restart gunicorn celerybeat
```

Both old and new units use `wareApp.tasks.*` task names, so queued messages are
processed by whichever workers run. The applied migrations stay; the old code ignores
the new columns and tables.

Unpacking the backup restores the old files but leaves the new ones (e.g. repo
migrations `0073`–`0095`) in place. Do not run `migrate` on the rolled-back code; for a
clean folder, move `django_project` aside and unpack the backup into an empty one.
