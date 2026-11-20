"""Catch-up spread (wareApp/catch_up_spread.py, POST /api/catchUpSpread/).

The site 114 case of 16 Nov: normal hours on 14 Nov until 19:00, nothing on
15 Nov, then 09:00 on 16 Nov carries the whole gap (43.60 kWh). Rules of
2026-11-20: ERROR404 hours count as gap, offered only when synced and the next
hour is in, manual spread required when the spread days do not match the daily
average, spread hours become real readings, undo for 5 days, automatic spread
at night for clear cases.
"""

from datetime import date, datetime, time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from wareApp import catch_up_spread
from wareApp.models import (
    AisleGroup, AisleSyncRecoveryStatus, AlarmNotifications, CatchUpSpread, DailySiteReading, HourlySiteReading,
    RecoveryMonitor, Site, SiteBaseline, User,
)
from wareApp.mqtt.services.consumption_alarms import find_spikes

D14, D15, D16 = date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16)
CATCH_UP = datetime(2026, 11, 16, 9)
GAP_FROM = datetime(2026, 11, 14, 20)
SHARE = 43.60 / 38
NIGHT = datetime(2026, 11, 16, 22, 0)  # Monday 22:00, in the automatic window


class SpreadTestData(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Myntra BGLR Inventory", site_type=2, is_live=True)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="F1-Outward&Hub area", is_active=True)
        self.aisle.refresh_from_db()
        self.leg = self.aisle.attached_leg_id
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=self.leg, baseline_value=36.72,
            working_hours=24, baseline_from=date(2025, 7, 5),
        )
        self.hours(D14, range(0, 20), 1.2)
        self.hours(D16, [9], 43.60)
        self.hours(D16, range(10, 19), 1.2)
        # The aisle's normal days before the gap (daily average 27.5 kWh; a spread day is 24 x 1.147 = 27.5).
        for n in range(1, 8):
            self.daily_row(D14 - timedelta(days=n), 27.5)
        for day, kwh in ((D14, 24.0), (D16, 43.60 + 9 * 1.2)):
            self.daily_row(day, kwh)
        self.spike = AlarmNotifications.objects.create(
            site_id=self.site, aisle_group=self.aisle, Alarm_type=17, created_time=datetime.combine(D16, time.min),
            to_do="Spike: 09:00 43.60 kWh (catch-up)",
        )

    def hours(self, day, hours, kwh):
        for hour in hours:
            at = datetime.combine(day, time(hour))
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=self.leg,
                unit_consumption=kwh, reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59),
                is_visible=True,
            )

    def gap_hours(self):
        hours, step = [], GAP_FROM
        while step < CATCH_UP:
            hours.append(step)
            step += timedelta(hours=1)
        return hours

    def daily_row(self, day, kwh):
        DailySiteReading.objects.create(
            associated_Site=self.site, aisle_group=self.aisle, leg_id=self.leg,
            reading_for=day, unit_consumption=kwh, is_visible=True,
        )

    def daily(self, day):
        return DailySiteReading.objects.get(leg_id=self.leg, reading_for=day).unit_consumption

    def kwh_at(self, at):
        return HourlySiteReading.objects.get(leg_id=self.leg, reading_from=at).unit_consumption


