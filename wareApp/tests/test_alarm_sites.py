"""Merged sites (virtual aisle groups): which site checks and stores an alarm.

The site 183 / 185 case (17 Nov): site 185 "FM FarukhNagar-2" is not live, its
aisles show under the live site 183 "FM MCF-1 Farrukhnagar"; gateway
..._185_2 feeds site 185's aisles and stopped sending on 6 Nov.
"""

from datetime import date, datetime, time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from wareApp import alarm_feed
from wareApp.models import (
    AisleGroup, AisleSyncRecoveryStatus, AlarmNotifications, AlarmSetting, DailySiteReading, HomeGatewayId,
    HomeGatewayStatus, HourlySiteReading, MeterDisconnectionEvent, Site, SiteBaseline,
)
from wareApp.mqtt import consumption
from wareApp.mqtt.services import alarm_sites, consumption_alarms, gateway_health, spike_alarms

NOW = datetime(2026, 11, 17, 10, 0)
DAY = date(2026, 11, 16)
GW_SHOWN = "avc_FMFarukhNagar_GGN_0000183_1"
GW_MERGED = "avc_FMFarukhNagar_GGN_0000185_2"


class MergedSiteData(TestCase):
    def setUp(self):
        cache.clear()
        self.shown = Site.objects.create(site_name="FM MCF-1 Farrukhnagar", site_type=2, is_live=True)
        self.merged = Site.objects.create(site_name="FM FarukhNagar-2", site_type=2, is_live=False)
        self.ucb = self.aisle(self.shown, "UCB-GF")
        self.cs = self.aisle(self.merged, "C&S-GF", virtual=self.shown)
        self.gw_shown = HomeGatewayId.objects.create(hgw_id=GW_SHOWN, connected_to=self.shown)
        self.gw_merged = HomeGatewayId.objects.create(hgw_id=GW_MERGED, connected_to=self.merged)
        for hgw, aisle in ((self.gw_shown, self.ucb), (self.gw_merged, self.cs)):
            AisleSyncRecoveryStatus.objects.create(site=aisle.site, home_gateway_id=hgw.hgw_id, aisle_group=aisle)
        self.ok = HomeGatewayStatus.objects.create(home_gateway=self.gw_shown, last_data_at=NOW - timedelta(minutes=1))
        self.silent = HomeGatewayStatus.objects.create(
            home_gateway=self.gw_merged, last_data_at=datetime(2026, 11, 6, 9, 59),
        )

    def aisle(self, site, name, virtual=None):
        aisle = AisleGroup.objects.create(site=site, aisleGroupName=name, is_active=True, virtual_siteID=virtual)
        aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=site, leg_id=aisle.attached_leg_id, baseline_value=36.72,
            working_hours=24, baseline_from=date(2025, 7, 5),
        )
        return aisle

    def active(self):
        return list(
            AlarmNotifications.objects.filter(is_active=True)
            .order_by("id").values_list("site_id_id", "Alarm_type", "object_id")
        )


class SiteRulesTests(MergedSiteData):
    def test_merged_site_is_monitored_and_aisles_show_under_the_live_site(self):
        self.assertEqual(alarm_sites.monitored_site_ids(), {self.shown.id, self.merged.id})
        self.assertEqual(alarm_sites.display_site_id(self.cs, self.merged.id), self.shown.id)
        self.assertEqual(alarm_sites.display_site_id(self.ucb, self.shown.id), self.shown.id)
        self.assertEqual(alarm_sites.gateway_aisles(self.gw_merged), [self.cs])

    def test_site_neither_live_nor_merged_into_a_live_site_is_not_monitored(self):
        self.shown.is_live = False
        self.shown.save()
        self.assertEqual(alarm_sites.monitored_site_ids(), set())


