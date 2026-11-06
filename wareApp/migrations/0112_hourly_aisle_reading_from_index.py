"""Index HourlySiteReading by (aisle_group, reading_from) instead of aisle_group
alone (2026-11-06).

Queries like "is there a reading for this aisle after the last meter error"
(alarm closer, Meter Reading Issue fixed) had to read every hourly row of the
aisle and filter by time; with the time in the index they are one probe. The
single aisle_group index is then redundant and dropped.
CONCURRENTLY: no table lock while building (hence atomic = False).
"""

import django.db.models.deletion
from django.db import migrations, models

NEW = "idx_hourly_aisle_reading_from"
OLD = "wareApp_hourlysitereading_aisle_group_id_c977c140"
TABLE = "wareApp_hourlysitereading"


def forward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{NEW}" ON "{TABLE}" ("aisle_group_id", "reading_from")'
        )
        cursor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{OLD}"')


def backward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{OLD}" ON "{TABLE}" ("aisle_group_id")')
        cursor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{NEW}"')


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("wareApp", "0111_drop_redundant_site_indexes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(forward, backward)],
            state_operations=[
                migrations.AlterField(
                    model_name="hourlysitereading",
                    name="aisle_group",
                    field=models.ForeignKey(
                        blank=True, db_index=False, null=True,
                        on_delete=django.db.models.deletion.CASCADE, to="wareApp.aislegroup",
                    ),
                ),
                migrations.AddIndex(
                    model_name="hourlysitereading",
                    index=models.Index(fields=["aisle_group", "reading_from"], name=NEW),
                ),
            ],
        ),
    ]
