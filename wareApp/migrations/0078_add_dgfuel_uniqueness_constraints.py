from django.db import migrations, models


def _dedupe_dg_fuel_rows(apps, schema_editor):
    schema_editor.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY site_id, vehicle_number, epoch_time
                    ORDER BY id
                ) AS rn
            FROM "wareApp_dgfuelconsumptiondata"
        )
        DELETE FROM "wareApp_dgfuelconsumptiondata"
        WHERE id IN (
            SELECT id
            FROM ranked
            WHERE rn > 1
        );
        """
    )


def _dedupe_dg_alert_rows(apps, schema_editor):
    schema_editor.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY site_id, vehicle_number, alert_name, epoch_time
                    ORDER BY id
                ) AS rn
            FROM "wareApp_dgfuelalertsdata"
        )
        DELETE FROM "wareApp_dgfuelalertsdata"
        WHERE id IN (
            SELECT id
            FROM ranked
            WHERE rn > 1
        );
        """
    )


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0077_quote_dgfuelconsumptiondata_table_name"),
    ]

    operations = [
        migrations.RunPython(_dedupe_dg_fuel_rows, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(_dedupe_dg_alert_rows, reverse_code=migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="dgfuelconsumptiondata",
            constraint=models.UniqueConstraint(
                fields=["site", "vehicle_number", "epoch_time"],
                name="uniq_dgfuel_site_vehicle_epoch",
            ),
        ),
        migrations.AddConstraint(
            model_name="dgfuelalertsdata",
            constraint=models.UniqueConstraint(
                fields=["site", "vehicle_number", "alert_name", "epoch_time"],
                name="uniq_dgfuel_alert_site_vehicle_name_epoch",
            ),
        ),
    ]