from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0091_site_consumption_alarm_settings_and_sync_status"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="alarmnotifications",
            index=models.Index(
                fields=["site_id", "aisle_group", "Alarm_type", "created_time"],
                name="idx_alarm_site_aisle_type_time",
            ),
        ),
    ]