class CatchUpSpreadTests(SpreadTestData):
    def test_preview_finds_the_catch_up_and_changes_nothing(self):
        items = catch_up_spread.plan(self.site, "2026/11/16")
        self.assertEqual(len(items), 1)
        preview = items[0][1]
        self.assertEqual((preview["catch_up_at"], preview["gap_from"], preview["gap_to"]),
                         ("2026/11/16 09:00", "2026/11/14 20:00", "2026/11/16 08:00"))
        self.assertEqual((preview["missing_hours"], preview["empty_hours"], preview["no_data_hours"]), (37, 37, 0))
        self.assertAlmostEqual(preview["share_kwh"], round(SHARE, 3))
        days = {d["day"]: d for d in preview["days"]}
        self.assertAlmostEqual(days["2026/11/15"]["after"], round(24 * SHARE, 2))
        self.assertEqual(days["2026/11/15"]["before"], 0)
        self.assertEqual((preview["warnings"], preview["manual_required"]), ([], False))
        self.assertEqual(preview["daily_average_kwh"], 27.5)
        self.assertEqual(HourlySiteReading.objects.count(), 30)  # nothing written

    def test_apply_makes_real_hours_recomputes_days_and_records_every_hour(self):
        items = catch_up_spread.plan(self.site, D16)
        (spread,) = catch_up_spread.apply(self.site, items)
        self.assertFalse(HourlySiteReading.objects.filter(is_estimated=True).exists())  # real readings now
        self.assertEqual(HourlySiteReading.objects.count(), 30 + 37)
        self.assertAlmostEqual(self.kwh_at(CATCH_UP), SHARE)
        self.assertAlmostEqual(self.daily(D14), 20 * 1.2 + 4 * SHARE)
        self.assertAlmostEqual(self.daily(D15), 24 * SHARE)  # created
        self.assertAlmostEqual(self.daily(D16), 10 * SHARE + 9 * 1.2)
        total = sum(HourlySiteReading.objects.values_list("unit_consumption", flat=True))
        self.assertAlmostEqual(total, 20 * 1.2 + 43.60 + 9 * 1.2)  # no energy lost or added
        self.assertAlmostEqual(DailySiteReading.objects.get(reading_for=D15).energy_saved, 36.72 - 24 * SHARE)
        self.spike.refresh_from_db()
        self.assertFalse(self.spike.is_active)
        self.assertIn("Spread (manual): 09:00 43.60 kWh over 38 h", self.spike.to_do)
        self.assertEqual((spread.hours, spread.original_kwh, spread.mode), (38, 43.60, "manual"))
        self.assertEqual(len(spread.hours_detail), 38)
        self.assertEqual(spread.hours_detail[0], {"at": "2026-11-14T20:00:00", "kind": "empty", "before": None,
                                                  "after": round(SHARE, 6)})
        self.assertEqual(spread.hours_detail[-1]["kind"], "catch_up")
        self.assertEqual(spread.hours_detail[-1]["before"], 43.60)
        self.assertEqual(catch_up_spread.plan(self.site, D16), [])  # nothing left to spread

    def test_undo_within_five_days_restores_everything_then_not_any_more(self):
        (spread,) = catch_up_spread.apply(self.site, catch_up_spread.plan(self.site, D16))
        self.assertEqual(catch_up_spread.undo(spread, now=spread.applied_at + timedelta(days=4)), 37)
        self.assertEqual(HourlySiteReading.objects.count(), 30)
        self.assertEqual(self.kwh_at(CATCH_UP), 43.60)
        self.assertAlmostEqual(self.daily(D14), 24.0)
        self.assertEqual(self.daily(D15), 0.0)
        with self.assertRaises(catch_up_spread.SpreadError):
            catch_up_spread.undo(spread)
        (again,) = catch_up_spread.apply(self.site, catch_up_spread.plan(self.site, D16))
        late = again.applied_at + timedelta(days=5, minutes=1)
        self.assertFalse(catch_up_spread.can_undo(again, late))
        with self.assertRaisesMessage(catch_up_spread.SpreadError, "undo was possible for 5 days"):
            catch_up_spread.undo(again, now=late)

    def test_changed_since_preview_is_refused(self):
        items = catch_up_spread.plan(self.site, D16)
        HourlySiteReading.objects.filter(reading_from=CATCH_UP).update(unit_consumption=40.0)
        with self.assertRaises(catch_up_spread.SpreadError):
            catch_up_spread.apply(self.site, items)
        self.assertEqual(HourlySiteReading.objects.count(), 30)

    def test_big_first_hour_without_earlier_readings_is_reported(self):
        HourlySiteReading.objects.filter(reading_from__date=D14).delete()
        not_spreadable = []
        self.assertEqual(catch_up_spread.plan(self.site, D16, not_spreadable=not_spreadable), [])
        self.assertEqual((not_spreadable[0]["at"], not_spreadable[0]["kwh"]), ("2026/11/16 09:00", 43.6))
        self.assertIn("gap's start is unknown", not_spreadable[0]["reason"])

    def test_normal_hour_after_a_gap_and_a_huge_jump(self):
        HourlySiteReading.objects.filter(reading_from=CATCH_UP).update(unit_consumption=1.3)
        self.assertEqual(catch_up_spread.plan(self.site, D16), [])  # genuine: not a catch-up
        HourlySiteReading.objects.filter(reading_from=CATCH_UP).update(unit_consumption=3000.0)
        (_, preview) = catch_up_spread.plan(self.site, D16)[0]
        self.assertTrue(preview["manual_required"])
        self.assertTrue(any("meter jump" in w for w in preview["warnings"]))

    def test_spread_days_not_matching_the_daily_average_need_a_manual_spread(self):
        DailySiteReading.objects.filter(reading_for__lt=D14).update(unit_consumption=80.0)
        (_, preview) = catch_up_spread.plan(self.site, D16)[0]
        self.assertTrue(preview["manual_required"])
        self.assertIn("daily average is 80.0 kWh", preview["warnings"][0])


