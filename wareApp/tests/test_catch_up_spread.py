"""Catch-up spread (wareApp/catch_up_spread.py, POST /api/catchUpSpread/).

The site 114 case of 16 Nov: normal hours on 14 Nov until 19:00, nothing on
15 Nov, then 09:00 on 16 Nov carries the whole gap (43.60 kWh).
"""

from datetime import date, datetime, time, timedelta

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from wareApp import catch_up_spread
from wareApp.models import (
    AisleGroup, AlarmNotifications, CatchUpSpread, DailySiteReading, HourlySiteReading, Site, SiteBaseline, User,
)

D14, D15, D16 = date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16)
CATCH_UP = datetime(2026, 11, 16, 9)


class SpreadTestData(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Myntra BGLR Inventory", site_type=2)
        self.aisle = AisleGroup.objects.create(site=self.site, aisleGroupName="F1-Outward&Hub area", is_active=True)
        self.aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=self.aisle.attached_leg_id, baseline_value=36.72,
            working_hours=24, baseline_from=date(2025, 7, 5),
        )
        self.hours(D14, range(0, 20), 1.2)
        self.hours(D16, [9], 43.60)
        self.hours(D16, range(10, 19), 1.2)
        for day, kwh in ((D14, 24.0), (D16, 43.60 + 9 * 1.2)):
            DailySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=self.aisle.attached_leg_id,
                reading_for=day, unit_consumption=kwh, is_visible=True,
            )
        self.spike = AlarmNotifications.objects.create(
            site_id=self.site, aisle_group=self.aisle, Alarm_type=17, created_time=datetime.combine(D16, time.min),
            to_do="Spike: 09:00 43.60 kWh (meter jump)",
        )

    def hours(self, day, hours, kwh):
        for hour in hours:
            at = datetime.combine(day, time(hour))
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=self.aisle, leg_id=self.aisle.attached_leg_id,
                unit_consumption=kwh, reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59),
                is_visible=True,
            )

    def daily(self, day):
        return DailySiteReading.objects.get(leg_id=self.aisle.attached_leg_id, reading_for=day).unit_consumption


