"""Daily consumption alarms of one aisle (Phase E, docs/alarm-feature-plan.md).

Evaluated once a day is complete: from the live path when the next day's first
reading arrives, and again after recovery rewrites a past day. Every alarm is
stored at most once per site, aisle, type and day, so re-evaluating is safe.

Rules (decided 2026-10-20):

* No baseline for the day, or a day before the baseline start: no alarm.
* Bypassed (11): consumption >= the aisle's daily baseline x
  ``ALARM_BYPASS_DEFAULT_PERCENT`` % (default 100: no saving at all that day),
  or >= ``site.bypass_consumption_units`` when the site sets it (override).
  It supersedes High Consumption for that day, so High covers 75-100 %.
  (Changed 2026-10-23: before, Bypassed fired only with the site value set.)
* High Consumption (7): consumption >= ``site.high_consumption_units``, else
  >= baseline x ``site.high_consumption_baseline_percent`` (default 75 %).
* Low Consumption (8): consumption < baseline x (1 - ``site.min_threshold_value`` %);
  only for sites that set ``min_threshold_value``.
  Not automatic on purpose: low consumption is the normal result (median
  aisle-day uses ~17 % of its baseline), so a default would flood alarms.
* Operation Hours Increased (12): NL aisles of sites with NL hours and a
  start/end time; an hour counts as active at >= 0.01 kWh. Raised when an
  active hour falls outside the window or there are more active hours than
  ``nl_operation_hours``. A High Consumption alarm on the same day names it
  as the cause.

Per site and type an AlarmSetting (wareApp/alarm_policy.py) can override these
rules (decided 2026-10-27): Off = not raised; Manual = its threshold in kWh per
day (Bypassed, High, Low); Auto = from the baseline only (Bypassed x
ALARM_BYPASS_DEFAULT_PERCENT, High x the site's or default percent, Low below
baseline less the site's or ALARM_LOW_CONSUMPTION_DEFAULT_PERCENT). Without a
setting the rules above apply unchanged.

E-mail: an alarm that also fired the day before is e-mailed again only when
its consumption is more than the repeat tolerance worse than the last e-mail.
"""

import logging
from datetime import datetime, timedelta

from django.conf import settings

from wareApp import alarm_policy
from wareApp.models import AlarmNotifications, AlarmSetting, HourlySiteReading
from wareApp.mqtt.services.baseline import baseline_info, effective_hours, is_emergency_supply
from wareApp.mqtt.services.notifications import notify
from wareApp.sendmail import send_alarm_email

logger = logging.getLogger(__name__)

HIGH_CONSUMPTION = 7
LOW_CONSUMPTION = 8
BYPASSED = 11
OPERATION_HOURS_INCREASED = 12


def _high_percent(site):
    value = getattr(site, "high_consumption_baseline_percent", None)
    if value is not None:
        return value
    return getattr(settings, "ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT", 75)


def _bypass_threshold(site, baseline):
    """``(threshold_kwh, how)`` for the Bypassed alarm, or (None, None).

    The site's ``bypass_consumption_units`` overrides; otherwise the aisle's
    own daily baseline x ALARM_BYPASS_DEFAULT_PERCENT %. No baseline, no alarm.
    """
    value = getattr(site, "bypass_consumption_units", None)
    if value is not None:
        return value, "site setting"
    if not baseline:
        return None, None
    percent = getattr(settings, "ALARM_BYPASS_DEFAULT_PERCENT", 100)
    return baseline * percent / 100, f"{percent:g} % of baseline"


def _threshold(site, alarm_type, legacy, auto):
    """``(threshold_kwh, how)`` from the site's AlarmSetting, or (None, None).

    ``legacy()`` and ``auto()`` return ``(value, how)`` for "no setting" and Auto.
    """
    mode = alarm_policy.mode(site.id, alarm_type)
    if mode == AlarmSetting.OFF:
        return None, None
    if mode == AlarmSetting.MANUAL:
        manual = alarm_policy.manual_threshold(site.id, alarm_type)
        if manual is not None:
            return manual, "manual setting"
        return legacy()
    if mode == AlarmSetting.AUTO:
        return auto()
    return legacy()


def _activity_threshold():
    return getattr(settings, "ALARM_ACTIVITY_THRESHOLD_KWH", 0.01)


def _in_window(hour, start, end):
    """Hour start ``hour`` lies in [start, end); the window may cross midnight."""
    if start.hour == end.hour:
        return True
    if start.hour < end.hour:
        return start.hour <= hour < end.hour
    return hour >= start.hour or hour < end.hour


