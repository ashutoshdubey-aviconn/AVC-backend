from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0085_add_aisle_dg_fuel_configuration"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="supplyloadtimeshare",
            index=models.Index(
                fields=["site", "power_source", "reading_from"],
                name="idx_supply_site_src_time",
            ),
        ),
        migrations.AddIndex(
            model_name="sitebaseline",
            index=models.Index(
                fields=["associated_site_id", "leg_id", "baseline_from", "baseline_to"],
                name="idx_baseline_site_leg_dates",
            ),
        ),
        migrations.AddIndex(
            model_name="siteloadpower",
            index=models.Index(
                fields=["Associated_Site", "Supply_Source", "Meter_Number"],
                name="idx_sitepower_site_src_meter",
            ),
        ),
        migrations.AddIndex(
            model_name="firepumpalarm",
            index=models.Index(
                fields=["Site", "Meter_Number"], name="idx_fpalarm_site_meter"
            ),
        ),
        migrations.AddIndex(
            model_name="email_history",
            index=models.Index(
                fields=["fire_site", "deviceName", "email_for", "created"],
                name="idx_email_site_dev_kind_time",
            ),
        ),
        migrations.AddIndex(
            model_name="newalarmsnotifications",
            index=models.Index(
                fields=["site_id", "power_source", "alarm_type", "created"],
                name="idx_alarm_site_src_type_time",
            ),
        ),
        migrations.AddIndex(
            model_name="siteloadparameters",
            index=models.Index(
                fields=["site_id", "power_source", "parameter_type", "created"],
                name="idx_lp_site_src_type_time",
            ),
        ),
    ]
