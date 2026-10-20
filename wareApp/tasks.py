import logging
from functools import wraps
from threading import Lock

from celery.signals import worker_ready
from django.db import close_old_connections
from kombu.exceptions import KombuError
from paho.mqtt.client import MQTT_ERR_SUCCESS

from wareApp.load_data import handle_load_data_message
from wareApp.models import Site
from wareApp.mqtt.consumers import run_mqtt_client1, run_mqtt_client2
from wareApp.mqtt.registry import handler_for
from wareApp.mqtt.services.notifications import ALLOWED_NOTIFICATIONS
from wareApp.mqtt.services import idempotency
from wareApp.mqtt.services import site_cache as site_config
from wareApp.mqtt.services.failures import run_with_db_retry
from warehouse.celery import app

logger = logging.getLogger(__name__)

_mqtt_start_lock = Lock()
_mqtt_start_dispatched = set()


def _run_mqtt_listener(listener, description):
    result = listener()
    if result not in (None, MQTT_ERR_SUCCESS):
        raise RuntimeError(f"{description} MQTT listener exited with status {result}")
    return result


@app.task(
    queue="queue1",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=False,
    max_retries=None,
)
def mqtt_client1():
    return _run_mqtt_listener(run_mqtt_client1, "Queue1")


@app.task(
    queue="queue2",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=False,
    max_retries=None,
)
def mqtt_client2():
    return _run_mqtt_listener(run_mqtt_client2, "Queue2")


def _task_is_active_or_reserved(task_name):
    try:
        inspector = app.control.inspect()
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
    except KombuError:
        logger.warning("Unable to inspect Celery tasks before starting %s", task_name)
        return None

    return any(
        task.get("name") == task_name
        for tasks in (*active.values(), *reserved.values())
        for task in tasks
    )


def _is_listener_worker(hostname, worker_queue):
    worker_name = hostname.partition("@")[0]
    return worker_name == worker_queue or worker_name.endswith(f".{worker_queue}")


def _consumed_queues(sender):
    """Queues this worker was started with (``-Q``), or None if unknown."""
    try:
        consume_from = sender.app.amqp.queues.consume_from
    except AttributeError:
        return None
    return set(consume_from) if consume_from else None


def _start_mqtt_client_for_worker(sender, worker_queue, task_name, description):
    hostname = str(getattr(sender, "hostname", ""))
    # Only the worker that consumes the listener queue starts the listener. The
    # hostname check alone also matched processing workers named e.g.
    # "processing.queue1", which queued a second listener task.
    consumed = _consumed_queues(sender)
    if consumed is not None:
        if worker_queue not in consumed:
            return
    elif not _is_listener_worker(hostname, worker_queue):
        return

    with _mqtt_start_lock:
        if task_name in _mqtt_start_dispatched:
            logger.info(
                "%s MQTT task has already been queued for this worker", description
            )
            return

        task_is_active = _task_is_active_or_reserved(task_name)
        if task_is_active is None:
            logger.warning(
                "Deferring %s MQTT startup until task inspection succeeds", description
            )
            return

        if task_is_active:
            logger.info("%s MQTT task is already active or reserved", description)
            return

        app.send_task(task_name, queue=worker_queue)
        _mqtt_start_dispatched.add(task_name)
        logger.info("Queued %s MQTT task for worker %s", description, hostname)


@worker_ready.connect
def start_queue_one_mqtt_client(sender, **kwargs):
    _start_mqtt_client_for_worker(
        sender,
        worker_queue="queue1",
        task_name="wareApp.tasks.mqtt_client1",
        description="Queue1",
    )


@worker_ready.connect
def start_queue_two_mqtt_client(sender, **kwargs):
    _start_mqtt_client_for_worker(
        sender,
        worker_queue="queue2",
        task_name="wareApp.tasks.mqtt_client2",
        description="LoadData",
    )


