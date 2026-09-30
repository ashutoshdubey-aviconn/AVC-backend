from django.test import SimpleTestCase
from unittest.mock import patch

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
