"""Meter Disconnected alarms (type 14) become High priority, like the gateway
alarms 15 / 16 (new ones are raised as High since 2026-11-06)."""

from django.db import migrations

METER_DISCONNECTED = 14


def to_high(apps, schema_editor):
    apps.get_model("wareApp", "AlarmNotifications").objects.filter(
        Alarm_type=METER_DISCONNECTED
    ).update(Alarm_priority=0)


def to_medium(apps, schema_editor):
    apps.get_model("wareApp", "AlarmNotifications").objects.filter(
        Alarm_type=METER_DISCONNECTED
    ).update(Alarm_priority=1)


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0109_pending_email"),
    ]

    operations = [migrations.RunPython(to_high, to_medium)]
