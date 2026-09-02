# Safe migration: add `fuel_data_source` column only if it doesn't already exist.
from django.db import migrations


def _ensure_fuel_data_source(apps, schema_editor):
    table_name = "wareApp_dgfuelconsumptiondata"
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }
        if "fuel_data_source" in columns:
            return
    schema_editor.execute(
        'ALTER TABLE "wareApp_dgfuelconsumptiondata" ADD COLUMN "fuel_data_source" varchar(32);'
    )


def _drop_fuel_data_source(apps, schema_editor):
    table_name = "wareApp_dgfuelconsumptiondata"
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }
        if "fuel_data_source" not in columns:
            return
    try:
        schema_editor.execute(
            'ALTER TABLE "wareApp_dgfuelconsumptiondata" DROP COLUMN "fuel_data_source";'
        )
    except Exception:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0073_dgfuelconsumptiondata_fuel_level_and_more"),
    ]

    operations = [
        migrations.RunPython(_ensure_fuel_data_source, _drop_fuel_data_source),
    ]