class NoDataAndReadinessTests(SpreadTestData):
    def zero_gap(self, error_hours=True):
        """The gap's hours stored as 0 by recovery (gateway answered ERROR404)."""
        for at in self.gap_hours():
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=self.leg, unit_consumption=0.0,
                reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59), is_visible=True,
            )
        return RecoveryMonitor.objects.create(
            site=self.site, aisle_group=self.aisle, leg_id=str(self.leg), recovery_type="hourly_consumption",
            status="verified", is_active=False, missing_from=GAP_FROM, missing_to=CATCH_UP, expected_slots=37,
            error_slots=37, catch_up_at=CATCH_UP,
            error_hours=[f"{at:%Y-%m-%dT%H:%M:%S}" for at in self.gap_hours()] if error_hours else [],
        )

    def test_error404_hours_are_the_gap_and_are_filled_then_put_back_to_zero(self):
        self.zero_gap()
        (_, preview) = catch_up_spread.plan(self.site, D16)[0]
        self.assertEqual((preview["empty_hours"], preview["no_data_hours"]), (0, 37))
        (spread,) = catch_up_spread.apply(self.site, catch_up_spread.plan(self.site, D16))
        self.assertAlmostEqual(self.kwh_at(GAP_FROM), SHARE)
        self.assertEqual(HourlySiteReading.objects.count(), 30 + 37)  # updated, none created
        self.assertEqual(spread.hours_detail[0]["kind"], "no_data")
        self.assertEqual(catch_up_spread.undo(spread), 37)
        self.assertEqual(self.kwh_at(GAP_FROM), 0.0)
        self.assertEqual(self.kwh_at(CATCH_UP), 43.60)

    def test_older_requests_without_error_hours_use_the_zero_run_before_the_catch_up(self):
        self.zero_gap(error_hours=False)
        (_, preview) = catch_up_spread.plan(self.site, D16)[0]
        self.assertEqual(preview["no_data_hours"], 37)

    def test_real_zero_hours_are_not_a_gap(self):
        for at in self.gap_hours():  # zeros without any ERROR404 answer: genuine readings
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=self.leg, unit_consumption=0.0,
                reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59), is_visible=True,
            )
        self.assertEqual(catch_up_spread.plan(self.site, D16), [])

    def test_waiting_until_synced_recovered_and_the_next_hour_is_in(self):
        HourlySiteReading.objects.filter(reading_from=CATCH_UP + timedelta(hours=1)).delete()
        waiting = []
        self.assertEqual(catch_up_spread.plan(self.site, D16, waiting=waiting), [])
        self.assertIn("hour after the catch-up", waiting[0]["reason"])
        self.hours(D16, [10], 1.2)
        status = AisleSyncRecoveryStatus.objects.create(site=self.site, home_gateway_id="gw", aisle_group=self.aisle,
                                                        leg_id=str(self.leg), sync_status="missing")
        waiting = []
        self.assertEqual(catch_up_spread.plan(self.site, D16, waiting=waiting), [])
        self.assertIn("not synced yet (missing)", waiting[0]["reason"])
        status.sync_status = "recovered"
        status.save()
        RecoveryMonitor.objects.create(site=self.site, leg_id=str(self.leg), recovery_type="hourly_consumption",
                                       status="requested", missing_from=GAP_FROM)
        waiting = []
        self.assertEqual(catch_up_spread.plan(self.site, D16, waiting=waiting), [])
        self.assertIn("recovery of the gap is still running", waiting[0]["reason"])
        RecoveryMonitor.objects.update(status="failed", is_active=False)
        self.assertEqual(len(catch_up_spread.plan(self.site, D16)), 1)

    def test_recovery_leaves_spread_hours_and_days_alone(self):
        catch_up_spread.apply(self.site, catch_up_spread.plan(self.site, D16))
        hours = catch_up_spread.spread_hours(self.site.id, self.leg, datetime(2026, 11, 14), datetime(2026, 11, 17))
        self.assertEqual((min(hours), max(hours), len(hours)), (GAP_FROM, CATCH_UP, 38))
        self.assertEqual(catch_up_spread.spread_days(self.site.id, self.leg, date(2026, 11, 13), date(2026, 11, 17)),
                         {D14, D15, D16})

    def test_a_big_hour_after_a_gap_is_a_catch_up_not_a_meter_jump(self):
        rows = [(datetime(2026, 11, 16, h), 1.2) for h in range(0, 5)] + [(datetime(2026, 11, 16, 9), 43.6)]
        (spike,) = find_spikes(rows, datetime(2026, 11, 16), daily_baseline=36.72)
        self.assertEqual(spike.kind, "catch_up")
        (spike,) = find_spikes(rows[:5] + [(datetime(2026, 11, 16, 5), 43.6)], datetime(2026, 11, 16), 36.72)
        self.assertEqual(spike.kind, "jump")  # no gap before it


