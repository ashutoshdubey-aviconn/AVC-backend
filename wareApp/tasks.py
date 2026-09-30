import logging

from paho.mqtt import publish as mqtt_publish

from warehouse.celery import app
from wareApp.models import Site
from wareApp.mqtt.consumers import run_mqtt_client1, run_mqtt_client2
from wareApp.mqtt.supply_time import handle_supply_time_message


logger = logging.getLogger(__name__)


@app.task(queue="queue1")
def mqtt_client1():
    return run_mqtt_client1()


@app.task(queue="queue2")
def mqtt_client2():
    return run_mqtt_client2()


def _publish_supply_time_recovery(topic, message):
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
