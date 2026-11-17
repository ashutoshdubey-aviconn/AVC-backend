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
* 15: no ping and no data for >= threshold - only when the broker log was read
  in the last GATEWAY_HEALTH_PING_FRESH_MINUTES and shows no recent ping.
* 16: pings arrive but no data for >= threshold. Also used when there is no
  ping information (e.g. the test server, gateways ping main only): without
  proof that pings stopped it is never called disconnected (decided 2026-11-02).
  A disconnected gateway (open 15) whose pings come back is NOT switched to 16
  for GATEWAY_HEALTH_RECONNECT_MINUTES (10): its first ping arrives before its
  queued data is written (last_data_at is written at most once a minute), so
  every reconnect raised a false 16 + e-mail (site 130, 17 Nov 06:16 / 10:26).

An alarm is one active row per issue, created_time = when the outage began
(lists show since when it is not solved). It is e-mailed when raised and
again once a day while it is not solved (GATEWAY_HEALTH_REMINDER_HOURS);
``last_seen`` moves at every check. When the meter / gateway is back the row
is closed (is_active False, off_time). No e-mail on clearing; the next e-mail
of the same issue carries a "Previous outage ... restored ..." line.
"""

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Max

from wareApp.alarm_feed import open_for
from wareApp.models import AisleGroup, AlarmNotifications, HomeGatewayStatus, MeterDisconnectionEvent, MonitoringMarker
from wareApp.mqtt.services import alarm_policy, alarm_sites
from wareApp.mqtt.services.notifications import notify
from wareApp.sendmail import send_alarm_email

logger = logging.getLogger(__name__)

METER_OBJECT = 4
GATEWAY_OBJECT = 5
# A gateway shown under another site whose number is already used there
# (two "..._1" gateways under one display site) gets object_id = this + its id.
GATEWAY_PK_OFFSET = 10000
PING_READ_MARKER = "broker_log_read_at"
LISTENER_STARTED_MARKER = "mqtt_listener_started_at"
LOG_OFFSET_KEY = "gateway-health:log-offset:{path}"
FIRST_READ_BYTES = 20 * 1024 * 1024

# "1793175085: Received PINGREQ from odroid.avc_x_000145_1"
# "1793175085: New client connected from 1.2.3.4:5 as odroid.avc_x_000145_1 (p2, c1, k60)."
# "1793175085: New bridge connected from 1.2.3.4:5 as odroid.avc_x_000145_1 (p2, c1, k45)."
#   (gateways connect to main's broker as bridges)
# "1793175085: Received PUBLISH from odroid.avc_x_000145_1 (d0, q0, ...)"
_ALIVE = re.compile(
    r"^(?P<epoch>\d+): (?:Received \S+ from|New (?:client|bridge) connected from \S+ as) (?P<client>\S+)"
)


def mark(name, at=None):
    MonitoringMarker.objects.update_or_create(name=name, defaults={"at": at or datetime.now()})


def marker(name):
    return MonitoringMarker.objects.filter(name=name).values_list("at", flat=True).first()


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
        alive = alive_from_lines(raw.decode("utf-8", "replace") for raw in log)
        offset = log.tell()
    if remember:
        cache.set(key, (stat.st_ino, offset), None)
    return alive


def alive_from_lines(lines):
    """``{home gateway id: last alive}`` from Mosquitto log lines."""
    alive = {}
    for line in lines:
        match = _ALIVE.match(line)
        if not match:
            continue
        client = match.group("client")
        gateway = client.split(".", 1)[1] if client.startswith("odroid.") else client
        alive[gateway] = max(alive.get(gateway, 0), int(match.group("epoch")))
    return {gateway: datetime.fromtimestamp(epoch) for gateway, epoch in alive.items()}


def fetch_remote_pings(now=None):
    """Gateway pings from another server's broker log over SSH (decided 2026-11-06).

    For the test server: gateways ping main only. GATEWAY_PINGS_SSH
    ("user@host") with key GATEWAY_PINGS_SSH_KEY; on main that key is locked
    to one forced command that prints the ping / connect lines of the last
    few MB of the broker log (docs/mqtt-flows/GATEWAY_PINGS_FROM_MAIN.md).
    Returns the number of gateways updated, or None when not configured or
    the fetch failed (then ping data stays stale: 15 is not raised).
    """
    target = getattr(settings, "GATEWAY_PINGS_SSH", "")
    if not target:
        return None
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "StrictHostKeyChecking=accept-new"]
    key = getattr(settings, "GATEWAY_PINGS_SSH_KEY", "")
    if key:
        command += ["-i", os.path.expanduser(key), "-o", "IdentitiesOnly=yes"]
    try:
        done = subprocess.run(command + [target], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("Gateway pings from %s failed: %s", target, error)
        return None
    if done.returncode != 0:
        logger.warning("Gateway pings from %s failed (exit %s): %s", target, done.returncode,
                       done.stderr.strip()[-300:])
        return None
    alive = alive_from_lines(done.stdout.splitlines())
    if not alive:
        logger.warning("Gateway pings from %s: no ping lines received", target)
        return None
    return store_pings(alive, now)


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
    mark(PING_READ_MARKER, now)
    return len(changed)


def ping_information_fresh(now):
    read_at = marker(PING_READ_MARKER)
    fresh = timedelta(minutes=getattr(settings, "GATEWAY_HEALTH_PING_FRESH_MINUTES", 15))
    return read_at is not None and now - read_at <= fresh


# ---------------------------------------------------------------- alarms
@dataclass
class Report:
    raised: list = field(default_factory=list)
    repeated: list = field(default_factory=list)
    cleared: list = field(default_factory=list)
    skipped: str = ""

    def __str__(self):
        text = f"raised={len(self.raised)} still_active={len(self.repeated)} cleared={len(self.cleared)}"
        return f"{text} (gateways skipped: {self.skipped})" if self.skipped else text


def _raise(report, site_id, alarm_type, object_type, object_id, detail, details, now, priority, started,
           physical_site_id=None):
    """Raise or keep an outage alarm. ``started`` is when the outage began
    (stored as created_time, so lists show since when it is not solved).
    While it stays open it is e-mailed again once a day
    (GATEWAY_HEALTH_REMINDER_HOURS, 24) until it is solved. ``site_id`` is
    the site it is stored under (alarm_sites); Off on it or on the physical
    site means not raised."""
    if alarm_policy.is_off(site_id, alarm_type) or (
        physical_site_id not in (None, site_id) and alarm_policy.is_off(physical_site_id, alarm_type)
    ):
        return
    issue = dict(site_id_id=site_id, Alarm_type=alarm_type, object_type=object_type, object_id=object_id)
    title = dict(AlarmNotifications.alarm_type)[alarm_type]
    open_alarm = AlarmNotifications.objects.filter(is_active=True, **issue).order_by("-id").first()
    if open_alarm is not None:
        update = dict(last_seen=now, to_do=detail[:200])
        notified = open_alarm.last_notified_at or open_alarm.created_time
        remind = timedelta(hours=getattr(settings, "GATEWAY_HEALTH_REMINDER_HOURS", 24))
        if remind.total_seconds() > 0 and now - notified >= remind:
            days, text = open_for(open_alarm.created_time, now)
            notify(send_alarm_email, f"{title} - still not solved ({text})", site_id, details + [
                ["Open since", f"{open_alarm.created_time:%d %b %H:%M}", False],
                ["Not solved for", text, True],
            ], alarm_type)
            update["last_notified_at"] = now
            logger.warning("Gateway health alarm reminder: site=%s type=%s object=%s open %s",
                           site_id, alarm_type, object_id, text)
        AlarmNotifications.objects.filter(pk=open_alarm.pk).update(**update)
        report.repeated.append((site_id, alarm_type, object_id))
        return
    previous = (
        AlarmNotifications.objects.filter(is_active=False, off_time__isnull=False, **issue)
        .order_by("-off_time")
        .first()
    )
    AlarmNotifications.objects.create(
        user_level=2, Alarm_priority=priority, created_time=started, last_seen=now,
        off_time=now, last_notified_at=now, to_do=detail[:200], **issue,
    )
    details = details + [["Open since", f"{started:%d %b %H:%M} ({open_for(started, now)[1]})", False]]
    if previous is not None:
        previous_start = previous.created_time
        details = details + [[
            "Previous outage",
            f"{previous_start:%d %b %H:%M} - restored {previous.off_time:%d %b %H:%M} "
            f"({_hours(previous.off_time - previous_start)})",
            False,
        ]]
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


def skipped_sites():
    """GATEWAY_HEALTH_SKIP_SITES: site ids whose gateways are not checked, e.g. on
    the test server a site whose data main does not forward (site 35)."""
    return list(getattr(settings, "GATEWAY_HEALTH_SKIP_SITES", []))


def _gateway_plan(statuses, live):
    """``{status.pk: [(target_site_id, object_id), ...]}`` and the sites to clear per status.

    Targets come from alarm_sites (display sites of the aisles the gateway
    feeds). object_id is the gateway number (..._<n>), unless that number is
    already used by another gateway under the same target site.
    """
    targets, candidates, by_target = {}, {}, {}
    for status in statuses:
        hgw = status.home_gateway
        aisles = alarm_sites.gateway_aisles(hgw)
        targets[status.pk] = alarm_sites.site_targets(hgw.connected_to_id, aisles, live)
        candidates[status.pk] = alarm_sites.candidate_sites(hgw.connected_to_id, aisles)
        for target in targets[status.pk]:
            by_target.setdefault(target, []).append(hgw)
    plan = {}
    for status in statuses:
        hgw = status.home_gateway
        number = gateway_number(hgw.hgw_id)
        plan[status.pk] = []
        for target in targets[status.pk]:
            same = [other for other in by_target[target] if gateway_number(other.hgw_id) == number]
            object_id = number
            if len(same) > 1 and hgw.connected_to_id != target:
                object_id = GATEWAY_PK_OFFSET + hgw.pk
                logger.warning("Gateway number %s used twice under site %s: %s stored as object %s",
                               number, target, hgw.hgw_id, object_id)
            plan[status.pk].append((target, object_id))
    return plan, candidates


def _reconnecting(site_id, number, now):
    """An open Gateway Disconnected whose last no-ping check is recent: the
    gateway has just reconnected and its data is on the way."""
    grace = timedelta(minutes=getattr(settings, "GATEWAY_HEALTH_RECONNECT_MINUTES", 10))
    open_alarm = (
        AlarmNotifications.objects.filter(
            site_id_id=site_id, Alarm_type=AlarmNotifications.GATEWAY_DISCONNECTED,
            object_type=GATEWAY_OBJECT, object_id=number, is_active=True,
        )
        .values_list("last_seen", flat=True)
        .first()
    )
    return open_alarm is not None and now - open_alarm < grace


def _gateway_details(hgw, target, aisles_text):
    if hgw.connected_to_id == target:
        return []
    site = hgw.connected_to
    return [["Gateway's site", f"{getattr(site, 'site_name', '')} ({hgw.connected_to_id})", False],
            ["Aisles", aisles_text, False]]


def evaluate_gateways(report, now):
    # No gateway at all has sent data lately: our side (listeners, broker,
    # network) is down, not the gateways. Judge nothing until data flows again.
    newest = HomeGatewayStatus.objects.aggregate(newest=Max("last_data_at"))["newest"]
    silent_limit = timedelta(minutes=getattr(settings, "GATEWAY_HEALTH_ALL_SILENT_MINUTES", 15))
    if newest is None or now - newest > silent_limit:
        report.skipped = "no gateway data at all since " + (f"{newest:%d %b %H:%M}" if newest else "ever")
        logger.warning("Gateway health check skipped: %s", report.skipped)
        return
    # Silence counts from our own (re)start at the earliest: a gateway is not
    # disconnected because our server or listener was down.
    listening_since = marker(LISTENER_STARTED_MARKER)
    with_pings = ping_information_fresh(now)
    live = alarm_sites.live_site_ids()
    # Live sites, and sites merged into a live site (alarm_sites).
    statuses = list(
        HomeGatewayStatus.objects.select_related("home_gateway", "home_gateway__connected_to").filter(
            home_gateway__connected_to_id__in=alarm_sites.monitored_site_ids(live), last_data_at__isnull=False,
        ).exclude(home_gateway__connected_to_id__in=skipped_sites())
    )
    plan, candidates = _gateway_plan(statuses, live)
    for status in statuses:
        hgw = status.home_gateway
        site_id = hgw.connected_to_id
        targets = plan[status.pk]
        # Alarms of this gateway stored under a site it no longer belongs to.
        stale = candidates[status.pk] - {target for target, _ in targets}
        for old_site in stale:
            for alarm_type in (AlarmNotifications.GATEWAY_DISCONNECTED, AlarmNotifications.GATEWAY_SERVICE_ISSUE):
                _clear(report, old_site, alarm_type, GATEWAY_OBJECT, gateway_number(hgw.hgw_id), now)
        # real_age: since the gateway's last data. data_age: the same, but not
        # before our own restart (grace). Raising uses data_age; clearing needs
        # real data again, so a restart never closes a real outage.
        real_age = now - status.last_data_at
        silent_since = status.last_data_at
        if listening_since and listening_since > silent_since:
            silent_since = listening_since
        data_age = now - silent_since
        ping_age = (now - status.last_ping_at) if (with_pings and status.last_ping_at) else None
        disconnected_after = _down_after(site_id, AlarmNotifications.GATEWAY_DISCONNECTED)
        service_after = _down_after(site_id, AlarmNotifications.GATEWAY_SERVICE_ISSUE)
        common = [["Gateway", hgw.hgw_id, False], ["Last data", f"{status.last_data_at:%d %b %H:%M}", True]]
        if data_age < disconnected_after and real_age >= disconnected_after:
            # In the grace after our restart while the gateway is still silent:
            # keep any open alarm as it is, raise nothing new.
            continue
        aisles_text = ", ".join(sorted(a.aisleGroupName for a in alarm_sites.gateway_aisles(hgw))) or "-"
        # 15 needs proof the gateway also stopped pinging (broker log read).
        # Pings but no data, or no ping information at all (the test server:
        # gateways ping main only), is a Service / Modbus issue (16), never 15
        # (decided 2026-11-02).
        no_pings = with_pings and (ping_age is None or ping_age >= disconnected_after)
        for target, number in targets:
            extra_site = _gateway_details(hgw, target, aisles_text)
            if data_age >= disconnected_after and no_pings:
                last_ping = f"{status.last_ping_at:%d %b %H:%M}" if status.last_ping_at else "unknown"
                _raise(
                    report, target, AlarmNotifications.GATEWAY_DISCONNECTED, GATEWAY_OBJECT, number,
                    f"Gateway {hgw.hgw_id}: no data and no ping for {_hours(real_age)}",
                    common + [["Last ping", last_ping, False]] + extra_site,
                    now, AlarmNotifications.PRIORITY_HIGH, status.last_data_at, physical_site_id=site_id,
                )
                _clear(report, target, AlarmNotifications.GATEWAY_SERVICE_ISSUE, GATEWAY_OBJECT, number, now)
            elif data_age >= service_after and not no_pings:
                if _reconnecting(target, number, now):
                    # Pings are back after a disconnection: keep 15 open and
                    # wait for the data that follows (no 16, no e-mail).
                    report.repeated.append((target, AlarmNotifications.GATEWAY_DISCONNECTED, number))
                    logger.info("Gateway reconnected, waiting for its data: site=%s gateway=%s", target, hgw.hgw_id)
                    continue
                if ping_age is not None:
                    detail = f"Gateway {hgw.hgw_id}: pings OK, no consumption / recovery / load data for {_hours(real_age)}"
                    extra = [["Last ping", f"{status.last_ping_at:%d %b %H:%M}", False]]
                else:
                    detail = f"Gateway {hgw.hgw_id}: no consumption / recovery / load data for {_hours(real_age)} (ping status unknown)"
                    extra = [["Last ping", "not available on this server (broker log not read)", False]]
                _raise(
                    report, target, AlarmNotifications.GATEWAY_SERVICE_ISSUE, GATEWAY_OBJECT, number,
                    detail, common + extra + extra_site, now, AlarmNotifications.PRIORITY_HIGH, status.last_data_at,
                    physical_site_id=site_id,
                )
                _clear(report, target, AlarmNotifications.GATEWAY_DISCONNECTED, GATEWAY_OBJECT, number, now)
            else:
                for alarm_type in (AlarmNotifications.GATEWAY_DISCONNECTED, AlarmNotifications.GATEWAY_SERVICE_ISSUE):
                    _clear(report, target, alarm_type, GATEWAY_OBJECT, number, now)
        online = data_age < disconnected_after
        if status.status != online:
            HomeGatewayStatus.objects.filter(pk=status.pk).update(status=online)


def evaluate_meters(report, now):
    latest = (
        MeterDisconnectionEvent.objects.values("meter_id")
        .annotate(last_end=Max("detection_window_end"))
    )
    live = alarm_sites.live_site_ids()
    monitored = alarm_sites.monitored_site_ids(live)
    for row in latest:
        event = (
            MeterDisconnectionEvent.objects.filter(meter_id=row["meter_id"], detection_window_end=row["last_end"])
            .order_by("-id")
            .first()
        )
        site_id = event.logged_site_id or event.remote_site_id
        if site_id not in monitored:
            continue
        meter = event.meter_number if event.meter_number is not None else event.meter_id
        # Under the live display site(s) of the site's aisles (alarm_sites).
        aisles = list(AisleGroup.objects.filter(site_id=site_id, is_active=True))
        targets = alarm_sites.site_targets(site_id, aisles, live)
        for old_site in alarm_sites.candidate_sites(site_id, aisles) - set(targets):
            _clear(report, old_site, AlarmNotifications.METER_DISCONNECTED, METER_OBJECT, meter, now)
        for target in targets:
            _evaluate_meter(report, now, event, site_id, target, meter)


def _evaluate_meter(report, now, event, site_id, target, meter):
    """Raise or clear Meter Disconnected for one meter under one target site."""
    if event.status == "disconnected":
        if now - event.detection_window_start >= _down_after(site_id, AlarmNotifications.METER_DISCONNECTED):
            _raise(
                report, target, AlarmNotifications.METER_DISCONNECTED, METER_OBJECT, meter,
                f"Meter {event.meter_name} (port {event.port_id or '-'}) disconnected since "
                f"{event.detection_window_start:%d %b %H:%M}",
                [
                    ["Meter", f"{event.meter_name} (number {meter})", False],
                    ["Port", event.port_id or "-", False],
                    ["Disconnected since", f"{event.detection_window_start:%d %b %H:%M}", True],
                ],
                # High since 2026-11-06, like the gateway alarms 15 / 16.
                now, AlarmNotifications.PRIORITY_HIGH, event.detection_window_start, physical_site_id=site_id,
            )
    else:
        _clear(report, target, AlarmNotifications.METER_DISCONNECTED, METER_OBJECT, meter, now)


def evaluate(now=None):
    """Raise, keep or clear alarms 14 / 15 / 16; returns a Report."""
    now = now or datetime.now()
    report = Report()
    evaluate_gateways(report, now)
    evaluate_meters(report, now)
    return report
