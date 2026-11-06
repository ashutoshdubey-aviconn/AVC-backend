"""Failed alarm e-mails are kept and retried with back-off for up to 24 h
(wareApp/mqtt/services/notifications.py, tasks.retry_pending_emails)."""

import smtplib
from datetime import datetime, timedelta
from unittest import mock

from django.test import TestCase, override_settings

from wareApp import sendmail, tasks
from wareApp.models import PendingEmail
from wareApp.mqtt.services import notifications
from wareApp.sendmail import EmailFailure

NOW = datetime(2026, 11, 6, 14, 55)
ARGS = ["Gateway Disconnected", 53, [["Gateway", "avc_x_000053_2", False]], 15]
REFUSED = EmailFailure("SMTPServerDisconnected: Connection unexpectedly closed", transient=True)


class EmailFailureTests(TestCase):
    def test_is_false_like_before(self):
        self.assertFalse(REFUSED)
        self.assertTrue(REFUSED == False)  # noqa: E712 - old callers compare with False
        self.assertTrue(REFUSED.transient)

    @override_settings(EMAIL_HOST="smtp.example.com", ALARM_EMAIL_OVERRIDE_TO="")
    def test_smtp_errors_are_classified(self):
        with mock.patch.object(sendmail.smtplib, "SMTP", side_effect=smtplib.SMTPServerDisconnected("closed")):
            result = sendmail._send_smtp_email("s", "<p>x</p>", ["a@example.com"])
        self.assertEqual((bool(result), result.transient), (False, True))
        refused = smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no")})
        with mock.patch.object(sendmail.smtplib, "SMTP", side_effect=refused):
            self.assertFalse(sendmail._send_smtp_email("s", "<p>x</p>", ["a@example.com"]).transient)
        self.assertFalse(sendmail._send_smtp_email("s", "<p>x</p>", []).transient)  # no recipients


class RememberFailedTests(TestCase):
    def test_transient_failure_is_kept(self):
        self.assertTrue(notifications.remember_failed("send_alarm_email", ARGS, REFUSED, NOW))
        pending = PendingEmail.objects.get()
        self.assertEqual(pending.summary, "Gateway Disconnected - site 53")
        self.assertEqual(pending.args, ARGS)
        self.assertEqual(pending.next_try_at, NOW + timedelta(minutes=5))

    def test_permanent_failure_success_and_off_are_not_kept(self):
        self.assertFalse(notifications.remember_failed("send_alarm_email", ARGS, EmailFailure("no recipients", False)))
        self.assertFalse(notifications.remember_failed("send_alarm_email", ARGS, True))
        self.assertFalse(notifications.remember_failed("not_allowed", ARGS, REFUSED))
        with self.settings(NOTIFICATION_RETRY_HOURS=0):
            self.assertFalse(notifications.remember_failed("send_alarm_email", ARGS, REFUSED))
        self.assertFalse(PendingEmail.objects.exists())

    def test_queued_send_that_fails_is_kept(self):
        with mock.patch.object(sendmail, "send_alarm_email", return_value=REFUSED):
            out = tasks.send_notification.run("send_alarm_email", ARGS)
        self.assertIn("kept for retry", out)
        self.assertEqual(PendingEmail.objects.count(), 1)

    @override_settings(MQTT_ASYNC_NOTIFICATIONS=False)
    def test_direct_send_that_fails_is_kept(self):
        def send_alarm_email(*args):
            return REFUSED
        notifications.notify(send_alarm_email, *ARGS)
        self.assertEqual(PendingEmail.objects.count(), 1)


class RetryPendingTests(TestCase):
    def keep(self, minutes_ago=0, summary_site=53):
        args = list(ARGS)
        args[1] = summary_site
        notifications.remember_failed("send_alarm_email", args, REFUSED, NOW - timedelta(minutes=minutes_ago))
        return PendingEmail.objects.latest("id")

    def test_due_email_is_sent_and_removed(self):
        self.keep(minutes_ago=10)
        with mock.patch.object(sendmail, "send_alarm_email", return_value=True) as send:
            out = notifications.retry_pending(NOW)
        send.assert_called_once_with(*ARGS)
        self.assertIn("sent=1", out)
        self.assertFalse(PendingEmail.objects.exists())

    def test_not_due_yet_is_left(self):
        self.keep(minutes_ago=2)  # next try 5 min after the failure
        with mock.patch.object(sendmail, "send_alarm_email") as send:
            notifications.retry_pending(NOW)
        send.assert_not_called()

    def test_still_refused_backs_off_and_stops_the_run(self):
        first = self.keep(minutes_ago=30, summary_site=53)
        self.keep(minutes_ago=20, summary_site=133)
        with mock.patch.object(sendmail, "send_alarm_email", return_value=REFUSED) as send:
            out = notifications.retry_pending(NOW)
        self.assertEqual(send.call_count, 1)  # the second is not tried in this run
        first.refresh_from_db()
        self.assertEqual((first.attempts, first.next_try_at), (2, NOW + timedelta(minutes=15)))
        self.assertIn("failed=1", out)
        self.assertIn("waiting=2", out)

    def test_back_off_grows_and_gives_up_after_24_hours(self):
        pending = self.keep(minutes_ago=0)
        delays = []
        at = NOW
        with mock.patch.object(sendmail, "send_alarm_email", return_value=REFUSED):
            while PendingEmail.objects.exists():
                pending.refresh_from_db()
                at = pending.next_try_at
                notifications.retry_pending(at)
                if PendingEmail.objects.exists():
                    pending.refresh_from_db()
                    delays.append(int((pending.next_try_at - at).total_seconds() // 60))
        self.assertEqual(delays[:7], [15, 30, 60, 120, 240, 480, 480])
        self.assertGreaterEqual(at - NOW, timedelta(hours=24))  # given up only after 24 h
        self.assertLess(at - NOW, timedelta(hours=24, minutes=481))

    def test_retry_task_runs(self):
        self.keep(minutes_ago=10)
        with mock.patch.object(sendmail, "send_alarm_email", return_value=True), \
                mock.patch("wareApp.tasks.close_old_connections"), \
                mock.patch.object(notifications, "datetime") as fake:
            fake.now.return_value = NOW
            out = tasks.retry_pending_emails.run()
        self.assertIn("sent=1", out)
