# Test Server Operations Runbook

Last verified: 2026-10-13 UTC

## Role And Access

- Role: test/staging MQTT and Django environment; also receives bridged LoadData from main.
- SSH: `ssh ubuntu@43.204.53.81`
- Hostname: `ip-172-31-1-90`
- Project: `/home/ubuntu/django_project`
- Local database: PostgreSQL database `warehouse`.
- Source is not a Git checkout. Back up active files before changing them.

Do not add passwords, private keys, API tokens, or provider credentials to this file.

## Current Baseline

| Item | Verified value |
| --- | --- |
| CPU / memory | 4 vCPU, 15 GiB RAM, no swap |
| Load average | 0.12 / 0.10 / 0.09 at verification |
| Disk | 48 GiB root; 35 GiB used; 14 GiB free (73%) |
| PostgreSQL | 16.15 |
| PostgreSQL shared buffers | 2 GiB |
| `work_mem` | 4 MiB |
| `maintenance_work_mem` | 128 MiB |
| `max_connections` | 100 |

Use the Linux `available` memory figure rather than the raw `free` memory figure when assessing pressure.

## Service Topology

| Service | Purpose | Key configuration |
| --- | --- | --- |
| `nginx` | Reverse proxy | Active |
| `gunicorn` | Django WSGI | 2 workers, 2 threads, 60 second timeout, binds `0.0.0.0:8000` |
| `postgresql` | Local `warehouse` DB | PostgreSQL 16 |
| `rabbitmq-server` | Celery broker | Active |
| `mosquitto` | MQTT broker | Active, TCP 1883 |
| `root-mqtt-queue1` | Queue 1 listener | Enabled unit; check status before relying on it |
| `root-mqtt-queue2` | Queue 2 LoadData listener | Enabled unit; check status before relying on it |
| `celerybeat` | Scheduled tasks | Enabled |

Health check:

```bash
systemctl is-active nginx gunicorn postgresql rabbitmq-server mosquitto \
  root-mqtt-queue1 root-mqtt-queue2 celerybeat
sudo rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

## Django Database Aliases

Test settings retain legacy multi-database configuration:

- `default`: test server PostgreSQL, configured through environment variables.
- `main`: PostgreSQL on `172.31.9.28`, database `warehouse`.
- `DATABASE_ROUTERS = ["wareApp.routers.SecondaryDBRouter"]`.

The old `secondary` block is commented out. Some DG-fuel/session code intentionally reads main-site reading data using the `main` alias. Do not assume a normal queryset on test always targets main; inspect explicit `.using()` calls and the router.

This differs from main, which deliberately exposes only `default`.

## MQTT Relationship To Main

Test Mosquitto itself has no configured bridge stanza in `/etc/mosquitto/mosquitto.conf`.

However, main has an active outbound MQTT bridge to this test broker for:

```text
/Acclivate/iOmniControl/+/+/in/LoadData/#
```

Main uses `both` bridge direction, so test may receive current main gateway LoadData and publish matching topics back. This is active integration traffic, not an isolated staging environment.

Before testing LoadData changes, decide whether the main bridge must be paused. Do not assume sending a test MQTT message is isolated.

## LoadData And DG-fuel Indexes

Verified key indexes on test:

| Table | Index | Columns |
| --- | --- | --- |
| `wareApp_rawloaddata` | `idx_live_rawload_site_created` | `site_id, created` |
| `wareApp_hourlyloaddata` | `idx_live_hourlyload_site_created` | `site_id, created` |
| `wareApp_dailyloaddata` | `idx_live_dailyload_site_created` | `site_id, created` |
| `wareApp_monthlyminmaxloaddata` | `idx_monthlyminmax_site_source_created` | `site_id, supply_source, created` |
| `wareApp_dgfuelconsumptiondata` | `uniq_dgfuel_site_vehicle_epoch` | unique `site_id, vehicle_number, epoch_time` |
| `wareApp_dgfuelalertsdata` | `uniq_dgfuel_alert_site_vehicle_name_epoch` | unique `site_id, vehicle_number, alert_name, epoch_time` |

At verification, `wareApp_mainsdgloaddata` had only the legacy separate indexes on `site_id` and `aisle_group_id`; it did not have main's composite `(site_id, aisle_group_id, created)` index. Avoid using the Mains/DG daily graph as a high-volume test workload until an approved index plan exists.

## CPU, Disk, And PostgreSQL Checks

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

- `active`: a query is running or waiting.
- `idle / ClientRead`: connection is open but no statement is running.
- `idle in transaction`: investigate; it can retain locks and delay vacuum.
- Use `EXPLAIN (ANALYZE, BUFFERS)` only for a controlled representative query; it executes the statement.

## Migration And Release Constraints

- Test migration lineage differs from both the workspace and main. Earlier audit observed it through a test-specific `0080_homegatewaystatus` and later bridge migration work.
- Do not copy local migrations directly to test or run broad `migrate` without checking `django_migrations` and migration dependencies.
- DG-fuel phase-1 deployed a test-specific bridge migration, `0081_dg_fuel_aisle_configuration_bridge`, to add per-aisle configuration safely.
- Test and main are not interchangeable release targets. Compare models, migrations, and database aliases before promotion.

## Security And Operational Risks

- Gunicorn binds publicly on `0.0.0.0:8000`.
- Mosquitto allows anonymous access and is exposed on TCP 1883.
- RabbitMQ and PostgreSQL exposure must be reviewed with host firewall and AWS security group rules.
- The test server is receiving live LoadData through the main broker bridge. Treat it as connected infrastructure, not a disposable isolated environment.

## Safe Change Procedure

1. Record `systemctl` health and RabbitMQ queue state first.
2. Create a timestamped backup of each touched server file.
3. Compile Python and run a targeted Django check using the intended environment.
4. For database/index work, collect `EXPLAIN` before and after.
5. Restart only the affected unit and confirm it has an active consumer.
6. Keep backups and migration evidence until the change is accepted.
