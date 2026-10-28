#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <backup-directory-on-this-server>" >&2
    exit 2
fi

backup_directory="$1"
start_at="2025-10-12 00:00:00+05:30"
end_at="2026-10-13 00:00:00+05:30"
database="warehouse"

declare -A table_columns=(
    [wareApp_mainsdgloaddata]="id,site_id,aisle_group_id,load_data,epoch_time,created,updated_on"
    [wareApp_rawloaddata]="id,site_id,aisle_group_id,load_data,created,epoch_time,is_anomaly"
    [wareApp_hourlyloaddata]="id,site_id,aisle_group_id,load_data,epoch_time,created,updated_on,is_bypassed"
    [wareApp_dailyloaddata]="id,site_id,aisle_group_id,load_data,epoch_time,created,updated_on"
    [wareApp_monthlyminmaxloaddata]="id,site_id,supply_source,min_load,min_load_created,max_load,max_load_created,created"
    [wareApp_dgfuelconsumptiondata]="id,site_id,aisle_group_id,vehicle_number,fuel_consumption,fuel_data_source,epoch_time,created"
    [wareApp_dgfuelalertsdata]="id,site_id,aisle_group_id,alert_name,vehicle_number,fuel_consumption,epoch_time,created"
    [wareApp_dgunitconsumption]="id,site_id,aisle_group_id,unit_consumption,dg_fuel_consumption,dg_start_date,dg_end_date,created,updated_on,epoch_time,is_dg_on,fetch_fuel_data,fuel_provider,fuel_vehicle_number"
)

declare -A insert_columns=(
    [wareApp_mainsdgloaddata]="site_id,aisle_group_id,load_data,epoch_time,created,updated_on"
    [wareApp_rawloaddata]="site_id,aisle_group_id,load_data,created,epoch_time,is_anomaly"
    [wareApp_hourlyloaddata]="site_id,aisle_group_id,load_data,epoch_time,created,updated_on,is_bypassed"
    [wareApp_dailyloaddata]="site_id,aisle_group_id,load_data,epoch_time,created,updated_on"
    [wareApp_monthlyminmaxloaddata]="site_id,supply_source,min_load,min_load_created,max_load,max_load_created,created"
    [wareApp_dgfuelconsumptiondata]="site_id,aisle_group_id,vehicle_number,fuel_consumption,fuel_data_source,epoch_time,created"
    [wareApp_dgfuelalertsdata]="site_id,aisle_group_id,alert_name,vehicle_number,fuel_consumption,epoch_time,created"
    [wareApp_dgunitconsumption]="site_id,aisle_group_id,unit_consumption,dg_fuel_consumption,dg_start_date,dg_end_date,created,updated_on,epoch_time,is_dg_on,fetch_fuel_data,fuel_provider,fuel_vehicle_number"
)

tables=(
    wareApp_mainsdgloaddata
    wareApp_rawloaddata
    wareApp_hourlyloaddata
    wareApp_dailyloaddata
    wareApp_monthlyminmaxloaddata
    wareApp_dgfuelconsumptiondata
    wareApp_dgfuelalertsdata
    wareApp_dgunitconsumption
)

manifest="${backup_directory}/manifest.tsv"
[[ -f "$manifest" ]] || { echo "Missing manifest: $manifest" >&2; exit 1; }

for table_name in "${tables[@]}"; do
    archive="${backup_directory}/${table_name}.csv.gz"
    [[ -f "$archive" ]] || { echo "Missing archive: $archive" >&2; exit 1; }

    expected_rows="$(awk -v table_name="$table_name" '$1 == table_name { print $2 }' "$manifest")"
    expected_checksum="$(awk -v table_name="$table_name" '$1 == table_name { print $3 }' "$manifest")"
    [[ -n "$expected_checksum" && -n "$expected_rows" ]] || {
        echo "Missing manifest row for $table_name" >&2
        exit 1
    }

    actual_checksum="$(sha256sum "$archive" | cut -d ' ' -f 1)"
    [[ "$actual_checksum" == "$expected_checksum" ]] || {
        echo "Checksum mismatch for $table_name" >&2
        exit 1
    }

    current_rows="$(sudo -n -u postgres psql -X -qAt -v ON_ERROR_STOP=1 -d "$database" -c "SELECT count(*) FROM public.\"${table_name}\" WHERE created >= TIMESTAMPTZ '${start_at}' AND created < TIMESTAMPTZ '${end_at}'")"
    if [[ "$current_rows" == "$expected_rows" ]]; then
        printf '%s: %s rows already verified; skipping\n' "$table_name" "$current_rows"
        continue
    fi

    staging_table="history_import_${table_name,,}"
    staging_table="${staging_table:0:63}"
    columns="${table_columns[$table_name]}"
    target_columns="${insert_columns[$table_name]}"

    sudo -n -u postgres psql -X -q -v ON_ERROR_STOP=1 -d "$database" \
        -c "DROP TABLE IF EXISTS ${staging_table}; CREATE UNLOGGED TABLE ${staging_table} (LIKE public.\"${table_name}\" INCLUDING DEFAULTS);"
    gzip -cd "$archive" | sudo -n -u postgres psql -X -q -v ON_ERROR_STOP=1 -d "$database" \
        -c "COPY ${staging_table} (${columns}) FROM STDIN WITH (FORMAT csv, HEADER true)"

    staged_rows="$(sudo -n -u postgres psql -X -qAt -v ON_ERROR_STOP=1 -d "$database" -c "SELECT count(*) FROM ${staging_table}")"
    [[ "$staged_rows" == "$expected_rows" ]] || {
        echo "Staged row count mismatch for $table_name: expected $expected_rows, got $staged_rows" >&2
        exit 1
    }

    sudo -n -u postgres psql -X -q -v ON_ERROR_STOP=1 -d "$database" <<SQL
BEGIN;
LOCK TABLE public."${table_name}" IN SHARE ROW EXCLUSIVE MODE;
DELETE FROM public."${table_name}"
WHERE created >= TIMESTAMPTZ '${start_at}'
  AND created < TIMESTAMPTZ '${end_at}';
INSERT INTO public."${table_name}" (${target_columns})
SELECT ${target_columns}
FROM ${staging_table};
COMMIT;
SQL

    imported_rows="$(sudo -n -u postgres psql -X -qAt -v ON_ERROR_STOP=1 -d "$database" -c "SELECT count(*) FROM public.\"${table_name}\" WHERE created >= TIMESTAMPTZ '${start_at}' AND created < TIMESTAMPTZ '${end_at}'")"
    [[ "$imported_rows" == "$expected_rows" ]] || {
        echo "Post-import row count mismatch for $table_name: expected $expected_rows, got $imported_rows" >&2
        exit 1
    }

    sudo -n -u postgres psql -X -q -v ON_ERROR_STOP=1 -d "$database" -c "DROP TABLE ${staging_table}"
    printf '%s: %s rows imported\n' "$table_name" "$imported_rows"
done