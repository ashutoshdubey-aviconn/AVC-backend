from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0088_add_daily_load_rollup_lookup_index"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="monthlyminmaxloaddata",
            index=models.Index(
                fields=["site", "supply_source", "created"],
                name="idx_monthlyload_site_src_time",
            ),
        ),
    ]
