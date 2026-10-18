"""Failure handling shared by the MQTT handlers and processing tasks.

* Transient database errors (connection dropped, server restarting) are
  re-raised by the handlers so the processing task can retry the packet.
  The retry happens inside the task, not by re-queueing, because a re-queued
  packet would land behind newer packets of the same site and could
  overwrite an hour with an older total.
* Every other failure is stored as an ``MqttDeadLetter`` row (topic type,
  site, gateway, payload, error) so it can be inspected and replayed, instead
  of existing only as a log line.
"""

import logging
import time

from django.db import InterfaceError, OperationalError, close_old_connections

logger = logging.getLogger(__name__)

TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError)
DB_RETRY_DELAYS = (0.5, 1.0, 2.0)
MAX_DEAD_LETTER_PAYLOAD = 20000


DEAD_LETTER_DEDUPE_SECONDS = 600


def record_dead_letter(message_type, site_id, gateway_id, payload, error):
    """Store a packet that could not be processed. Never raises.

    The same error from the same gateway (e.g. an aisle group missing from
    the configuration, repeated on every packet) is stored once per
    ``DEAD_LETTER_DEDUPE_SECONDS``.
    """
    from django.core.cache import cache

    from wareApp.models import MqttDeadLetter

    try:
        dedupe_key = (
            f"mqtt:dead-letter:{message_type}:{site_id}:{gateway_id}:"
            f"{type(error).__name__}:{str(error)[:100]}"
        )
        if not cache.add(dedupe_key, 1, DEAD_LETTER_DEDUPE_SECONDS):
            return
        MqttDeadLetter.objects.create(
            message_type=str(message_type)[:50],
            site_id=site_id if isinstance(site_id, int) else None,
            gateway_id=str(gateway_id or "")[:200],
            payload=str(payload)[:MAX_DEAD_LETTER_PAYLOAD],
            error=f"{type(error).__name__}: {error}"[:2000],
        )
    except Exception:
        logger.exception(
            "Could not store MQTT dead letter: type=%s site=%s gateway=%s",
            message_type,
            site_id,
            gateway_id,
        )


def run_with_db_retry(function, *args, delays=DB_RETRY_DELAYS, sleep=None, **kwargs):
    """Run ``function``; on a transient DB error reconnect and retry in place."""
    sleep = sleep or time.sleep
    for attempt, delay in enumerate((*delays, None)):
        try:
            return function(*args, **kwargs)
        except TRANSIENT_DB_ERRORS:
            if delay is None:
                raise
            logger.warning(
                "Transient database error, retrying in %ss (attempt %s)",
                delay,
                attempt + 1,
                exc_info=True,
            )
            close_old_connections()
            sleep(delay)
