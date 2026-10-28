"""Data-missing alarms: Meter Disconnected (14), Gateway Disconnected (15),
Gateway Service / Modbus Issue (16). Zero-consumption cases 3, 5 and 6.

Sources (existing tables):
* MeterDisconnectionEvent - meter disconnect / reconnect events the gateways
  report themselves (meter-disconnections/ingest/).
* HomeGatewayStatus.last_data_at - last consumption / recovery / load /
  LoadData packet, written by our MQTT listeners (gateway_activity.py).
* HomeGatewayStatus.last_ping_at - last PINGREQ / connection / packet from the
  gateway's client in the Mosquitto log, written by ``read_broker_log`` (run
  ``manage.py gateway_health --broker-log PATH`` as a user that can read it).

Rules (threshold GATEWAY_HEALTH_DOWN_MINUTES = 60, or an AlarmSetting's
Manual threshold in hours; Off = not raised):
* 14: the meter's latest event is "disconnected" since >= threshold.
* 15: no ping and no data for >= threshold. Without fresh ping information
  (log not read in the last GATEWAY_HEALTH_PING_FRESH_MINUTES) a gateway
  silent >= threshold counts as disconnected.
* 16: pings arrive but no data for >= threshold.

An alarm is one active row per issue: it is e-mailed when raised and only
``last_seen`` moves while it lasts. When the meter / gateway is back the row
is closed (is_active False, off_time). No e-mail on clearing; the next e-mail
of the same issue carries a "Previous outage ... restored ..." line.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Max

from wareApp.models import AlarmNotifications, HomeGatewayStatus, MeterDisconnectionEvent, Site
from wareApp.mqtt.services import alarm_policy
from wareApp.mqtt.services.notifications import notify
from wareApp.sendmail import send_alarm_email

logger = logging.getLogger(__name__)

METER_OBJECT = 4
GATEWAY_OBJECT = 5
PING_READ_KEY = "gateway-health:ping-log-read-at"
LOG_OFFSET_KEY = "gateway-health:log-offset:{path}"
FIRST_READ_BYTES = 20 * 1024 * 1024

# "1793175085: Received PINGREQ from odroid.avc_x_000145_1"
# "1793175085: New client connected from 1.2.3.4:5 as odroid.avc_x_000145_1 (p2, c1, k60)."
# "1793175085: Received PUBLISH from odroid.avc_x_000145_1 (d0, q0, ...)"
_ALIVE = re.compile(
    r"^(?P<epoch>\d+): (?:Received \S+ from|New client connected from \S+ as) (?P<client>\S+)"
)


def _down_after(site_id, alarm_type):
    hours = alarm_policy.manual_threshold(site_id, alarm_type)
    if hours:
        return timedelta(hours=hours)
    return timedelta(minutes=getattr(settings, "GATEWAY_HEALTH_DOWN_MINUTES", 60))


def gateway_number(hgw_id):
    """``avc_x_000145_2`` -> 2 (the alarm's object_id, as the alarm feed expects)."""
    tail = str(hgw_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _hours(delta):
    return f"{delta.total_seconds() / 3600:.1f} h"


# ---------------------------------------------------------------- broker log
def read_broker_log(path, from_start=False, remember=True):
    """Read new lines of the Mosquitto log; returns {home gateway id: last alive}.

    Remembers the read position (Django cache); after a rotation or on the
    first run it starts at the beginning (``from_start``) or the last 20 MB.
    """
    stat = os.stat(path)
    key = LOG_OFFSET_KEY.format(path=path)
    inode, offset = cache.get(key) or (None, None)
    mid_line = False
    if from_start:
        offset = 0
    elif inode != stat.st_ino or offset is None or offset > stat.st_size:
        offset = max(0, stat.st_size - FIRST_READ_BYTES)
        mid_line = offset > 0
    alive = {}
    with open(path, "rb") as log:
        log.seek(offset)
        if mid_line:
            log.readline()  # started inside a line
        for raw in log:
            match = _ALIVE.match(raw.decode("utf-8", "replace"))
            if not match:
                continue
            client = match.group("client")
            gateway = client.split(".", 1)[1] if client.startswith("odroid.") else client
            alive[gateway] = max(alive.get(gateway, 0), int(match.group("epoch")))
        offset = log.tell()
    if remember:
        cache.set(key, (stat.st_ino, offset), None)
    return {gateway: datetime.fromtimestamp(epoch) for gateway, epoch in alive.items()}


def store_pings(alive, now=None):
    """Write last_ping_at for known gateways; marks ping information as fresh."""
    statuses = {
        status.home_gateway.hgw_id: status
        for status in HomeGatewayStatus.objects.select_related("home_gateway").filter(
            home_gateway__hgw_id__in=list(alive)
        )
    }
    changed = []
    for gateway, seen_at in alive.items():
        status = statuses.get(gateway)
        if status is not None and (status.last_ping_at is None or seen_at > status.last_ping_at):
            status.last_ping_at = seen_at
            changed.append(status)
    HomeGatewayStatus.objects.bulk_update(changed, ["last_ping_at"])
    cache.set(PING_READ_KEY, now or datetime.now(), None)
    return len(changed)


def ping_information_fresh(now):
    read_at = cache.get(PING_READ_KEY)
    fresh = timedelta(minutes=getattr(settings, "GATEWAY_HEALTH_PING_FRESH_MINUTES", 15))
    return read_at is not None and now - read_at <= fresh


# ---------------------------------------------------------------- alarms
@dataclass
class Report:
    raised: list = field(default_factory=list)
    repeated: list = field(default_factory=list)
    cleared: list = field(default_factory=list)

    def __str__(self):
        return f"raised={len(self.raised)} still_active={len(self.repeated)} cleared={len(self.cleared)}"


def _raise(report, site_id, alarm_type, object_type, object_id, detail, details, now, priority):
    if alarm_policy.is_off(site_id, alarm_type):
        return
    issue = dict(site_id_id=site_id, Alarm_type=alarm_type, object_type=object_type, object_id=object_id)
    if AlarmNotifications.objects.filter(is_active=True, **issue).update(last_seen=now, to_do=detail[:200]):
        report.repeated.append((site_id, alarm_type, object_id))
        return
    previous = (
        AlarmNotifications.objects.filter(is_active=False, off_time__isnull=False, **issue)
        .order_by("-off_time")
        .first()
    )
    AlarmNotifications.objects.create(
        user_level=2, Alarm_priority=priority, created_time=now, last_seen=now,
        off_time=now, to_do=detail[:200], **issue,
    )
    if previous is not None:
        started = previous.created_time
        details = details + [[
            "Previous outage",
            f"{started:%d %b %H:%M} - restored {previous.off_time:%d %b %H:%M} "
            f"({_hours(previous.off_time - started)})",
            False,
        ]]
    title = dict(AlarmNotifications.alarm_type)[alarm_type]
    notify(send_alarm_email, title, site_id, details, alarm_type)
    report.raised.append((site_id, alarm_type, object_id))
    logger.warning("Gateway health alarm raised: site=%s type=%s object=%s %s", site_id, alarm_type, object_id, detail)


def _clear(report, site_id, alarm_type, object_type, object_id, now):
    closed = AlarmNotifications.objects.filter(
        site_id_id=site_id, Alarm_type=alarm_type, object_type=object_type,
        object_id=object_id, is_active=True,
    ).update(is_active=False, off_time=now, last_seen=now)
    if closed:
        report.cleared.append((site_id, alarm_type, object_id))
        logger.info("Gateway health alarm cleared: site=%s type=%s object=%s", site_id, alarm_type, object_id)


def evaluate_gateways(report, now):
    with_pings = ping_information_fresh(now)
    statuses = HomeGatewayStatus.objects.select_related("home_gateway").filter(
        home_gateway__connected_to__is_live=True, last_data_at__isnull=False,
    )
    for status in statuses:
        hgw = status.home_gateway
        site_id, number = hgw.connected_to_id, gateway_number(hgw.hgw_id)
        data_age = now - status.last_data_at
        ping_age = (now - status.last_ping_at) if (with_pings and status.last_ping_at) else None
        disconnected_after = _down_after(site_id, AlarmNotifications.GATEWAY_DISCONNECTED)
        service_after = _down_after(site_id, AlarmNotifications.GATEWAY_SERVICE_ISSUE)
        common = [["Gateway", hgw.hgw_id, False], ["Last data", f"{status.last_data_at:%d %b %H:%M}", True]]
        if data_age >= disconnected_after and (ping_age is None or ping_age >= disconnected_after):
            last_ping = f"{status.last_ping_at:%d %b %H:%M}" if status.last_ping_at else "unknown"
            _raise(
                report, site_id, AlarmNotifications.GATEWAY_DISCONNECTED, GATEWAY_OBJECT, number,
                f"Gateway {hgw.hgw_id}: no data and no ping for {_hours(data_age)}",
                common + [["Last ping", last_ping if with_pings else "not available", False]],
                now, AlarmNotifications.PRIORITY_HIGH,
            )
            _clear(report, site_id, AlarmNotifications.GATEWAY_SERVICE_ISSUE, GATEWAY_OBJECT, number, now)
        elif data_age >= service_after and ping_age is not None:
            _raise(
                report, site_id, AlarmNotifications.GATEWAY_SERVICE_ISSUE, GATEWAY_OBJECT, number,
                f"Gateway {hgw.hgw_id}: pings OK, no consumption / recovery / load data for {_hours(data_age)}",
                common + [["Last ping", f"{status.last_ping_at:%d %b %H:%M}", False]],
                now, AlarmNotifications.PRIORITY_HIGH,
            )
            _clear(report, site_id, AlarmNotifications.GATEWAY_DISCONNECTED, GATEWAY_OBJECT, number, now)
        else:
            for alarm_type in (AlarmNotifications.GATEWAY_DISCONNECTED, AlarmNotifications.GATEWAY_SERVICE_ISSUE):
                _clear(report, site_id, alarm_type, GATEWAY_OBJECT, number, now)
        online = data_age < disconnected_after
        if status.status != online:
            HomeGatewayStatus.objects.filter(pk=status.pk).update(status=online)


def evaluate_meters(report, now):
    latest = (
        MeterDisconnectionEvent.objects.values("meter_id")
        .annotate(last_end=Max("detection_window_end"))
    )
    live_sites = set(Site.objects.filter(is_live=True).values_list("id", flat=True))
    for row in latest:
        event = (
            MeterDisconnectionEvent.objects.filter(meter_id=row["meter_id"], detection_window_end=row["last_end"])
            .order_by("-id")
            .first()
        )
        site_id = event.logged_site_id or event.remote_site_id
        if site_id not in live_sites:
            continue
        meter = event.meter_number if event.meter_number is not None else event.meter_id
        if event.status == "disconnected":
            if now - event.detection_window_start >= _down_after(site_id, AlarmNotifications.METER_DISCONNECTED):
                _raise(
                    report, site_id, AlarmNotifications.METER_DISCONNECTED, METER_OBJECT, meter,
                    f"Meter {event.meter_name} (port {event.port_id or '-'}) disconnected since "
                    f"{event.detection_window_start:%d %b %H:%M}",
                    [
                        ["Meter", f"{event.meter_name} (number {meter})", False],
                        ["Port", event.port_id or "-", False],
                        ["Disconnected since", f"{event.detection_window_start:%d %b %H:%M}", True],
                    ],
                    now, AlarmNotifications.PRIORITY_MEDIUM,
                )
        else:
            _clear(report, site_id, AlarmNotifications.METER_DISCONNECTED, METER_OBJECT, meter, now)


def evaluate(now=None):
    """Raise, keep or clear alarms 14 / 15 / 16; returns a Report."""
    now = now or datetime.now()
    report = Report()
    evaluate_gateways(report, now)
    evaluate_meters(report, now)
    return report
