"""Batched consumption (consumption_batch.py) must store exactly what the
one-by-one handler stores.

Every scenario runs the same packets twice, on two identical sites: once
through ``consumption.handle_consumption_message`` (one packet at a time) and
once through ``consumption_batch.process_consumption_batch`` (all at once),
then compares the hourly, daily and sensor rows, sync status, alarms, dead
letters and recovery requests.
"""

import re
from datetime import date, datetime
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from wareApp.models import (
    AisleGroup,
    AisleSyncRecoveryStatus,
    AlarmNotifications,
    DailySiteReading,
    HourlySiteReading,
    MqttDeadLetter,
    SensorAisleUnitConsumption,
    Site,
    SiteBaseline,
)
from wareApp.mqtt import consumers, consumption, consumption_batch
from wareApp.mqtt.consumption_batch import Packet


def packet(day, hour, current_total, previous_total, new_units=1.5, leg="{leg}"):
    return (
        f"Consumption_time:60,Consumption:{new_units},Saving:0,Time:2026-10-{day:02d} {hour},"
        f"Leg_Meter_Reading:{leg}_meter,Current_hour_total_consumption:{current_total},"
        f"Aisle_group:{leg},GW_total_cumulative:0,"
        f"Previous_hour_total_consumption:{previous_total}"
    )


class World:
    """One site with aisles; rows and packets refer to aisles by name."""

    def __init__(self, name, aisles):
        self.site = Site.objects.create(site_name=name, site_type=1)
        self.legs = {}
        self.aisles = {}
        for aisle_name, options in aisles.items():
            aisle = AisleGroup.objects.create(
                site=self.site, aisleGroupName=aisle_name, **options
            )
            aisle.refresh_from_db()  # post_save sets attached_leg_id
            self.aisles[aisle_name] = aisle
            self.legs[aisle_name] = aisle.attached_leg_id
            SiteBaseline.objects.create(
                associated_site_id=self.site,
                leg_id=aisle.attached_leg_id,
                baseline_value=48.0,
                working_hours=24,
            )
        self.published = []

    def publish(self, topic, message):
        self.published.append(
            (topic.replace(f"/{self.site.id}/", "/SITE/"), self._names(message))
        )

    def _names(self, text):
        # Elapsed seconds depend on the wall clock; the leg id on the site.
        text = re.sub(r"Missed_consumption_time_in_secs :[0-9.]+", "Missed :N", text)
        for name, leg in self.legs.items():
            text = text.replace(f"Aisle_grp :{leg},", f"Aisle_grp :<{name}>,")
        return text

    def payload(self, aisle_name, text):
        return text.replace("{leg}", self.legs[aisle_name])

    def hourly(self, aisle_name, day, hour, units):
        HourlySiteReading.objects.create(
            associated_Site=self.site,
            aisle_group=self.aisles[aisle_name],
            leg_id=self.legs[aisle_name],
            unit_consumption=units,
            reading_from=datetime(2026, 10, day, hour),
            reading_to=datetime(2026, 10, day, hour, 59, 59),
            is_visible=True,
        )

    def daily(self, aisle_name, day, units):
        DailySiteReading.objects.create(
            associated_Site=self.site,
            aisle_group=self.aisles[aisle_name],
            leg_id=self.legs[aisle_name],
            unit_consumption=units,
            reading_for=date(2026, 10, day),
            is_visible=True,
        )

    def snapshot(self):
        names = {leg: name for name, leg in self.legs.items()}

        def rows(model, *fields, order):
            return sorted(
                (names.get(str(r["leg_id"])),) + tuple(r[f] for f in fields)
                for r in model.objects.filter(associated_Site=self.site)
                .order_by(order)
                .values("leg_id", *fields)
            )

        return {
            "hourly": rows(
                HourlySiteReading,
                "reading_from", "reading_to", "unit_consumption", "energy_saved",
                "hourly_baseline_value", "is_visible",
                order="id",
            ),
            "daily": rows(
                DailySiteReading,
                "reading_for", "unit_consumption", "energy_saved",
                "daily_baseline_value", "is_visible",
                order="id",
            ),
            "sensor": rows(
                SensorAisleUnitConsumption, "reading_for", "unit_consumption", order="id"
            ),
            "status": sorted(
                (s.aisle_group.aisleGroupName, s.sync_status, s.last_sync_at,
                 s.recovery_requested, s.is_sync_gone)
                for s in AisleSyncRecoveryStatus.objects.filter(site=self.site)
            ),
            "alarms": sorted(
                (a.aisle_group.aisleGroupName if a.aisle_group else None, a.Alarm_type)
                for a in AlarmNotifications.objects.filter(site_id=self.site)
            ),
            "dead_letters": MqttDeadLetter.objects.filter(site_id=self.site.id).count(),
            "published": self.published,
        }


