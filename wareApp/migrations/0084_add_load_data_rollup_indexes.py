from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0083_alter_monthlyloadsharepercentage_created_on_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="rawloaddata",
            index=models.Index(
                fields=["site", "created"], name="idx_rawload_site_created"
            ),
        ),
        migrations.AddIndex(
            model_name="hourlyloaddata",
            index=models.Index(
                fields=["site", "aisle_group", "created"],
                name="idx_hourlyload_rollup",
            ),
        ),
        migrations.AddIndex(
            model_name="dailyloaddata",
            index=models.Index(
                fields=["site", "aisle_group", "created"],
                name="idx_dailyload_rollup",
            ),
        ),
    ]
