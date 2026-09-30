from dataclasses import dataclass


class TopicParseError(ValueError):
    """Raised when an MQTT topic does not match the gateway topic contract."""


@dataclass(frozen=True)
class GatewayTopic:
    site_id: int
    gateway_id: str
    message_type: str
    message_subtype: str


def parse_gateway_topic(topic: str) -> GatewayTopic:
    """Parse a gateway inbound MQTT topic into its stable routing fields."""
    segments = topic.split("/")

    if len(segments) < 8 or segments[1:3] != ["Acclivate", "iOmniControl"]:
        raise TopicParseError("unexpected gateway topic format")

    if segments[5] != "in":
        raise TopicParseError("gateway topic must be inbound")

    try:
        site_id = int(segments[3])
    except ValueError as error:
        raise TopicParseError("gateway topic site ID must be an integer") from error

    gateway_id = segments[4]
    message_type = segments[6].split("_", 1)[0]
    message_subtype = segments[7]
    if not gateway_id or not message_type or not message_subtype:
        raise TopicParseError("gateway topic contains an empty routing field")

    return GatewayTopic(
        site_id=site_id,
        gateway_id=gateway_id,
        message_type=message_type,
        message_subtype=message_subtype,
    )
