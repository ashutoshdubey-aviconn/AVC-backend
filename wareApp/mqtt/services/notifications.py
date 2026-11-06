"""Send alarm emails outside the MQTT processing path.

Handlers call :func:`notify` instead of the ``wareApp.sendmail`` functions.
With ``MQTT_ASYNC_NOTIFICATIONS`` enabled the email is queued on the
``notifications`` Celery queue after the DB transaction commits, so a slow or
hanging SMTP server can no longer stall MQTT processing.
"""

import logging
from datetime import datetime, timedelta

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
        result = send_function(*args)
        remember_failed(name, args, result)
        return result

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
            remember_failed(name, args, outcome["delivered"])

    transaction.on_commit(enqueue)
    # Outside an atomic block on_commit runs immediately, so the outcome is known.
    return outcome.get("delivered")


# ---------------------------------------------------------------- retries
# Minutes until the next try after the 1st, 2nd, ... failure; the last value
# repeats until NOTIFICATION_RETRY_HOURS after the first failure.
RETRY_MINUTES = (5, 15, 30, 60, 120, 240, 480)
RETRY_BATCH = 20


def _summary(function_name, args):
    if function_name == "send_alarm_email" and args:
        return f"{args[0]} - site {args[1] if len(args) > 1 else '?'}"[:200]
    return function_name


def remember_failed(function_name, args, result, now=None):
    """Keep a failed alarm e-mail for a later retry; True when kept.

    Only for a passing failure (``sendmail.EmailFailure.transient``) of an
    allowed notification, and only while retries are on
    (NOTIFICATION_RETRY_HOURS > 0)."""
    from wareApp.models import PendingEmail

    if (
        result
        or not getattr(result, "transient", False)
        or function_name not in ALLOWED_NOTIFICATIONS
        or getattr(settings, "NOTIFICATION_RETRY_HOURS", 24) <= 0
    ):
        return False
    now = now or datetime.now()
    pending = PendingEmail.objects.create(
        function_name=function_name, args=list(args), summary=_summary(function_name, args),
        first_failed_at=now, next_try_at=now + timedelta(minutes=RETRY_MINUTES[0]),
        last_error=result.error,
    )
    logger.warning("Email kept for retry: id=%s %s (next try %s)", pending.id, pending.summary,
                   f"{pending.next_try_at:%H:%M}")
    return True


def retry_pending(now=None):
    """Send pending alarm e-mails that are due; returns a summary string.

    Stops at the first failure of a run (the mail server is still refusing;
    no need to try the others now). Gives an e-mail up after
    NOTIFICATION_RETRY_HOURS from its first failure.
    """
    from wareApp import sendmail
    from wareApp.models import PendingEmail

    now = now or datetime.now()
    limit = timedelta(hours=getattr(settings, "NOTIFICATION_RETRY_HOURS", 24))
    sent = failed = given_up = 0
    for pending in PendingEmail.objects.filter(next_try_at__lte=now).order_by("first_failed_at")[:RETRY_BATCH]:
        if pending.function_name not in ALLOWED_NOTIFICATIONS:
            pending.delete()
            continue
        result = getattr(sendmail, pending.function_name)(*pending.args)
        if result:
            logger.info("Email sent on retry %s: id=%s %s (first failed %s)", pending.attempts,
                        pending.id, pending.summary, f"{pending.first_failed_at:%d %b %H:%M}")
            pending.delete()
            sent += 1
            continue
        pending.attempts += 1
        pending.last_error = getattr(result, "error", str(result))[:300]
        if not getattr(result, "transient", False) or now - pending.first_failed_at >= limit:
            logger.error("Email given up after %s attempts: id=%s %s (first failed %s) error=%s",
                         pending.attempts, pending.id, pending.summary,
                         f"{pending.first_failed_at:%d %b %H:%M}", pending.last_error)
            pending.delete()
            given_up += 1
            continue
        delay = RETRY_MINUTES[min(pending.attempts - 1, len(RETRY_MINUTES) - 1)]
        pending.next_try_at = now + timedelta(minutes=delay)
        pending.save(update_fields=["attempts", "last_error", "next_try_at"])
        failed += 1
        break  # still refused: try the rest next run
    waiting = PendingEmail.objects.count()
    return f"email retries: sent={sent} failed={failed} given_up={given_up} waiting={waiting}"