def operation_hours_check(site, aisle_group, day):
    """Return ``(active_hours, extra_hours)`` for an NL aisle, or None when not evaluated."""
    if is_emergency_supply(getattr(aisle_group, "aisleGroupName", "")):
        return None
    nl_hours = getattr(site, "nl_operation_hours", None)
    start = getattr(site, "nl_operation_start_time", None)
    end = getattr(site, "nl_operation_end_time", None)
    if not (nl_hours and start and end):
        return None
    day_start = datetime.combine(day, datetime.min.time())
    active = sorted(
        reading_from.hour
        for reading_from in HourlySiteReading.objects.filter(
            associated_Site=site,
            leg_id=aisle_group.attached_leg_id,
            reading_from__gte=day_start,
            reading_from__lt=day_start + timedelta(days=1),
            unit_consumption__gte=_activity_threshold(),
        ).values_list("reading_from", flat=True)
    )
    extra = [hour for hour in active if not _in_window(hour, start, end)]
    if extra or len(active) > nl_hours:
        return active, extra
    return None


def _record(site, aisle_group, day, alarm_type, title, to_do, details,
            value=None, worse_when_higher=True):
    day_start = datetime.combine(day, datetime.min.time())
    if AlarmNotifications.objects.filter(
        site_id=site,
        aisle_group=aisle_group,
        Alarm_type=alarm_type,
        created_time__gte=day_start,
        created_time__lt=day_start + timedelta(days=1),
        is_active=True,
    ).exists():
        return False
    meter_id = str(aisle_group.attached_leg_id or "")
    # The same alarm the day before (not cleared): compare with its last e-mail.
    last_value = (
        AlarmNotifications.objects.filter(
            site_id=site,
            aisle_group=aisle_group,
            Alarm_type=alarm_type,
            created_time=day_start - timedelta(days=1),
        )
        .values_list("notified_value", flat=True)
        .first()
    )
    send = alarm_policy.should_email(
        last_value, value, worse_when_higher, alarm_policy.tolerance_percent(site.id, alarm_type)
    )
    AlarmNotifications.objects.create(
        created_by=None,
        user_level=2,
        site_id=site,
        object_type=4,
        object_id=int(meter_id) if meter_id.isdigit() else None,
        aisle_group=aisle_group,
        Alarm_type=alarm_type,
        Alarm_priority=1,
        created_time=day_start,
        to_do=to_do[:200],
        # Carry the last e-mailed value forward when this one is not e-mailed.
        notified_value=value if send else last_value,
    )
    if send:
        notify(
            send_alarm_email,
            title,
            site.id,
            [
                ["Aisle group", getattr(aisle_group, "aisleGroupName", ""), False],
                ["Leg", meter_id, False],
                ["Date", str(day), False],
                *details,
            ],
            alarm_type,
        )
    logger.warning(
        "Consumption alarm stored: site=%s leg_id=%s aisle_group_name=%s date=%s alarm=%s emailed=%s %s",
        site.id,
        meter_id,
        getattr(aisle_group, "aisleGroupName", ""),
        day,
        title,
        send,
        to_do,
    )
    return True


