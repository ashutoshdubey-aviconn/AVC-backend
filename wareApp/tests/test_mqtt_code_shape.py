from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt.envelope import MqttEnvelope
from wareApp.mqtt.payloads import KeyValuePayload
from wareApp.mqtt import handlers
from wareApp.mqtt.registry import LEGACY_TASK_NAMES, handler_for, is_handled
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
    def test_types_map_to_handlers(self):
        expected = {
            ("consumption", "state"): handlers.ConsumptionHandler,
            ("FIREALARM", "state"): handlers.FireAlarmHandler,
            ("load", "state"): handlers.LoadHandler,
            ("SupplyTime", "state"): handlers.SupplyTimeHandler,
            ("recovery", "dailyConsumption"): handlers.DailyConsumptionRecoveryHandler,
            ("recovery", "hourlyConsumption"): handlers.HourlyConsumptionRecoveryHandler,
            ("recovery", "loadRuntime"): handlers.LoadRuntimeRecoveryHandler,
        }
        for (message_type, subtype), handler_class in expected.items():
            with self.subTest(message_type=message_type, subtype=subtype):
                self.assertTrue(is_handled(message_type, subtype))
                self.assertIsInstance(handler_for(message_type, subtype), handler_class)
        self.assertIs(handler_for("consumption", "a"), handler_for("consumption", "b"))

    def test_unhandled_types(self):
        for message_type, subtype in (
            ("sync", "consumption"),
            ("recovery", "unknown"),
            ("LoadData", "state"),
        ):
            self.assertFalse(is_handled(message_type, subtype))
            self.assertIsNone(handler_for(message_type, subtype))

    def test_only_consumption_is_deduplicated(self):
        deduped = {
            key for key in LEGACY_TASK_NAMES if handler_for(key[0], key[1] or "state").dedupe
        }
        self.assertEqual(deduped, {("consumption", None)})


class ProcessMqttMessageTests(SimpleTestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.site = SimpleNamespace(id=156)

    def run_task(self, message_type, subtype, payload="payload"):
        return tasks.process_mqtt_message.run(message_type, subtype, 156, "gw-1", payload)

    def test_dispatches_to_the_handler_and_returns_its_outcome(self):
        with patch("wareApp.tasks.site_config.site", return_value=self.site), patch(
            "wareApp.mqtt.handlers.handle_load_message", return_value="stored: load"
        ) as handle:
            outcome = self.run_task("load", "state")

        self.assertEqual(outcome, "stored: load")
        handle.assert_called_once_with(self.site, 156, "gw-1", "payload")

    @patch("django.conf.settings.MQTT_IDEMPOTENCY_TTL_SECONDS", 600, create=True)
    def test_duplicate_consumption_packet_is_skipped(self):
        with patch("wareApp.tasks.site_config.site", return_value=self.site), patch(
            "wareApp.mqtt.handlers.handle_consumption_message", return_value="stored"
        ) as handle:
            first = self.run_task("consumption", "state")
            second = self.run_task("consumption", "state")

        self.assertEqual(first, "stored")
        self.assertEqual(second, "skipped: duplicate consumption packet (already processed)")
        handle.assert_called_once()

    def test_unknown_site_and_unknown_type(self):
        from wareApp.models import Site

        with patch("wareApp.tasks.site_config.site", side_effect=Site.DoesNotExist):
            self.assertEqual(self.run_task("load", "state"), "skipped: unknown site 156")
        self.assertEqual(
            self.run_task("recovery", "unknown"), "skipped: no handler for recovery/unknown"
        )

    def test_legacy_task_names_still_dispatch(self):
        for (message_type, subtype), task_name in LEGACY_TASK_NAMES.items():
            with self.subTest(task=task_name), patch(
                "wareApp.tasks._dispatch", return_value="ok"
            ) as dispatch:
                self.assertEqual(getattr(tasks, task_name).run(156, "gw-1", "p"), "ok")
                dispatch.assert_called_once_with(message_type, subtype, 156, "gw-1", "p")
