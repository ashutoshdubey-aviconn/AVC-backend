# Main Server Operations Runbook

Last verified: 2026-10-13 UTC

## Role And Access

- Role: production/main application, MQTT intake, and authoritative API database.
- SSH: `ssh ubuntu@asem.aviconncorp.com`
- Hostname: `ip-172-31-9-28`
- Project: `/home/ubuntu/django_project`
- Database: local PostgreSQL database `warehouse`.
- Source is not a Git checkout. Back up an active server file before changing it.

Do not record database passwords or tokens in this file.

## Current Baseline

| Item | Verified value |
| --- | --- |
| CPU / memory | 4 vCPU, 15 GiB RAM, no swap |
| Load average | 0.56 / 0.43 / 0.49 at verification |
| Disk | 67 GiB root; 50 GiB used; 17 GiB free (75%) |
| PostgreSQL | 16.15 |
| PostgreSQL shared buffers | 2 GiB |
| `work_mem` | 4 MiB |
| `maintenance_work_mem` | 128 MiB |
| `max_connections` | 100 |
| Django database aliases in production | `default` only |

`free` may show low raw free memory because Linux uses available memory for page cache. Use the `available` column, not `free`, when assessing memory pressure.

## Service Topology

| Service | Purpose | Key configuration |
| --- | --- | --- |
| `nginx` | HTTPS reverse proxy | Proxies application traffic to Gunicorn |
| `gunicorn` | Django WSGI API | 2 workers, 2 threads each, `127.0.0.1:8000`, 60 second timeout |
| `postgresql` | Local `warehouse` database | PostgreSQL 16 cluster |
| `rabbitmq-server` | Celery broker | Queue listener/task transport |
| `mosquitto` | MQTT broker | Listens on TCP 1883 |
| `root-mqtt-queue1` | Business/recovery MQTT listener | Celery queue `queue1`, concurrency 1 |
| `root-mqtt-queue2` | LoadData MQTT listener | Celery queue `queue2`, concurrency 1 |

Useful health check:

```bash
systemctl is-active nginx gunicorn postgresql rabbitmq-server mosquitto \
  root-mqtt-queue1 root-mqtt-queue2
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

The historical `celery_worker1.service` is obsolete and should remain inactive. The active listeners are `root-mqtt-queue1` and `root-mqtt-queue2`.

## Django Database Routing

Production `warehouse/settings.py` has:

```python
DATABASE_ROUTERS = []
DATABASES = {"default": {"HOST": "localhost", "NAME": "warehouse", ...}}
```

There is no production `secondary` alias. LoadData and DG-fuel APIs must use the local `default` database. Validate after a deployment:

```bash
cd /home/ubuntu/django_project
ENV=PROD virtualwarehouse/bin/python manage.py shell -c '
from wareApp.models import RawLoadData, DgFuelConsumptionData
print(RawLoadData.objects.db, DgFuelConsumptionData.objects.db)
'
```

Expected output: `default default`.

## MQTT And LoadData Flow

1. Gateways publish to Mosquitto on port 1883.
2. `root-mqtt-queue2` subscribes only to:

   ```text
   /Acclivate/iOmniControl/+/+/in/LoadData/#
   ```

3. Queue 2 calls the modular LoadData handler and persists to local PostgreSQL.
4. Queue 1 handles business telemetry/recovery types separately.

### Important: Active Test-Server Bridge

Main Mosquitto currently has this active bridge configuration:

```conf
connection whmetering_dhl
address 43.204.53.81:1883
clientid bridge-dhl
topic /Acclivate/iOmniControl/+/+/in/LoadData/# both 0 "" ""
```

`both` means LoadData is mirrored in both directions between main and test MQTT brokers. Main Mosquitto logs prove inbound gateway LoadData is sent to both `server_paho_client_2` and `local.bridge-dhl`.

This bridge is independent of Django database routing. Even though main writes only to `default`, LoadData still reaches test through MQTT. Do not remove or change it without an approved cutover plan and a Mosquitto backup.

### Disable The Bridge Safely

Disabling the bridge stops only main-to-test MQTT mirroring. It does not stop main's local MQTT broker, Queue 1, Queue 2, or main database writes.

During an approved maintenance window:

```bash
sudo cp -a /etc/mosquitto/mosquitto.conf \
  /etc/mosquitto/mosquitto.conf.backup-$(date +%Y%m%d-%H%M%S)

