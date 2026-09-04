from django.test import TestCase
from unittest.mock import patch
from django.utils import timezone
from datetime import timedelta

from wareApp.models import (
    Site,
    AisleGroup,
    DailySiteReading,
    DgUnitConsumption,
    DGFuelAlertsData,
    NewAlarmsNotifications,
)
from wareApp.dg_fuel.sessions import attempt_fetch_for_unit, reconcile_daily_unit_consumption


class DgSessionIntegrationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            site_name="Test Site",
            partner_dg_fuel_id="12345",
            partner_dg_provider="roadcast",
            dg_fuel_tank_capacity=50,
        )
        self.aisle = AisleGroup.objects.create(
            site=self.site, aisleGroupName="A1", power_source=1
        )

    def make_unit(self, start_offset_min=60, end_offset_min=0, unit_consumption=None):
        now = timezone.now()
        start = now - timedelta(minutes=start_offset_min)
        end = now - timedelta(minutes=end_offset_min)
        return DgUnitConsumption.objects.create(
            site=self.site,
            aisle_group=self.aisle,
            unit_consumption=unit_consumption,
            dg_fuel_consumption=None,
            dg_start_date=start,
            dg_end_date=end,
            is_dg_on=False,
            fetch_fuel_data=True,
        )

    def make_daily_reading(self, aisle=None, unit_consumption=79.69, reading_for=None):
        aisle = aisle or self.aisle
        reading_for = reading_for or timezone.now().date()
        return DailySiteReading.objects.create(
            associated_Site=self.site,
            aisle_group=aisle,
            leg_id=str(aisle.id),
            unit_consumption=unit_consumption,
            daily_baseline_value=0,
            reading_for=reading_for,
            is_visible=True,
        )

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_attempt_fetch_success_roadcast(self, mock_fetch):
        self.make_daily_reading(unit_consumption=79.69)
        mock_fetch.return_value = 12.5
        reconcile_daily_unit_consumption(self.site)
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertTrue(ok)
        self.assertEqual(unit.unit_consumption, 79.69)
        self.assertEqual(unit.dg_fuel_consumption, 12.5)
        self.assertFalse(unit.fetch_fuel_data)

    @patch("wareApp.dg_fuel.sessions.fetch_loconav_fuel")
    def test_attempt_fetch_success_loconav(self, mock_fetch):
        site = Site.objects.create(
            site_name="Loconav Site",
            partner_dg_fuel_id="DG-LOC-01",
            partner_dg_provider="loconav",
            dg_fuel_tank_capacity=50,
        )
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="A1", power_source=1)
        now = timezone.now()
        DailySiteReading.objects.create(
            associated_Site=site,
            aisle_group=aisle,
            leg_id=str(aisle.id),
            unit_consumption=79.69,
            daily_baseline_value=0,
            reading_for=timezone.now().date(),
            is_visible=True,
        )
        mock_fetch.return_value = 7.25

        reconcile_daily_unit_consumption(site)
        unit = DgUnitConsumption.objects.get(site=site, aisle_group=aisle)

        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()

        self.assertTrue(ok)
        self.assertEqual(unit.unit_consumption, 79.69)
        self.assertEqual(unit.dg_fuel_consumption, 7.25)
        self.assertFalse(unit.fetch_fuel_data)
        mock_fetch.assert_called_once()

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_attempt_fetch_sets_flag_on_failure(self, mock_fetch):
        self.make_daily_reading(unit_consumption=79.69)
        mock_fetch.return_value = None
        reconcile_daily_unit_consumption(self.site)
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertFalse(ok)
        self.assertEqual(unit.unit_consumption, 79.69)
        self.assertTrue(unit.fetch_fuel_data)

    def test_attempt_fetch_requires_explicit_provider(self):
        site = Site.objects.create(
            site_name="Invalid Provider Site",
            partner_dg_fuel_id="12345",
            partner_dg_provider=None,
            dg_fuel_tank_capacity=50,
        )
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="A1", power_source=1)
        unit = DgUnitConsumption.objects.create(
            site=site,
            aisle_group=aisle,
            unit_consumption=None,
            dg_fuel_consumption=None,
            dg_start_date=timezone.now() - timedelta(hours=1),
            dg_end_date=timezone.now(),
            is_dg_on=False,
            fetch_fuel_data=True,
        )

        with patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel") as mock_roadcast, patch(
            "wareApp.dg_fuel.sessions.fetch_loconav_fuel"
        ) as mock_loconav:
            ok = attempt_fetch_for_unit(unit)

        unit.refresh_from_db()
        self.assertFalse(ok)
        self.assertTrue(unit.fetch_fuel_data)
        self.assertIsNone(unit.dg_fuel_consumption)
        mock_roadcast.assert_not_called()
        mock_loconav.assert_not_called()

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_suspicious_fuel_triggers_alert(self, mock_fetch):
        # return a value exceeding 120% of tank capacity (50)
        self.make_daily_reading(unit_consumption=79.69)
        mock_fetch.return_value = 100
        reconcile_daily_unit_consumption(self.site)
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertTrue(ok)
        # alert rows created
        alerts = DGFuelAlertsData.objects.filter(
            site=self.site, alert_name="suspicious_fuel"
        )
        self.assertTrue(alerts.exists())
        new_alarms = NewAlarmsNotifications.objects.filter(
            site_id=self.site, alarm_type=6
        )
        self.assertTrue(new_alarms.exists())

    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_report")
    @patch("wareApp.dg_fuel.sessions.fetch_roadcast_fuel")
    def test_roadcast_report_events_are_persisted(self, mock_fetch, mock_report):
        self.make_daily_reading(unit_consumption=79.69)
        mock_fetch.return_value = 12.5
        mock_report.return_value = {
            "refuels": [{"fuel_liters": 29.39, "epoch_ms": 1788064800000}],
            "thefts": [{"fuel_liters": 1.25, "epoch_ms": 1788072000000}],
        }
        reconcile_daily_unit_consumption(self.site)
        unit = DgUnitConsumption.objects.get(site=self.site, aisle_group=self.aisle)
        ok = attempt_fetch_for_unit(unit)
        self.assertTrue(ok)
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=self.site, alert_name="refuel", epoch_time="1788064800000"
            ).exists()
        )
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=self.site, alert_name="theft", epoch_time="1788072000000"
            ).exists()
        )

    @patch("wareApp.dg_fuel.sessions.fetch_loconav_report")
    @patch("wareApp.dg_fuel.sessions.fetch_loconav_fuel")
    def test_loconav_report_events_are_persisted(self, mock_fetch, mock_report):
        site = Site.objects.create(
            site_name="Loconav Report Site",
            partner_dg_fuel_id="DCGenerator-01",
            partner_dg_provider="loconav",
            dg_fuel_tank_capacity=50,
        )
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="A1", power_source=1)
        DailySiteReading.objects.create(
            associated_Site=site,
            aisle_group=aisle,
            leg_id=str(aisle.id),
            unit_consumption=79.69,
            daily_baseline_value=0,
            reading_for=timezone.now().date(),
            is_visible=True,
        )
        mock_fetch.return_value = 12.5
        mock_report.return_value = {
            "alerts": {
                "REFUELING_ALERT": [{"timestamp": 1788115579, "value": 14.4}],
                "POSSIBLE_FUEL_THEFT_ALERT": [{"timestamp": 1788116679, "value": 1.4}],
            }
        }

        reconcile_daily_unit_consumption(site)
        unit = DgUnitConsumption.objects.get(site=site, aisle_group=aisle)
        ok = attempt_fetch_for_unit(unit)

        self.assertTrue(ok)
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=site, alert_name="refuel", epoch_time="1788115579000"
            ).exists()
        )
        self.assertTrue(
            DGFuelAlertsData.objects.filter(
                site=site, alert_name="theft", epoch_time="1788116679000"
            ).exists()
        )
