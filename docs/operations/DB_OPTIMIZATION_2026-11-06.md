# Database optimization, 2026-11-06 (test server)

Survey of the `warehouse` PostgreSQL 16 database on test and main (read only),
and the changes made on the **test server** only (main rollout not permitted).

## Findings

**Settings** (same on test and main): shared_buffers 2.5 GB, effective_cache_size
10 GB, faster autovacuum (scale factors 0.05 / 0.02), pg_stat_statements
installed. Left at defaults that do not fit the hardware: `random_page_cost=4`
(for spinning disks; the DB is on an EBS SSD), `effective_io_concurrency=1`,
`jit=on` (adds compile time to short OLTP queries).

**Live load on test (new code):** in 3 minutes of live traffic, zero sequential
scans on any big table; every read used an index. Writes are small (about 290
RawLoadData rows / 3 min). The trillions of rows read by sequential scans in the
statistics are the old code's history (stats never reset); main still runs that
code, so only the rollout fixes them there.

**Where DB time goes (test, cumulative):** ~83 % is RawLoadData inserts, one row
at a time (28.6 %), plus the two foreign-key checks PostgreSQL runs for every
inserted row (`... FOR KEY SHARE` on wareApp_aislegroup 31.4 %, wareApp_site
23.1 %). Each is < 0.1 ms: it is volume, not slowness.

**Slow query:** the alarm closer's "Meter Reading Issue fixed" check averaged
198 ms: to find "a reading for this aisle after the last error" it read every
hourly row of the aisle (index on aisle_group only) and filtered by time.

**Space:** the load tables' indexes are nearly as big as the tables, and four
single-column site indexes were redundant (a bigger index starting with the same
column exists).

## Changes (test server)

| | Change | How | Effect |
|---|---|---|---|
| A | Dropped 4 redundant single-column site indexes: RawLoadData `site_id` (239 MB), HourlyLoadData `site_id` (93 MB), HourlySiteReading `associated_Site_id` (73 MB), DgFuelConsumptionData `site_id` (76 MB) | Migration 0111 (`DROP INDEX CONCURRENTLY`, no table lock). Drops an index **only where a covering index exists**; databases differ (e.g. a local DB without the composite keeps its index) | ~480 MB less, lighter inserts; site lookups use `(site_id, created)`, `(associated_Site_id, leg_id, reading_from)`, `(site_id, vehicle_number, epoch_time)` |
| B | HourlySiteReading index `(aisle_group_id, reading_from)` replaces `(aisle_group_id)` | Migration 0112 (`CREATE INDEX CONCURRENTLY`, then drop the old one) | The alarm closer's probe: one index lookup, 0.085 ms |
| D | `random_page_cost = 1.1`, `effective_io_concurrency = 200`, `jit = off` | `ALTER SYSTEM` + `pg_reload_conf()` (no restart; written to `postgresql.auto.conf`) | Planner costs that match an SSD; no JIT compile on short queries |

Index space on the four tables: 6,373 MB → 6,160 MB (480 MB dropped, ~270 MB new
index). Migrations ran in 17 s; no errors in processing afterwards.

Query plans after the change (EXPLAIN ANALYZE on test): RawLoadData by site +
time → `idx_rawload_site_created` (0.14 ms); hourly readings by site →
`idx_hourlysitereading_site_leg_reading_from`; aisle + time probe →
`idx_hourly_aisle_reading_from` (0.085 ms); fuel by site →
`uniq_dgfuel_site_vehicle_epoch`. All index-only scans.

## Not done (for later)

- **C:** RawLoadData written in batches and/or without database-level foreign
  keys (removes the two per-row FK checks, ~54 % of DB time on test). Bigger
  change; worth it mainly on main.
- **E:** partitioning / BRIN indexes for the load tables, which grow forever
  (retention is intentional).
- **Main:** the same changes apply there with the rollout (migrations 0111 /
  0112 check for covering indexes; main has them).

## Rolling back

- A / B: `python manage.py migrate wareApp 0110` (recreates the dropped
  indexes concurrently and removes the new one).
- D: `ALTER SYSTEM RESET random_page_cost; ALTER SYSTEM RESET
  effective_io_concurrency; ALTER SYSTEM RESET jit; SELECT pg_reload_conf();`
  (backup of the file before: `backups/deploy/postgresql.auto.conf.before_ssd_settings_20261106`).

## Tests

`wareApp/tests/test_db_indexes.py`: every site column still leads an index; the
single index is gone wherever a covering one exists; hourly readings are indexed
by aisle + time and not by aisle alone.
