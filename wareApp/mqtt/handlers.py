"""Queue-1 message handlers: one class per gateway message type.

Each handler wraps the existing ``handle_*`` function unchanged and declares
what the processing task needs to know about it (its label for logs and dead
letters, and whether duplicate packets are skipped). ``registry.py`` maps a
topic's type/subtype to one of these instances.
"""

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
from wareApp.mqtt.services.publisher import publish_after_commit
from wareApp.mqtt.supply_time import handle_supply_time_message


def publish_recovery_request(topic, message):
    """Publish a gateway sync request once the current transaction commits."""
    publish_after_commit(topic, message)


class MessageHandler:
    """One gateway message type.

    ``name``    label used in logs and as the duplicate-check family.
    ``dedupe``  skip packets already processed (see services/idempotency.py;
                only consumption is safe to de-duplicate by payload).
    """

    name = ""
    dedupe = False

    def handle(self, site, site_id, gateway_id, message):
        raise NotImplementedError

    def __repr__(self):
        return f"<{type(self).__name__} {self.name}>"


class ConsumptionHandler(MessageHandler):
    name = "consumption"
    dedupe = True

    def handle(self, site, site_id, gateway_id, message):
        return handle_consumption_message(
            site, site_id, gateway_id, message, publish_recovery=publish_recovery_request
        )


class SupplyTimeHandler(MessageHandler):
    name = "SupplyTime"

    def handle(self, site, site_id, gateway_id, message):
        return handle_supply_time_message(
            None, site, site_id, gateway_id, message, publish_recovery=publish_recovery_request
        )


class LoadHandler(MessageHandler):
    name = "load"

    def handle(self, site, site_id, gateway_id, message):
        return handle_load_message(site, site_id, gateway_id, message)


class FireAlarmHandler(MessageHandler):
    name = "FIREALARM"

    def handle(self, site, site_id, gateway_id, message):
        return handle_fire_alarm_message(site, site_id, gateway_id, message)


class HourlyConsumptionRecoveryHandler(MessageHandler):
    name = "recovery/hourlyConsumption"

    def handle(self, site, site_id, gateway_id, message):
        return handle_hourly_consumption_recovery_message(site, site_id, gateway_id, message)


class DailyConsumptionRecoveryHandler(MessageHandler):
    name = "recovery/dailyConsumption"

    def handle(self, site, site_id, gateway_id, message):
        return handle_daily_consumption_recovery_message(site, site_id, gateway_id, message)


class LoadRuntimeRecoveryHandler(MessageHandler):
    name = "recovery/loadRuntime"

    def handle(self, site, site_id, gateway_id, message):
        return handle_load_runtime_recovery_message(site, site_id, gateway_id, message)