sudoedit /etc/mosquitto/mosquitto.conf
sudo mosquitto -c /etc/mosquitto/mosquitto.conf -t
sudo systemctl restart mosquitto
```

In the editor, remove the entire bridge block only:

```conf
connection whmetering_dhl
address 43.204.53.81:1883
clientid bridge-dhl
cleansession false
keepalive_interval 60
restart_timeout 5
notifications false
bridge_protocol_version mqttv311
topic /Acclivate/iOmniControl/+/+/in/LoadData/# both 0 "" ""
```

Do not remove `port 1883`, logging settings, or other broker-wide directives.

Verify the cutover:

```bash
sudo ss -tnp | grep '43.204.53.81:1883' || true
sudo grep 'Sending PUBLISH to local.bridge-dhl' /var/log/mosquitto/mosquitto.log | tail
systemctl is-active mosquitto root-mqtt-queue2
```

After restart, the TCP bridge connection must be absent, no new bridge forwarding log lines should appear, and `root-mqtt-queue2` must return to `active`. Roll back by restoring the timestamped config backup, validating with `mosquitto -t`, and restarting Mosquitto.

## LoadData Tables And Performance Indexes

The one-year migration populated main for these tables:

- `wareApp_mainsdgloaddata`
- `wareApp_rawloaddata`
- `wareApp_hourlyloaddata`
- `wareApp_dailyloaddata`
- `wareApp_monthlyminmaxloaddata`
- `wareApp_dgfuelconsumptiondata`
- `wareApp_dgfuelalertsdata`
- `wareApp_dgunitconsumption`

The key main-server indexes are:

| Table | Index | Columns | Why it exists |
| --- | --- | --- | --- |
| `wareApp_rawloaddata` | `idx_rawload_site_created` | `site_id, created` | Raw rollup windows |
| `wareApp_hourlyloaddata` | `idx_load_site_created` | `site_id, created` | Hourly graph/rollup windows |
| `wareApp_hourlyloaddata` | `idx_hourlyload_rollup` | `site_id, aisle_group_id, created` | Per-aisle hourly rollups |
| `wareApp_dailyloaddata` | `idx_dailyload_site_created` | `site_id, created` | Calendar-month daily graph |
| `wareApp_monthlyminmaxloaddata` | `idx_monthlyload_site_src_time` | `site_id, supply_source, created` | Monthly extrema lookup |
| `wareApp_mainsdgloaddata` | `idx_mainsdgload_site_aisle_created` | `site_id, aisle_group_id, created` | Mains/DG daily graph |

All were verified valid after `CREATE INDEX CONCURRENTLY`.

### Query Rules

- Use timestamp ranges, e.g. `created__gte=start, created__lt=end`; avoid `created__date` on large tables because it prevents direct timestamp-index range scans.
- The daily/monthly LoadData graph is a calendar-month query: from the first day of the selected month to, but excluding, the first day of the next month.
- The Mains/DG daily graph is one selected day: `[midnight, next midnight)`.

Verify an index plan before adding a new graph query:

```sql
EXPLAIN (COSTS OFF)
SELECT id
FROM "wareApp_mainsdgloaddata"
WHERE site_id = 35
  AND aisle_group_id = 272
  AND created >= timestamp '2026-10-13 00:00:00'
  AND created < timestamp '2026-10-14 00:00:00';
```

Expected plan: `Index Scan using idx_mainsdgload_site_aisle_created`.

## CPU, Load, And PostgreSQL Diagnostics

### Read-only checks

```bash
uptime
free -h
df -h /
ps -eo pid,ppid,user,%cpu,%mem,etime,cmd --sort=-%cpu | head -30

sudo -u postgres psql -d warehouse -P pager=off -c '
SELECT pid, client_addr, state, wait_event_type, wait_event,
       now() - backend_start AS connection_age,
       now() - xact_start AS transaction_age,
       now() - query_start AS query_age,
       left(query, 500)
FROM pg_stat_activity
WHERE datname = ''warehouse''
ORDER BY query_start NULLS LAST;
'
```

Interpretation:

- `active` with a non-null `query_age`: statement is executing or waiting.
- `idle` with `ClientRead`: open connection waiting for its client; it is not currently executing the displayed last query.
- `idle in transaction`: investigate promptly; it can retain locks and prevent cleanup.
- `TIME+` in `htop` is process CPU accumulated over connection lifetime, not necessarily one long SQL statement.

At the 2026-10-13 check, eight Django/Celery database sessions were `idle / ClientRead`, no session was `idle in transaction`, and no application query was active. Two persistent sessions had been open for about three days.

### Current database timeout posture

`statement_timeout`, `lock_timeout`, and `idle_in_transaction_session_timeout` are currently `0` (unlimited). This did not cause the recorded incident, but it means runaway statements and abandoned transactions are not automatically stopped. Change this only through a reviewed PostgreSQL/Django policy.

## Recorded Incidents And Fixes

### Post-import CPU and API timeouts

After historical import, raw and Mains/DG graph queries performed broad scans because composite indexes were absent. The missing indexes above were created concurrently. `EXPLAIN` now confirms index scans.

### `/api/loadDataMainsDgDaily/` timeout

Cause: query filtered a 40M-row Mains/DG table with separate `site_id`, `aisle_group_id`, and `created__date` predicates.

Fix: added `idx_mainsdgload_site_aisle_created` and converted the endpoint to a timestamp range. The production endpoint reached authentication in approximately 8 ms after the change.

### Monthly LoadData graph date range

Cause: previous implementation used a rolling day window, causing selected-month graphs to include the preceding month.

Fix: graph and matching Excel export now use exact calendar-month bounds. September returns September 1 through September 30 only.

## Change Safety

1. Take a timestamped backup of each active server file before editing.
2. Compile touched Python: `ENV=PROD virtualwarehouse/bin/python -m py_compile <file>`.
3. Run `ENV=PROD virtualwarehouse/bin/python manage.py check`; existing model warnings are known and unrelated.
4. Validate query plans with `EXPLAIN` for large-table changes.
5. Restart only the affected service. Use `sudo systemctl restart gunicorn` for API code changes.
6. Do not run migrations from the local workspace on main; migration lineage differs.
7. Classify RabbitMQ messages before purging. Historical listener-command envelopes are not telemetry payloads.

## Relevant Backups Created During 2026-10-13 Changes

- `/home/ubuntu/django_project/backups/default-db-routing-20261013-183900`
- `/home/ubuntu/django_project/backups/mainsdg-query-fix-20261013-190500`
- `/home/ubuntu/django_project/backups/monthly-load-window-fix-20261013-192200`
- `/home/ubuntu/django_project/backups/calendar-month-load-fix-20261013-193000`
