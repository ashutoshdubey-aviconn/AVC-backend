# Re-ensure `fuel_data_source` on databases where a table rebuild dropped it.
#
# Between 0074 and 0082 the column existed in the database but not in the
# migration state, so SQLite's table-rebuild ALTERs (test databases) recreated
# the table without it. PostgreSQL never rebuilds, so there this is a no-op.
from django.db import migrations

TABLE = "wareApp_dgfuelconsumptiondata"


def _ensure_fuel_data_source(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, TABLE)
        }
    if "fuel_data_source" not in columns:
        schema_editor.execute(
            f'ALTER TABLE "{TABLE}" ADD COLUMN "fuel_data_source" varchar(32) NULL;'
        )


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0094_mqtt_dead_letter"),
    ]

    operations = [
        migrations.RunPython(_ensure_fuel_data_source, migrations.RunPython.noop),
    ]