class BatchMatchesSinglePacketTests(TestCase):
    """Same packets, one by one vs in one batch: same stored result."""

    aisles = {"A1": {"is_active": True}, "A2": {"is_active": True}}

    def setUp(self):
        cache.clear()

    def run_both(self, prepare, packets):
        """``packets``: list of (aisle name, payload text with {leg})."""
        single = World("single", self.aisles)
        batch = World("batch", self.aisles)
        for world in (single, batch):
            prepare(world)

        for aisle_name, text in packets:
            with self.captureOnCommitCallbacks(execute=True):
                consumption.handle_consumption_message(
                    single.site, single.site.id, "gw-1",
                    single.payload(aisle_name, text), single.publish,
                )
        with self.captureOnCommitCallbacks(execute=True):
            summary = consumption_batch.process_consumption_batch(
                [Packet(batch.site.id, "gw-1", batch.payload(a, t)) for a, t in packets],
                batch.publish,
            )
        self.assertEqual(batch.snapshot(), single.snapshot())
        return single, batch, summary

    def test_first_reading_updates_and_new_hours(self):
        _, batch, summary = self.run_both(
            lambda w: None,
            [
                ("A1", packet(2, 10, 1.5, 0)),
                ("A1", packet(2, 10, 3.0, 0)),
                ("A2", packet(2, 10, 0.5, 0, new_units=0.5)),
                ("A1", packet(2, 11, 1.0, 3.2, new_units=1.0)),
                ("A1", packet(2, 11, 2.0, 3.2, new_units=1.0)),
                ("A2", packet(2, 11, 0.7, 0.9, new_units=0.7)),
                ("A1", packet(2, 12, 0.4, 2.5, new_units=0.4)),
            ],
        )
        self.assertIn("stored=7", summary)
        self.assertEqual(HourlySiteReading.objects.filter(associated_Site=batch.site).count(), 5)

    def test_existing_rows_current_hour_and_new_hour(self):
        def prepare(w):
            w.hourly("A1", 2, 8, 3.0)
            w.hourly("A1", 2, 9, 4.0)
            w.daily("A1", 2, 99.0)
            w.hourly("A2", 2, 10, 5.0)
            w.daily("A2", 2, 5.0)

        self.run_both(
            prepare,
            [
                ("A1", packet(2, 10, 1.5, 5.0)),
                ("A2", packet(2, 10, 6.5, 0)),
                ("A1", packet(2, 10, 2.5, 5.0, new_units=1.0)),
            ],
        )

    def test_midnight_creates_new_day_and_evaluates_yesterday(self):
        def prepare(w):
            for hour in range(0, 23):
                w.hourly("A1", 1, hour, 2.0)
            w.daily("A1", 1, 46.0)

        self.run_both(
            prepare,
            [
                ("A1", packet(1, 23, 1.0, 2.0, new_units=1.0)),
                ("A1", packet(1, 23, 2.2, 2.0, new_units=1.2)),
                ("A1", packet(2, 0, 0.8, 2.4, new_units=0.8)),
                ("A1", packet(2, 1, 0.5, 1.1, new_units=0.5)),
            ],
        )

    def test_gap_requests_recovery_and_drops_packets(self):
        def prepare(w):
            w.hourly("A1", 2, 5, 3.0)
            w.daily("A1", 2, 3.0)
            w.hourly("A2", 2, 9, 1.0)
            w.daily("A2", 2, 1.0)

        single, batch, summary = self.run_both(
            prepare,
            [
                ("A1", packet(2, 10, 1.5, 2.0)),
                ("A2", packet(2, 10, 1.5, 2.0)),
                ("A1", packet(2, 10, 2.5, 2.0, new_units=1.0)),
            ],
        )
        # A1 has a 06:00-09:00 gap: one request, both of its packets dropped.
        self.assertEqual(len(batch.published), 1)
        self.assertIn("stored=1 skipped=2", summary)

    def test_inactive_and_sensor_aisles(self):
        self.aisles = {
            "A1": {"is_active": False},
            "S1": {"is_active": True, "on_sensor_power": True},
        }

        def prepare(w):
            w.hourly("A1", 2, 9, 1.0)
            w.daily("A1", 2, 1.0)

        self.run_both(
            prepare,
            [
                ("A1", packet(2, 10, 1.5, 2.0)),
                ("S1", packet(2, 10, 0.3, 0, new_units=0.3)),
                ("S1", packet(2, 10, 0.6, 0, new_units=0.3)),
            ],
        )

    def test_diagnostic_bad_payload_and_unknown_leg(self):
        single, batch, summary = self.run_both(
            lambda w: None,
            [
                ("A1", "ERROR!!! meter {leg} not responding"),
                ("A1", "garbage"),
                ("A1", packet(2, 10, 1.5, 0, leg="999999")),
                ("A2", packet(2, 10, 1.5, 0)),
            ],
        )
        self.assertIn("failed=2", summary)
        self.assertIn("stored=1", summary)


