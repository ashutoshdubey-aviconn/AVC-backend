# Main Server: Before and After Rollout Record

**Server:** `ubuntu@asem.aviconncorp.com` (`ip-172-31-9-28`)

**Rollout period:** 2026-10-09 UTC

This record covers the main-server MQTT, LoadData, `HourlySiteReading`, and
DG-fuel rollout. It records the production state before the work, every file
and schema change, the reason for each optimisation, the validation performed,
and the available rollback material.

## Important Migration Note

No blanket `manage.py migrate` was executed on the main server.

Production's recorded `wareApp` history ends at the legacy migration
`0074_alter_monthlyloadsharepercentage_created_on_and_more`. The local branch
has a different migration lineage using the same migration number plus later
DG-fuel migrations. Applying the local chain would be unsafe.

The DG-fuel database changes below were an explicitly scoped **direct schema
bridge**, applied only after backup and compatibility checks. Before any future
global Django migration, create a migration-reconciliation plan that represents
these already-applied schema changes.

## Before Main-Server Rollout

### MQTT and Celery

| Area | State before rollout |
| --- | --- |
| Queue 1 worker | `celery_worker1.service` ran `celery -A warehouse worker -Q queue1 -c 1`. |
| Queue 2 worker | No healthy Queue 2 listener. `celery_worker2.service` was disabled/broken. |
| MQTT subscriptions | Queue 1 used broad legacy subscriptions, so `LoadData` arrived beside business telemetry. |
| Initial RabbitMQ snapshot | `queue1` had about 127 waiting messages and `queue2` about 349, with zero consumers. |
| Active task module | The intended listener implementation was not available under `wareApp.tasks`. |

### Why `HourlySiteReading` Was Investigated

Production was diagnosed read-only using `pg_stat_statements` and `EXPLAIN`.
The high-cost query family checked whether an hourly site record existed:

```sql
SELECT 1
FROM "wareApp_hourlysitereading"
WHERE associated_Site_id = $2
  AND leg_id = $3
  AND reading_from >= $4
  AND reading_from <= $5
LIMIT 1;
```

| Query family | Calls | Mean time | Total time |
| --- | ---: | ---: | ---: |
| Hourly existence lookup | about 17.12 million | about 295 ms | about 5.06 billion ms |
| Hourly update | about 12.55 million | about 253 ms | about 3.17 billion ms |

`wareApp_hourlysitereading` had about 11 million rows. The original plan used a
parallel bitmap heap scan with a site-oriented path and then filtered by
`leg_id` and timestamp. For one sampled site, PostgreSQL estimated roughly
855,000 candidate rows before applying those filters. Indexing was therefore
chosen because a measured, high-frequency filter was expensive, not as a
speculative optimisation.

### DG-Fuel State Before the New Runner

| Area | State before rollout |
| --- | --- |
| Service | `fetch-fuel-data.service` ran the legacy standalone script. |
| Provider behavior | Some Roadcast responses produced `'data'` errors. |
| Fuel samples | `wareApp_dgfuelconsumptiondata`: 12,249,438 rows. |
| Fuel alerts | `wareApp_dgfuelalertsdata`: 483 rows. |
| DG units | `wareApp_dgunitconsumption`: 2,701 rows. |
| Duplicate fuel identities | 979,188 groups; 1,666,250 surplus rows. |
| Candidate mismatch | Normalized code required provider/source fields, aisle bindings, and uniqueness constraints absent from production. |

The normalized writer uses idempotent `get_or_create` identities. A unique
constraint could not be added to the old populated data without a decision on
duplicate retention. The user approved deleting the three DG runtime tables
after confirming fresh backups and that the test server retained the old data.

## Backups and Rollback Material

All artifacts were created before their associated destructive/deployment step,
copied locally, and validated.

