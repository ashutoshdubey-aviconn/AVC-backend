from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from kombu.exceptions import OperationalError
from paho.mqtt.client import MQTT_ERR_CONN_LOST, MQTT_ERR_SUCCESS

from wareApp import tasks
from wareApp.load_data import handler as load_data_handler
from wareApp.management.commands.simulate_mqtt_gateway_traffic import (
    Command as SimulatorCommand,
)
from wareApp.mqtt import consumers
from wareApp.mqtt.remote_access import request_remote_access
from wareApp.mqtt.routing import (
    QUEUE_ONE,
    QUEUE_ONE_NOOP_MESSAGE_TYPES,
    QUEUE_ONE_SUBSCRIPTIONS,
    QUEUE_TWO,
    QUEUE_TWO_SUBSCRIPTIONS,
    queue_for_gateway_topic,
)
from wareApp.mqtt.topics import TopicParseError, parse_gateway_topic
from warehouse.celery import app


class GatewayTopicParserTests(SimpleTestCase):
    def setUp(self):
        tasks._mqtt_start_dispatched.clear()

    def test_parses_gateway_inbound_topic(self):
        parsed = parse_gateway_topic(
            "/Acclivate/iOmniControl/12/gateway-001/in/LoadData/current"
        )

        self.assertEqual(parsed.site_id, 12)
        self.assertEqual(parsed.gateway_id, "gateway-001")
        self.assertEqual(parsed.message_type, "LoadData")
        self.assertEqual(parsed.message_subtype, "current")

    def test_parses_message_type_with_legacy_suffix(self):
        parsed = parse_gateway_topic(
            "/Acclivate/iOmniControl/12/gateway-001/in/recovery_data/dailyConsumption"
        )

        self.assertEqual(parsed.message_type, "recovery")
        self.assertEqual(parsed.message_subtype, "dailyConsumption")

    def test_preserves_unknown_message_type_for_the_consumer(self):
        parsed = parse_gateway_topic(
            "/Acclivate/iOmniControl/12/gateway-001/in/futureType/current"
        )

        self.assertEqual(parsed.message_type, "futureType")

    def test_rejects_topics_with_missing_segments(self):
        with self.assertRaises(TopicParseError):
            parse_gateway_topic("/Acclivate/iOmniControl/12/gateway-001/in/LoadData")

    def test_rejects_topics_with_non_numeric_site_id(self):
        with self.assertRaises(TopicParseError):
            parse_gateway_topic(
                "/Acclivate/iOmniControl/not-a-site/gateway-001/in/LoadData/current"
            )

    def test_rejects_unknown_topic_root(self):
        with self.assertRaises(TopicParseError):
            parse_gateway_topic("/other/root/12/gateway-001/in/LoadData/current")

    def test_queue_one_task_delegates_to_extracted_consumer(self):
        with patch("wareApp.tasks.run_mqtt_client1", return_value=MQTT_ERR_SUCCESS):
            result = tasks.mqtt_client1.run()

        self.assertEqual(result, MQTT_ERR_SUCCESS)

    def test_queue_two_task_delegates_to_extracted_consumer(self):
        with patch("wareApp.tasks.run_mqtt_client2", return_value=MQTT_ERR_SUCCESS):
            result = tasks.mqtt_client2.run()

        self.assertEqual(result, MQTT_ERR_SUCCESS)

    def test_listener_non_success_exit_is_reported_as_a_task_failure(self):
        with self.assertRaisesRegex(RuntimeError, "Queue1 MQTT listener exited"):
            tasks._run_mqtt_listener(lambda: MQTT_ERR_CONN_LOST, "Queue1")

    def test_listener_tasks_retry_unexpected_failures_with_bounded_backoff(self):
        for task in (tasks.mqtt_client1, tasks.mqtt_client2):
            self.assertEqual(task.autoretry_for, (Exception,))
            self.assertTrue(task.retry_backoff)
            self.assertEqual(task.retry_backoff_max, 30)
            self.assertFalse(task.retry_jitter)
            self.assertIsNone(task.max_retries)

    def test_queue_two_worker_starts_load_data_mqtt_task(self):
        sender = SimpleNamespace(hostname="worker.queue2@test-server")
        inspector = Mock()
        inspector.active.return_value = {}
        inspector.reserved.return_value = {}

        with (
            patch("wareApp.tasks.app.control.inspect", return_value=inspector),
            patch("wareApp.tasks.app.send_task") as send_task,
        ):
            tasks.start_queue_two_mqtt_client(sender)

        send_task.assert_called_once_with("wareApp.tasks.mqtt_client2", queue="queue2")

    def test_queue_one_worker_starts_business_mqtt_task(self):
        sender = SimpleNamespace(hostname="worker.queue1@test-server")
        inspector = Mock()
        inspector.active.return_value = {}
        inspector.reserved.return_value = {}

        with (
            patch("wareApp.tasks.app.control.inspect", return_value=inspector),
            patch("wareApp.tasks.app.send_task") as send_task,
        ):
            tasks.start_queue_one_mqtt_client(sender)

        send_task.assert_called_once_with("wareApp.tasks.mqtt_client1", queue="queue1")

    def test_queue_two_worker_does_not_restart_active_load_data_task(self):
        sender = SimpleNamespace(hostname="worker.queue2@test-server")
        inspector = Mock()
        inspector.active.return_value = {
            "worker.queue2@test-server": [{"name": "wareApp.tasks.mqtt_client2"}]
        }
        inspector.reserved.return_value = {}

        with (
            patch("wareApp.tasks.app.control.inspect", return_value=inspector),
            patch("wareApp.tasks.app.send_task") as send_task,
        ):
            tasks.start_queue_two_mqtt_client(sender)

        send_task.assert_not_called()

    def test_queue_two_worker_defers_start_when_broker_inspection_fails(self):
        sender = SimpleNamespace(hostname="worker.queue2@test-server")

        with (
            patch(
                "wareApp.tasks.app.control.inspect",
                side_effect=OperationalError("broker unavailable"),
            ),
            patch("wareApp.tasks.app.send_task") as send_task,
        ):
            tasks.start_queue_two_mqtt_client(sender)

        send_task.assert_not_called()

    def test_queue_two_worker_starts_load_data_mqtt_task_once(self):
        sender = SimpleNamespace(hostname="worker.queue2@test-server")
        inspector = Mock()
        inspector.active.return_value = {}
        inspector.reserved.return_value = {}

        with (
            patch("wareApp.tasks.app.control.inspect", return_value=inspector),
            patch("wareApp.tasks.app.send_task") as send_task,
        ):
            tasks.start_queue_two_mqtt_client(sender)
            tasks.start_queue_two_mqtt_client(sender)

        send_task.assert_called_once_with("wareApp.tasks.mqtt_client2", queue="queue2")

    def test_non_queue_two_worker_does_not_start_load_data_mqtt_task(self):
        sender = SimpleNamespace(hostname="worker.queue1@test-server")

        with patch("wareApp.tasks.app.send_task") as send_task:
            tasks.start_queue_two_mqtt_client(sender)

        send_task.assert_not_called()

    def test_non_queue_one_worker_does_not_start_business_mqtt_task(self):
        sender = SimpleNamespace(hostname="worker.queue2@test-server")

        with patch("wareApp.tasks.app.send_task") as send_task:
            tasks.start_queue_one_mqtt_client(sender)

        send_task.assert_not_called()

    def test_queue_one_processing_worker_does_not_start_business_listener(self):
        sender = SimpleNamespace(hostname="worker.queue1_processing@test-server")

        with patch("wareApp.tasks.app.send_task") as send_task:
            tasks.start_queue_one_mqtt_client(sender)

        send_task.assert_not_called()

    def test_celery_declares_isolated_mqtt_queues(self):
        queue_names = {queue.name for queue in app.conf.task_queues}

        self.assertTrue(
            {"queue1", "queue2", "queue1_processing", "queue2_processing"}.issubset(
                queue_names
            )
        )

    def test_real_queue_one_topic_routes_only_to_queue_one(self):
        topic = (
            "/Acclivate/iOmniControl/186/avc_ZeptoNebSarai_Delhi_0000186_1/"
            "in/consumption/state"
        )

        self.assertEqual(queue_for_gateway_topic(topic), QUEUE_ONE)

    def test_real_load_data_topic_routes_only_to_queue_two(self):
        topic = (
            "/Acclivate/iOmniControl/156/avc_DHL_Kalpathru_000156_1/"
            "in/LoadData/state"
        )

        self.assertEqual(queue_for_gateway_topic(topic), QUEUE_TWO)

    def test_observed_remote_access_topic_routes_to_queue_one(self):
        topic = "/Acclivate/iOmniControl/12/gateway-001/in/remoteAccess/state"

        self.assertEqual(queue_for_gateway_topic(topic), QUEUE_ONE)

    def test_remote_access_command_publishes_gateway_protocol(self):
        publish_command = Mock()

        request_remote_access(
            156,
            "gateway-01",
            "start",
            retry_count=3,
            publish_command=publish_command,
        )

        publish_command.assert_called_once_with(
            "/Acclivate/iOmniControl/156/gateway-01/in/remoteAccess/state",
            payload="start_3",
            hostname="127.0.0.1",
            port=1883,
            qos=1,
            retain=False,
        )

    def test_remote_access_command_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            request_remote_access(156, "gateway-01", "shell")

    def test_remote_access_command_rejects_invalid_topic_components(self):
        invalid_commands = (
            (0, "gateway-01", "start", 0),
            (156, "gateway/other", "start", 0),
            (156, "gateway-01", "start", True),
        )

        for site_id, gateway_id, action, retry_count in invalid_commands:
            with self.assertRaises(ValueError):
                request_remote_access(site_id, gateway_id, action, retry_count)

    def test_consumers_subscribe_only_to_their_assigned_topics(self):
        queue_one_client = FakeMqttClient()
        queue_two_client = FakeMqttClient()
        with patch(
            "wareApp.mqtt.consumers.mqtt.Client",
            side_effect=[queue_one_client, queue_two_client],
        ):
            consumers.run_mqtt_client1()
            consumers.run_mqtt_client2()

        self.assertEqual(queue_one_client.subscriptions, list(QUEUE_ONE_SUBSCRIPTIONS))
        self.assertEqual(queue_two_client.subscriptions, list(QUEUE_TWO_SUBSCRIPTIONS))

    def test_consumers_retry_initial_broker_connection_with_bounded_backoff(self):
        queue_one_client = FakeMqttClient()
        queue_two_client = FakeMqttClient()
        with patch(
            "wareApp.mqtt.consumers.mqtt.Client",
            side_effect=[queue_one_client, queue_two_client],
        ):
            consumers.run_mqtt_client1()
            consumers.run_mqtt_client2()

        for client in (queue_one_client, queue_two_client):
            self.assertEqual(client.connection, ("127.0.0.1", 1883, 60))
            self.assertEqual(client.reconnect_delay, (1, 30))
            self.assertTrue(client.retry_first_connection)

    def test_queue_one_does_not_subscribe_to_noop_topics(self):
        subscribed_types = {topic.split("/")[-2] for topic in QUEUE_ONE_SUBSCRIPTIONS}

        self.assertTrue(subscribed_types.isdisjoint(QUEUE_ONE_NOOP_MESSAGE_TYPES))

    def test_gateway_simulator_emits_messages_for_both_queues(self):
        messages = SimulatorCommand()._messages(
            156, "967", "simulation-gateway-01", all_topics=True
        )
        queues = {queue_for_gateway_topic(topic) for topic, _payload in messages}

        self.assertEqual(queues, {QUEUE_ONE, QUEUE_TWO})
        self.assertEqual(len(messages), 8)

    def test_gateway_simulator_can_emit_only_load_data(self):
        messages = SimulatorCommand()._messages(
            156, "967", "simulation-gateway-01", all_topics=False, load_data_only=True
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(queue_for_gateway_topic(messages[0][0]), QUEUE_TWO)

    def test_load_data_handler_saves_updates_and_rolls_up(self):
        site = SimpleNamespace(is_loadGraph_visible=True)
        reading = SimpleNamespace(
            leg_id="967",
            load_value=31766.992,
            epoch_time="1790800402065",
            created="2026-10-01T02:03:22",
        )
        aisle_group = object()

        with (
            patch(
                "wareApp.load_data.handler.parse_load_data_message",
                return_value=reading,
            ),
            patch(
                "wareApp.load_data.handler.AisleGroup.objects.get",
                return_value=aisle_group,
            ),
            patch("wareApp.load_data.handler.save_raw_load_reading") as save_raw,
            patch(
                "wareApp.load_data.handler.update_monthly_min_max_load"
            ) as update_monthly,
            patch("wareApp.load_data.handler.roll_up_load_data_if_due") as roll_up,
        ):
            load_data_handler.handle_load_data_message(
                object(), site, 156, "gateway-01", "payload", ["LoadData"]
            )

        save_raw.assert_called_once_with(site, aisle_group, reading)
        update_monthly.assert_called_once_with(site, aisle_group, reading)
        roll_up.assert_called_once_with(site, reading.created)

    def test_queue_one_ignores_malformed_topics(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        with self.assertLogs("wareApp.mqtt.consumers", "WARNING") as logs:
            client.on_message(
                client,
                None,
                SimpleNamespace(topic="/invalid/topic", payload=b"payload"),
            )

        self.assertIn("Ignoring malformed queue1 topic", logs.output[0])

    def test_queue_one_defers_missing_site_validation_to_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/999999/gateway-01/in/consumption/state",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get") as get_site,
            patch("wareApp.tasks.process_consumption_message.apply_async") as enqueue,
        ):
            client.on_message(client, None, message)

        get_site.assert_not_called()
        enqueue.assert_called_once_with(
            args=(999999, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_two_defers_load_data_processing_without_a_site_query(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client2()

        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/LoadData/state",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get") as get_site,
            patch("wareApp.tasks.process_load_data_message.apply_async") as enqueue,
        ):
            client.on_message(client, None, message)

        get_site.assert_not_called()
        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue2_processing"
        )

    def test_queue_one_queues_consumption_for_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/consumption/state",
            payload=b"payload",
        )
        with patch("wareApp.tasks.process_consumption_message.apply_async") as enqueue:
            client.on_message(client, None, message)

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_one_queues_supply_time_for_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        site = SimpleNamespace(id=156, site_name="Test site")
        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/SupplyTime/state",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get", return_value=site),
            patch("wareApp.tasks.process_supply_time_message.apply_async") as enqueue,
        ):
            client.on_message(client, None, message)

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_one_queues_fire_alarm_for_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        site = SimpleNamespace(id=156, site_name="Test site")
        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/FIREALARM/state",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get", return_value=site),
            patch("wareApp.tasks.process_fire_alarm_message.apply_async") as enqueue,
        ):
            client.on_message(client, None, message)

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_one_queues_load_for_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        site = SimpleNamespace(id=156, site_name="Test site")
        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/load/state",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get", return_value=site),
            patch("wareApp.tasks.process_load_message.apply_async") as enqueue,
        ):
            client.on_message(client, None, message)

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_one_queues_hourly_consumption_recovery_for_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        site = SimpleNamespace(id=156, site_name="Test site")
        message = SimpleNamespace(
            topic=(
                "/Acclivate/iOmniControl/156/gateway-01/in/"
                "recovery/hourlyConsumption"
            ),
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get", return_value=site),
            patch(
                "wareApp.tasks.process_hourly_consumption_recovery_message.apply_async"
            ) as enqueue,
        ):
            client.on_message(client, None, message)

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_one_queues_load_runtime_recovery_for_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        site = SimpleNamespace(id=156, site_name="Test site")
        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/recovery/loadRuntime",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get", return_value=site),
            patch(
                "wareApp.tasks.process_load_runtime_recovery_message.apply_async"
            ) as enqueue,
        ):
            client.on_message(client, None, message)

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_one_queues_daily_consumption_recovery_for_processing(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        site = SimpleNamespace(id=156, site_name="Test site")
        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/recovery/dailyConsumption",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get", return_value=site),
            patch(
                "wareApp.tasks.process_daily_consumption_recovery_message.apply_async"
            ) as enqueue,
        ):
            client.on_message(client, None, message)

        enqueue.assert_called_once_with(
            args=(156, "gateway-01", "payload"), queue="queue1_processing"
        )

    def test_queue_one_ignores_sync_without_a_processing_handler(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        site = SimpleNamespace(id=156, site_name="Test site")
        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/sync/state",
            payload=b"payload",
        )
        with (
            patch("wareApp.mqtt.consumers.Site.objects.get", return_value=site),
            patch("wareApp.tasks.process_consumption_message.apply_async") as enqueue,
        ):
            client.on_message(client, None, message)

        enqueue.assert_not_called()

    def test_queue_one_ignores_unknown_recovery_subtype(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/recovery/unknown",
            payload=b"payload",
        )
        with patch(
            "wareApp.tasks.process_daily_consumption_recovery_message.apply_async"
        ) as enqueue:
            client.on_message(client, None, message)

        enqueue.assert_not_called()


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.subscriptions = []

    def connect_async(self, host, port, keepalive):
        self.connection = (host, port, keepalive)

    def reconnect_delay_set(self, min_delay, max_delay):
        self.reconnect_delay = (min_delay, max_delay)

    def subscribe(self, topic):
        self.subscriptions.append(topic)

    def loop_forever(self, retry_first_connection=False):
        self.retry_first_connection = retry_first_connection
        self.on_connect(self, None, None, 0)
