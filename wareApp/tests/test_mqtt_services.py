"""Phase M step M3: partition routing, recovery cooldown, publisher, notifications."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from wareApp import tasks
from wareApp.mqtt import handlers
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

    @override_settings(MQTT_SITE_PARTITIONS=4, MQTT_CONSUMPTION_BATCH_SECONDS=0)
    def test_listener_enqueues_on_the_site_partition(self):
        topic = parse_gateway_topic(
            "/Acclivate/iOmniControl/198/gw-198/in/consumption/state"
        )
        with patch("wareApp.tasks.process_mqtt_message.apply_async") as enqueue:
            consumers._queue_one_message_for_processing(198, "gw-198", "payload", topic)

        enqueue.assert_called_once_with(
            args=("consumption", "state", 198, "gw-198", "payload"), queue="mqtt.site.2", delivery_mode=1
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
        with patch("wareApp.mqtt.handlers.publish_after_commit") as publish:
            handlers.publish_recovery_request("/t", "m")
            handlers.publish_recovery_request("/t2", "m2")
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
        # The real call closes the test transaction's connection on PostgreSQL
        # (autocommit is off inside TestCase), breaking the following tests.
        patcher = patch("wareApp.mqtt.services.failures.close_old_connections")
        self.close_old_connections = patcher.start()
        self.addCleanup(patcher.stop)

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
        self.assertEqual(self.close_old_connections.call_count, 2)

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


@override_settings(MQTT_IDEMPOTENCY_TTL_SECONDS=3600)
class IdempotencyTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_duplicate_consumption_packet_is_processed_once(self):
        site = SimpleNamespace(id=156)
        with patch("wareApp.tasks.site_config.site", return_value=site), patch(
            "wareApp.mqtt.handlers.handle_consumption_message"
        ) as handle:
            tasks.process_consumption_message.run(156, "gw-1", "payload-A")
            tasks.process_consumption_message.run(156, "gw-1", "payload-A")
            tasks.process_consumption_message.run(156, "gw-1", "payload-B")

        self.assertEqual(handle.call_count, 2)

    def test_failed_packet_can_be_processed_again(self):
        from django.db import OperationalError

        site = SimpleNamespace(id=156)
        with patch("wareApp.tasks.site_config.site", return_value=site), patch(
            "wareApp.mqtt.handlers.handle_consumption_message",
            side_effect=[OperationalError("down")] * 4 + [None],
        ) as handle, patch("wareApp.mqtt.services.failures.time.sleep"):
            with self.assertRaises(OperationalError):
                tasks.process_consumption_message.run(156, "gw-1", "payload-A")
            tasks.process_consumption_message.run(156, "gw-1", "payload-A")

        self.assertEqual(handle.call_count, 5)

    def test_other_families_are_not_guarded(self):
        from wareApp.mqtt.services import idempotency

        self.assertIsNotNone(idempotency.claim("SupplyTime", 1, "gw", "same"))
        self.assertIsNotNone(idempotency.claim("SupplyTime", 1, "gw", "same"))


class LocalCacheSizeTests(SimpleTestCase):
    def test_cooldowns_survive_more_keys_than_the_django_default(self):
        from django.conf import settings

        if settings.CACHES["default"]["BACKEND"].endswith("LocMemCache"):
            self.assertGreaterEqual(
                settings.CACHES["default"]["OPTIONS"]["MAX_ENTRIES"], 100_000
            )
        cache.clear()
        for index in range(1000):
            cache.set(f"filler:{index}", 1, 600)
        self.assertTrue(recovery_request_allowed(94, "aisle", 490))
        for index in range(1000, 2000):
            cache.set(f"filler:{index}", 1, 600)
        self.assertFalse(recovery_request_allowed(94, "aisle", 490))
        cache.clear()


class PersistentMessageSettingTests(SimpleTestCase):
    @override_settings(MQTT_TRANSIENT_MESSAGES=False, MQTT_CONSUMPTION_BATCH_SECONDS=0)
    def test_persistent_when_transient_messages_are_off(self):
        topic = parse_gateway_topic("/Acclivate/iOmniControl/198/gw-198/in/consumption/state")
        with patch("wareApp.tasks.process_mqtt_message.apply_async") as enqueue:
            consumers._queue_one_message_for_processing(198, "gw-198", "payload", topic)

        self.assertNotIn("delivery_mode", enqueue.call_args.kwargs)


class PfThresholdWarningTests(SimpleTestCase):
    def test_missing_thresholds_are_logged_once_per_site_per_hour(self):
        from wareApp.mqtt import load

        cache.clear()
        site = SimpleNamespace(
            id=145, site_name="Site 145", is_pf_visible=True,
            r_phase_pf_threshold=None, y_phase_pf_threshold=0.85, b_phase_pf_threshold=0.85,
        )
        values = {"power_factors": (0.5, 0.5, 0.5), "status": "ON", "power_source": "Mains Supply", "meter_number": 1}
        with self.assertLogs("wareApp.mqtt.load", level="WARNING") as logs:
            for _ in range(5):
                load._record_power_factor_alarm(site, values)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("site=145", logs.output[0])
        cache.clear()
