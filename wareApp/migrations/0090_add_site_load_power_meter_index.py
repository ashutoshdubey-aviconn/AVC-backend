from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0089_add_monthly_load_lookup_index"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="siteloadpower",
            index=models.Index(
                fields=["Associated_Site", "Meter_Number"],
                name="idx_sitepower_site_meter",
            ),
        ),
    ]
