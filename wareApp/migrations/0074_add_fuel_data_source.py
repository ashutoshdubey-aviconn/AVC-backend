# Safe migration: add `fuel_data_source` column only if it doesn't already exist.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0073_dgfuelconsumptiondata_fuel_level_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE IF EXISTS wareApp_dgfuelconsumptiondata "
                "ADD COLUMN IF NOT EXISTS fuel_data_source varchar(32);"
            ),
            reverse_sql=(
                "ALTER TABLE IF EXISTS wareApp_dgfuelconsumptiondata "
                "DROP COLUMN IF EXISTS fuel_data_source;"
            ),
        ),
    ]
