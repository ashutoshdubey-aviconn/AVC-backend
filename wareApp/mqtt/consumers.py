import logging

import paho.mqtt.client as mqtt
from django.conf import settings

from wareApp.mqtt.registry import is_handled
from wareApp.mqtt.routing import (
    QUEUE_ONE_MESSAGE_TYPES,
    QUEUE_ONE_SUBSCRIPTIONS,
    QUEUE_TWO_SUBSCRIPTIONS,
    processing_queue_for_site,
    subscribe,
)
from wareApp.mqtt.envelope import MqttEnvelope
from wareApp.mqtt.topics import TopicParseError

logger = logging.getLogger(__name__)


def _queue_one_message_for_processing(site_id, gateway_id, message, topic):
    """``topic`` is anything with ``message_type`` / ``message_subtype`` (an envelope)."""
    if not is_handled(topic.message_type, topic.message_subtype):
        logger.info(
            "Ignoring queue1 message without a processing handler: type=%s subtype=%s "
            "site=%s gateway=%s",
            topic.message_type,
            topic.message_subtype,
            site_id,
            gateway_id,
        )
        return False

    from wareApp import tasks

    tasks.process_mqtt_message.apply_async(
        args=(topic.message_type, topic.message_subtype, site_id, gateway_id, message),
        queue=processing_queue_for_site(site_id),
    )
    logger.debug(
        "Queued %s%s for site %s from gateway %s",
        topic.message_type,
        f"/{topic.message_subtype}" if topic.message_type == "recovery" else "",
        site_id,
        gateway_id,
    )
    return True


def _run_isolated_mqtt_client(client_id, subscriptions, description, on_message):
    def on_connect(client, userdata, flags, rc):
        if rc:
            logger.error("%s MQTT connection rejected: rc=%s", description, rc)
            return

        subscribe(client, subscriptions)
        logger.info("%s MQTT connected", description)

    # clean_session=False: the broker keeps this listener's subscriptions and
    # queues its messages while it is disconnected (restart, deploy, crash).
    client = mqtt.Client(client_id, clean_session=False)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(
        getattr(settings, "MQTT_BROKER_HOST", "127.0.0.1"),
        getattr(settings, "MQTT_BROKER_PORT", 1883),
        60,
    )
    logger.info("%s MQTT client started", description)
    return client.loop_forever(retry_first_connection=True)


def run_mqtt_client1():
    """Run the isolated queue1 MQTT consumer."""

    def on_message(client, userdata, msg):
        try:
            envelope = MqttEnvelope.from_mqtt(msg.topic, msg.payload)
            if envelope.message_type not in QUEUE_ONE_MESSAGE_TYPES:
                logger.warning("Ignoring unexpected queue1 topic: %s", msg.topic)
                return

            _queue_one_message_for_processing(
                envelope.site_id, envelope.gateway_id, envelope.payload, envelope
            )
        except TopicParseError as error:
            logger.warning("Ignoring malformed queue1 topic %r: %s", msg.topic, error)
        except Exception:
            logger.exception("Failed to queue queue1 message from topic %s", msg.topic)

    return _run_isolated_mqtt_client(
        getattr(settings, "MQTT_QUEUE1_CLIENT_ID", "server_paho_client_1"),
        QUEUE_ONE_SUBSCRIPTIONS,
        "Queue1",
        on_message,
    )


def run_mqtt_client2():
    """Run the isolated LoadData MQTT consumer for queue2."""

    def on_message(client, userdata, msg):
        envelope = None
        try:
            envelope = MqttEnvelope.from_mqtt(msg.topic, msg.payload)
            if envelope.message_type != "LoadData":
                logger.warning("Ignoring unexpected queue2 topic: %s", msg.topic)
                return

            from wareApp import tasks

            tasks.process_load_data_message.apply_async(
                args=envelope.task_args,
                queue="queue2_processing",
            )
            logger.debug(
                "Queued LoadData for site %s from gateway %s",
                envelope.site_id,
                envelope.gateway_id,
            )
        except TopicParseError as error:
            logger.warning("Ignoring malformed LoadData topic %r: %s", msg.topic, error)
        except Exception:
            logger.exception(
                "Failed to queue LoadData for site %s from gateway %s",
                envelope.site_id if envelope else "unknown",
                envelope.gateway_id if envelope else "unknown",
            )

    return _run_isolated_mqtt_client(
        getattr(settings, "MQTT_QUEUE2_CLIENT_ID", "server_paho_client_2"),
        QUEUE_TWO_SUBSCRIPTIONS,
        "Queue2 LoadData",
        on_message,
    )
