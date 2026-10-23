#!/usr/bin/env bash
# Bring a database with the MAIN server's migration history up to the repo's
# migrations (0073 ... 0098). Dry run by default; --apply to execute.
#
# Why: main applied its own 0073_alter_meterdisconnectionevent_options_and_more and
# 0074_alter_monthlyloadsharepercentage_created_on_and_more, and already has most
# of the repo's 0073-0090 schema under other names. A plain `migrate` stops with
# InconsistentMigrationHistory or tries to create objects that already exist.
#
# Checked 2026-10-23 by comparing main's schema (pg_dump --schema-only) with the
# repo schema at 0098, table / column / index / constraint by constraint:
#
#   repo 0073-0080, 0082, 0083        schema already on main        -> fake
#   repo 0081                          4 dgunitconsumption columns   -> run
#   repo 0084                          2 of 3 indexes on main;       -> create idx_dailyload_rollup, fake
#   repo 0085                          aisle_group_id is integer on  -> alter to bigint + Django-named
#                                      main (repo: bigint FK + idx)     FK/index, fake
#   repo 0086, 0087                    missing indexes / defaults    -> run
#   repo 0088, 0089                    indexes already on main       -> fake
#   repo 0090-0098                     missing                       -> run
#   meterdisconnectionevent            main: UNIQUE(meter_id), null  -> repo's UNIQUE(meter_id, window
#                                      windows allowed                  start, end), windows NOT NULL
#                                                                       (127 rows, none null, no dup)
# Main's two extra tables wareApp_*_backup_site124_*20261014 are left alone.
#
# On main: run in a maintenance window, after a backup. Large tables:
# dgfuelconsumptiondata (1.5 GB) is rewritten by the bigint change.
#
# Usage: deploy/main_lineage_migrate.sh [--apply]   (from the project root)

set -euo pipefail
cd "$(dirname "$0")/.."
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
PY=virtualwarehouse/bin/python
PSQL=(sudo -n -u postgres psql -d warehouse -v ON_ERROR_STOP=1 -At)

run() { echo "+ $*"; if (( APPLY )); then "$@"; fi; }
sql() { echo "+ SQL: ${1//$'\n'/ }"; if (( APPLY )); then "${PSQL[@]}" -c "$1"; fi; }

echo "== 0. Current state"
"${PSQL[@]}" -c "select name from django_migrations where app='wareApp' order by id desc limit 2"

echo "== 1. Schema fixes so faked migrations match the repo"
sql 'BEGIN;
ALTER TABLE "wareApp_dgfuelalertsdata" DROP CONSTRAINT IF EXISTS "wareApp_dgfuelalertsdata_aisle_group_id_fkey";
ALTER TABLE "wareApp_dgfuelalertsdata" ALTER COLUMN aisle_group_id TYPE bigint;
ALTER TABLE "wareApp_dgfuelalertsdata" ADD CONSTRAINT "wareApp_dgfuelalerts_aisle_group_id_e4366c53_fk_wareApp_a"
  FOREIGN KEY (aisle_group_id) REFERENCES "wareApp_aislegroup"(id) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX IF NOT EXISTS "wareApp_dgfuelalertsdata_aisle_group_id_e4366c53" ON "wareApp_dgfuelalertsdata" (aisle_group_id);
ALTER TABLE "wareApp_dgfuelconsumptiondata" DROP CONSTRAINT IF EXISTS "wareApp_dgfuelconsumptiondata_aisle_group_id_fkey";
ALTER TABLE "wareApp_dgfuelconsumptiondata" ALTER COLUMN aisle_group_id TYPE bigint;
ALTER TABLE "wareApp_dgfuelconsumptiondata" ADD CONSTRAINT "wareApp_dgfuelconsum_aisle_group_id_74a9701b_fk_wareApp_a"
  FOREIGN KEY (aisle_group_id) REFERENCES "wareApp_aislegroup"(id) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX IF NOT EXISTS "wareApp_dgfuelconsumptiondata_aisle_group_id_74a9701b" ON "wareApp_dgfuelconsumptiondata" (aisle_group_id);
ALTER TABLE "wareApp_meterdisconnectionevent" DROP CONSTRAINT IF EXISTS "wareApp_meterdisconnectionevent_meter_id_c4b73da0_uniq";
ALTER TABLE "wareApp_meterdisconnectionevent" ALTER COLUMN detection_window_start SET NOT NULL;
ALTER TABLE "wareApp_meterdisconnectionevent" ALTER COLUMN detection_window_end SET NOT NULL;
ALTER TABLE "wareApp_meterdisconnectionevent" ADD CONSTRAINT "wareApp_meterdisconnecti_meter_id_detection_windo_e6d37275_uniq"
  UNIQUE (meter_id, detection_window_start, detection_window_end);
COMMIT;'
# Outside a transaction so it can run while the table is in use.
sql 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dailyload_rollup ON "wareApp_dailyloaddata" (site_id, aisle_group_id, created);'

echo "== 2. Migrations"
run $PY manage.py migrate wareApp 0080 --fake
run $PY manage.py migrate wareApp 0081
run $PY manage.py migrate wareApp 0085 --fake
run $PY manage.py migrate wareApp 0087
run $PY manage.py migrate wareApp 0089 --fake
run $PY manage.py migrate wareApp
run $PY manage.py migrate

echo "== 3. Check"
run $PY manage.py makemigrations --check --dry-run
"${PSQL[@]}" -c "select name from django_migrations where app='wareApp' order by id desc limit 1"
(( APPLY )) || echo "dry run: nothing changed (use --apply)"
