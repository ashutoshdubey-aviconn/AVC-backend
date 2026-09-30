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
