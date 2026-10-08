from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.load_data import handler, monthly, rollups
from wareApp.load_data.parser import LoadReading, parse_load_data_message
from warehouse.celery import app


class QuerySet(list):
    def select_related(self, *args):
        return self

    def order_by(self, *args):
        return self

    def exists(self):
        return bool(self)

    def values_list(self, *fields):
        return [tuple(getattr(item, field) for field in fields) for item in self]


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

    def test_parser_accepts_current_gateway_keys_in_any_order(self):
        reading = parse_load_data_message(
            "b'epochTime:1790801110167,Datetime:2026-10-01 02:15:10.167000,"
            "Meter_Number:1,LoadValue:42203.784,leg_id:967'"
        )

        self.assertEqual(reading.load_value, 42203.784)
        self.assertEqual(reading.leg_id, "967")
        self.assertEqual(reading.meter_number, "1")
        self.assertEqual(reading.created, datetime(2026, 10, 1, 2, 15, 10, 167000))
        self.assertEqual(reading.epoch_time, "1790801110167")

    def test_handler_processes_load_data_with_dummy_dependencies(self):
        site = SimpleNamespace(site_name="Dummy", is_loadGraph_visible=False)
        aisle_group = SimpleNamespace(id=7, aisleGroupName="Mains-1")

        with (
            patch.object(
                handler.AisleGroup.objects,
                "get",
                return_value=aisle_group,
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

    def test_processing_task_resolves_site_before_handling_load_data(self):
        site = SimpleNamespace(id=156)

        with (
            patch("wareApp.tasks.Site.objects.get", return_value=site) as get_site,
            patch("wareApp.tasks.handle_load_data_message") as handle_message,
        ):
            tasks.process_load_data_message.run(156, "gateway-01", "payload")

        get_site.assert_called_once_with(id=156)
        handle_message.assert_called_once_with(
            None, site, 156, "gateway-01", "payload", ["LoadData"]
        )

    def test_monthly_update_skips_site_load_query_when_bounds_do_not_change(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(aisleGroupName="Mains-Supply")
        reading = LoadReading(
            load_value=50.0,
            leg_id="967",
            meter_number="1",
            created=datetime(2026, 10, 1, 2, 15),
            epoch_time="1790801110167",
        )
        monthly_record = SimpleNamespace(min_load=10.0, max_load=100.0)

        with (
            patch(
                "wareApp.load_data.monthly.MonthlyMinMaxLoadData.objects.filter"
            ) as filter_monthly,
            patch(
                "wareApp.load_data.monthly.SiteLoadPower.objects.filter"
            ) as filter_load,
        ):
            filter_monthly.return_value.first.return_value = monthly_record
            monthly.update_monthly_min_max_load(site, aisle_group, reading)

        filter_monthly.return_value.update.assert_not_called()
        filter_load.assert_not_called()

    def test_monthly_update_uses_calendar_month_bounds(self):
        site = SimpleNamespace(id=156)
        aisle_group = SimpleNamespace(aisleGroupName="Mains-Supply")
        reading = LoadReading(
            load_value=50.0,
            leg_id="967",
            meter_number="1",
            created=datetime(2026, 10, 1, 2, 15),
            epoch_time="1790801110167",
        )

        with (
            patch("wareApp.load_data.monthly.datetime") as current_datetime,
            patch(
                "wareApp.load_data.monthly.MonthlyMinMaxLoadData.objects.filter"
            ) as filter_monthly,
        ):
            current_datetime.now.return_value = datetime(2026, 10, 4, 6, 35)
            filter_monthly.return_value.first.return_value = SimpleNamespace(
                min_load=10.0, max_load=100.0
            )
            monthly.update_monthly_min_max_load(site, aisle_group, reading)

        filter_monthly.assert_called_once_with(
            site=site,
            supply_source="Mains-Supply",
            created__gte=datetime(2026, 10, 1),
            created__lt=datetime(2026, 11, 1),
        )

    def test_rollup_batches_minimum_and_maximum_records(self):
        class FakeModel:
            objects = SimpleNamespace(bulk_create=Mock())

            def __init__(self, **fields):
                self.__dict__.update(fields)

        site = SimpleNamespace(id=1)
        aisle_group = SimpleNamespace(id=7)
        readings = [
            SimpleNamespace(
                load_data=8.5,
                epoch_time="1000",
                created=datetime(2026, 9, 30, 12, 0, 5),
            ),
            SimpleNamespace(
                load_data=12.5,
                epoch_time="1010",
                created=datetime(2026, 9, 30, 12, 0, 55),
            ),
        ]

        rollups._save_extrema(FakeModel, site, aisle_group, readings)

        saved = FakeModel.objects.bulk_create.call_args.args[0]
        self.assertEqual([record.load_data for record in saved], [8.5, 12.5])
        self.assertTrue(all(record.site is site for record in saved))
        self.assertTrue(all(record.aisle_group is aisle_group for record in saved))

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

    def test_rollup_supports_gateway_intervals_from_five_to_three_hundred_seconds(
        self,
    ):
        site = SimpleNamespace(id=1)
        aisle_group = SimpleNamespace(id=7, aisleGroupName="Mains-1")
        bucket_start = datetime(2026, 9, 30, 12, 0)
        observed_at = datetime(2026, 9, 30, 12, 5)

        for interval_seconds in (5, 10, 12, 30, 60, 120, 300):
            with self.subTest(interval_seconds=interval_seconds):
                raw_readings = QuerySet(
                    [
                        SimpleNamespace(
                            aisle_group_id=7,
                            aisle_group=aisle_group,
                            load_data=float(sample_index + 1),
                            epoch_time=str(sample_index),
                            created=bucket_start + timedelta(seconds=offset_seconds),
                        )
                        for sample_index, offset_seconds in enumerate(
                            range(0, 60, interval_seconds)
                        )
                    ]
                )
                saved = []

                with (
                    patch.object(
                        rollups.RawLoadData.objects,
                        "filter",
                        return_value=raw_readings,
                    ),
                    patch.object(
                        rollups.HourlyLoadData.objects,
                        "filter",
                        return_value=QuerySet(),
                    ),
                    patch.object(
                        rollups.DailyLoadData.objects,
                        "filter",
                        return_value=QuerySet(),
                    ),
                    patch(
                        "wareApp.load_data.rollups._save_extrema",
                        side_effect=lambda model, _site, _aisle, readings: saved.append(
                            (
                                model.__name__,
                                [
                                    reading.load_data
                                    for reading in rollups._extrema(readings)
                                ],
                            )
                        ),
                    ),
                ):
                    rollups.roll_up_completed_load_data(site, observed_at)

                expected_values = [1.0, float(len(raw_readings))]
                self.assertEqual(
                    saved,
                    [
                        ("HourlyLoadData", expected_values),
                        ("MainsDgLoadData", expected_values),
                    ],
                )

    def test_rollup_skips_already_materialized_minute_bucket(self):
        site = SimpleNamespace(id=1)
        aisle_group = SimpleNamespace(id=7, aisleGroupName="Mains-1")
        bucket_start = datetime(2026, 9, 30, 12, 0)
        raw_readings = QuerySet(
            [
                SimpleNamespace(
                    aisle_group_id=7,
                    aisle_group=aisle_group,
                    load_data=8.5,
                    epoch_time="1000",
                    created=bucket_start + timedelta(seconds=5),
                )
            ]
        )
        existing_hourly = QuerySet(
            [
                SimpleNamespace(
                    aisle_group_id=7, created=bucket_start + timedelta(seconds=5)
                )
            ]
        )

        with (
            patch.object(
                rollups.RawLoadData.objects, "filter", return_value=raw_readings
            ),
            patch.object(
                rollups.HourlyLoadData.objects,
                "filter",
                side_effect=[existing_hourly, QuerySet()],
            ),
            patch.object(
                rollups.DailyLoadData.objects, "filter", return_value=QuerySet()
            ),
            patch("wareApp.load_data.rollups._save_extrema") as save_extrema,
        ):
            rollups.roll_up_completed_load_data(site, datetime(2026, 9, 30, 12, 5))

        save_extrema.assert_not_called()

    def test_celery_registers_mqtt_client_task(self):
        app.autodiscover_tasks(force=True)

        self.assertIn("wareApp.tasks.mqtt_client2", app.tasks)
