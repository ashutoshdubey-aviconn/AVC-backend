"""Alarm configuration, recipients and repeat e-mail rule, in one place.

* ``setting(site_id, alarm_type)``: the site's AlarmSetting for the type, or None
  (no row: the alarm works as before, from the site fields and defaults).
* ``is_off`` / ``manual_threshold``: what the setting says.
* ``recipients(site_id, alarm_type)``: software team (every site) and the site's
  ground team from alarm_recipients.py, as enabled for the type. While both
  lists are empty the former ALARM_EMAIL_DEFAULT_TO list is used.
* ``should_email(last_value, value, worse_when_higher, ...)``: a repeat of an
  alarm is e-mailed again only when its value is more than the tolerance
  (ALARM_REPEAT_TOLERANCE_PERCENT, default 5 %) worse than the last e-mailed
  value. ``last_emailed_value`` finds that value for an issue: today's row, or
  an earlier row seen within ALARM_REPEAT_CLEAR_HOURS (an alarm absent for
  longer has cleared, so its next occurrence is e-mailed again).

Settings are cached for CACHE_SECONDS; saving or deleting an AlarmSetting
clears the cache (signals at the bottom).
"""

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from wareApp.models import AlarmNotifications, AlarmSetting
from wareApp.mqtt.services import alarm_recipients

CACHE_SECONDS = 5 * 60
_VERSION_KEY = "alarm-policy:version"
_NO_ROW = "none"


def _version():
    version = cache.get(_VERSION_KEY)
    if version is None:
        version = 1
        cache.add(_VERSION_KEY, version, None)
    return version


def clear_cache():
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 2, None)


def setting(site_id, alarm_type):
    key = f"alarm-policy:{_version()}:setting:{site_id}:{alarm_type}"
    row = cache.get(key)
    if row is None:
        row = AlarmSetting.objects.filter(site_id=site_id, alarm_type=alarm_type).first() or _NO_ROW
        cache.set(key, row, CACHE_SECONDS)
    return None if row == _NO_ROW else row


def mode(site_id, alarm_type):
    """AlarmSetting.AUTO / MANUAL / OFF, or None without a setting row."""
    row = setting(site_id, alarm_type)
    return row.mode if row else None


def is_off(site_id, alarm_type):
    return mode(site_id, alarm_type) == AlarmSetting.OFF


def manual_threshold(site_id, alarm_type):
    """The typed-in threshold when the type is in Manual mode, else None."""
    row = setting(site_id, alarm_type)
    if row and row.mode == AlarmSetting.MANUAL:
        return row.threshold
    return None


def recipients(site_id, alarm_type=None):
    """E-mail addresses for one alarm of a site (software + ground team)."""
    row = setting(site_id, alarm_type) if alarm_type is not None else None
    software = alarm_recipients.SOFTWARE_TEAM if (row.email_software if row else True) else []
    ground = (
        alarm_recipients.GROUND_TEAM.get(int(site_id), [])
        if (row.email_ground if row else True)
        else []
    )
    if not alarm_recipients.SOFTWARE_TEAM and not alarm_recipients.GROUND_TEAM:
        # Nobody configured yet: keep the former single list.
        return list(getattr(settings, "ALARM_EMAIL_DEFAULT_TO", []) or [])
    return list(dict.fromkeys(address.strip() for address in [*software, *ground] if address.strip()))


def tolerance_percent(site_id, alarm_type):
    row = setting(site_id, alarm_type)
    if row and row.repeat_tolerance_percent is not None:
        return row.repeat_tolerance_percent
    return getattr(settings, "ALARM_REPEAT_TOLERANCE_PERCENT", 5)


def should_email(last_value, value, worse_when_higher, tolerance):
    """True when nothing was e-mailed yet or ``value`` is > tolerance % worse."""
    if last_value is None or value is None:
        return True
    margin = abs(last_value) * tolerance / 100
    if worse_when_higher:
        return value > last_value + margin
    return value < last_value - margin


def last_emailed_value(site, alarm_type, now=None, **issue):
    """The last e-mailed value of an issue still considered active, or None.

    ``issue`` narrows the alarm: aisle_group=..., object_id=..., power_source=...
    An alarm whose newest occurrence is older than ALARM_REPEAT_CLEAR_HOURS has
    cleared; its next occurrence counts as new.
    """
    now = now or timezone.now()
    since = now - timedelta(hours=getattr(settings, "ALARM_REPEAT_CLEAR_HOURS", 24))
    return (
        AlarmNotifications.objects.filter(
            Q(last_seen__gte=since) | Q(last_seen__isnull=True, created_time__gte=since),
            site_id=site,
            Alarm_type=alarm_type,
            notified_value__isnull=False,
            **issue,
        )
        .order_by("-id")
        .values_list("notified_value", flat=True)
        .first()
    )


def decide_email(site, alarm_type, value, worse_when_higher, **issue):
    """``(send, last_value)`` for an occurrence of an issue with ``value``."""
    last_value = last_emailed_value(site, alarm_type, **issue)
    site_id = getattr(site, "id", site)
    send = should_email(
        last_value, value, worse_when_higher, tolerance_percent(site_id, alarm_type)
    )
    return send, last_value


@receiver([post_save, post_delete], sender=AlarmSetting)
def _settings_changed(**kwargs):
    clear_cache()
