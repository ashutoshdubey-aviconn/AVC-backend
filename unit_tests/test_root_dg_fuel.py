from datetime import datetime
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

import tasks as root_tasks


class RootDgFuelCompatibilityTests(SimpleTestCase):
    def test_roadcast_helper_uses_optimized_provider(self):
        start = datetime(2026, 10, 8, 10, 0)
        end = datetime(2026, 10, 8, 11, 0)

        with patch("tasks.fetch_roadcast_fuel", return_value=3.5) as fetch:
            result = root_tasks.roadcasteAPIUpdated("road-01", start, end)

        self.assertEqual(result, 3.5)
        fetch.assert_called_once_with("road-01", start, end)

    def test_loconav_helper_uses_optimized_provider(self):
        start = datetime(2026, 10, 8, 10, 0)
        end = datetime(2026, 10, 8, 11, 0)

        with patch("tasks.fetch_loconav_fuel", return_value=4.5) as fetch:
            result = root_tasks.get_loconav_fuel_data("loconav-01", start, end)

        self.assertEqual(result, 4.5)
        fetch.assert_called_once_with("loconav-01", start, end)

    def test_legacy_dg_hook_delegates_to_normalized_session_workflow(self):
        entry_time = datetime(2026, 10, 8, 10, 0)
        site = Mock()
        aisle = Mock(spec=[])
        pending_unit = Mock()
        pending_units = Mock()
        pending_units.filter.return_value = [pending_unit]

        with (
            patch("tasks.Site.objects.get", return_value=site),
            patch("tasks.DgUnitConsumption.objects", pending_units),
            patch("tasks.reconcile_daily_unit_consumption", return_value={"created": 1}) as reconcile,
            patch("tasks.attempt_fetch_for_unit") as fetch,
        ):
            result = root_tasks.DG_fuel_for_Roadcaste(156, aisle, 12.5, entry_time)

        self.assertEqual(result, {"created": 1})
        reconcile.assert_called_once_with(site, reading_date=entry_time.date())
        pending_units.filter.assert_called_once_with(
            site=site,
            aisle_group=aisle,
            created__date=entry_time.date(),
            fetch_fuel_data=True,
        )
        fetch.assert_called_once_with(pending_unit)