from django.db import migrations, models
from django.utils import timezone


def _drop_fuel_level_if_present(apps, schema_editor):
    table_name = "wareApp_dgfuelconsumptiondata"

    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table_name
            )
        }

    if "fuel_level" not in columns:
        return

    schema_editor.execute(
        'ALTER TABLE "wareApp_dgfuelconsumptiondata" DROP COLUMN "fuel_level";'
    )


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0079_ensure_site_baseline_date"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    _drop_fuel_level_if_present,
                    migrations.RunPython.noop,
                ),

                migrations.AlterField(
                    model_name="monthlyloadsharepercentage",
                    name="created_on",
                    field=models.DateTimeField(default=timezone.now),
                ),

                migrations.AlterField(
                    model_name="supplyloadtimeshare",
                    name="reading_from",
                    field=models.DateTimeField(default=timezone.now),
                ),

                migrations.AlterField(
                    model_name="supplyloadtimeshare",
                    name="reading_to",
                    field=models.DateTimeField(default=timezone.now),
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="dgfuelconsumptiondata",
                    name="fuel_level",
                ),

                migrations.AlterField(
                    model_name="monthlyloadsharepercentage",
                    name="created_on",
                    field=models.DateTimeField(default=timezone.now),
                ),

                migrations.AlterField(
                    model_name="supplyloadtimeshare",
                    name="reading_from",
                    field=models.DateTimeField(default=timezone.now),
                ),

                migrations.AlterField(
                    model_name="supplyloadtimeshare",
                    name="reading_to",
                    field=models.DateTimeField(default=timezone.now),
                ),
            ],
        ),
    ]