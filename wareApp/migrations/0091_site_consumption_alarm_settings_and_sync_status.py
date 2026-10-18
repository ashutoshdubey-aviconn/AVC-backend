import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wareApp", "0090_add_site_load_power_meter_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="bypass_consumption_units",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="site",
            name="high_consumption_baseline_percent",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="site",
            name="high_consumption_units",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="site",
            name="nl_operation_end_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="site",
            name="nl_operation_hours",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="site",
            name="nl_operation_start_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="alarmnotifications",
            name="Alarm_type",
            field=models.PositiveIntegerField(
                choices=[
                    (0, "Low_balance"),
                    (1, "Power_Cut"),
                    (2, "Pending Balance"),
                    (3, "Pending Request"),
                    (4, "Zero balance"),
                    (5, "Box opened"),
                    (6, "Internet_Gone"),
                    (7, "High Consumption"),
                    (8, "Low Consumption"),
                    (9, "No DG Run"),
                    (10, "Meter Reading Issue"),
                    (11, "Bypassed"),
                    (12, "Operation Hours Increased"),
                ]
            ),
        ),
        migrations.CreateModel(
            name="AisleSyncRecoveryStatus",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("home_gateway_id", models.CharField(max_length=200)),
                ("leg_id", models.CharField(max_length=50)),
                (
                    "sync_status",
                    models.CharField(
                        choices=[
                            ("unknown", "Unknown"),
                            ("healthy", "Healthy"),
                            ("late", "Late"),
                            ("missing", "Missing"),
                            ("recovery_requested", "Recovery Requested"),
                            ("recovery_received", "Recovery Received"),
                            ("recovered", "Recovered"),
                            ("failed", "Failed"),
                        ],
                        default="unknown",
                        max_length=30,
                    ),
                ),
                ("is_sync_gone", models.BooleanField(default=False)),
                ("recovery_requested", models.BooleanField(default=False)),
                ("recovery_received", models.BooleanField(default=False)),
                ("last_sync_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_recovery_requested_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "last_recovery_received_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "last_recovery_applied_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("expected_from", models.DateTimeField(blank=True, null=True)),
                ("expected_to", models.DateTimeField(blank=True, null=True)),
                ("missing_slots", models.PositiveIntegerField(default=0)),
                ("recovered_slots", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "aisle_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="wareApp.aislegroup",
                    ),
                ),
                (
                    "recovery_monitor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="current_statuses",
                        to="wareApp.recoverymonitor",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="wareApp.site",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="aislesyncrecoverystatus",
            constraint=models.UniqueConstraint(
                fields=("site", "home_gateway_id", "aisle_group"),
                name="uniq_sync_status_site_gateway_aisle",
            ),
        ),
        migrations.AddIndex(
            model_name="aislesyncrecoverystatus",
            index=models.Index(
                fields=["site", "sync_status"], name="idx_sync_status_site_state"
            ),
        ),
        migrations.AddIndex(
            model_name="aislesyncrecoverystatus",
            index=models.Index(
                fields=["site", "leg_id"], name="idx_sync_status_site_leg"
            ),
        ),
    ]