| Purpose | Main-server archive | Workspace copy | Validation |
| --- | --- | --- | --- |
| Full database | `/home/ubuntu/db_backups/warehouse-20261009T175645Z.dump` | `backups/main-server/warehouse-20261009T175645Z.dump` | `pg_restore --list`; SHA-256 `14dc53f1fe881243e22c421b4e0cc3124a243db7c91c7ebf6041154a7827177a` |
| MQTT rollout | `/home/ubuntu/rollout_backups/main-mqtt-20261009T185307Z.tar.gz` | `backups/main-server/rollout/main-mqtt-20261009T185307Z.tar.gz` | SHA-256 `cd66c3ed5dfea699e768ceddbf7401f0c3b12828e36d474248322ac03efe9b7a` |
| DG runtime tables | `/home/ubuntu/db_backups/dg-fuel/dg-fuel-runtime-20261009T191020Z.dump` | `backups/main-server/dg-fuel/dg-fuel-runtime-20261009T191020Z.dump` | `pg_restore --list`; SHA-256 `446436c6d2afc090a5982d161ffbe682575641f5dbe0830112a905d8cd299025` |
| DG code and unit | `/home/ubuntu/rollout_backups/dg-fuel/dg-fuel-code-20261009T191308Z.tar.gz` | `backups/main-server/dg-fuel/dg-fuel-code-20261009T191308Z.tar.gz` | `tar -tzf`; SHA-256 `42ca033a6a89370f9ddc05424f55b29d99f740c4702b87e2c96e8259253c14fe` |

Before production DG cleanup, the test database was verified to retain
12,249,438 fuel samples, 483 fuel alerts, and 2,701 DG-unit rows.

## Main-Server Changes

### MQTT Queue Isolation

Gunicorn was stopped first for the approved rollout. The legacy Queue 1 worker
was stopped/disabled only after the replacement task module passed import
preflight. Gunicorn was restored after listener validation.

Installed and enabled service files:

| Path | Purpose |
| --- | --- |
| `/etc/systemd/system/root-mqtt-queue1.service` | One Queue 1 listener for business telemetry. |
| `/etc/systemd/system/root-mqtt-queue2.service` | One Queue 2 listener for `LoadData` only. |

Both use `celery -A wareApp.tasks`. The active tasks are
`wareApp.tasks.mqtt_client1` on `queue1` and `wareApp.tasks.mqtt_client2` on
`queue2`. Queue 2's initial start failed only because
`/home/ubuntu/django_project/celerylogs2` did not exist; creating that directory
and resetting the service resolved the `209/STDOUT` failure.

### Uploaded MQTT and LoadData Files

| Production path | Change |
| --- | --- |
| `/home/ubuntu/django_project/wareApp/tasks.py` | Phase 2 listener implementation. Queue 1 handles business telemetry; Queue 2 delegates to optimized LoadData handling. |
| `/home/ubuntu/django_project/wareApp/load_data/` | Complete optimized LoadData package, uploaded after task import preflight identified it as missing. |
| `/home/ubuntu/django_project/wareApp/mqtt/__init__.py` | Added package marker. |
| `/home/ubuntu/django_project/wareApp/mqtt/routing.py` | Queue-specific subscription lists: Queue 1 excludes `LoadData`; Queue 2 receives only `LoadData`. |
| `/home/ubuntu/django_project/wareApp/mqtt/topics.py` | Validated gateway-topic parser. |

`wareApp/mqtt/consumers.py` was deliberately not promoted as the active listener
path because its modular architecture was incomplete for the agreed Phase 2
behavior.

### Application Query Improvements

The deployed Queue 1 implementation changed hourly filtering to a half-open
hour range:

```python
reading_from__gte=dateHourLowerLimitCheck,
reading_from__lt=dateHourUpperLimitCheck,
```

This prevents the exact boundary reading from belonging to two adjacent hours.
It also replaced `exists()` followed by `update()` with `update()` and its
affected-row count, and replaced `exists()` plus indexed queryset access with
one `.first()` query. These changes reduce redundant database round trips while
preserving business behavior.

### `HourlySiteReading` Composite Index

The following index was built with `CONCURRENTLY`, allowing normal production
reads/writes while it was created:

