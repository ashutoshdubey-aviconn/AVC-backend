"""Automatic baseline setup (wareApp/baseline_setup.py, POST /api/baselineSetup/)."""

from datetime import date, datetime, time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from wareApp import baseline_setup
from wareApp.models import AisleGroup, DailySiteReading, HourlySiteReading, Site, SiteBaseline, User

TODAY = date(2026, 11, 5)
SAMPLE = (date(2026, 10, 29), date(2026, 10, 31))


class SetupData(TestCase):
    """Site with two aisles, sample days 29-31 Oct and readings without a baseline since."""

    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Yusen test", site_type=2, is_live=False)
        self.fans = self.aisle("MTS-FANS(G+3)", active=False)
        self.el = self.aisle("MTS-EL", active=False)
        # Sample days: fans 150 / 152 / 153.28 kWh; EL misses 30 Oct and is 0 on 31 Oct.
        for day, kwh in zip(self.days(*SAMPLE), (150.0, 152.0, 153.28)):
            self.daily(self.fans, day, kwh)
            self.hours(self.fans, day, kwh / 24)
        self.daily(self.el, date(2026, 10, 29), 45.0)
        self.daily(self.el, date(2026, 10, 31), 0.0)
        # After the baseline date: readings stored without a baseline (as on main).
        for day in self.days(date(2026, 11, 1), TODAY):
            for aisle in (self.fans, self.el):
                self.daily(aisle, day, 30.0)
                self.hours(aisle, day, 1.25)

    # helpers
    def aisle(self, name, active):
        aisle = AisleGroup.objects.create(site=self.site, aisleGroupName=name, is_active=active)
        aisle.refresh_from_db()
        return aisle

    @staticmethod
    def days(first, last):
        return [first + timedelta(days=n) for n in range((last - first).days + 1)]

    def daily(self, aisle, day, kwh):
        DailySiteReading.objects.create(
            associated_Site=self.site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
            unit_consumption=kwh, reading_for=day, daily_baseline_value=0, energy_saved=0, is_visible=True,
        )

    def hours(self, aisle, day, kwh):
        for hour in range(24):
            at = datetime.combine(day, time(hour))
            HourlySiteReading.objects.create(
                associated_Site=self.site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
                unit_consumption=kwh, reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59),
                hourly_baseline_value=0, energy_saved=0, is_visible=True,
            )

    def plan(self, **kw):
        kw.setdefault("today", TODAY)
        return baseline_setup.plan(self.site, "2026/10/29", "2026/10/31", **kw)

    def leg(self, aisle):
        return str(aisle.attached_leg_id)


