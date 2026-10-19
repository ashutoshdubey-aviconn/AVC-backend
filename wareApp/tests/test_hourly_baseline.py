from datetime import date, datetime

from django.core.cache import cache
from django.test import TestCase

from wareApp.models import AisleGroup, HourlySiteReading, Site, SiteBaseline
from wareApp.mqtt import hourly_consumption_recovery
from wareApp.mqtt.services.baseline import hourly_baseline, is_emergency_supply


class EmergencySupplyRuleTests(TestCase):
    def test_el_token(self):
        for name in ("RPC-EL", "HB-Part-1_EL", "EL-GF&F1", "UCB-EL", "EL", "F1 EL"):
            self.assertTrue(is_emergency_supply(name), name)
        for name in ("SHELTER", "RPC-el", "ELEVATOR", "HB-Part-1", "", None):
            self.assertFalse(is_emergency_supply(name), name)


class HourlyBaselineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Baseline site", site_type=1)

    def aisle(self, name, active=True):
        aisle = AisleGroup.objects.create(site=self.site, aisleGroupName=name, is_active=active)
        aisle.refresh_from_db()  # post_save sets attached_leg_id
        return aisle

    def baseline(self, aisle, value, hours=12, start=None, end=None):
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=aisle.attached_leg_id,
            baseline_value=value, working_hours=hours, baseline_from=start, baseline_to=end,
        )

    def test_nl_without_site_hours_keeps_legacy_working_hours(self):
        aisle = self.aisle("HB-Part-1")
        self.baseline(aisle, 120.0, hours=12)
        self.assertEqual(hourly_baseline(self.site, aisle, date(2026, 10, 1)), (10.0, 120.0))

    def test_nl_uses_site_operation_hours(self):
        self.site.nl_operation_hours = 8
        aisle = self.aisle("HB-Part-1")
        self.baseline(aisle, 120.0, hours=12)
        self.assertEqual(hourly_baseline(self.site, aisle, date(2026, 10, 1)), (15.0, 120.0))

    def test_el_runs_24_hours(self):
        self.site.nl_operation_hours = 8
        aisle = self.aisle("RPC-EL")
        self.baseline(aisle, 120.0, hours=12)
        self.assertEqual(hourly_baseline(self.site, aisle, date(2026, 10, 1)), (5.0, 120.0))

    def test_dated_row_wins_over_latest(self):
        aisle = self.aisle("HB-Part-1")
        self.baseline(aisle, 120.0, hours=12, start=date(2026, 9, 1), end=date(2026, 9, 30))
        self.baseline(aisle, 240.0, hours=12, start=date(2026, 10, 1), end=date(2026, 12, 31))
        self.assertEqual(hourly_baseline(self.site, aisle, date(2026, 9, 15))[1], 120.0)
        self.assertEqual(hourly_baseline(self.site, aisle, date(2026, 10, 15))[1], 240.0)
        # Outside every range: the latest row.
        self.assertEqual(hourly_baseline(self.site, aisle, date(2027, 1, 5))[1], 240.0)

    def test_missing_baseline(self):
        aisle = self.aisle("HB-Part-1")
        self.assertEqual(hourly_baseline(self.site, aisle, date(2026, 10, 1)), (0.0, 0.0))


class RecoveredHoursGetABaselineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Recovery baseline site", site_type=1)
        self.aisle = AisleGroup.objects.create(
            site=self.site, aisleGroupName="RPC-EL", is_active=True
        )
        self.aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=self.site, leg_id=self.aisle.attached_leg_id,
            baseline_value=48.0, working_hours=12,
        )

    def test_recovered_rows_store_hourly_baseline_and_saving(self):
        leg = self.aisle.attached_leg_id
        message = (
            f"Aisle_group_id : {leg}; Recovery_Hours : 2026-10-01 09:00:00.000000,"
            "2026-10-01 10:00:00.000000,; Unit_consumptions : 0.5,ERROR404,;"
            " GW_total_cumulative : 100"
        )
        hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
            self.site, self.site.id, "gw-1", message
        )

        rows = {
            row.reading_from.hour: row
            for row in HourlySiteReading.objects.filter(associated_Site=self.site)
        }
        self.assertEqual(rows[9].hourly_baseline_value, 2.0)  # EL: 48 / 24
        self.assertEqual(rows[9].energy_saved, 1.5)
        self.assertEqual(rows[10].unit_consumption, 0.0)  # ERROR404 stored as 0
        self.assertEqual(rows[10].hourly_baseline_value, 2.0)
        self.assertEqual(datetime(2026, 10, 1, 9), rows[9].reading_from.replace(tzinfo=None))


class RebuildCommandTests(TestCase):
    def test_dry_run_then_apply(self):
        from io import StringIO

        from django.core.management import call_command

        cache.clear()
        site = Site.objects.create(site_name="Rebuild site", site_type=1)
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="HB-1", is_active=True)
        aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=site, leg_id=aisle.attached_leg_id, baseline_value=24.0, working_hours=12
        )
        row = HourlySiteReading.objects.create(
            associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
            unit_consumption=0.5, hourly_baseline_value=0.0, energy_saved=0.0,
            reading_from=datetime(2026, 10, 1, 9), reading_to=datetime(2026, 10, 1, 9, 59, 59),
        )
        args = ["--from", "2026-10-01", "--to", "2026-10-01", "--site", str(site.id)]

        out = StringIO()
        call_command("rebuild_hourly_baseline", *args, stdout=out)
        self.assertIn("would update", out.getvalue())
        row.refresh_from_db()
        self.assertEqual(row.hourly_baseline_value, 0.0)

        call_command("rebuild_hourly_baseline", *args, "--apply", stdout=StringIO())
        row.refresh_from_db()
        self.assertEqual(row.hourly_baseline_value, 2.0)
        self.assertEqual(row.energy_saved, 1.5)