@override_settings(CATCH_UP_AUTO_FROM_HOUR=19, CATCH_UP_AUTO_UNTIL_HOUR=11)
class AutoSpreadTests(SpreadTestData):
    def test_window_is_night_and_all_sunday(self):
        self.assertTrue(catch_up_spread.in_auto_window(datetime(2026, 11, 16, 19, 0)))
        self.assertTrue(catch_up_spread.in_auto_window(datetime(2026, 11, 17, 10, 59)))
        self.assertFalse(catch_up_spread.in_auto_window(datetime(2026, 11, 17, 11, 0)))
        self.assertFalse(catch_up_spread.in_auto_window(datetime(2026, 11, 17, 18, 59)))
        self.assertTrue(catch_up_spread.in_auto_window(datetime(2026, 11, 22, 14, 0)))  # Sunday

    @mock.patch("wareApp.mqtt.services.notifications.notify")
    def test_clear_case_is_spread_automatically(self, notify):
        self.assertIn("outside", catch_up_spread.auto_spread(now=datetime(2026, 11, 16, 14, 0)))
        self.assertFalse(CatchUpSpread.objects.exists())
        summary = catch_up_spread.auto_spread(now=NIGHT)
        self.assertIn("spread=1", summary)
        spread = CatchUpSpread.objects.get()
        self.assertEqual((spread.mode, spread.applied_by), ("automatic", "automatic"))
        self.spike.refresh_from_db()
        self.assertIn("Spread (automatic)", self.spike.to_do)
        notify.assert_not_called()

    @mock.patch("wareApp.mqtt.services.notifications.notify")
    def test_doubtful_case_is_left_and_e_mailed_once(self, notify):
        DailySiteReading.objects.filter(reading_for__lt=D14).update(unit_consumption=80.0)
        self.assertIn("manual_required=1", catch_up_spread.auto_spread(now=NIGHT))
        self.assertFalse(CatchUpSpread.objects.exists())
        self.assertEqual(notify.call_count, 1)
        _, subject, site_id, details = notify.call_args[0]
        self.assertEqual((subject, site_id), ("Catch-up spread: manual spread required", self.site.id))
        self.assertIn("daily average", details[1][1])
        catch_up_spread.auto_spread(now=NIGHT + timedelta(minutes=30))
        self.assertEqual(notify.call_count, 1)  # not e-mailed again


