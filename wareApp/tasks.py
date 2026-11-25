import logging
from functools import wraps
from threading import Lock

from celery.signals import worker_ready
from django.conf import settings
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
from wareApp.mqtt.services.failures import TRANSIENT_DB_ERRORS, record_dead_letter, run_with_db_retry
from warehouse.celery import app

logger = logging.getLogger(__name__)

_mqtt_start_lock = Lock()
_mqtt_start_dispatched = set()


def _run_mqtt_listener(listener, description):
    """Runs an MQTT listener until it stops; raises when it exits with an error so Celery logs it.

    Origin: Ashu
    """
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
    """Celery task: queue 1 MQTT listener (every type except LoadData).

    Origin: Ashu (changed from main)
    """
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
    """Celery task: queue 2 MQTT listener (LoadData only).

    Origin: Ashu (changed from main)
    """
    return _run_mqtt_listener(run_mqtt_client2, "Queue2")


def _task_is_active_or_reserved(task_name):
    """True when a task with this name is already running or waiting on some worker (so a second
    listener is not started).

    Origin: Ashu
    """
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
    """True when a worker's host name is the listener worker of a queue.

    Origin: Ashu
    """
    worker_name = hostname.partition("@")[0]
    return worker_name == worker_queue or worker_name.endswith(f".{worker_queue}")


def _consumed_queues(sender):
    """Queues this worker was started with (``-Q``), or None if unknown.

    Origin: Ashu
    """
    try:
        consume_from = sender.app.amqp.queues.consume_from
    except AttributeError:
        return None
    return set(consume_from) if consume_from else None


def _start_mqtt_client_for_worker(sender, worker_queue, task_name, description):
    """When the listener worker of a queue starts, queues its MQTT listener task once (not when it is
    already running).

    Origin: Ashu
    """
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
    """Worker-ready signal: starts the queue 1 listener on the queue1 worker.

    Origin: Ashu
    """
    _start_mqtt_client_for_worker(
        sender,
        worker_queue="queue1",
        task_name="wareApp.tasks.mqtt_client1",
        description="Queue1",
    )


@worker_ready.connect
def start_queue_two_mqtt_client(sender, **kwargs):
    """Worker-ready signal: starts the LoadData listener on the queue2 worker.

    Origin: Ashu
    """
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
    """Send one alarm email queued by ``wareApp.mqtt.services.notifications``.

    Origin: Ashu
    """
    if function_name not in ALLOWED_NOTIFICATIONS:
        logger.error("Rejected unknown notification function %r", function_name)
        return
    from wareApp import sendmail

    result = getattr(sendmail, function_name)(*args)
    if result is True:
        return f"{function_name}: email sent"
    if not result and result is not None:
        from wareApp.mqtt.services.notifications import remember_failed

        kept = remember_failed(function_name, args, result)
        return f"{function_name}: email FAILED{' (kept for retry)' if kept else ''} (see 'Email failed' log line)"
    return f"{function_name}: {result}"



