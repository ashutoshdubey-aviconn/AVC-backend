from datetime import datetime
from unittest.mock import patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt.envelope import MqttEnvelope
from wareApp.mqtt.payloads import KeyValuePayload
from wareApp.mqtt.registry import processing_task_for, task_name_for
from wareApp.mqtt.topics import TopicParseError


class KeyValuePayloadTests(SimpleTestCase):
    def test_keys_ignore_case_underscores_and_dashes(self):
        payload = KeyValuePayload.parse("Meter_Number:3, R-Volt : 230.5", "load")

        self.assertEqual(payload.get("meternumber"), "3")
        self.assertEqual(payload.get("rvolt"), "230.5")
        self.assertIn("rvolt", payload)

    def test_first_present_alias_wins(self):
        payload = KeyValuePayload.parse("totalload:12", "load")

        self.assertEqual(payload.get("loadpower", "totalload"), "12")

    def test_unwraps_bytes_and_str_bytes(self):
        self.assertEqual(KeyValuePayload.parse(b"a:1", "x").get("a"), "1")
        self.assertEqual(KeyValuePayload.parse(str(b"a:1"), "x").get("a"), "1")

    def test_value_quotes_are_kept_unless_asked(self):
        self.assertEqual(KeyValuePayload.parse("status:'ON'", "x").get("status"), "'ON'")
        self.assertEqual(
            KeyValuePayload.parse("status:'ON'", "x", strip_value_quotes=True).get("status"),
            "ON",
        )

    def test_errors_name_the_payload_kind(self):
        with self.assertRaisesMessage(ValueError, "Invalid SupplyTime field: 'broken'"):
            KeyValuePayload.parse("broken", "SupplyTime")
        with self.assertRaisesMessage(ValueError, "Missing load field: loadpower"):
            KeyValuePayload.parse("a:1", "load").get("loadpower", "totalload")


class MqttEnvelopeTests(SimpleTestCase):
    topic = "/Acclivate/iOmniControl/156/gateway-01/in/recovery/hourlyConsumption"

    def test_from_mqtt_parses_topic_and_decodes_payload(self):
        envelope = MqttEnvelope.from_mqtt(self.topic, b"payload")

        self.assertEqual(envelope.site_id, 156)
        self.assertEqual(envelope.gateway_id, "gateway-01")
        self.assertEqual(envelope.message_type, "recovery")
        self.assertEqual(envelope.message_subtype, "hourlyConsumption")
        self.assertEqual(envelope.task_args, (156, "gateway-01", "payload"))
        self.assertIsInstance(envelope.received_at, datetime)

    def test_message_id_depends_only_on_topic_and_payload(self):
        first = MqttEnvelope.from_mqtt(self.topic, "payload")
        again = MqttEnvelope.from_mqtt(self.topic, b"payload")
        other = MqttEnvelope.from_mqtt(self.topic, "other")

        self.assertEqual(first.message_id, again.message_id)
        self.assertNotEqual(first.message_id, other.message_id)

    def test_malformed_topic_raises(self):
        with self.assertRaises(TopicParseError):
            MqttEnvelope.from_mqtt("/bad/topic", "payload")


class RegistryTests(SimpleTestCase):
    def test_every_registered_name_is_a_task(self):
        for message_type, subtype in (
            ("consumption", "state"),
            ("FIREALARM", "state"),
            ("load", "state"),
            ("SupplyTime", "state"),
            ("recovery", "dailyConsumption"),
            ("recovery", "hourlyConsumption"),
            ("recovery", "loadRuntime"),
        ):
            with self.subTest(message_type=message_type, subtype=subtype):
                task = processing_task_for(message_type, subtype)
                self.assertIs(task, getattr(tasks, task_name_for(message_type, subtype)))

    def test_unhandled_types_have_no_task(self):
        self.assertIsNone(task_name_for("sync", "consumption"))
        self.assertIsNone(task_name_for("recovery", "unknown"))
        self.assertIsNone(task_name_for("LoadData", "state"))