class BaselineSetupTests(SetupData):
    def test_preview_averages_sample_days_and_changes_nothing(self):
        the_plan = self.plan()
        fans, el = {a.aisle.aisleGroupName: a for a in the_plan.aisles}.values()
        self.assertEqual(the_plan.effective_from, date(2026, 11, 1))  # day after the samples
        self.assertAlmostEqual(fans.average, (150.0 + 152.0 + 153.28) / 3)
        self.assertEqual(fans.warnings, [])
        self.assertEqual(el.average, 45.0)  # only 29 Oct is usable
        self.assertIn("30 Oct: no data (left out)", el.warnings)
        self.assertIn("31 Oct: 0 kWh (left out)", el.warnings)
        self.assertIn("29 Oct: only 0 of 24 hours stored", el.warnings)
        self.assertEqual(the_plan.errors, [])
        self.assertFalse(SiteBaseline.objects.exists())
        self.assertFalse(AisleGroup.objects.filter(is_active=True).exists())

    def test_apply_does_every_step_and_backfills_from_the_baseline_date(self):
        SiteBaseline.objects.create(  # an old open baseline of the fans aisle
            associated_site_id=self.site, aisle_group=self.fans, leg_id=self.leg(self.fans),
            baseline_value=500.0, baseline_from=date(2026, 9, 1),
        )
        with mock.patch.object(baseline_setup, "_schedule_refresh") as refresh, \
                self.captureOnCommitCallbacks(execute=True):
            result = baseline_setup.apply(
                self.site, self.plan(overrides={self.leg(self.el): 44.97}),
                {"name": "Site Manager", "contact": "+91 90000 00000", "email": "manager@example.com"},
            )
        refresh.assert_called_once()
        value = (150.0 + 152.0 + 153.28) / 3
        old, new = SiteBaseline.objects.filter(leg_id=self.leg(self.fans)).order_by("baseline_from")
        self.assertEqual((old.baseline_to, new.baseline_from, new.baseline_to), (date(2026, 10, 31), date(2026, 11, 1), None))
        self.assertAlmostEqual(new.baseline_value, value)
        self.assertEqual(SiteBaseline.objects.get(leg_id=self.leg(self.el)).baseline_value, 44.97)
        self.assertEqual(AisleGroup.objects.filter(site=self.site, is_active=True).count(), 2)
        self.site.refresh_from_db()
        self.assertTrue(self.site.is_live)
        self.assertIsNotNone(self.site.live_date)
        self.assertEqual(self.site.baseline_date, datetime(2026, 11, 1))
        self.assertEqual(self.site.site_manager_email, "manager@example.com")
        # Daily rows from 1 Nov: baseline and saving; before 1 Nov untouched.
        day = DailySiteReading.objects.get(leg_id=self.leg(self.fans), reading_for=date(2026, 11, 3))
        self.assertAlmostEqual(day.daily_baseline_value, value)
        self.assertAlmostEqual(day.energy_saved, value - 30.0)
        before = DailySiteReading.objects.get(leg_id=self.leg(self.fans), reading_for=date(2026, 10, 31))
        self.assertEqual((before.daily_baseline_value, before.energy_saved), (0, 0))
        # Hourly rows from 1 Nov: daily / 24 (no NL hours on this site; EL is 24 h anyway).
        hour = HourlySiteReading.objects.get(leg_id=self.leg(self.el), reading_from=datetime(2026, 11, 2, 9))
        self.assertAlmostEqual(hour.hourly_baseline_value, 44.97 / 24)
        self.assertAlmostEqual(hour.energy_saved, 44.97 / 24 - 1.25)
        self.assertEqual(result["backfill"]["daily"], 2 * 5)

    def test_nl_hours_spread_the_daily_baseline(self):
        Site.objects.filter(pk=self.site.pk).update(nl_operation_hours=12)
        self.site.refresh_from_db()
        with mock.patch.object(baseline_setup, "_schedule_refresh"):
            baseline_setup.apply(self.site, self.plan(overrides={self.leg(self.el): 44.97}))
        fans_hour = HourlySiteReading.objects.get(leg_id=self.leg(self.fans), reading_from=datetime(2026, 11, 2, 9))
        el_hour = HourlySiteReading.objects.get(leg_id=self.leg(self.el), reading_from=datetime(2026, 11, 2, 9))
        self.assertAlmostEqual(fans_hour.hourly_baseline_value, (150.0 + 152.0 + 153.28) / 3 / 12)  # NL aisle
        self.assertAlmostEqual(el_hour.hourly_baseline_value, 44.97 / 24)  # EL aisle: always 24 h

    def test_same_date_again_updates_the_baseline(self):
        with mock.patch.object(baseline_setup, "_schedule_refresh"):
            baseline_setup.apply(self.site, self.plan())
            baseline_setup.apply(self.site, self.plan(overrides={self.leg(self.el): 50.0}))
        self.assertEqual(SiteBaseline.objects.filter(leg_id=self.leg(self.el)).count(), 1)
        self.assertEqual(SiteBaseline.objects.get(leg_id=self.leg(self.el)).baseline_value, 50.0)
        day = DailySiteReading.objects.get(leg_id=self.leg(self.el), reading_for=date(2026, 11, 2))
        self.assertEqual((day.daily_baseline_value, day.energy_saved), (50.0, 20.0))

    def test_refused_cases(self):
        SiteBaseline.objects.create(
            associated_site_id=self.site, aisle_group=self.el, leg_id=self.leg(self.el),
            baseline_value=40.0, baseline_from=date(2026, 11, 3),
        )
        the_plan = self.plan()
        self.assertTrue(any("a later baseline starts 2026/11/03" in e for e in the_plan.errors))
        with self.assertRaises(baseline_setup.BaselineSetupError):
            baseline_setup.apply(self.site, the_plan)
        with self.assertRaises(baseline_setup.BaselineSetupError):
            baseline_setup.plan(self.site, "2026/10/31", "2026/10/29", today=TODAY)  # reversed
        with self.assertRaises(baseline_setup.BaselineSetupError):
            baseline_setup.plan(self.site, "2026/11/04", "2026/11/05", today=TODAY)  # today not complete
        with self.assertRaises(baseline_setup.BaselineSetupError):
            self.plan(legs=["999999"])

    def test_aisle_without_sample_data_needs_an_override(self):
        empty = self.aisle("MTS-NEW", active=False)
        the_plan = self.plan()
        self.assertTrue(any(e.startswith("MTS-NEW") for e in the_plan.errors))
        self.assertEqual(self.plan(overrides={self.leg(empty): 10.0}).errors, [])

    def test_refresh_task_runs_the_backfill_again(self):
        from wareApp.tasks import refresh_baseline_backfill
        with mock.patch.object(baseline_setup, "_schedule_refresh"):
            baseline_setup.apply(self.site, self.plan())
        HourlySiteReading.objects.filter(reading_from=datetime(2026, 11, 4, 10)).update(hourly_baseline_value=0)
        with mock.patch("wareApp.tasks.close_old_connections"):  # keep the test's connection
            out = refresh_baseline_backfill(self.site.id, "2026-11-01")
        self.assertIn("'hourly': 2", out)


