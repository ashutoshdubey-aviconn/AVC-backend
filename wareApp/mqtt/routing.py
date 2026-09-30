from collections.abc import Iterable

from wareApp.mqtt.topics import GatewayTopic, parse_gateway_topic


QUEUE_ONE = "queue1"
QUEUE_TWO = "queue2"

QUEUE_ONE_MESSAGE_TYPES = frozenset(
    {
        "consumption",
        "sync",
        "FIREALARM",
        "load",
        "SupplyTime",
        "recovery",
        "remoteAccess",
    }
)
QUEUE_TWO_MESSAGE_TYPES = frozenset({"LoadData"})

MQTT_TOPIC_PREFIX = "/Acclivate/iOmniControl/+/+/in"
QUEUE_ONE_SUBSCRIPTIONS = tuple(
    f"{MQTT_TOPIC_PREFIX}/{message_type}/#"
    for message_type in sorted(QUEUE_ONE_MESSAGE_TYPES)
)
QUEUE_TWO_SUBSCRIPTIONS = tuple(
    f"{MQTT_TOPIC_PREFIX}/{message_type}/#"
    for message_type in sorted(QUEUE_TWO_MESSAGE_TYPES)
)


def queue_for_gateway_topic(topic: str) -> str | None:
    """Return the one consumer queue responsible for a valid gateway topic."""
    return queue_for_parsed_topic(parse_gateway_topic(topic))


def queue_for_parsed_topic(topic: GatewayTopic) -> str | None:
    if topic.message_type in QUEUE_ONE_MESSAGE_TYPES:
        return QUEUE_ONE
    if topic.message_type in QUEUE_TWO_MESSAGE_TYPES:
        return QUEUE_TWO
    return None


def subscribe(client, topics: Iterable[str]) -> None:
    """Subscribe a Paho client to every topic assigned to its queue."""
    for topic in topics:
        client.subscribe(topic)