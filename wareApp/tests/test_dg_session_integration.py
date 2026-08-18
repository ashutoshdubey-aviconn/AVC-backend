from django.test import TestCase
from unittest.mock import patch
from django.utils import timezone
from datetime import timedelta

from wareApp.models import (
    Site,
    AisleGroup,
    DgUnitConsumption,
    DGFuelAlertsData,
    NewAlarmsNotifications,
)
from wareApp.dg_session import attempt_fetch_for_unit


class DgSessionIntegrationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(
            site_name="Test Site", partner_dg_fuel_id="12345", dg_fuel_tank_capacity=50
        )
        self.aisle = AisleGroup.objects.create(
            site=self.site, aisleGroupName="A1", power_source=1
        )

    def make_unit(self, start_offset_min=60, end_offset_min=0, unit_consumption=10):
        now = timezone.now()
        start = now - timedelta(minutes=start_offset_min)
        end = now - timedelta(minutes=end_offset_min)
        return DgUnitConsumption.objects.create(
            site=self.site,
            aisle_group=self.aisle,
            unit_consumption=unit_consumption,
            dg_start_date=start,
            dg_end_date=end,
            is_dg_on=False,
            fetch_fuel_data=True,
        )

    @patch("wareApp.dg_session.fetch_roadcast_fuel")
    def test_attempt_fetch_success_roadcast(self, mock_fetch):
        mock_fetch.return_value = 12.5
        unit = self.make_unit()
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertTrue(ok)
        self.assertEqual(unit.dg_fuel_consumption, 12.5)
        self.assertFalse(unit.fetch_fuel_data)

    @patch("wareApp.dg_session.fetch_roadcast_fuel")
    def test_attempt_fetch_sets_flag_on_failure(self, mock_fetch):
        mock_fetch.return_value = None
        unit = self.make_unit()
        ok = attempt_fetch_for_unit(unit)
        unit.refresh_from_db()
        self.assertFalse(ok)
        self.assertTrue(unit.fetch_fuel_data)

    @patch("wareApp.dg_session.fetch_roadcast_fuel")
    def test_suspicious_fuel_triggers_alert(self, mock_fetch):
        # return a value exceeding 120% of tank capacity (50)
        mock_fetch.return_value = 100
        unit = self.make_unit()
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
