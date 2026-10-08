import logging

from paho.mqtt import publish as mqtt_publish

logger = logging.getLogger(__name__)

REMOTE_ACCESS_ACTIONS = frozenset({"start", "stop", "restart"})


def request_remote_access(
    site_id,
    gateway_id,
    action,
    retry_count=0,
    publish_command=mqtt_publish.single,
):
    """Publish a remote-access command for the gateway agent to execute."""
    if isinstance(site_id, bool) or not isinstance(site_id, int) or site_id <= 0:
        raise ValueError("Remote access site_id must be a positive integer")
    if (
        not isinstance(gateway_id, str)
        or not gateway_id
        or gateway_id.strip() != gateway_id
        or any(character in gateway_id for character in "/#+")
    ):
        raise ValueError("Remote access gateway_id must be one MQTT topic segment")
    if action not in REMOTE_ACCESS_ACTIONS:
        raise ValueError(f"Unsupported remote access action: {action!r}")
    if (
        isinstance(retry_count, bool)
        or not isinstance(retry_count, int)
        or retry_count < 0
    ):
        raise ValueError("Remote access retry_count must be a non-negative integer")

    topic = f"/Acclivate/iOmniControl/{site_id}/{gateway_id}/in/remoteAccess/state"
    payload = f"{action}_{retry_count}"
    publish_command(
        topic,
        payload=payload,
        hostname="127.0.0.1",
        port=1883,
        qos=1,
        retain=False,
    )
    logger.info(
        "Published remote access command %s for site %s gateway %s",
        action,
        site_id,
        gateway_id,
    )
