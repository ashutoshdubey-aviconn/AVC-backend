"""One inbound gateway packet as it travels from the listener to a handler."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from wareApp.mqtt.topics import parse_gateway_topic


def _payload_text(payload):
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)


@dataclass(frozen=True, slots=True)
class MqttEnvelope:
    topic: str
    site_id: int
    gateway_id: str
    message_type: str
    message_subtype: str
    payload: str
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_mqtt(cls, topic, payload):
        """Build an envelope from a raw topic; raises ``TopicParseError`` if malformed."""
        parsed = parse_gateway_topic(topic)
        return cls(
            topic=topic,
            site_id=parsed.site_id,
            gateway_id=parsed.gateway_id,
            message_type=parsed.message_type,
            message_subtype=parsed.message_subtype,
            payload=_payload_text(payload),
        )

    @property
    def message_id(self):
        """Stable id of the packet content (same topic + payload → same id)."""
        return hashlib.sha1(f"{self.topic}\n{self.payload}".encode()).hexdigest()

    @property
    def task_args(self):
        """Arguments of the ``process_*`` tasks: ``(site_id, gateway_id, payload)``."""
        return (self.site_id, self.gateway_id, self.payload)