@app.task(
    queue="notifications",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
)
def send_notification(function_name, args):
    """Send one alarm email queued by ``wareApp.mqtt.services.notifications``."""
    if function_name not in ALLOWED_NOTIFICATIONS:
        logger.error("Rejected unknown notification function %r", function_name)
        return
    from wareApp import sendmail

    result = getattr(sendmail, function_name)(*args)
    if result is True:
        return f"{function_name}: email sent"
    if result is False:
        return f"{function_name}: email FAILED (see 'Email failed' log line)"
    return f"{function_name}: {result}"


def _site_for_queued_message(site_id, gateway_id, message_type):
    try:
        return site_config.site(site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued %s for missing site %s from gateway %s",
            message_type,
            site_id,
            gateway_id,
        )
        return None


def _with_database_connection_cleanup(task_handler):
    """Fresh DB connection per task; transient DB errors retried in place.

    Handlers re-raise only transient database errors (everything else is
    stored as an MqttDeadLetter). Retrying inside the task keeps the packet in
    its place in the site's queue instead of re-queueing it behind newer ones.
    """

    @wraps(task_handler)
    def wrapped(*args, **kwargs):
        close_old_connections()
        try:
            return run_with_db_retry(task_handler, *args, **kwargs)
        finally:
            close_old_connections()

    return wrapped


def _dispatch(message_type, message_subtype, site_id, gateway_id, message):
    """Run one queue-1 packet through its handler and return the outcome text."""
    handler = handler_for(message_type, message_subtype)
    if handler is None:
        logger.warning(
            "Ignoring queued packet without a handler: type=%s subtype=%s site=%s gateway=%s",
            message_type,
            message_subtype,
            site_id,
            gateway_id,
        )
        return f"skipped: no handler for {message_type}/{message_subtype}"

    key = None
    if handler.dedupe:
        key = idempotency.claim(handler.name, site_id, gateway_id, message)
        if key is None:
            logger.info(
                "Skipped duplicate %s packet: site=%s gateway=%s",
                handler.name,
                site_id,
                gateway_id,
            )
            return f"skipped: duplicate {handler.name} packet (already processed)"
    try:
        return _run_handler(handler, site_id, gateway_id, message)
    except BaseException:
        if key is not None:
            idempotency.release(key)
        raise


@_with_database_connection_cleanup
def _run_handler(handler, site_id, gateway_id, message):
    site = _site_for_queued_message(site_id, gateway_id, handler.name)
    if site is None:
        return f"skipped: unknown site {site_id}"
    return handler.handle(site, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_mqtt_message(message_type, message_subtype, site_id, gateway_id, message):
    """Process one queue-1 gateway packet (all types; see mqtt/registry.py)."""
    return _dispatch(message_type, message_subtype, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
@_with_database_connection_cleanup
def flush_consumption_batch():
    """Write the consumption packets collected since the last run in bulk."""
    from wareApp.mqtt import consumption_batch
    from wareApp.mqtt.handlers import publish_recovery_request

    return consumption_batch.flush(publish_recovery_request)


@app.task(queue="queue2_processing")
@_with_database_connection_cleanup
def process_load_data_message(site_id, gateway_id, message):
    site = _site_for_queued_message(site_id, gateway_id, "LoadData")
    if site is None:
        return f"skipped: unknown site {site_id}"

    return handle_load_data_message(
        None,
        site,
        site_id,
        gateway_id,
        message,
        ["LoadData"],
    )


# Per-type tasks queued by listeners deployed before process_mqtt_message.
# Kept registered so packets already waiting in RabbitMQ are still processed.
@app.task(queue="queue1_processing")
def process_supply_time_message(site_id, gateway_id, message):
    return _dispatch("SupplyTime", None, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_load_runtime_recovery_message(site_id, gateway_id, message):
    return _dispatch("recovery", "loadRuntime", site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_daily_consumption_recovery_message(site_id, gateway_id, message):
    return _dispatch("recovery", "dailyConsumption", site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_hourly_consumption_recovery_message(site_id, gateway_id, message):
    return _dispatch("recovery", "hourlyConsumption", site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_fire_alarm_message(site_id, gateway_id, message):
    return _dispatch("FIREALARM", None, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_consumption_message(site_id, gateway_id, message):
    return _dispatch("consumption", None, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_load_message(site_id, gateway_id, message):
    return _dispatch("load", None, site_id, gateway_id, message)