def evaluate_daily_alarms(site, aisle_group, daily_reading):
    """Evaluate all daily alarms of one aisle for ``daily_reading.reading_for``.

    Returns the titles of the alarms stored by this call.
    """
    day = daily_reading.reading_for
    consumption = daily_reading.unit_consumption or 0.0
    leg_id = aisle_group.attached_leg_id
    info = baseline_info(site.id, leg_id, day)
    if info is None:
        logger.debug("Consumption alarms skipped, no baseline: site=%s leg=%s date=%s", site.id, leg_id, day)
        return []
    baseline, working_hours, baseline_from = info
    if baseline_from and day < baseline_from:
        return []

    supply = "EL" if is_emergency_supply(getattr(aisle_group, "aisleGroupName", "")) else "NL"
    hours = effective_hours(site, aisle_group, working_hours)
    common = [
        ["Supply", f"{supply} ({hours} h)", False],
        ["Consumption (kWh)", f"{consumption:.2f}", True],
        ["Daily baseline (kWh)", f"{baseline:.2f}", False],
    ]
    stored = []

    def bypass_auto():
        percent = getattr(settings, "ALARM_BYPASS_DEFAULT_PERCENT", 100)
        return (baseline * percent / 100, f"{percent:g} % of baseline") if baseline else (None, None)

    bypass, bypass_how = _threshold(site, BYPASSED, lambda: _bypass_threshold(site, baseline), bypass_auto)
    if bypass is not None and consumption >= bypass:
        if _record(
            site, aisle_group, day, BYPASSED, "Bypassed Alarm",
            f"Bypassed: consumption={consumption:.2f}, threshold={bypass:.2f} ({bypass_how}), baseline={baseline:.2f}.",
            common + [["Bypass threshold (kWh)", f"{bypass:.2f} ({bypass_how})", False]],
            value=consumption,
        ):
            stored.append("Bypassed")
        return stored

    hours_check = (
        None
        if alarm_policy.is_off(site.id, OPERATION_HOURS_INCREASED)
        else operation_hours_check(site, aisle_group, day)
    )
    if hours_check is not None:
        active, extra = hours_check
        if _record(
            site, aisle_group, day, OPERATION_HOURS_INCREASED, "Operation Hours Increased Alarm",
            f"Operation hours increased: active={len(active)} h (NL {site.nl_operation_hours} h), "
            f"outside window={len(extra)} h.",
            common + [
                ["NL window", f"{site.nl_operation_start_time:%H:%M}-{site.nl_operation_end_time:%H:%M} ({site.nl_operation_hours} h)", False],
                ["Active hours", f"{len(active)}", True],
                ["Active outside window", ", ".join(f"{hour:02d}:00" for hour in extra) or "-", bool(extra)],
            ],
            value=float(len(active)),
        ):
            stored.append("Operation Hours Increased")

    def high_auto():
        return (baseline * _high_percent(site) / 100, "baseline") if baseline else (None, None)

    def high_legacy():
        units = getattr(site, "high_consumption_units", None)
        return (units, "site setting") if units is not None else high_auto()

    high, _ = _threshold(site, HIGH_CONSUMPTION, high_legacy, high_auto)
    if high is not None and consumption >= high:
        cause = " Cause: operation hours increased." if hours_check is not None else ""
        if _record(
            site, aisle_group, day, HIGH_CONSUMPTION, "High Consumption Alarm",
            f"High consumption: consumption={consumption:.2f}, threshold={high:.2f}, baseline={baseline:.2f}.{cause}",
            common + [["High threshold (kWh)", f"{high:.2f}", False]]
            + ([["Cause", "Operation hours increased", True]] if cause else []),
            value=consumption,
        ):
            stored.append("High Consumption")
        return stored

    def low_from(percent):
        if percent is None or not baseline:
            return None, None
        return baseline * (1 - percent / 100), f"baseline less {percent:g}%"

    def low_auto():
        percent = getattr(site, "min_threshold_value", None)
        if percent is None:
            percent = getattr(settings, "ALARM_LOW_CONSUMPTION_DEFAULT_PERCENT", 90)
        return low_from(percent)

    low, low_how = _threshold(
        site, LOW_CONSUMPTION, lambda: low_from(getattr(site, "min_threshold_value", None)), low_auto
    )
    if low is not None:
        if consumption < low:
            if _record(
                site, aisle_group, day, LOW_CONSUMPTION, "Low Consumption Alarm",
                f"Low consumption: consumption={consumption:.2f}, minimum={low:.2f}, baseline={baseline:.2f}.",
                common + [["Minimum (kWh)", f"{low:.2f} ({low_how})", False]],
                value=consumption,
                worse_when_higher=False,
            ):
                stored.append("Low Consumption")
    return stored


def evaluate_days(site, aisle_group, days):
    """Re-evaluate complete past days after recovery rewrote them; returns stored titles."""
    from wareApp.models import DailySiteReading

    today = datetime.now().date()
    # Only recent days: a recovery covering weeks must not raise a burst of old alarms.
    oldest = today - timedelta(days=getattr(settings, "ALARM_REEVALUATE_DAYS", 7))
    past_days = sorted({day for day in days if oldest <= day < today})
    if not past_days or not getattr(aisle_group, "is_active", False):
        return []
    stored = []
    for reading in DailySiteReading.objects.filter(
        associated_Site=site, leg_id=aisle_group.attached_leg_id, reading_for__in=past_days
    ).order_by("reading_for"):
        stored += [f"{reading.reading_for} {title}" for title in evaluate_daily_alarms(site, aisle_group, reading)]
    return stored