```sql
CREATE INDEX CONCURRENTLY idx_hourlysitereading_site_leg_reading_from
ON public."wareApp_hourlysitereading"
("associated_Site_id", leg_id, reading_from);
```

The column order matches the measured workload: equality predicates first
(`associated_Site`, `leg_id`) and the timestamp range last. PostgreSQL can seek
to a site/leg pair, then scan only the requested hour.

| Environment | Result |
| --- | --- |
| Test server | Index valid/ready, 272 MB; planner selected `Index Only Scan`; cost 8.46. |
| Main server | Index valid/ready, 335 MB; planner selected `Index Only Scan`; cost 8.58. |

This replaced the broad bitmap heap scan that was responsible for the dominant
hourly query cost.

### DG-Fuel Data Reset

Only these runtime tables were backed up and truncated in one transaction with
`RESTART IDENTITY`:

```sql
TRUNCATE TABLE
    public."wareApp_dgfuelconsumptiondata",
    public."wareApp_dgfuelalertsdata",
    public."wareApp_dgunitconsumption"
RESTART IDENTITY;
```

The fuel service was stopped before backup/truncate. The three tables had no
foreign-key dependents. The following tables were intentionally preserved:

- `wareApp_dgalertsdata`
- `wareApp_mainsdgloaddata`

Counts were checked at zero before the normalized service was started.

### DG-Fuel Direct Schema Bridge

The following additive changes were applied in one transaction while the
poller was stopped. The empty runtime tables allowed uniqueness constraints to
be created without a second duplicate-deletion operation.

| Table | Added field/constraint | Purpose |
| --- | --- | --- |
| `wareApp_site` | `partner_dg_provider` | Stores provider separately from the device ID. |
| `wareApp_aislegroup` | `dg_fuel_enabled`, `dg_fuel_provider`, `dg_fuel_vehicle_number` | Allows per-aisle DG configuration. |
| `wareApp_dgfuelconsumptiondata` | `aisle_group_id`, `fuel_data_source` | Associates samples with an aisle and records source. |
| `wareApp_dgfuelalertsdata` | `aisle_group_id` | Associates refuel/theft events with an aisle. |
| `wareApp_dgunitconsumption` | `fuel_provider`, `fuel_vehicle_number` | Stores resolved provider/device on a DG session. |
| `wareApp_dgfuelconsumptiondata` | `uniq_dgfuel_site_vehicle_epoch` | Makes tank-level inserts idempotent. |
| `wareApp_dgfuelalertsdata` | `uniq_dgfuel_alert_site_vehicle_name_epoch` | Makes refuel/theft inserts idempotent. |

Ten configured sites were backfilled with a provider: numeric existing device
IDs were set to `roadcast`; other non-empty IDs were set to `loconav`.

### Uploaded DG-Fuel Files

