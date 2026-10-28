from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0080_remove_dgfuelconsumptiondata_fuel_level_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dgunitconsumption",
            name="daily_data_status",
            field=models.CharField(
                choices=[
                    ("OPEN", "Open"),
                    ("PENDING", "Pending"),
                    ("COMPLETED", "Completed"),
                    ("FAILED", "Failed"),
                ],
                default="COMPLETED",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="dgunitconsumption",
            name="daily_data_retry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dgunitconsumption",
            name="daily_data_last_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dgunitconsumption",
            name="daily_data_retry_deadline",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]