class CatchUpSpreadTests(SpreadTestData):
    def test_preview_finds_the_catch_up_and_changes_nothing(self):
        items = catch_up_spread.plan(self.site, "2026/11/16")
        self.assertEqual(len(items), 1)
        preview = items[0][1]
        self.assertEqual((preview["catch_up_at"], preview["gap_from"], preview["gap_to"]),
                         ("2026/11/16 09:00", "2026/11/14 20:00", "2026/11/16 08:00"))
        self.assertEqual(preview["missing_hours"], 37)
        share = 43.60 / 38
        self.assertAlmostEqual(preview["share_kwh"], round(share, 3))
        days = {d["day"]: d for d in preview["days"]}
        self.assertAlmostEqual(days["2026/11/15"]["after"], round(24 * share, 2))
        self.assertEqual(days["2026/11/15"]["before"], 0)
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(HourlySiteReading.objects.count(), 30)  # nothing written

    def test_apply_spreads_recomputes_days_and_closes_the_spike(self):
        items = catch_up_spread.plan(self.site, D16)
        (spread,) = catch_up_spread.apply(self.site, items)
        share = 43.60 / 38
        estimated = HourlySiteReading.objects.filter(is_estimated=True)
        self.assertEqual(estimated.count(), 38)  # 37 created + the catch-up hour
        self.assertAlmostEqual(HourlySiteReading.objects.get(reading_from=CATCH_UP).unit_consumption, share)
        self.assertAlmostEqual(self.daily(D14), 20 * 1.2 + 4 * share)
        self.assertAlmostEqual(self.daily(D15), 24 * share)  # created
        self.assertAlmostEqual(self.daily(D16), 10 * share + 9 * 1.2)
        total = sum(HourlySiteReading.objects.values_list("unit_consumption", flat=True))
        self.assertAlmostEqual(total, 20 * 1.2 + 43.60 + 9 * 1.2)  # no energy lost or added
        day15 = DailySiteReading.objects.get(reading_for=D15)
        self.assertAlmostEqual(day15.energy_saved, 36.72 - 24 * share)
        self.spike.refresh_from_db()
        self.assertFalse(self.spike.is_active)
        self.assertIn("Spread: 09:00 43.60 kWh over 38 h", self.spike.to_do)
        self.assertEqual((spread.hours, spread.original_kwh), (38, 43.60))
        self.assertEqual(catch_up_spread.plan(self.site, D16), [])  # nothing left to spread

    def test_undo_restores_everything(self):
        (spread,) = catch_up_spread.apply(self.site, catch_up_spread.plan(self.site, D16))
        self.assertEqual(catch_up_spread.undo(spread), 37)
        self.assertFalse(HourlySiteReading.objects.filter(is_estimated=True).exists())
        self.assertEqual(HourlySiteReading.objects.get(reading_from=CATCH_UP).unit_consumption, 43.60)
        self.assertAlmostEqual(self.daily(D14), 24.0)
        self.assertEqual(self.daily(D15), 0.0)
        with self.assertRaises(catch_up_spread.SpreadError):
            catch_up_spread.undo(spread)

    def test_changed_since_preview_is_refused(self):
        items = catch_up_spread.plan(self.site, D16)
        HourlySiteReading.objects.filter(reading_from=CATCH_UP).update(unit_consumption=40.0)
        with self.assertRaises(catch_up_spread.SpreadError):
            catch_up_spread.apply(self.site, items)
        self.assertFalse(HourlySiteReading.objects.filter(is_estimated=True).exists())

    def test_big_first_hour_without_earlier_readings_is_reported(self):
        HourlySiteReading.objects.filter(reading_from__date=D14).delete()  # no reading in the 7 days before
        not_spreadable = []
        self.assertEqual(catch_up_spread.plan(self.site, D16, not_spreadable=not_spreadable), [])
        self.assertEqual(len(not_spreadable), 1)
        self.assertEqual((not_spreadable[0]["at"], not_spreadable[0]["kwh"]), ("2026/11/16 09:00", 43.6))
        self.assertIn("gap's start is unknown", not_spreadable[0]["reason"])

    def test_normal_hour_after_a_gap_and_a_huge_jump(self):
        HourlySiteReading.objects.filter(reading_from=CATCH_UP).update(unit_consumption=1.3)
        self.assertEqual(catch_up_spread.plan(self.site, D16), [])  # normal-sized: not a catch-up
        HourlySiteReading.objects.filter(reading_from=CATCH_UP).update(unit_consumption=3000.0)
        (item, preview) = catch_up_spread.plan(self.site, D16)[0]
        self.assertTrue(any("meter jump" in w for w in preview["warnings"]))


class CatchUpSpreadApiTests(SpreadTestData):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))

    def test_preview_apply_undo(self):
        body = {"site_id": self.site.id, "day": "2026/11/16", "legs": [str(self.aisle.attached_leg_id)]}
        preview = self.client.post("/api/catchUpSpread/", body, format="json")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual((preview.data["applied"], len(preview.data["catch_ups"])), (False, 1))
        applied = self.client.post("/api/catchUpSpread/", {**body, "apply": True}, format="json")
        self.assertTrue(applied.data["applied"])
        spread_id = applied.data["spreads"][0]["id"]
        self.assertEqual(CatchUpSpread.objects.get(id=spread_id).applied_by, "admin")
        # A later preview of the day lists the spread (for an Undo button) and nothing left to spread.
        again = self.client.post("/api/catchUpSpread/", body, format="json")
        self.assertEqual(again.data["catch_ups"], [])
        (listed,) = again.data["applied_spreads"]
        self.assertEqual((listed["id"], listed["aisle_name"], listed["hours"], listed["original_kwh"]),
                         (spread_id, "F1-Outward&Hub area", 38, 43.6))
        self.assertEqual(listed["gap_from"], "2026/11/14 20:00")
        undone = self.client.post("/api/catchUpSpread/", {"undo": spread_id}, format="json")
        self.assertEqual(undone.data["estimated_hours_removed"], 37)
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
