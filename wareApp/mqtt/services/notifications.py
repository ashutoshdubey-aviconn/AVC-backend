"""Send alarm emails outside the MQTT processing path.

Handlers call :func:`notify` instead of the ``wareApp.sendmail`` functions.
With ``MQTT_ASYNC_NOTIFICATIONS`` enabled the email is queued on the
``notifications`` Celery queue after the DB transaction commits, so a slow or
hanging SMTP server can no longer stall MQTT processing.
"""

import logging

from django.conf import settings
from django.db import transaction
from kombu.exceptions import KombuError

# Broker not reachable / refused / timed out while publishing.
QUEUE_ERRORS = (KombuError, OSError)

logger = logging.getLogger(__name__)

# Only these wareApp.sendmail functions may be invoked by name from the queue.
ALLOWED_NOTIFICATIONS = frozenset(
    {
        "send_alarm_for_high_voltage",
        "send_alarm_for_low_voltage",
        "send_mail_for_pf_fluctuation",
        "send_mail_fire_alarm_user",
        "send_alarm_email",
    }
)


def notify(send_function, *args):
    """Deliver ``send_function(*args)`` now, or via the notifications queue.

    Returns True when the e-mail was handed to the queue (the worker retries
    it), otherwise the send function's own result (True / False). When the
    queue is unavailable (RabbitMQ down or still starting) the e-mail is sent
    directly instead of being lost. Inside an open transaction the hand-off
    happens after commit and None is returned (outcome not known yet).
    """
    name = getattr(send_function, "__name__", None)
    if not getattr(settings, "MQTT_ASYNC_NOTIFICATIONS", False) or (
        name not in ALLOWED_NOTIFICATIONS
    ):
        return send_function(*args)

    outcome = {}

    def enqueue():
        from wareApp.tasks import send_notification

        try:
            send_notification.apply_async(args=(name, list(args)), queue="notifications")
            outcome["delivered"] = True
        except QUEUE_ERRORS as error:
            logger.warning(
                "Notification queue unavailable (%s: %s); sending %s directly",
                type(error).__name__,
                error,
                name,
            )
            outcome["delivered"] = send_function(*args)

    transaction.on_commit(enqueue)
    # Outside an atomic block on_commit runs immediately, so the outcome is known.
    return outcome.get("delivered")
