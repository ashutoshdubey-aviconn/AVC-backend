from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from wareApp import sendmail
from wareApp.models import Site


class FakeSMTP:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    ehlo = starttls = login = MagicMock()

    def sendmail(self, from_addr, recipients, message):
        FakeSMTP.sent.append((from_addr, recipients, message))


@patch("wareApp.sendmail.smtplib.SMTP", FakeSMTP)
# SMTP settings normally come from warehouse/.env, which CI does not have.
@override_settings(
    EMAIL_HOST="smtp.example.com", EMAIL_PORT=587, EMAIL_USE_TLS=True,
    EMAIL_HOST_USER="alarms@example.com", EMAIL_HOST_PASSWORD="test",
    DEFAULT_FROM_EMAIL="alarms@example.com",
)
class AlarmEmailTests(TestCase):
    def setUp(self):
        FakeSMTP.sent = []
        self.site = Site.objects.create(site_name="Alarm test site")

    @override_settings(ALARM_EMAIL_OVERRIDE_TO=["tester@example.com"])
    def test_override_replaces_every_alarm_recipient(self):
        result = sendmail._send_smtp_email(
            "High Voltage Alarm", "<p>x</p>", ["customer@example.com"], cc=["cc@example.com"]
        )

        self.assertTrue(result)
        _, recipients, message = FakeSMTP.sent[0]
        self.assertEqual(recipients, ["tester@example.com"])
        self.assertIn("customer@example.com", message)  # shown as intended recipient

    @override_settings(ALARM_EMAIL_OVERRIDE_TO=["tester@example.com"])
    def test_registration_email_is_not_redirected(self):
        sendmail._send_smtp_email("Welcome", "<p>x</p>", ["user@example.com"], is_alarm=False)

        self.assertEqual(FakeSMTP.sent[0][1], ["user@example.com"])

    @override_settings(ALARM_EMAIL_OVERRIDE_TO=[], ALARM_EMAIL_DEFAULT_TO=[])
    @patch.multiple(
        "wareApp.mqtt.services.alarm_recipients",
        SOFTWARE_TEAM=[], GROUND_TEAM_ALL_SITES=[], GROUND_TEAM={},
    )
    def test_generic_alarm_without_recipients_is_not_sent(self):
        self.assertFalse(
            sendmail.send_alarm_email("Low Consumption Alarm", self.site.id, [["Leg", "735", False]])
        )
        self.assertEqual(FakeSMTP.sent, [])

    @override_settings(ALARM_EMAIL_OVERRIDE_TO=["tester@example.com"])
    def test_pf_alarm_sends_an_email(self):
        result = sendmail.send_mail_for_pf_fluctuation(
            {
                "r_pf": 0.86, "y_pf": 0.60, "b_pf": 0.65,
                "r_pf_threshold": 0.85, "y_pf_threshold": 0.85, "b_pf_threshold": 0.85,
                "site_id": self.site.id, "power_source": "Mains Supply",
            }
        )

        self.assertTrue(result)
        _, recipients, message = FakeSMTP.sent[0]
        self.assertEqual(recipients, ["tester@example.com"])
        self.assertIn("PF Fluctuation Alarm", message)
        self.assertIn("Alarm test site", message)
