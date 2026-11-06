from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0087_use_callable_datetime_defaults"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="dailyloaddata",
            index=models.Index(
                fields=["site", "created"], name="idx_dailyload_site_created"
            ),
        ),
    ]