def _site_for_queued_message(site_id, gateway_id, message_type):
    """Site of a queued packet (cached); None and a warning when the site doesn't exist.

    Origin: Ashu
    """
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

    Origin: Ashu
    """

    @wraps(task_handler)
    def wrapped(*args, **kwargs):
        """Runs the task with fresh database connections before and after, retrying once on a dropped
        connection.

        Origin: Ashu
        """
        close_old_connections()
        try:
            return run_with_db_retry(task_handler, *args, **kwargs)
        finally:
            close_old_connections()

    return wrapped


def _dispatch(message_type, message_subtype, site_id, gateway_id, message):
    """Run one queue-1 packet through its handler and return the outcome text.

    Origin: Ashu
    """
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
    """Runs a message handler for a queued packet; skips packets of unknown sites.

    Origin: Ashu
    """
    site = _site_for_queued_message(site_id, gateway_id, handler.name)
    if site is None:
        return f"skipped: unknown site {site_id}"
    return handler.handle(site, site_id, gateway_id, message)


# Merged from the colleague's code (54313d5, mqtt_pipeline/mqtt_pipeline/tasks/*_task.py), 2026-11-25:
# his acks_late + Celery retry, rebuilt on our RabbitMQ queues, with a dead letter after the last retry.
MQTT_PACKET_TASK_OPTIONS = {
    "bind": True,
    "acks_late": True,              # acknowledge after the packet is processed, not on receipt
    "reject_on_worker_lost": True,  # worker killed mid-task (restart, OOM): RabbitMQ delivers it again
}


def _retry_or_dead_letter(task, error, message_type, site_id, gateway_id, message):
    """Database still failing after the in-place retries: retry the task later (Celery retry,
    MQTT_TASK_RETRY_DELAY_SECONDS apart, at most MQTT_TASK_RETRY_MAX times), then keep the packet
    as a dead letter for replay_dead_letters instead of losing it.

    Origin: Ashu + Daksh (idea: acks_late / retry of his mqtt_pipeline tasks, 54313d5)
    """
    max_retries = getattr(settings, "MQTT_TASK_RETRY_MAX", 3)
    if task.request.retries < max_retries:
        logger.warning(
            "Database error on %s packet, task retry %s/%s: site=%s gateway=%s error=%s",
            message_type, task.request.retries + 1, max_retries, site_id, gateway_id, error,
        )
        raise task.retry(
            exc=error,
            countdown=getattr(settings, "MQTT_TASK_RETRY_DELAY_SECONDS", 10),
            max_retries=max_retries,
        )
    record_dead_letter(message_type, site_id, gateway_id, message, error, dedupe=False)
    return f"failed: {type(error).__name__} after {max_retries} task retries (dead letter)"


def _process_packet(task, message_type, message_subtype, site_id, gateway_id, message):
    """Run one packet through _dispatch; on a database error retry the task or keep a dead letter.

    Origin: Ashu + Daksh (idea: acks_late / retry of his mqtt_pipeline tasks, 54313d5)
    """
    try:
        return _dispatch(message_type, message_subtype, site_id, gateway_id, message)
    except TRANSIENT_DB_ERRORS as error:
        return _retry_or_dead_letter(task, error, message_type, site_id, gateway_id, message)


@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_mqtt_message(self, message_type, message_subtype, site_id, gateway_id, message):
    """Process one queue-1 gateway packet (all types; see mqtt/registry.py). Acknowledged only
    after processing; retried on a database error.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, message_type, message_subtype, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
@_with_database_connection_cleanup
def flush_consumption_batch():
    """Write the consumption packets collected since the last run in bulk.

    Origin: Ashu
    """
    from wareApp.mqtt import consumption_batch
    from wareApp.mqtt.handlers import publish_recovery_request

    return consumption_batch.flush(publish_recovery_request)


@app.task(queue="queue2_processing")
@_with_database_connection_cleanup
def check_gateway_health():
    """Raise / clear Meter Disconnected, Gateway Disconnected, Service / Modbus alarms.

    Origin: Ashu
    """
    from wareApp.mqtt.services import gateway_health

    # Test server: pings come from main's broker log (GATEWAY_PINGS_SSH).
    pings = gateway_health.fetch_remote_pings()
    prefix = f"pings updated={pings}; " if pings is not None else ""
    return f"gateway health: {prefix}{gateway_health.evaluate()}"


@app.task(queue="queue2_processing")
@_with_database_connection_cleanup
def close_resolved_alarms():
    """Close alarms that are no longer happening (services/alarm_closer.py).

    Origin: Ashu
    """
    from wareApp.mqtt.services import alarm_closer

    counts = alarm_closer.close_resolved()
    return "alarms closed: " + (", ".join(f"{k}={v}" for k, v in counts.items() if v) or "none")


