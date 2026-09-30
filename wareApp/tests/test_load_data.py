from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from wareApp.load_data import handler, rollups
from wareApp.load_data.parser import parse_load_data_message
from warehouse.celery import app


class QuerySet(list):
    def select_related(self, *args):
        return self

    def order_by(self, *args):
        return self

    def exists(self):
        return bool(self)


class LoadDataTests(SimpleTestCase):
    message = (
        "b'load_value:12.5,leg_id:7,meter_number:99,"
        "date:2026-09-30 12:34:56.000000,epoch:1696077296'"
    )

    def setUp(self):
        rollups._last_rollup_minute_by_site.clear()

    def test_parser_reads_gateway_payload(self):
        reading = parse_load_data_message(self.message)

        self.assertEqual(reading.load_value, 12.5)
        self.assertEqual(reading.leg_id, "7")
        self.assertEqual(reading.meter_number, "99")
        self.assertEqual(reading.created, datetime(2026, 9, 30, 12, 34, 56))
        self.assertEqual(reading.epoch_time, "1696077296")

    def test_handler_processes_load_data_with_dummy_dependencies(self):
        site = SimpleNamespace(site_name="Dummy", is_loadGraph_visible=False)
        aisle_group = SimpleNamespace(id=7, aisleGroupName="Mains-1")

        with (
            patch.object(
                handler.AisleGroup.objects,
                "filter",
                return_value=[aisle_group],
            ),
            patch("wareApp.load_data.handler.save_raw_load_reading") as save_raw,
            patch("wareApp.load_data.handler.roll_up_load_data_if_due") as roll_up,
        ):
            handler.handle_load_data_message(
                None, site, 1, "gw-1", self.message, ["LoadData"]
            )

        save_raw.assert_called_once()
        roll_up.assert_called_once_with(site, datetime(2026, 9, 30, 12, 34, 56))

    def test_scheduler_skips_repeat_packets_in_the_same_minute(self):
        site = SimpleNamespace(id=1)

        with patch("wareApp.load_data.rollups.roll_up_completed_load_data") as roll_up:
            self.assertTrue(
                rollups.roll_up_load_data_if_due(site, datetime(2026, 9, 30, 12, 34, 1))
            )
            self.assertFalse(
                rollups.roll_up_load_data_if_due(
                    site, datetime(2026, 9, 30, 12, 34, 50)
                )
            )
            self.assertTrue(
                rollups.roll_up_load_data_if_due(site, datetime(2026, 9, 30, 12, 35))
            )

        self.assertEqual(roll_up.call_count, 2)

    def test_handler_skips_malformed_payload(self):
        site = SimpleNamespace(site_name="Dummy", is_loadGraph_visible=False)

        handler.handle_load_data_message(
            None, site, 1, "gw-1", "b'bad-payload'", ["LoadData"]
        )

    def test_rollup_processes_delayed_packet_once(self):
        site = SimpleNamespace(id=1)
        aisle_group = SimpleNamespace(id=7, aisleGroupName="Mains-1")
        raw_readings = QuerySet(
            [
                SimpleNamespace(
                    aisle_group_id=7,
                    aisle_group=aisle_group,
                    load_data=8.5,
                    epoch_time="1000",
                    created=datetime(2026, 9, 30, 12, 0, 5),
                ),
                SimpleNamespace(
                    aisle_group_id=7,
                    aisle_group=aisle_group,
                    load_data=12.5,
                    epoch_time="1010",
                    created=datetime(2026, 9, 30, 12, 0, 55),
                ),
            ]
        )
        saved = []

        with (
            patch.object(
                rollups.RawLoadData.objects, "filter", return_value=raw_readings
            ),
            patch.object(
                rollups.HourlyLoadData.objects, "filter", return_value=QuerySet()
            ),
            patch.object(
                rollups.DailyLoadData.objects, "filter", return_value=QuerySet()
            ),
            patch(
                "wareApp.load_data.rollups._bucket_has_rows", side_effect=[False, True]
            ),
            patch(
                "wareApp.load_data.rollups._save_extrema",
                side_effect=lambda model, _site, _aisle, readings: saved.append(
                    (
                        model.__name__,
                        [reading.load_data for reading in rollups._extrema(readings)],
                    )
                ),
            ),
        ):
            rollups.roll_up_completed_load_data(site, datetime(2026, 9, 30, 12, 5))

        self.assertEqual(
            saved,
            [
                ("HourlyLoadData", [8.5, 12.5]),
                ("MainsDgLoadData", [8.5, 12.5]),
            ],
        )

    def test_celery_registers_mqtt_client_task(self):
        app.autodiscover_tasks(force=True)

        self.assertIn("wareApp.tasks.mqtt_client2", app.tasks)
