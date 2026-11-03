"""10,000 kWh meter-glitch cap: saving (2) and submetering (5) sites only, never
WH-metering (1), on every write path (decided 2026-11-03)."""

from datetime import date, datetime, timedelta

from django.core.cache import cache
from django.test import TestCase

from wareApp.models import (
    AisleGroup,
    DailySiteReading,
    HourlySiteReading,
    Site,
    SiteBaseline,
    cap_reading,
    reading_capped,
)
from wareApp.mqtt import consumption, daily_consumption_recovery, hourly_consumption_recovery

CASES = ((1, False), (2, True), (5, True))  # (site_type, capped)


class ReadingCapTests(TestCase):
    def setUp(self):
        cache.clear()

    def make_site(self, site_type):
        site = Site.objects.create(site_name=f"Cap site {site_type}", site_type=site_type)
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="Main-Supply", is_active=True)
        aisle.refresh_from_db()
        SiteBaseline.objects.create(
            associated_site_id=site, leg_id=aisle.attached_leg_id, baseline_value=48.0,
            working_hours=24, baseline_from=date(2026, 1, 1),
        )
        return site, aisle

    def test_rule(self):
        for site_type, capped in CASES + ((None, False), (3, False)):
            site = Site(site_type=site_type)
            self.assertEqual(reading_capped(site), capped, site_type)
            self.assertEqual(cap_reading(site, 25000.0), 0.0 if capped else 25000.0)
            self.assertEqual(cap_reading(site, 9999.0), 9999.0)

    def test_model_save(self):
        for site_type, capped in CASES:
            with self.subTest(site_type=site_type):
                site, aisle = self.make_site(site_type)
                at = datetime(2026, 11, 3, 10)
                hour = HourlySiteReading.objects.create(
                    associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
                    unit_consumption=25000.0, hourly_baseline_value=2.0, energy_saved=0.0,
                    reading_from=at, reading_to=at + timedelta(minutes=59, seconds=59),
                )
                day = DailySiteReading.objects.create(
                    associated_Site=site, aisle_group=aisle, leg_id=aisle.attached_leg_id,
                    unit_consumption=60000.0, daily_baseline_value=48.0, energy_saved=0.0,
                    reading_for=at.date(),
                )
                hour.refresh_from_db()
                day.refresh_from_db()
                if capped:
                    self.assertEqual((hour.unit_consumption, hour.energy_saved), (0.0, 2.0))
                    self.assertEqual((day.unit_consumption, day.energy_saved), (0.0, 48.0))
                else:
                    self.assertEqual((hour.unit_consumption, day.unit_consumption), (25000.0, 60000.0))

    def test_live_packet_values(self):
        values = {"new_unit_consumption": 25000.0, "current_hour_consumption": 25000.0,
                  "previous_hour_consumption": 9000.0}
        for site_type, capped in CASES:
            capped_values = consumption._cap_warehouse_saving_values(Site(site_type=site_type), dict(values))
            self.assertEqual(capped_values["current_hour_consumption"], 0.0 if capped else 25000.0)
            self.assertEqual(capped_values["previous_hour_consumption"], 9000.0)

    def test_hourly_recovery(self):
        for site_type, capped in CASES:
            with self.subTest(site_type=site_type):
                site, aisle = self.make_site(site_type)
                message = (
                    f"Aisle_group_id : {aisle.attached_leg_id}; Recovery_Hours : 2026-11-02 01:00:00.000,"
                    f"2026-11-02 02:00:00.000,; Unit_consumptions : 30000,12.5,; GW_total_cumulative : 0"
                )
                with self.captureOnCommitCallbacks(execute=True):
                    hourly_consumption_recovery.handle_hourly_consumption_recovery_message(
                        site, site.id, "gw-1", message
                    )
                hours = dict(HourlySiteReading.objects.filter(associated_Site=site)
                             .values_list("reading_from__hour", "unit_consumption"))
                self.assertEqual(hours, {1: 0.0 if capped else 30000.0, 2: 12.5})

    def test_daily_recovery(self):
        for site_type, capped in CASES:
            with self.subTest(site_type=site_type):
                site, aisle = self.make_site(site_type)
                message = (
                    f"Aisle_group_id : {aisle.attached_leg_id}; Recovery_Dates : 2026-11-01,; "
                    f"Unit_consumptions : 45000,; GW_Total_cumulative : 0"
                )
                with self.captureOnCommitCallbacks(execute=True):
                    daily_consumption_recovery.handle_daily_consumption_recovery_message(
                        site, site.id, "gw-1", message
                    )
                day = DailySiteReading.objects.get(associated_Site=site)
                self.assertEqual(day.unit_consumption, 0.0 if capped else 45000.0)
