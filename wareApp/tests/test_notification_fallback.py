"""Alarm e-mails survive a missing broker (notify falls back to sending directly)."""

from unittest import mock

from django.core.cache import cache
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from kombu.exceptions import OperationalError as KombuOperationalError

from wareApp import gateway_overheat
from wareApp.models import Site
from wareApp.mqtt.services import notifications


def send_alarm_email(*args):  # name must be in ALLOWED_NOTIFICATIONS
    return send_alarm_email.result


send_alarm_email.result = True


@override_settings(MQTT_ASYNC_NOTIFICATIONS=True)
class NotifyFallbackTests(TransactionTestCase):
    """Outside a transaction (as in gunicorn / the workers) the outcome is known."""

    def setUp(self):
        send_alarm_email.result = True

    def test_queued_when_broker_is_up(self):
        with mock.patch("wareApp.tasks.send_notification.apply_async") as queue, \
                mock.patch.object(send_alarm_email, "result", True):
            self.assertIs(notifications.notify(send_alarm_email, "x"), True)
        queue.assert_called_once()

    def test_sent_directly_when_broker_is_down(self):
        sent = mock.Mock(return_value=True, __name__="send_alarm_email")
        with mock.patch("wareApp.tasks.send_notification.apply_async",
                        side_effect=KombuOperationalError("[Errno 111] Connection refused")):
            self.assertIs(notifications.notify(sent, "Alarm", 1, []), True)
        sent.assert_called_once_with("Alarm", 1, [])

    def test_direct_send_failure_is_reported(self):
        sent = mock.Mock(return_value=False, __name__="send_alarm_email")
        with mock.patch("wareApp.tasks.send_notification.apply_async",
                        side_effect=ConnectionRefusedError(111, "refused")):
            self.assertIs(notifications.notify(sent), False)



@override_settings(MQTT_ASYNC_NOTIFICATIONS=True)
class NotifyInTransactionTests(TestCase):
    def test_inside_transaction_hand_off_waits_for_commit(self):
        with mock.patch("wareApp.tasks.send_notification.apply_async") as queue:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    self.assertIsNone(notifications.notify(send_alarm_email, "x"))
                    queue.assert_not_called()
        queue.assert_called_once()


class OverheatEmailRetryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = Site.objects.create(site_name="Hot", site_type=1)

    def alert(self):
        return gateway_overheat.OverheatAlert(self.site.id, "3", 87.0, "-", "240")

    def test_unsent_email_is_retried_by_the_next_alert(self):
        with mock.patch.object(gateway_overheat, "notify", return_value=False) as notify:
            gateway_overheat.record_overheat(self.alert())
            cache.delete(f"gateway-overheat-store:{self.site.id}:3")  # store window passed
            gateway_overheat.record_overheat(self.alert())
        self.assertEqual(notify.call_count, 2)

    def test_sent_email_is_not_repeated_within_the_hour(self):
        with mock.patch.object(gateway_overheat, "notify", return_value=True) as notify:
            gateway_overheat.record_overheat(self.alert())
            cache.delete(f"gateway-overheat-store:{self.site.id}:3")
            gateway_overheat.record_overheat(self.alert())
        self.assertEqual(notify.call_count, 1)