@mock.patch.object(gateway_health, "notify")
class GatewayTests(MergedSiteData):
    def test_silent_gateway_of_a_merged_site_raises_under_the_live_site(self, notify):
        report = gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [(self.shown.id, 16, 2)])  # number 2, under site 183
        self.assertEqual(len(report.raised), 1)
        self.assertEqual(notify.call_args.args[1], "Gateway Service / Modbus Issue")
        self.assertEqual(notify.call_args.args[2], self.shown.id)
        details = {row[0]: row[1] for row in notify.call_args.args[3]}
        self.assertEqual(details["Gateway"], GW_MERGED)
        self.assertEqual(details["Gateway's site"], f"FM FarukhNagar-2 ({self.merged.id})")
        self.assertEqual(details["Aisles"], "C&S-GF")
        alarm = AlarmNotifications.objects.get(Alarm_type=16)
        self.assertEqual(alarm.created_time, datetime(2026, 11, 6, 9, 59))  # open since the outage began

    def test_data_back_clears_it(self, notify):
        gateway_health.evaluate(NOW)
        self.silent.last_data_at = NOW
        self.silent.save()
        gateway_health.evaluate(NOW + timedelta(minutes=5))
        self.assertEqual(self.active(), [])

    def test_not_live_site_without_a_live_display_site_is_not_checked(self, notify):
        AisleGroup.objects.filter(pk=self.cs.pk).update(virtual_siteID=self.merged)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])
        notify.assert_not_called()

    def test_off_on_the_display_site_is_off(self, notify):
        AlarmSetting.objects.create(site=self.shown, alarm_type=16, mode=AlarmSetting.OFF)
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [])

    def test_same_gateway_number_under_one_site_gets_its_own_id(self, notify):
        HomeGatewayId.objects.filter(pk=self.gw_merged.pk).update(hgw_id="avc_FMFarukhNagar_GGN_0000185_1")
        AisleSyncRecoveryStatus.objects.filter(aisle_group=self.cs).update(home_gateway_id="avc_FMFarukhNagar_GGN_0000185_1")
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [(self.shown.id, 16, gateway_health.GATEWAY_PK_OFFSET + self.gw_merged.pk)])
        rows = alarm_feed.active_alarms([self.shown.id])
        self.assertEqual(rows[0]["home_gateway_id"], "avc_FMFarukhNagar_GGN_0000185_1")

    def test_alarm_feed_names_the_merged_gateway(self, notify):
        gateway_health.evaluate(NOW)
        (row,) = alarm_feed.active_alarms([self.shown.id])
        self.assertEqual((row["site_id"], row["home_gateway_id"]), (self.shown.id, GW_MERGED))

    def test_meter_of_a_merged_site_raises_under_the_live_site(self, notify):
        MeterDisconnectionEvent.objects.create(
            logged_site_id=self.merged.id, meter_id=790, meter_number=79, meter_name="meter790", status="disconnected",
            port_id="ttyUSB0", detection_window_start=NOW - timedelta(hours=2), detection_window_end=NOW - timedelta(hours=2),
        )
        self.silent.last_data_at = NOW
        self.silent.save()
        gateway_health.evaluate(NOW)
        self.assertEqual(self.active(), [(self.shown.id, 14, 79)])


class AisleAlarmTests(MergedSiteData):
    def hours(self, aisle, day, values, first_hour=0):
        for offset, kwh in enumerate(values):
            at = datetime.combine(day, time(first_hour + offset))
            HourlySiteReading.objects.create(
                associated_Site=aisle.site, aisle_group=aisle, leg_id=aisle.attached_leg_id, unit_consumption=kwh,
                reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59), is_visible=True,
            )

    @mock.patch.object(consumption_alarms, "notify")
    def test_bypassed_of_a_merged_aisle_is_stored_under_the_live_site(self, notify):
        self.hours(self.cs, DAY, [2.0] * 24)
        daily = DailySiteReading.objects.create(
            associated_Site=self.merged, aisle_group=self.cs, leg_id=self.cs.attached_leg_id,
            reading_for=DAY, unit_consumption=48.0, is_visible=True,
        )
        self.assertEqual(consumption_alarms.evaluate_daily_alarms(self.merged, self.cs, daily), ["Bypassed"])
        alarm = AlarmNotifications.objects.get(Alarm_type=11)
        self.assertEqual((alarm.site_id_id, alarm.aisle_group_id), (self.shown.id, self.cs.id))
        self.assertEqual(notify.call_args.args[2], self.shown.id)
        details = {row[0]: row[1] for row in notify.call_args.args[3]}
        self.assertEqual(details["Aisle's site"], f"FM FarukhNagar-2 ({self.merged.id})")
        # The day-end check again: still one alarm.
        self.assertEqual(consumption_alarms.evaluate_daily_alarms(self.merged, self.cs, daily), [])
        self.assertEqual(AlarmNotifications.objects.filter(Alarm_type=11).count(), 1)

    @mock.patch.object(consumption, "notify")
    def test_meter_reading_issue_of_a_merged_aisle(self, notify):
        message = (f"ERROR!!! New meter reading for energy of aisle group id {self.cs.attached_leg_id} "
                   "is smaller than previous meter reading")
        consumption._notify_meter_reading_issue(self.merged, self.merged.id, GW_MERGED, message)
        alarm = AlarmNotifications.objects.get(Alarm_type=10)
        self.assertEqual((alarm.site_id_id, alarm.aisle_group_id), (self.shown.id, self.cs.id))
        self.assertTrue(consumption_alarms.meter_issue_on(self.merged, self.cs, alarm.created_time.date()))
        cache.clear()  # past the storage cooldown: a repeat counts on the open alarm
        consumption._notify_meter_reading_issue(self.merged, self.merged.id, GW_MERGED, message)
        alarm.refresh_from_db()
        self.assertEqual((AlarmNotifications.objects.filter(Alarm_type=10).count(), alarm.occurrences), (1, 2))

    @mock.patch.object(spike_alarms, "notify")
    def test_spike_scan_covers_the_merged_site(self, notify):
        self.hours(self.cs, DAY, [1.2] * 20)
        self.hours(self.cs, NOW.date(), [43.6] + [1.2] * 2, first_hour=7)
        self.assertIn("raised=1", spike_alarms.scan(NOW))
        alarm = AlarmNotifications.objects.get(Alarm_type=17)
        self.assertEqual((alarm.site_id_id, alarm.aisle_group_id), (self.shown.id, self.cs.id))
        self.assertEqual(notify.call_args.args[2], self.shown.id)
        self.assertIn("raised=0", spike_alarms.scan(NOW))  # found again by the aisle: not a second alarm
