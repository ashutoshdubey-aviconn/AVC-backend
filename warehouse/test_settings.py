from .settings import *  # noqa: F401,F403

# Packet de-duplication is exercised by its own tests (override_settings);
# disabled here so unrelated tests may process the same sample payload twice.
MQTT_IDEMPOTENCY_TTL_SECONDS = 0