class BaselineSetupApiTests(SetupData):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create(username="admin", UserType=1))
        self.body = {"site_id": self.site.id, "sample_from": "2026/10/29", "sample_to": "2026/10/31",
                     "overrides": {self.leg(self.el): 44.97}}

    def test_preview_then_apply(self):
        preview = self.client.post("/api/baselineSetup/", self.body, format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["applied"])
        self.assertEqual(preview.data["plan"]["effective_from"], "2026/11/01")
        self.assertFalse(SiteBaseline.objects.exists())
        with mock.patch.object(baseline_setup, "_schedule_refresh"):
            applied = self.client.post("/api/baselineSetup/", {**self.body, "apply": True}, format="json")
        self.assertEqual(applied.status_code, 200)
        self.assertTrue(applied.data["applied"])
        self.assertEqual(SiteBaseline.objects.count(), 2)

    def test_only_super_admin_and_bad_input(self):
        other = APIClient()
        other.force_authenticate(User.objects.create(username="customer", UserType=4))
        self.assertEqual(other.post("/api/baselineSetup/", self.body, format="json").status_code, 403)
        bad = self.client.post("/api/baselineSetup/", {**self.body, "sample_to": "31-10-2026"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("sample_to", bad.data["error"])


class SaveBaselineFirstTimeTests(TestCase):
    def test_first_baseline_of_an_aisle_no_longer_crashes(self):
        site = Site.objects.create(site_name="First baseline", site_type=2)
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="RPC-F1")
        aisle.refresh_from_db()
        DailySiteReading.objects.create(
            associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
            unit_consumption=10.0, reading_for=date(2026, 11, 1),
        )
        client = APIClient()
        client.force_authenticate(User.objects.create(username="admin2", UserType=1))
        response = client.post("/api/saveBaseline/", {
            "siteId": site.id, "legId": "RPC-F1", "baselineValue": 25.0, "date": "2026/11/01",
        }, format="json")
        self.assertEqual(response.data["result"], 1)
        row = SiteBaseline.objects.get()
        self.assertEqual((row.leg_id, row.baseline_value), (str(aisle.attached_leg_id), 25.0))
        self.assertEqual(DailySiteReading.objects.get().daily_baseline_value, 25.0)
