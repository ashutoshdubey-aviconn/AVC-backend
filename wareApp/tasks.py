import logging
from threading import Lock

from celery.signals import worker_ready
from paho.mqtt import publish as mqtt_publish

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

_queue_two_mqtt_start_lock = Lock()
_queue_two_mqtt_start_dispatched = False


@app.task(queue="queue1")
def mqtt_client1():
    return run_mqtt_client1()


@app.task(queue="queue2")
def mqtt_client2():
    return run_mqtt_client2()


def _task_is_active_or_reserved(task_name):
    try:
        inspector = app.control.inspect()
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
    except Exception:
        logger.warning("Unable to inspect Celery tasks before starting %s", task_name)
        return False

    return any(
        task.get("name") == task_name
        for tasks in (*active.values(), *reserved.values())
        for task in tasks
    )


@worker_ready.connect
def start_queue_two_mqtt_client(sender, **kwargs):
    hostname = str(getattr(sender, "hostname", ""))
    if "queue2" not in hostname:
        return

    task_name = "wareApp.tasks.mqtt_client2"
    global _queue_two_mqtt_start_dispatched
    with _queue_two_mqtt_start_lock:
        if _queue_two_mqtt_start_dispatched:
            logger.info("LoadData MQTT task has already been queued for this worker")
            return

        if _task_is_active_or_reserved(task_name):
            logger.info("LoadData MQTT task is already active or reserved")
            return

        app.send_task(task_name, queue="queue2")
        _queue_two_mqtt_start_dispatched = True
        logger.info("Queued LoadData MQTT task for worker %s", hostname)


def _publish_supply_time_recovery(topic, message):
    mqtt_publish.single(topic, payload=message, hostname="127.0.0.1", port=1883)


def _publish_consumption_recovery(topic, message):
    mqtt_publish.single(topic, payload=message, hostname="127.0.0.1", port=1883)


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
