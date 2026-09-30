from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from wareApp.mqtt import consumers
from wareApp.mqtt.routing import (
    QUEUE_ONE,
    QUEUE_ONE_SUBSCRIPTIONS,
    QUEUE_TWO,
    QUEUE_TWO_SUBSCRIPTIONS,
    queue_for_gateway_topic,
)
from wareApp.mqtt.topics import TopicParseError, parse_gateway_topic
from wareApp.management.commands.simulate_mqtt_gateway_traffic import (
    Command as SimulatorCommand,
)
from wareApp.load_data import handler as load_data_handler
from wareApp import tasks


class GatewayTopicParserTests(SimpleTestCase):
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
        with patch("wareApp.tasks.run_mqtt_client1", return_value="queue-one"):
            result = tasks.mqtt_client1.run()

        self.assertEqual(result, "queue-one")

    def test_queue_two_task_delegates_to_extracted_consumer(self):
        with patch("wareApp.tasks.run_mqtt_client2", return_value="queue-two"):
            result = tasks.mqtt_client2.run()

        self.assertEqual(result, "queue-two")

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

    def test_queue_one_ignores_messages_for_missing_sites(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/999999/gateway-01/in/consumption/state",
            payload=b"payload",
        )
        with (
            patch(
                "wareApp.mqtt.consumers.Site.objects.get",
                side_effect=consumers.Site.DoesNotExist,
            ),
            self.assertLogs("wareApp.mqtt.consumers", "WARNING") as logs,
        ):
            client.on_message(client, None, message)

        self.assertIn("Ignoring queue1 message for missing site 999999", logs.output[0])

    def test_queue_one_logs_malformed_consumption_payloads(self):
        client = FakeMqttClient()
        with patch("wareApp.mqtt.consumers.mqtt.Client", return_value=client):
            consumers.run_mqtt_client1()

        message = SimpleNamespace(
            topic="/Acclivate/iOmniControl/156/gateway-01/in/consumption/state",
            payload=b"payload",
        )
        with (
            patch(
                "wareApp.mqtt.consumers.Site.objects.get",
                return_value=SimpleNamespace(site_name="Test site"),
            ),
            self.assertLogs("wareApp.mqtt.consumers", "ERROR") as logs,
        ):
            client.on_message(client, None, message)

        self.assertIn(
            "Queue1 consumption processing failed for site 156", logs.output[0]
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
            args=(156, "gateway-01", "b'payload'"), queue="queue1_processing"
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
            args=(156, "gateway-01", "b'payload'"), queue="queue1_processing"
        )


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.subscriptions = []

    def connect(self, host, port, keepalive):
        self.connection = (host, port, keepalive)

    def subscribe(self, topic):
        self.subscriptions.append(topic)

    def loop_forever(self):
        self.on_connect(self, None, None, 0)
