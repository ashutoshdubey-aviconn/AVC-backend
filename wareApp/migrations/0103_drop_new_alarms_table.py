"""Drop NewAlarmsNotifications: migration 0099 copied every row to AlarmNotifications.

Before dropping, check that the copy happened: AlarmNotifications must hold at
least as many power / DG alarms (types 0-6, 9) as the old table has rows.
Otherwise the migration stops and nothing is dropped.
"""

from django.db import migrations

POWER_TYPES = (0, 1, 2, 3, 4, 5, 6, 9)


def check_copied(apps, schema_editor):
    Old = apps.get_model("wareApp", "NewAlarmsNotifications")
    Alarm = apps.get_model("wareApp", "AlarmNotifications")
    old = Old.objects.count()
    copied = Alarm.objects.filter(Alarm_type__in=POWER_TYPES).count()
    if copied < old:
        raise RuntimeError(
            f"NewAlarmsNotifications has {old} rows but AlarmNotifications only {copied} "
            "power / DG alarms: run migration 0099's copy before dropping the table."
        )


class Migration(migrations.Migration):

    dependencies = [
        ('wareApp', '0102_alarm_recipients_in_file'),
    ]

    operations = [
        migrations.RunPython(check_copied, migrations.RunPython.noop),
        migrations.DeleteModel(
            name='NewAlarmsNotifications',
        ),
    ]
