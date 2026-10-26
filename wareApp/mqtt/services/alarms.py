"""Store power / DG alarms in the single alarm table (AlarmNotifications).

One row per site, power source, alarm type and day. A repeat inside the day
updates ``last_seen``, ``occurrences`` and the latest measured values instead
of adding a row. ``repeat_every`` keeps the former behaviour of alarms that
repeat (voltage, PF: at most one occurrence and one e-mail per 30 minutes);
without it every call counts and e-mails (DG alarms, once per DG unit).
"""

import logging
from datetime import datetime

from django.db.models import F
from django.utils import timezone

from wareApp.models import AlarmNotifications
from wareApp.mqtt.services.notifications import notify

logger = logging.getLogger(__name__)

MEASURED_FIELDS = ("r_phase", "y_phase", "b_phase", "fuel_level", "run_hours")


def raise_power_alarm(
    site,
    alarm_type,
    *,
    power_source=None,
    priority=AlarmNotifications.PRIORITY_MEDIUM,
    values=None,
    repeat_every=None,
    email=None,
):
    """Record one occurrence of a power / DG alarm; returns the row or None.

    ``values``  measured values (keys of MEASURED_FIELDS) shown with the alarm.
    ``email``   ``(send_function, *args)`` passed to ``notify`` when recorded.
    Returns None when ``repeat_every`` has not passed since the last occurrence.
    """
    now = timezone.now()
    values = {k: v for k, v in (values or {}).items() if k in MEASURED_FIELDS}
    day_start = datetime.combine(now.date(), datetime.min.time())
    today = (
        AlarmNotifications.objects.filter(
            site_id=site,
            Alarm_type=alarm_type,
            power_source=power_source,
            is_active=True,
            created_time__gte=day_start,
        )
        .order_by("-id")
        .first()
    )
    if (
        today is not None
        and repeat_every is not None
        and today.last_notified_at is not None
        and now - today.last_notified_at < repeat_every
    ):
        return None

    if today is None:
        alarm = AlarmNotifications.objects.create(
            site_id=site,
            user_level=2,
            Alarm_type=alarm_type,
            Alarm_priority=priority,
            power_source=power_source,
            created_time=now,
            last_seen=now,
            last_notified_at=now,
            occurrences=1,
            **values,
        )
    else:
        AlarmNotifications.objects.filter(pk=today.pk).update(
            last_seen=now,
            last_notified_at=now,
            occurrences=F("occurrences") + 1,
            **values,
        )
        alarm = today
    logger.warning(
        "Power alarm %s: site=%s source=%s type=%s values=%s",
        "stored" if today is None else "repeated",
        getattr(site, "id", site),
        power_source,
        alarm_type,
        values,
    )
    if email:
        notify(*email)
    return alarm
