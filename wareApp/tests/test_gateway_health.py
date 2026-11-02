"""Data-missing alarms 14 / 15 / 16 (wareApp/mqtt/services/gateway_health.py)."""

import io
import os
import tempfile
import time
from datetime import datetime, timedelta
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from wareApp.models import (
    AlarmNotifications,
    AlarmSetting,
    HomeGatewayId,
    HomeGatewayStatus,
    MeterDisconnectionEvent,
    Site,
    SiteConsumptionPing,
)
from wareApp.mqtt.services import gateway_activity, gateway_health

NOW = datetime(2026, 10, 28, 12, 0)
GW = "avc_test_site_000501_2"


class BrokerLogTests(TestCase):
    def setUp(self):
        cache.clear()

    def write_log(self, lines):
        handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".log")
        handle.write("\n".join(lines) + "\n")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_pings_connections_and_received_packets_count_as_alive(self):
        path = self.write_log([
            f"1793175000: New client connected from 1.2.3.4:5000 as odroid.{GW} (p2, c1, k60).",
            f"1793175060: Received PINGREQ from odroid.{GW}",
            "1793175070: Sending PUBLISH to odroid.avc_other_000502_1 (d0, q0, r0, m0, '/x', ... (5 bytes))",
            "1793175080: Received PINGREQ from odroid.avc_other_000503_1",
            "not a log line",
        ])
        alive = gateway_health.read_broker_log(path)
        self.assertEqual(alive[GW], datetime.fromtimestamp(1793175060))
        self.assertIn("avc_other_000503_1", alive)
        self.assertNotIn("avc_other_000502_1", alive)  # server -> gateway only

    def test_second_read_continues_after_the_last_line(self):
        path = self.write_log([f"1793175060: Received PINGREQ from odroid.{GW}"])
        gateway_health.read_broker_log(path)
        with open(path, "a") as log:
            log.write(f"1793175999: Received PINGREQ from odroid.{GW}\n")
        self.assertEqual(gateway_health.read_broker_log(path), {GW: datetime.fromtimestamp(1793175999)})
        self.assertEqual(gateway_health.read_broker_log(path), {})


class GatewayActivityTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(site_name="Activity site", site_type=1, is_live=True)
        HomeGatewayId.objects.create(hgw_id=GW, connected_to=self.site)
        gateway_activity._pending.clear()

    def test_data_packets_update_status_and_consumption_ping(self):
        gateway_activity.seen(self.site.id, GW, "consumption", now=NOW)
        gateway_activity.seen(self.site.id, GW, "SupplyTime", now=NOW + timedelta(minutes=5))  # not data
        gateway_activity.seen(self.site.id, "avc_unknown_000999_1", "load", now=NOW)
        self.assertEqual(gateway_activity.flush(), 1)
        status = HomeGatewayStatus.objects.get()
        self.assertEqual((status.last_data_at, status.status), (NOW, True))
        self.assertEqual(SiteConsumptionPing.objects.get().consumption_ping_time, NOW)