| Production path | Change |
| --- | --- |
| `/home/ubuntu/django_project/fetch_fuel_data.py` | Normalized five-minute poller with per-cycle summary logging. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/__init__.py` | DG-fuel package marker. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/collection.py` | Read-only provider collection. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/dedupe.py` | Dedupe helper. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/ingestion.py` | Normalized, idempotent fuel-level and alert persistence. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/normalization.py` | Provider timestamp/numeric normalization. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/poller.py` | Collection orchestration. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/providers.py` | LocoNav/Roadcast payload parsers. |
| `/home/ubuntu/django_project/wareApp/dg_fuel/sessions.py` | Reconciliation and DG-run fuel retrieval. |
| `/home/ubuntu/django_project/wareApp/fuel_providers.py` | Provider HTTP/report helpers. |
| `/home/ubuntu/django_project/wareApp/models.py` | Minimal DG declarations matching the direct schema bridge; unrelated production model definitions retained. |

The systemd unit stayed at `/etc/systemd/system/fetch-fuel-data.service` and
uses the main-server virtual environment.

### DG-Fuel Database Routing

DG energy-reading routing is confined to `wareApp.dg_fuel.sessions` through
`_main_database_alias()`.

| Host | Configured aliases | Alias used for `DailySiteReading`/`HourlySiteReading` |
| --- | --- | --- |
| Main server | `default`, `secondary` | `default` |
| Test server | `default`, `main` | `main` |

The production fuel service therefore reads the main server's local database
through `default`; it does not read the test-server database.

## Improvements Achieved

| Change | Outcome |
| --- | --- |
| Queue isolation | High-rate LoadData no longer occupies Queue 1 business listener time. |
| Optimized LoadData path | Dedicated parsing, persistence, extrema, and rollup modules replace inline legacy work. |
| Query/index alignment | Broad hourly scans became focused index-only lookups; redundant ORM queries were removed. |
| Normalized DG ingestion | Timestamps/values are validated before storage; malformed data is skipped with a reason. |
| DG idempotency | Repeated provider samples cannot produce duplicate current-level or alert rows. |
| Per-aisle DG configuration | A site can have multiple DG configurations while preserving a site-level fallback. |
| Dedicated systemd poller | Fuel polling has an independent lifecycle and restart behavior. |
| Better observability | Cycle summaries distinguish created, existing, failed, unavailable, stale, and offline states. |

## Validation

### Pre-Deployment

- Local focused root MQTT and topic tests passed (45 tests); later root checks
  also passed.
- Test-server index build was valid and selected by the query planner before the
  main-server index was created.
- Production task import initially exposed missing `wareApp.load_data`; the
  required package was uploaded and the candidate then registered only the two
  intended MQTT listener tasks.
- DG-fuel staged files compiled and passed Django-initialized module/ORM
  preflight before installation.

### Immediate Main-Server Results

- Queue 1 processed live business telemetry.
- Queue 2 continuously saved live optimized LoadData packets.
- The hourly composite index was valid, ready, and planner-selected.
- Gunicorn was restored as active.
- `fetch-fuel-data.service` started with `NRestarts=0` and immediately saved
  current fuel-level samples.

### Five-Minute Health Window

Monitoring ran approximately 19:35-19:40 UTC.

| Check | Result |
| --- | --- |
| `gunicorn.service` | Active; no restarts during observation. |
| `root-mqtt-queue1.service` | Active; no restarts during observation. |
| `root-mqtt-queue2.service` | Active. `NRestarts=1` was the earlier log-directory start failure, not a new restart. |
| `fetch-fuel-data.service` | Active; `NRestarts=0`. |
| CPU | 90.48% average idle; 0.38% average I/O wait. |
| Load | One-minute load stayed at or below 0.34 on four vCPUs. |
| Blocked processes | Zero. |
| Memory | About 11 GiB available of 15 GiB; no swap configured. |
| Disk | 16 GiB free on 48 GiB root filesystem (67% used). |
| PostgreSQL | One active monitoring query and six idle connections; no blocking/long-running app query. |
| DG writes | Fuel-level rows increased from 16 to 21; zero dead tuples. |
| Logs | No new MQTT/DG-fuel traceback or service-failure entry. |

Four Roadcast devices reported stale/offline telemetry. Those are
provider/device states; the runner logged them and did not crash or persist them
as current data.

## Current State and Follow-Up

| Component | Current state |
| --- | --- |
| `gunicorn.service` | Active |
| `root-mqtt-queue1.service` | Active |
| `root-mqtt-queue2.service` | Active |
| `fetch-fuel-data.service` | Active |
| Legacy `celery_worker1.service` | Disabled after replacement; retained in rollout backup. |

The retained RabbitMQ backlog was not purged. Long-running listener tasks occupy
their serial workers, so processing old queued tasks requires a separate,
approved processor-worker and payload-classification plan.

Required follow-up:

1. Reconcile the direct DG schema bridge into the Django migration history
   before any blanket migration command.
2. Classify and decide a safe strategy for retained RabbitMQ messages; do not
   purge without explicit approval.
3. Monitor Roadcast stale/offline devices as provider/device work, separate from
   service availability.
4. Track normal autovacuum progress for `wareApp_hourlysitereading`; no manual
   vacuum was necessary during this rollout.
5. Keep credentials in environment configuration. This document intentionally
   contains no provider, database, or service secrets.