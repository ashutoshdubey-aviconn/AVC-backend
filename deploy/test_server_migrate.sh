#!/usr/bin/env bash
# Bring the TEST server's wareApp migration history in line with this repo.
#
# Test diverged after 0072: it applied its own 0076..0081 (and old 0002..0004
# "alter_*" files) whose schema matches this repo's 0073..0085 under other
# names. Verified on 2026-10-19 by comparing the repo migrations with the
# server's columns, indexes and constraints:
#
#   0073..0083, 0085   schema already present          -> recorded as applied (fake)
#   0084, 0088, 0089   same index under an idx_live_* / other name -> renamed, then fake;
#                      the two new 0084 rollup indexes are built CONCURRENTLY
#   0086, 0087, 0090..0095  really missing (small tables) -> run normally
#
# Run from /home/ubuntu/django_project AFTER the new code is unpacked and with
# the MQTT units stopped. Without --apply it only prints what it would do.
set -euo pipefail
cd "$(dirname "$0")/.."

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
PY=virtualwarehouse/bin/python
PSQL=(sudo -u postgres psql -d warehouse -v ON_ERROR_STOP=1 -At -c)
TS=$(date -u +%Y%m%dT%H%M%SZ)

run() { echo "+ $*"; if (( APPLY )); then "$@"; fi; }
sql() { echo "+ SQL: $1"; if (( APPLY )); then "${PSQL[@]}" "$1"; fi; }

echo "== 1. Move test-only migration files aside (their django_migrations rows stay)"
SERVER_ONLY=(
  0002_alter_monthlyloadsharepercentage_created_on_and_more
  0003_alter_monthlyloadsharepercentage_created_on_and_more
  0004_alter_monthlyloadsharepercentage_created_on_and_more
  0076_dgunitconsumption_daily_data_status_and_more
  0077_add_site_baseline_date
  0078_add_dg_fuel_unique_constraints
  0079_alter_monthlyloadsharepercentage_created_on_and_more
  0080_homegatewaystatus
  0081_dg_fuel_aisle_configuration_bridge
)
run mkdir -p "backups/test-only-migrations-$TS"
for name in "${SERVER_ONLY[@]}"; do
  if [[ -f "wareApp/migrations/$name.py" ]]; then
    run mv "wareApp/migrations/$name.py" "backups/test-only-migrations-$TS/"
  fi
done

echo "== 2. Record 0073 (repo 0074/0075 are applied on test and depend on it)"
sql "INSERT INTO django_migrations (app, name, applied)
     SELECT 'wareApp', '0073_dgfuelconsumptiondata_fuel_level_and_more', now()
     WHERE NOT EXISTS (SELECT 1 FROM django_migrations
                       WHERE app='wareApp' AND name='0073_dgfuelconsumptiondata_fuel_level_and_more');"

echo "== 3. 0076..0083: schema already present -> fake"
run $PY manage.py migrate wareApp 0083 --fake

echo "== 4. 0084: rename the existing raw-load index, build the two new ones without locking writes"
sql 'ALTER INDEX IF EXISTS idx_live_rawload_site_created RENAME TO idx_rawload_site_created;'
sql 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hourlyload_rollup ON "wareApp_hourlyloaddata" (site_id, aisle_group_id, created);'
sql 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dailyload_rollup ON "wareApp_dailyloaddata" (site_id, aisle_group_id, created);'
run $PY manage.py migrate wareApp 0084 --fake

echo "== 5. 0085: aisle DG fuel columns already present -> fake"
run $PY manage.py migrate wareApp 0085 --fake

echo "== 6. 0086, 0087: run (indexes on tables under 50 MB)"
run $PY manage.py migrate wareApp 0087

echo "== 7. 0088, 0089: same indexes exist under other names -> rename, fake"
sql 'ALTER INDEX IF EXISTS idx_live_dailyload_site_created RENAME TO idx_dailyload_site_created;'
run $PY manage.py migrate wareApp 0088 --fake
sql 'ALTER INDEX IF EXISTS idx_monthlyminmax_site_source_created RENAME TO idx_monthlyload_site_src_time;'
run $PY manage.py migrate wareApp 0089 --fake

echo "== 8. 0090..0095: run"
run $PY manage.py migrate wareApp

echo "== 9. Result"
run $PY manage.py showmigrations wareApp
run $PY manage.py makemigrations wareApp --check --dry-run

(( APPLY )) || echo -e "\nDry run only. Re-run with --apply to execute."