@mock.patch.object(gateway_health, "notify")
class GatewayAlarmTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Gateway site", site_type=1, is_live=True)
        hgw = HomeGatewayId.objects.create(hgw_id=GW, connected_to=self.site)
        self.status = HomeGatewayStatus.objects.create(home_gateway=hgw, last_data_at=NOW - timedelta(minutes=10))
        # Another gateway keeps sending: our own side is receiving data.
        other = HomeGatewayId.objects.create(hgw_id="avc_healthy_000502_1", connected_to=self.site)
        self.healthy = HomeGatewayStatus.objects.create(home_gateway=other, last_data_at=NOW - timedelta(minutes=1))

    def set(self, data_minutes_ago, ping_minutes_ago=None):
        self.status.last_data_at = NOW - timedelta(minutes=data_minutes_ago)
        self.status.last_ping_at = (
            NOW - timedelta(minutes=ping_minutes_ago) if ping_minutes_ago is not None else None
        )
        self.status.save()
        if ping_minutes_ago is not None:
            gateway_health.mark(gateway_health.PING_READ_MARKER, NOW)

    def active(self):
        return list(
            AlarmNotifications.objects.filter(is_active=True).values_list("Alarm_type", "object_id")
        )

    def test_silent_gateway_without_ping_information_is_disconnected(self, notify):
        self.set(data_minutes_ago=59)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])
        self.set(data_minutes_ago=61)
        report = gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [(15, 2)])  # object_id = gateway number
        self.assertEqual(len(report.raised), 1)
        self.assertEqual(notify.call_args.args[1], "Gateway Disconnected")
        self.assertEqual(notify.call_args.args[4], 15)
        # No broker log read: it must not claim "no ping" (it may be a service issue).
        self.assertIn("(ping status unknown)", AlarmNotifications.objects.get().to_do)
        self.assertIn("Gateway Service / Modbus Issue", dict((r[0], r[1]) for r in notify.call_args.args[3])["Note"])
        self.status.refresh_from_db()
        self.assertFalse(self.status.status)

    def test_pings_but_no_data_is_a_service_issue_and_switches_to_disconnected(self, notify):
        self.set(data_minutes_ago=90, ping_minutes_ago=2)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [(16, 2)])
        self.set(data_minutes_ago=150, ping_minutes_ago=70)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [(15, 2)])

    def test_one_e_mail_per_outage_then_cleared_and_restored_line_next_time(self, notify):
        self.set(data_minutes_ago=90)
        gateway_health.evaluate(NOW)
        gateway_health.evaluate(NOW + timedelta(minutes=5))
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(AlarmNotifications.objects.get().last_seen, NOW + timedelta(minutes=5))

        self.status.last_data_at = NOW + timedelta(minutes=9)
        self.status.save()
        HomeGatewayStatus.objects.filter(pk=self.healthy.pk).update(last_data_at=NOW + timedelta(minutes=79))
        report = gateway_health.evaluate(NOW + timedelta(minutes=10))
        self.assertEqual(len(report.cleared), 1)
        cleared = AlarmNotifications.objects.get()
        self.assertEqual((cleared.is_active, cleared.off_time), (False, NOW + timedelta(minutes=10)))
        self.assertEqual(notify.call_count, 1)  # no e-mail on clearing

        gateway_health.evaluate(NOW + timedelta(minutes=80))
        self.assertEqual(notify.call_count, 2)
        labels = [row[0] for row in notify.call_args.args[3]]
        self.assertIn("Previous outage", labels)

    def test_no_gateway_data_at_all_skips_the_check(self, notify):
        self.set(data_minutes_ago=300)
        HomeGatewayStatus.objects.filter(pk=self.healthy.pk).update(last_data_at=NOW - timedelta(minutes=40))
        report = gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])
        self.assertIn("no gateway data at all", str(report))
        notify.assert_not_called()

    def test_silence_counts_from_our_listener_restart_at_the_earliest(self, notify):
        self.set(data_minutes_ago=35 * 60)  # our server was down 35 h
        gateway_health.mark(gateway_health.LISTENER_STARTED_MARKER, NOW - timedelta(minutes=5))
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])  # 5 min since we listen again
        HomeGatewayStatus.objects.filter(pk=self.healthy.pk).update(last_data_at=NOW + timedelta(minutes=60))
        gateway_health.evaluate(NOW + timedelta(minutes=61))
        self.assertEqual(self.active(), [(15, 2)])

    def test_our_restart_does_not_clear_a_real_outage(self, notify):
        self.set(data_minutes_ago=180)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [(15, 2)])
        gateway_health.mark(gateway_health.LISTENER_STARTED_MARKER, NOW + timedelta(minutes=1))
        report = gateway_health.evaluate(NOW + timedelta(minutes=5))
        self.assertEqual(self.active(), [(15, 2)])  # still silent: stays open
        self.assertEqual(report.cleared, [])

    def test_off_and_manual_threshold_in_hours(self, notify):
        self.set(data_minutes_ago=90)
        setting = AlarmSetting.objects.create(site=self.site, alarm_type=15, mode=AlarmSetting.MANUAL, threshold=2)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])  # 1.5 h < 2 h
        setting.mode = AlarmSetting.OFF
        setting.save()
        self.set(data_minutes_ago=300)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])

    def test_sites_that_are_not_live_are_skipped(self, notify):
        Site.objects.filter(pk=self.site.pk).update(is_live=False)
        self.set(data_minutes_ago=300)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])


@mock.patch.object(gateway_health, "notify")
class MeterDisconnectedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Meter site", site_type=1, is_live=True)

    def event(self, status, start, end, meter_id=790):
        return MeterDisconnectionEvent.objects.create(
            logged_site_id=self.site.id, meter_id=meter_id, meter_number=79, meter_name="meter790",
            status=status, port_id="ttyUSB0", detection_window_start=start, detection_window_end=end,
        )

    def test_disconnected_for_an_hour_raises_and_connected_clears(self, notify):
        self.event("disconnected", NOW - timedelta(minutes=30), NOW - timedelta(minutes=29))
        gateway_health.evaluate(NOW)
        self.assertFalse(AlarmNotifications.objects.exists())  # < 1 h

        gateway_health.evaluate(NOW + timedelta(minutes=31))
        alarm = AlarmNotifications.objects.get()
        self.assertEqual((alarm.Alarm_type, alarm.object_type, alarm.object_id, alarm.is_active), (14, 4, 79, True))
        self.assertEqual(notify.call_args.args[1], "Meter Disconnected")

        self.event("connected", NOW - timedelta(minutes=30), NOW + timedelta(minutes=40))
        gateway_health.evaluate(NOW + timedelta(minutes=41))
        alarm.refresh_from_db()
        self.assertFalse(alarm.is_active)


class CommandTests(TestCase):
    def test_dry_run_stores_nothing_and_sends_nothing(self):
        cache.clear()
        site = Site.objects.create(site_name="Dry site", site_type=1, is_live=True)
        hgw = HomeGatewayId.objects.create(hgw_id=GW, connected_to=site)
        HomeGatewayStatus.objects.create(home_gateway=hgw, last_data_at=datetime.now() - timedelta(hours=3))
        other = HomeGatewayId.objects.create(hgw_id="avc_healthy_000502_1", connected_to=site)
        HomeGatewayStatus.objects.create(home_gateway=other, last_data_at=datetime.now())
        log = tempfile.NamedTemporaryFile("w", delete=False, suffix=".log")
        log.write(f"{int(time.time())}: Received PINGREQ from odroid.{GW}\n")
        log.close()
        self.addCleanup(os.unlink, log.name)
        out = io.StringIO()
        with mock.patch.object(gateway_health, "notify") as notify:
            call_command("gateway_health", broker_log=log.name, from_start=True, dry_run=True, stdout=out)
        self.assertIn("raised: site=", out.getvalue())
        self.assertIn("would e-mail: Gateway Service / Modbus Issue", out.getvalue())
        self.assertFalse(AlarmNotifications.objects.exists())
        notify.assert_not_called()
        self.assertIsNone(HomeGatewayStatus.objects.get(home_gateway=hgw).last_ping_at)
        self.assertIsNone(gateway_health.marker(gateway_health.PING_READ_MARKER))
