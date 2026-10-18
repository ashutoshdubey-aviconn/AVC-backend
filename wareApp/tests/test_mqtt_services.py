"""Phase M step M3: partition routing, recovery cooldown, publisher, notifications."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from wareApp import tasks
from wareApp.mqtt import consumers
from wareApp.mqtt.routing import processing_queue_for_site
from wareApp.mqtt.services import notifications
from wareApp.mqtt.services.cooldown import recovery_request_allowed
from wareApp.mqtt.services.publisher import MqttPublisher, publish_after_commit
from wareApp.mqtt.topics import parse_gateway_topic


class PartitionRoutingTests(SimpleTestCase):
    @override_settings(MQTT_SITE_PARTITIONS=0)
    def test_zero_partitions_keeps_the_legacy_queue(self):
        self.assertEqual(processing_queue_for_site(198), "queue1_processing")

    @override_settings(MQTT_SITE_PARTITIONS=4)
    def test_site_always_maps_to_the_same_partition(self):
        self.assertEqual(processing_queue_for_site(198), "mqtt.site.2")
        self.assertEqual(processing_queue_for_site(125), "mqtt.site.1")
        self.assertEqual(processing_queue_for_site(124), "mqtt.site.0")

    @override_settings(MQTT_SITE_PARTITIONS=4)
    def test_listener_enqueues_on_the_site_partition(self):
        topic = parse_gateway_topic(
            "/Acclivate/iOmniControl/198/gw-198/in/consumption/state"
        )
        with patch("wareApp.tasks.process_consumption_message.apply_async") as enqueue:
            consumers._queue_one_message_for_processing(198, "gw-198", "payload", topic)

        enqueue.assert_called_once_with(
            args=(198, "gw-198", "payload"), queue="mqtt.site.2"
        )


class RecoveryCooldownTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_only_the_first_request_of_a_gap_is_allowed(self):
        self.assertTrue(recovery_request_allowed(198, "aisle", 1271))
        self.assertFalse(recovery_request_allowed(198, "aisle", 1271))
        self.assertFalse(recovery_request_allowed(198, "aisle", 1271))

    def test_cooldown_is_per_site_and_scope(self):
        self.assertTrue(recovery_request_allowed(198, "aisle", 1271))
        self.assertTrue(recovery_request_allowed(198, "aisle", 1272))
        self.assertTrue(recovery_request_allowed(107, "aisle", 1271))
        self.assertTrue(recovery_request_allowed(198, "source", 1271))


class PublisherTests(SimpleTestCase):
    def test_publisher_keeps_one_connected_client_and_publishes_qos1(self):
        client = Mock()
        client.publish.return_value = SimpleNamespace(rc=0)
        publisher = MqttPublisher(
            host="broker", port=1883, client_factory=Mock(return_value=client)
        )

        publisher.publish("/topic", "payload")
        publisher.publish("/topic", "payload-2")

        client.connect_async.assert_called_once_with("broker", 1883, 60)
        client.loop_start.assert_called_once_with()
        self.assertEqual(client.publish.call_count, 2)
        self.assertEqual(client.publish.call_args.kwargs["qos"], 1)

    def test_get_reuses_the_process_instance(self):
        with patch.object(MqttPublisher, "__init__", return_value=None) as init:
            MqttPublisher._instance = None
            first = MqttPublisher.get()
            second = MqttPublisher.get()
        self.assertIs(first, second)
        init.assert_called_once()
        MqttPublisher._instance = None


class PublishAfterCommitTests(TestCase):
    def test_recovery_request_is_published_only_after_commit(self):
        publisher = Mock()
        with patch.object(MqttPublisher, "get", return_value=publisher):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                publish_after_commit("/topic", "payload")
            publisher.publish.assert_not_called()
            for callback in callbacks:
                callback()
        publisher.publish.assert_called_once_with("/topic", "payload", qos=1)

    def test_task_publish_helpers_use_the_persistent_publisher(self):
        with patch("wareApp.tasks.publish_after_commit") as publish:
            tasks._publish_consumption_recovery("/t", "m")
            tasks._publish_supply_time_recovery("/t2", "m2")
        self.assertEqual(publish.call_count, 2)


class NotificationTests(TestCase):
    @override_settings(MQTT_ASYNC_NOTIFICATIONS=True)
    def test_allowed_notification_is_queued_after_commit(self):
        def send_alarm_for_high_voltage(data):
            raise AssertionError("must not be sent inline")

        with patch("wareApp.tasks.send_notification.apply_async") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                notifications.notify(send_alarm_for_high_voltage, {"site_id": 1})

        enqueue.assert_called_once_with(
            args=("send_alarm_for_high_voltage", [{"site_id": 1}]),
            queue="notifications",
        )

    @override_settings(MQTT_ASYNC_NOTIFICATIONS=False)
    def test_sync_mode_sends_inline(self):
        send = Mock(__name__="send_alarm_for_high_voltage")
        notifications.notify(send, {"site_id": 1})
        send.assert_called_once_with({"site_id": 1})

    def test_unknown_function_is_rejected_by_the_task(self):
        with patch("wareApp.sendmail.send_alarm_for_high_voltage") as send:
            tasks.send_notification.run("os_system", [])
        send.assert_not_called()

    def test_task_calls_the_named_sendmail_function(self):
        with patch("wareApp.sendmail.send_alarm_for_low_voltage") as send:
            tasks.send_notification.run("send_alarm_for_low_voltage", [{"site_id": 2}])
        send.assert_called_once_with({"site_id": 2})


class FailureHandlingTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_transient_database_error_is_retried_in_place(self):
        from django.db import OperationalError

        from wareApp.mqtt.services.failures import run_with_db_retry

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise OperationalError("server closed the connection")
            return "done"

        self.assertEqual(run_with_db_retry(flaky, sleep=lambda _: None), "done")
        self.assertEqual(len(calls), 3)

    def test_retry_gives_up_after_the_last_delay(self):
        from django.db import OperationalError

        from wareApp.mqtt.services.failures import run_with_db_retry

        def broken():
            raise OperationalError("down")

        with self.assertRaises(OperationalError):
            run_with_db_retry(broken, delays=(0, 0), sleep=lambda _: None)

    def test_unprocessable_packet_is_stored_once_as_dead_letter(self):
        from wareApp.models import MqttDeadLetter
        from wareApp.mqtt import supply_time

        for _ in range(3):
            supply_time.handle_supply_time_message(
                None, SimpleNamespace(id=1), 1, "gw-1", "garbage-without-fields"
            )

        letter = MqttDeadLetter.objects.get()
        self.assertEqual(letter.message_type, "SupplyTime")
        self.assertEqual(letter.site_id, 1)
        self.assertIn("ValueError", letter.error)

    def test_handlers_reraise_transient_database_errors(self):
        from django.db import OperationalError

        from wareApp.mqtt import load

        with patch(
            "wareApp.mqtt.load._parse_load_message",
            side_effect=OperationalError("gone"),
        ):
            with self.assertRaises(OperationalError):
                load.handle_load_message(SimpleNamespace(id=1), 1, "gw-1", "x")

    def test_listener_uses_a_persistent_session(self):
        client = Mock()
        client.loop_forever.return_value = 0
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client) as factory:
            consumers.run_mqtt_client1()

        self.assertFalse(factory.call_args.kwargs["clean_session"])
