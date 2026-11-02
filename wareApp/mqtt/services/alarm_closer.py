"""Close alarms that are no longer happening (is_active False, off_time set).

Outage alarms 14 / 15 / 16 are closed by gateway_health when data returns.
Every other type is closed here, without an e-mail (decided 2026-11-02):

* 0 / 1 High / Low Voltage, 2 PF Bad Value: not seen for
  ALARM_CLOSE_POWER_MINUTES (60). While the problem lasts the alarm is
  counted again every 30 minutes, so an hour without it means it stopped.
  off_time = last seen.
* 13 Gateway Overheat: no overheat post for ALARM_CLOSE_OVERHEAT_HOURS (2).
* 10 Meter Reading Issue: no repeat for ALARM_CLOSE_EVENT_HOURS (24).
* Daily alarms (6, 7, 8, 9, 11, 12, 17, and old rows of 3, 4, 5), one row per day: closed at the end
  of the day after their day, so they stay visible for one full day.
  off_time = end of their day.

So "active" (alarmList active_alarms, consumptionAlarms, the super-admin
list) means "still happening". A closed issue that happens again is raised
as a new alarm.
"""

import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import F

from wareApp.models import AlarmNotifications

logger = logging.getLogger(__name__)

A = AlarmNotifications
POWER = (A.HIGH_VOLTAGE, A.LOW_VOLTAGE, A.PF_BAD_VALUE)
DAILY = (A.FUEL_DRAIN, A.HIGH_CONSUMPTION, A.LOW_CONSUMPTION, A.DG_RUNNING_WITHOUT_LOAD,
         A.BYPASSED, A.OPERATION_HOURS_INCREASED, A.CONSUMPTION_SPIKE,
         # Not raised by the current code; only old rows: close them the same way.
         A.DG_OVERTIME, A.DG_FUEL_UNDER_LEVEL, A.MAINS_HIGHER_CONSUMPTION)


def _setting(name, default):
    return getattr(settings, name, default)


def rules(now):
    """``[(label, queryset, off_time expression)]`` of alarms to close now."""
    active = A.objects.filter(is_active=True)
    seen = lambda: F("last_seen")  # noqa: E731
    today_start = datetime.combine(now.date(), time.min)
    return [
        (
            "voltage / PF not seen",
            active.filter(Alarm_type__in=POWER).filter(
                last_seen__lt=now - timedelta(minutes=_setting("ALARM_CLOSE_POWER_MINUTES", 60))
            ),
            seen(),
        ),
        (
            "voltage / PF without last_seen (old rows)",
            active.filter(Alarm_type__in=POWER, last_seen__isnull=True,
                          created_time__lt=now - timedelta(minutes=_setting("ALARM_CLOSE_POWER_MINUTES", 60))),
            F("created_time"),
        ),
        (
            "gateway overheat not seen",
            active.filter(Alarm_type=A.GATEWAY_OVERHEAT).filter(
                last_seen__lt=now - timedelta(hours=_setting("ALARM_CLOSE_OVERHEAT_HOURS", 2))
            ),
            seen(),
        ),
        (
            "meter reading issue not repeated",
            active.filter(Alarm_type=A.METER_READING_ISSUE).filter(
                last_seen__lt=now - timedelta(hours=_setting("ALARM_CLOSE_EVENT_HOURS", 24))
            ),
            seen(),
        ),
        (
            "daily alarm, day after its day is over",
            # created_time is the start of the alarm's day (or the time, for DG).
            active.filter(Alarm_type__in=DAILY, created_time__lt=today_start - timedelta(days=1)),
            None,
        ),
    ]


def close_resolved(now=None, dry_run=False):
    """Close resolved alarms; returns ``{label: count}``."""
    now = now or datetime.now()
    counts = {}
    for label, queryset, off_time in rules(now):
        if dry_run:
            counts[label] = queryset.count()
            continue
        if off_time is None:
            # Daily alarms: closed at the end of their own day.
            closed = 0
            for day_start in queryset.dates("created_time", "day"):
                end = datetime.combine(day_start, time.max).replace(microsecond=0)
                closed += queryset.filter(
                    created_time__gte=datetime.combine(day_start, time.min),
                    created_time__lt=datetime.combine(day_start, time.min) + timedelta(days=1),
                ).update(is_active=False, off_time=end)
            counts[label] = closed
        else:
            counts[label] = queryset.update(is_active=False, off_time=off_time)
    total = sum(counts.values())
    if total and not dry_run:
        logger.info("Alarms closed (resolved): %s", ", ".join(f"{k}={v}" for k, v in counts.items() if v))
    return counts