class BatchBehaviourTests(TestCase):
    def setUp(self):
        cache.clear()
        self.world = World("batch", {"A1": {"is_active": True}, "A2": {"is_active": True}})

    def batch(self, *texts, aisle="A1"):
        with self.captureOnCommitCallbacks(execute=True):
            return consumption_batch.process_consumption_batch(
                [Packet(self.world.site.id, "gw-1", self.world.payload(aisle, t)) for t in texts],
                self.world.publish,
            )

    @override_settings(MQTT_IDEMPOTENCY_TTL_SECONDS=3600)
    def test_duplicate_packets_are_skipped(self):
        summary = self.batch(packet(2, 10, 1.5, 0), packet(2, 10, 1.5, 0))
        self.assertIn("duplicates 1", summary)
        self.assertEqual(DailySiteReading.objects.get().unit_consumption, 1.5)

    def test_bulk_writes_are_logged_with_duration(self):
        self.world.hourly("A1", 2, 9, 1.0)
        self.world.daily("A1", 2, 1.0)
        with self.assertLogs("wareApp.mqtt.consumption_batch", level="INFO") as logs:
            self.batch(packet(2, 10, 1.5, 2.0), packet(2, 10, 2.0, 2.0, new_units=0.5))
        bulk = [line for line in logs.output if "BULK" in line]
        self.assertTrue(any("BULK CREATE HourlySiteReading" in l for l in bulk), bulk)
        self.assertTrue(any("BULK UPDATE HourlySiteReading" in l for l in bulk), bulk)
        self.assertTrue(any("BULK UPDATE DailySiteReading" in l for l in bulk), bulk)
        self.assertTrue(all("duration=" in l and "ms" in l and "RPC" not in l for l in bulk))
        self.assertTrue(all("A1 (leg" in l and "gw " in l for l in bulk), bulk)

    def test_bulk_line_lists_only_the_aisles_of_its_rows(self):
        self.world.hourly("A1", 2, 9, 1.0)
        self.world.daily("A1", 2, 1.0)
        self.world.hourly("A2", 2, 10, 1.0)
        self.world.daily("A2", 2, 1.0)
        with self.assertLogs("wareApp.mqtt.consumption_batch", level="INFO") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                consumption_batch.process_consumption_batch(
                    [
                        Packet(self.world.site.id, "gw-1", self.world.payload("A1", packet(2, 10, 1.5, 2.0))),
                        Packet(self.world.site.id, "gw-1", self.world.payload("A2", packet(2, 10, 2.0, 0))),
                    ],
                    self.world.publish,
                )
        create = next(l for l in logs.output if "BULK CREATE HourlySiteReading" in l)
        update = next(l for l in logs.output if "BULK UPDATE HourlySiteReading" in l)
        self.assertIn("aisles=1 [", create)
        self.assertIn(":A1 (leg", create)
        self.assertNotIn(":A2 (leg", create)
        # A1's previous hour and A2's current hour are both updated.
        self.assertIn("aisles=2 [", update)

    def test_bulk_writes_use_one_statement_per_table(self):
        for name in ("A1", "A2"):
            self.world.hourly(name, 2, 9, 1.0)
            self.world.daily(name, 2, 1.0)
        texts = [
            (name, packet(2, hour, 1.0, 1.0, new_units=1.0))
            for hour in (10, 11, 12)
            for name in ("A1", "A2")
        ]
        with mock.patch.object(
            HourlySiteReading.objects, "bulk_create", wraps=HourlySiteReading.objects.bulk_create
        ) as create:
            with self.captureOnCommitCallbacks(execute=True):
                consumption_batch.process_consumption_batch(
                    [Packet(self.world.site.id, "gw-1", self.world.payload(n, t)) for n, t in texts],
                    self.world.publish,
                )
        self.assertEqual(create.call_count, 1)
        self.assertEqual(len(create.call_args.args[0]), 6)


