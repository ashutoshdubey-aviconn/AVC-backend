from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import fire_alarm


class FireAlarmHandlerTests(SimpleTestCase):
    message = b"Meter_Number:1,R_Volt:230,Y_Volt:80,B_Volt:230,Power_Status:1"

    def test_parser_reads_gateway_payload(self):
        self.assertEqual(
            fire_alarm._parse_fire_alarm_message(str(self.message)),
            (1, 230.0, 80.0, 230.0, 1),
        )

    def test_updates_fire_pump_and_sends_first_motor_on_email(self):
        site = SimpleNamespace(customer=SimpleNamespace(email="test@example.com"))
        record = SimpleNamespace(
            r_volt=230.0, y_volt=80.0, b_volt=230.0, aisleGroup="Pump A"
        )
        fire_pump_entries = Mock(first=Mock(return_value=record))
        previous_emails = Mock()
        previous_emails.order_by.return_value.first.return_value = None

        with patch(
            "wareApp.mqtt.fire_alarm.FirePumpAlarm.objects.filter",
            return_value=fire_pump_entries,
        ), patch(
            "wareApp.mqtt.fire_alarm.Email_History.objects.filter",
            return_value=previous_emails,
        ), patch("wareApp.mqtt.fire_alarm.Email_History.objects.create") as create, patch(
            "wareApp.mqtt.fire_alarm.send_mail_fire_alarm_user"
        ) as send:
            fire_alarm.handle_fire_alarm_message(site, 156, "gateway-01", str(self.message))

        fire_pump_entries.update.assert_called_once()
        send.assert_called_once_with(
            "test@example.com", "Motor-On in Auto-Mode", "Pump A", 1
        )
        create.assert_called_once()

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)
        with patch("wareApp.tasks.Site.objects.get", return_value=site), patch(
            "wareApp.tasks.handle_fire_alarm_message"
        ) as handle:
            tasks.process_fire_alarm_message.run(156, "gateway-01", str(self.message))

        handle.assert_called_once_with(site, 156, "gateway-01", str(self.message))