@app.task(queue="queue2_processing")
@_with_database_connection_cleanup
def refresh_baseline_backfill(site_id, effective_from, legs=None):
    """Re-run a baseline setup's backfill (wareApp/baseline_setup.py) after the
    workers' baseline cache has expired, for hours stored in between.

    Origin: Ashu
    """
    from wareApp import baseline_setup
    from wareApp.models import Site

    site = Site.objects.filter(id=site_id).first()
    if site is None:
        return f"skipped: unknown site {site_id}"
    return f"baseline backfill site={site_id}: {baseline_setup.backfill(site, effective_from, legs)}"


@app.task(queue="notifications")
@_with_database_connection_cleanup
def retry_pending_emails():
    """Send failed alarm e-mails again (wareApp/mqtt/services/notifications.py).

    Origin: Ashu
    """
    from wareApp.mqtt.services.notifications import retry_pending

    return retry_pending()


@app.task(queue="queue2_processing")
@_with_database_connection_cleanup
def check_consumption_spikes():
    """Raise / update Consumption Spike alarms (type 17) for today and yesterday.

    Origin: Ashu
    """
    from wareApp.mqtt.services import spike_alarms

    return spike_alarms.scan()


@app.task(queue="queue2_processing")
@_with_database_connection_cleanup
def auto_spread_catch_ups():
    """Spread clear catch-up hours at night / on Sunday; e-mail the ones that need a manual spread.

    Origin: Ashu
    """
    from wareApp import catch_up_spread

    return catch_up_spread.auto_spread()


@_with_database_connection_cleanup
def _save_load_data(site_id, gateway_id, message):
    """Saves one LoadData packet and its roll-ups (our LoadData code, wareApp/load_data/).

    Origin: Ashu
    """
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


@app.task(queue="queue2_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_load_data_message(self, site_id, gateway_id, message):
    """Celery task (queue 2): saves a LoadData packet and its roll-ups. Acknowledged only after
    processing; retried on a database error, then kept as a dead letter. The LoadData logic is ours.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    try:
        return _save_load_data(site_id, gateway_id, message)
    except TRANSIENT_DB_ERRORS as error:
        return _retry_or_dead_letter(self, error, "LoadData", site_id, gateway_id, message)


# Per-type tasks queued by listeners deployed before process_mqtt_message.
# Kept registered so packets already waiting in RabbitMQ are still processed.
@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_supply_time_message(self, site_id, gateway_id, message):
    """Celery task: processes a SupplyTime packet.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, "SupplyTime", None, site_id, gateway_id, message)


@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_load_runtime_recovery_message(self, site_id, gateway_id, message):
    """Celery task: processes a loadRuntime recovery packet.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, "recovery", "loadRuntime", site_id, gateway_id, message)


@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_daily_consumption_recovery_message(self, site_id, gateway_id, message):
    """Celery task: processes a dailyConsumption recovery packet.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, "recovery", "dailyConsumption", site_id, gateway_id, message)


@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_hourly_consumption_recovery_message(self, site_id, gateway_id, message):
    """Celery task: processes an hourlyConsumption recovery packet.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, "recovery", "hourlyConsumption", site_id, gateway_id, message)


@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_fire_alarm_message(self, site_id, gateway_id, message):
    """Celery task: processes a FIREALARM packet.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, "FIREALARM", None, site_id, gateway_id, message)


@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_consumption_message(self, site_id, gateway_id, message):
    """Celery task: processes one consumption packet (when batching is off).

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, "consumption", None, site_id, gateway_id, message)


@app.task(queue="queue1_processing", **MQTT_PACKET_TASK_OPTIONS)
def process_load_message(self, site_id, gateway_id, message):
    """Celery task: processes a load packet.

    Origin: Ashu + Daksh (acks_late / retry idea from his mqtt_pipeline tasks, 54313d5)
    """
    return _process_packet(self, "load", None, site_id, gateway_id, message)
