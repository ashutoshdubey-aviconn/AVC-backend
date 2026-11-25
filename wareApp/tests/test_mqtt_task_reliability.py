"""Packet tasks: acknowledged after processing, retried on a database error, then a dead letter.

The acks_late / retry idea comes from Daksh's mqtt_pipeline tasks (54313d5); merged into our
tasks on 2026-11-25 (merge-final).
"""

from unittest.mock import patch

from celery.exceptions import Retry
from django.db import OperationalError
from django.test import TestCase, override_settings

from wareApp import tasks
from wareApp.models import MqttDeadLetter

PACKET_TASKS = [
    tasks.process_mqtt_message,
    tasks.process_load_data_message,
    tasks.process_supply_time_message,
    tasks.process_load_runtime_recovery_message,
    tasks.process_daily_consumption_recovery_message,
    tasks.process_hourly_consumption_recovery_message,
    tasks.process_fire_alarm_message,
    tasks.process_consumption_message,
    tasks.process_load_message,
]


class PacketTaskOptionsTests(TestCase):
    """Every task that processes a gateway packet acknowledges late and is re-queued on worker loss."""

    def test_every_packet_task_acks_late_and_requeues_on_worker_loss(self):
        for task in PACKET_TASKS:
            with self.subTest(task=task.name):
                self.assertTrue(task.acks_late)
                self.assertTrue(task.reject_on_worker_lost)


@override_settings(MQTT_TASK_RETRY_MAX=3, MQTT_TASK_RETRY_DELAY_SECONDS=10)
class PacketTaskRetryTests(TestCase):
    """A database error after the in-place retries: task retry, then a dead letter."""

    ARGS = ("SupplyTime", None, 156, "gw-1", "source:1,runtime:60,time:2026-11-25 10:15:00")

    def test_database_error_retries_the_task_later(self):
        with patch("wareApp.tasks._dispatch", side_effect=OperationalError("db down")):
            with patch.object(tasks.process_mqtt_message, "retry", side_effect=Retry()) as retry:
                with self.assertRaises(Retry):
                    tasks.process_mqtt_message.run(*self.ARGS)
        self.assertEqual(retry.call_args.kwargs["countdown"], 10)
        self.assertEqual(retry.call_args.kwargs["max_retries"], 3)
        self.assertEqual(MqttDeadLetter.objects.count(), 0)

    def test_after_the_last_retry_the_packet_is_kept_as_a_dead_letter(self):
        with patch("wareApp.tasks._dispatch", side_effect=OperationalError("db down")):
            result = tasks.process_mqtt_message.apply(args=self.ARGS, retries=3).get()
        self.assertIn("dead letter", result)
        letter = MqttDeadLetter.objects.get()
        self.assertEqual(letter.message_type, "SupplyTime")
        self.assertEqual(letter.site_id, 156)
        self.assertIn("runtime:60", letter.payload)

    def test_other_errors_are_not_retried(self):
        with patch("wareApp.tasks._dispatch", side_effect=ValueError("bad packet")):
            with patch.object(tasks.process_mqtt_message, "retry") as retry:
                with self.assertRaises(ValueError):
                    tasks.process_mqtt_message.run(*self.ARGS)
        retry.assert_not_called()

    def test_load_data_database_error_retries_then_dead_letter(self):
        with patch("wareApp.tasks._save_load_data", side_effect=OperationalError("db down")):
            with patch.object(tasks.process_load_data_message, "retry", side_effect=Retry()):
                with self.assertRaises(Retry):
                    tasks.process_load_data_message.run(156, "gw-1", "payload")
            result = tasks.process_load_data_message.apply(args=(156, "gw-1", "payload"), retries=3).get()
        self.assertIn("dead letter", result)
        self.assertEqual(MqttDeadLetter.objects.get().message_type, "LoadData")

    def test_success_returns_the_handler_outcome(self):
        with patch("wareApp.tasks._dispatch", return_value="stored: ok"):
            self.assertEqual(tasks.process_mqtt_message.run(*self.ARGS), "stored: ok")