class _FakeMessage:
    def __init__(self, body, log):
        self.payload = body
        self.log = log

    def ack(self):
        self.log.append(("ack", self.payload["payload"]))

    def requeue(self):
        self.log.append(("requeue", self.payload["payload"]))


class _FakeQueue:
    def __init__(self, bodies, log):
        self.messages = [_FakeMessage(b, log) for b in bodies]

    def get(self, block=False):
        from queue import Empty

        if not self.messages:
            raise Empty()
        return self.messages.pop(0)

    def close(self):
        pass


class FlushAndListenerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.world = World("flush", {"A1": {"is_active": True}})
        self.log = []

    def flush(self, bodies, **patches):
        connection = mock.MagicMock()
        connection.__enter__.return_value.SimpleQueue.return_value = _FakeQueue(bodies, self.log)
        with mock.patch("warehouse.celery.app.connection_for_read", return_value=connection):
            with self.captureOnCommitCallbacks(execute=True):
                return consumption_batch.flush(self.world.publish)

    def body(self, text):
        return {"site_id": self.world.site.id, "gateway_id": "gw-1",
                "payload": self.world.payload("A1", text)}

    def test_flush_processes_and_acks_after_commit(self):
        summary = self.flush([self.body(packet(2, 10, 1.5, 0)), self.body(packet(2, 10, 2.0, 0, new_units=0.5))])
        self.assertIn("2 packets, stored=2", summary)
        self.assertEqual([kind for kind, _ in self.log], ["ack", "ack"])
        self.assertEqual(DailySiteReading.objects.get().unit_consumption, 2.0)

    def test_flush_requeues_everything_on_error(self):
        with mock.patch.object(
            consumption_batch, "process_consumption_batch", side_effect=RuntimeError("db down")
        ):
            with self.assertRaises(RuntimeError):
                self.flush([self.body(packet(2, 10, 1.5, 0))])
        self.assertEqual([kind for kind, _ in self.log], ["requeue"])

    def test_empty_queue(self):
        self.assertEqual(self.flush([]), "consumption batch: queue empty")

    @override_settings(MQTT_CONSUMPTION_BATCH_SECONDS=60)
    def test_listener_parks_consumption_packets(self):
        topic = mock.Mock(message_type="consumption", message_subtype=None)
        with mock.patch.object(consumption_batch, "enqueue") as enqueue, mock.patch(
            "wareApp.tasks.process_mqtt_message.apply_async"
        ) as apply_async:
            self.assertTrue(consumers._queue_one_message_for_processing(5, "gw", "p", topic))
        enqueue.assert_called_once_with(5, "gw", "p")
        apply_async.assert_not_called()

    @override_settings(MQTT_CONSUMPTION_BATCH_SECONDS=0)
    def test_listener_per_packet_when_batching_off(self):
        topic = mock.Mock(message_type="consumption", message_subtype=None)
        with mock.patch.object(consumption_batch, "enqueue") as enqueue, mock.patch(
            "wareApp.tasks.process_mqtt_message.apply_async"
        ) as apply_async:
            consumers._queue_one_message_for_processing(5, "gw", "p", topic)
        enqueue.assert_not_called()
        apply_async.assert_called_once()

    @override_settings(MQTT_CONSUMPTION_BATCH_SECONDS=60)
    def test_other_packets_stay_per_packet(self):
        topic = mock.Mock(message_type="supplyTime", message_subtype=None)
        with mock.patch.object(consumption_batch, "enqueue") as enqueue, mock.patch(
            "wareApp.tasks.process_mqtt_message.apply_async"
        ) as apply_async, mock.patch.object(consumers, "is_handled", return_value=True):
            consumers._queue_one_message_for_processing(5, "gw", "p", topic)
        enqueue.assert_not_called()
        apply_async.assert_called_once()
