"""Existing Bypassed, High Consumption, Meter Reading Issue, Operation Hours
Increased and Consumption Spike alarms become High priority (new ones are
raised as High since 2026-11-02). Low Consumption stays Medium."""

from django.db import migrations

HIGH_TYPES = (7, 10, 11, 12, 17)


def to_high(apps, schema_editor):
    apps.get_model("wareApp", "AlarmNotifications").objects.filter(
        Alarm_type__in=HIGH_TYPES
    ).update(Alarm_priority=0)


def to_medium(apps, schema_editor):
    apps.get_model("wareApp", "AlarmNotifications").objects.filter(
        Alarm_type__in=HIGH_TYPES
    ).update(Alarm_priority=1)


class Migration(migrations.Migration):

    dependencies = [
        ("wareApp", "0107_consumption_spike_alarm"),
    ]

    operations = [migrations.RunPython(to_high, to_medium)]
