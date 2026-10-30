"""Consumption Spike alarm (type 17): an hour that is not real use, and why.

A spike hour (consumption_alarms.find_spikes) is either
* a meter jump - one hour above the aisle's whole daily baseline. With a Meter
  Reading Issue the same day the gateway reported a lower meter reading: the
  meter was reset or replaced and the difference landed in one hour.
* a catch-up hour - the first hour after a data gap, more than 3 x the day's
  median hour: it carries the consumption of the missing hours. The cause of
  the gap is named when known: a Gateway Disconnected / Service alarm on the
  site, or our own server / listener restarting in the gap.

Spike hours are not counted by Bypassed / High Consumption; the spike itself
is kept for manual spreading. One alarm per aisle per day (e-mailed when
raised); later spikes the same day update its text. One e-mail per site and
scan lists all its newly raised aisles (one gateway gap hits many aisles).
Scanned every CONSUMPTION_SPIKE_CHECK_SECONDS by Celery beat over today and
yesterday.
"""

import logging
from datetime import datetime, time, timedelta
from itertools import groupby

from wareApp.models import AisleGroup, AlarmNotifications, HourlySiteReading, MonitoringMarker, Site
from wareApp.mqtt.services import alarm_policy
from wareApp.mqtt.services.baseline import baseline_info
from wareApp.mqtt.services.consumption_alarms import find_spikes, meter_issue_on
from wareApp.mqtt.services.notifications import notify
from wareApp.sendmail import send_alarm_email

logger = logging.getLogger(__name__)

CONSUMPTION_SPIKE = AlarmNotifications.CONSUMPTION_SPIKE
GATEWAY_ALARMS = (AlarmNotifications.GATEWAY_DISCONNECTED, AlarmNotifications.GATEWAY_SERVICE_ISSUE)


def _gap_reason(site_id, gap_from, gap_to, restarts):
    # A restart up to the end of the spike hour also ended the gap.
    if any(gap_from <= at < gap_to + timedelta(hours=2) for at in restarts):
        return "our server / listener was down (restarted in the gap)"
    gateway_alarm = (
        AlarmNotifications.objects.filter(
            site_id_id=site_id, Alarm_type__in=GATEWAY_ALARMS, created_time__lte=gap_to,
        )
        .exclude(is_active=False, off_time__lt=gap_from)
        .exclude(to_do__startswith="FALSE")
        .order_by("-created_time")
        .values_list("Alarm_type", "to_do")
        .first()
    )
    if gateway_alarm:
        name = dict(AlarmNotifications.alarm_type)[gateway_alarm[0]]
        return f"{name}: {gateway_alarm[1].split(':')[0]}"
    return "no readings stored (gateway offline or not sending)"


def cause(site, aisle, day, spike, baseline, restarts):
    """Plain-text cause of one spike hour."""
    if spike.kind == "jump":
        if meter_issue_on(site, aisle, day):
            return "meter reset or replaced: the gateway reported a lower meter reading (ERROR!!!) the same day"
        return f"meter jump: {spike.kwh:.0f} kWh in one hour, more than the whole daily baseline ({baseline:.0f} kWh)"
    if spike.previous is None:
        return "catch-up: first reading after more than 2 days without data"
    gap_from = spike.previous + timedelta(hours=1)
    gap_to = spike.at - timedelta(hours=1)
    missing = int((spike.at - spike.previous).total_seconds() // 3600) - 1
    return (
        f"catch-up: carries {missing} missing hour(s) {gap_from:%d %b %H:%M}-{gap_to:%H:%M}; "
        f"gap cause: {_gap_reason(site.id, gap_from, gap_to, restarts)}"
    )


def scan(now=None):
    """Raise / update Consumption Spike alarms for today and yesterday; returns a summary."""
    now = now or datetime.now()
    today = now.date()
    days = (today - timedelta(days=1), today)
    window_start = datetime.combine(days[0], time.min) - timedelta(days=2)
    sites = {site.id: site for site in Site.objects.filter(is_live=True)}
    aisles = {
        (aisle.site_id, str(aisle.attached_leg_id)): aisle
        for aisle in AisleGroup.objects.filter(site_id__in=sites)
    }
    restarts = list(
        MonitoringMarker.objects.filter(name="mqtt_listener_started_at", at__gte=window_start)
        .values_list("at", flat=True)
    )
    rows = (
        HourlySiteReading.objects.filter(associated_Site_id__in=sites, reading_from__gte=window_start)
        .order_by("associated_Site_id", "leg_id", "reading_from")
        .values_list("associated_Site_id", "leg_id", "reading_from", "unit_consumption")
        .iterator(chunk_size=5000)
    )
    raised = updated = 0
    new_by_site = {}
    for (site_id, leg_id), group in groupby(rows, key=lambda row: (row[0], row[1])):
        aisle = aisles.get((site_id, str(leg_id)))
        if aisle is None or alarm_policy.is_off(site_id, CONSUMPTION_SPIKE):
            continue
        series = [(at, kwh) for _, _, at, kwh in group]
        site = sites[site_id]
        for day in days:
            info = baseline_info(site_id, leg_id, day)
            baseline = info[0] if info else None
            spikes = find_spikes(series, datetime.combine(day, time.min), baseline)
            if not spikes:
                continue
            reasons = [cause(site, aisle, day, spike, baseline or 0, restarts) for spike in spikes]
            text = "Spike: " + "; ".join(
                f"{spike.at:%H:%M} {spike.kwh:.2f} kWh ({reason.split(':')[0]})"
                for spike, reason in zip(spikes, reasons)
            )
            day_start = datetime.combine(day, time.min)
            existing = AlarmNotifications.objects.filter(
                site_id=site, aisle_group=aisle, Alarm_type=CONSUMPTION_SPIKE, created_time=day_start,
            )
            if existing.exists():
                updated += existing.exclude(to_do=text[:200]).update(to_do=text[:200], last_seen=now)
                continue
            meter_id = str(aisle.attached_leg_id or "")
            AlarmNotifications.objects.create(
                user_level=2, site_id=site, object_type=4, aisle_group=aisle,
                object_id=int(meter_id) if meter_id.isdigit() else None,
                Alarm_type=CONSUMPTION_SPIKE, Alarm_priority=AlarmNotifications.PRIORITY_MEDIUM,
                created_time=day_start, last_seen=now, to_do=text[:200],
                notified_value=max(spike.kwh for spike in spikes),
            )
            raised += 1
            new_by_site.setdefault(site_id, []).extend(
                [f"{aisle.aisleGroupName} {spike.at:%d %b %H:%M}", f"{spike.kwh:.2f} kWh - {reason}", True]
                for spike, reason in zip(spikes, reasons)
            )
    for site_id, rows in new_by_site.items():
        notify(
            send_alarm_email, "Consumption Spike Alarm", site_id,
            [["Aisles", str(len({row[0].rsplit(' ', 2)[0] for row in rows})), False], *rows,
             ["Note", "Spike hours are not counted by Bypassed / High Consumption; spread them by hand if needed", False]],
            CONSUMPTION_SPIKE,
        )
    summary = f"spike scan: raised={raised} updated={updated}"
    if raised or updated:
        logger.warning(summary)
    return summary
