"""Drop single-column site indexes that a bigger index already covers (2026-11-06).

Each of these tables has an index that starts with the same column, e.g.
RawLoadData (site_id, created); PostgreSQL uses it for site lookups, so the
single-column index only costs space (~480 MB on test) and insert time.

Databases differ (raw-SQL migrations created some composite indexes under
other names, or not at all), so the single index is dropped only where a
covering index (same first column, 2+ columns) exists; elsewhere it is kept.
DROP INDEX CONCURRENTLY: no table lock (hence atomic = False).
"""

import django.db.models.deletion
from django.db import migrations, models

# (table, column, Django's name of the single-column index)
SINGLE_INDEXES = (
    ("wareApp_rawloaddata", "site_id", "wareApp_rawloaddata_site_id_dfbcd5e2"),
    ("wareApp_hourlyloaddata", "site_id", "wareApp_hourlyloaddata_site_id_617af8e6"),
    ("wareApp_hourlysitereading", "associated_Site_id", "wareApp_hourlysitereading_associated_Site_id_40320db8"),
    ("wareApp_dgfuelconsumptiondata", "site_id", "wareApp_dgfuelconsumptiondata_site_id_40975a2c"),
)

COVERED = """
select exists (
  select 1 from pg_index x
  join pg_class t on t.oid = x.indrelid
  join pg_attribute a on a.attrelid = t.oid and a.attnum = x.indkey[0]
  where t.relname = %s and a.attname = %s and x.indnkeyatts >= 2
)
"""


def drop_covered(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, column, name in SINGLE_INDEXES:
            cursor.execute(COVERED, [table, column])
            if cursor.fetchone()[0]:
                cursor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')


def recreate(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, column, name in SINGLE_INDEXES:
            cursor.execute(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{name}" ON "{table}" ("{column}")')


def site_fk(to="wareApp.site"):
    return models.ForeignKey(
        blank=True, db_index=False, null=True, on_delete=django.db.models.deletion.CASCADE, to=to
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("wareApp", "0110_meter_disconnected_high_priority"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(drop_covered, recreate)],
            state_operations=[
                migrations.AlterField(model_name="rawloaddata", name="site", field=site_fk()),
                migrations.AlterField(model_name="hourlyloaddata", name="site", field=site_fk()),
                migrations.AlterField(model_name="hourlysitereading", name="associated_Site", field=site_fk()),
                migrations.AlterField(model_name="dgfuelconsumptiondata", name="site", field=site_fk()),
            ],
        ),
    ]
