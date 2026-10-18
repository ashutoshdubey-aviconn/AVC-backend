"""Persistent MQTT publisher for server-to-gateway commands.

``paho.mqtt.publish.single`` opens a TCP connection, performs the MQTT
handshake, publishes at QoS 0 and disconnects for *every* message. Recovery
requests are published from the processing workers many times per minute, so
each worker process keeps one connected client instead.
"""

import logging
import os
import threading

import paho.mqtt.client as mqtt
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


class MqttPublisher:
    """One background-connected paho client per worker process."""

    _instance = None
    _instance_pid = None
    _lock = threading.Lock()

    def __init__(self, host=None, port=None, client_factory=mqtt.Client):
        self.host = host or getattr(settings, "MQTT_BROKER_HOST", "127.0.0.1")
        self.port = port or getattr(settings, "MQTT_BROKER_PORT", 1883)
        self._client = client_factory(client_id=f"server-publisher-{os.getpid()}")
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.connect_async(self.host, self.port, 60)
        self._client.loop_start()

    @classmethod
    def get(cls):
        """Return this process's publisher, creating it after a fork if needed."""
        pid = os.getpid()
        with cls._lock:
            if cls._instance is None or cls._instance_pid != pid:
                cls._instance = cls()
                cls._instance_pid = pid
            return cls._instance

    def publish(self, topic, payload, qos=1):
        info = self._client.publish(topic, payload=payload, qos=qos, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            # With qos >= 1 paho keeps the message queued and sends it once the
            # connection is (re)established; log so a broker outage is visible.
            logger.warning(
                "MQTT publish queued without an active connection: topic=%s rc=%s",
                topic,
                info.rc,
            )
        return info


def publish_after_commit(topic, payload, qos=1):
    """Publish once the surrounding DB transaction commits (immediately if none)."""
    transaction.on_commit(lambda: MqttPublisher.get().publish(topic, payload, qos=qos))
