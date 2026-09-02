from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0077_quote_dgfuelconsumptiondata_table_name"),
    ]

    operations = [
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