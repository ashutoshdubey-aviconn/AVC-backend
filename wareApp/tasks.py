import logging
from threading import Lock

from celery.signals import worker_ready
from kombu.exceptions import KombuError
from paho.mqtt import publish as mqtt_publish
from paho.mqtt.client import MQTT_ERR_SUCCESS

from wareApp.load_data import handle_load_data_message
from wareApp.models import Site
from wareApp.mqtt.consumers import run_mqtt_client1, run_mqtt_client2
from wareApp.mqtt.consumption import handle_consumption_message
from wareApp.mqtt.daily_consumption_recovery import (
    handle_daily_consumption_recovery_message,
)
from wareApp.mqtt.fire_alarm import handle_fire_alarm_message
from wareApp.mqtt.hourly_consumption_recovery import (
    handle_hourly_consumption_recovery_message,
)
from wareApp.mqtt.load import handle_load_message
from wareApp.mqtt.load_runtime_recovery import handle_load_runtime_recovery_message
from wareApp.mqtt.supply_time import handle_supply_time_message
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


def _start_mqtt_client_for_worker(sender, worker_queue, task_name, description):
    hostname = str(getattr(sender, "hostname", ""))
    if not _is_listener_worker(hostname, worker_queue):
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


def _publish_supply_time_recovery(topic, message):
    mqtt_publish.single(topic, payload=message, hostname="127.0.0.1", port=1883)


def _publish_consumption_recovery(topic, message):
    mqtt_publish.single(topic, payload=message, hostname="127.0.0.1", port=1883)


@app.task(queue="queue2_processing")
def process_load_data_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued LoadData for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_load_data_message(
        None,
        site,
        site_id,
        gateway_id,
        message,
        ["LoadData"],
    )


@app.task(queue="queue1_processing")
def process_supply_time_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued SupplyTime for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_supply_time_message(
        None,
        site,
        site_id,
        gateway_id,
        message,
        publish_recovery=_publish_supply_time_recovery,
    )


@app.task(queue="queue1_processing")
def process_load_runtime_recovery_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued loadRuntime recovery for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_load_runtime_recovery_message(site, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_daily_consumption_recovery_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued dailyConsumption recovery for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_daily_consumption_recovery_message(site, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_hourly_consumption_recovery_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued hourlyConsumption recovery for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_hourly_consumption_recovery_message(site, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_fire_alarm_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued FIREALARM for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_fire_alarm_message(site, site_id, gateway_id, message)


@app.task(queue="queue1_processing")
def process_consumption_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued consumption for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_consumption_message(
        site,
        site_id,
        gateway_id,
        message,
        publish_recovery=_publish_consumption_recovery,
    )


@app.task(queue="queue1_processing")
def process_load_message(site_id, gateway_id, message):
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        logger.warning(
            "Ignoring queued load message for missing site %s from gateway %s",
            site_id,
            gateway_id,
        )
        return

    handle_load_message(site, site_id, gateway_id, message)