class CatchUpSpreadApiTests(SpreadTestData):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))

    def test_preview_apply_undo_history(self):
        body = {"site_id": self.site.id, "day": "2026/11/16", "legs": [str(self.leg)]}
        preview = self.client.post("/api/catchUpSpread/", body, format="json")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual((preview.data["applied"], len(preview.data["catch_ups"]), preview.data["waiting"]),
                         (False, 1, []))
        applied = self.client.post("/api/catchUpSpread/", {**body, "apply": True}, format="json")
        self.assertTrue(applied.data["applied"])
        spread_id = applied.data["spreads"][0]["id"]
        self.assertEqual(applied.data["spreads"][0]["mode"], "manual")
        self.assertEqual(CatchUpSpread.objects.get(id=spread_id).applied_by, "admin")
        again = self.client.post("/api/catchUpSpread/", body, format="json")
        self.assertEqual(again.data["catch_ups"], [])
        (listed,) = again.data["applied_spreads"]
        self.assertEqual((listed["id"], listed["aisle_name"], listed["hours"], listed["original_kwh"], listed["mode"]),
                         (spread_id, "F1-Outward&Hub area", 38, 43.6, "manual"))
        self.assertTrue(listed["can_undo"])
        self.assertEqual(listed["empty_hours"], 37)
        history = self.client.post("/api/catchUpSpread/", {"site_id": self.site.id, "history": True,
                                                           "from": "2026/11/01", "to": "2026/11/30"}, format="json")
        self.assertEqual(history.data["count"], 1)
        self.assertEqual(len(history.data["spreads"][0]["hours_detail"]), 38)
        undone = self.client.post("/api/catchUpSpread/", {"undo": spread_id}, format="json")
        self.assertEqual(undone.data["hours_reverted"], 37)
        after = self.client.post("/api/catchUpSpread/", body, format="json")
        self.assertEqual((len(after.data["catch_ups"]), after.data["applied_spreads"]), (1, []))

    def test_permissions_and_errors(self):
        other = APIClient()
        other.force_authenticate(User.objects.create(username="customer", UserType=4))
        self.assertEqual(other.post("/api/catchUpSpread/", {"site_id": self.site.id, "day": "2026/11/16"},
                                    format="json").status_code, 403)
        bad = self.client.post("/api/catchUpSpread/", {"site_id": self.site.id, "day": "16-11-2026"}, format="json")
        self.assertEqual(bad.status_code, 400)
        none = self.client.post("/api/catchUpSpread/", {"site_id": self.site.id, "day": "2026/11/14", "apply": True},
                                format="json")
        self.assertEqual(none.data["error"], "no catch-up hour to spread")
        too_long = self.client.post("/api/catchUpSpread/", {"site_id": self.site.id, "history": True,
                                                            "from": "2026/01/01", "to": "2026/11/30"}, format="json")
        self.assertEqual(too_long.status_code, 400)
