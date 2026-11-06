#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <ssh-host> <backup-directory>" >&2
    exit 2
fi

host="$1"
backup_directory="$2"
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

remote() {
    ssh -o BatchMode=yes -o ConnectTimeout=10 "ubuntu@${host}" "$@"
}

remote "mkdir -p '${backup_directory}'"

manifest="${backup_directory}/manifest.tsv"
remote "printf '%s\n' 'table_name\trow_count\tsha256\tfile_name' > '${manifest}'"

for table_name in "${tables[@]}"; do
    columns="${table_columns[$table_name]}"
    archive="${backup_directory}/${table_name}.csv.gz"
    sql="COPY (SELECT ${columns} FROM public.\\\"${table_name}\\\" WHERE created >= TIMESTAMPTZ '${start_at}' AND created < TIMESTAMPTZ '${end_at}' ORDER BY id) TO STDOUT WITH (FORMAT csv, HEADER true)"

    remote "set -o pipefail; sudo -n -u postgres psql -X -q -v ON_ERROR_STOP=1 -d '${database}' -c \"${sql}\" | gzip -c > '${archive}'"
    remote "gzip -t '${archive}'"

    row_count="$(remote "sudo -n -u postgres psql -X -qAt -v ON_ERROR_STOP=1 -d '${database}' -c \"SELECT count(*) FROM public.\\\"${table_name}\\\" WHERE created >= TIMESTAMPTZ '${start_at}' AND created < TIMESTAMPTZ '${end_at}'\"")"
    checksum="$(remote "sha256sum '${archive}' | cut -d ' ' -f 1")"
    remote "printf '%s\\t%s\\t%s\\t%s\\n' '${table_name}' '${row_count}' '${checksum}' '${table_name}.csv.gz' >> '${manifest}'"
done

remote "cat '${manifest}'"