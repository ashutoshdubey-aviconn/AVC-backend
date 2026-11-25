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
    """Publish a gateway sync request once the current transaction commits.

    Origin: Ashu
    """
    publish_after_commit(topic, message)


class MessageHandler:
    """One gateway message type.

    ``name``    label used in logs and as the duplicate-check family.
    ``dedupe``  skip packets already processed (see services/idempotency.py;
                only consumption is safe to de-duplicate by payload).

    Origin: Ashu
    """

    name = ""
    dedupe = False

    def handle(self, site, site_id, gateway_id, message):
        """Processes one packet; each message type's handler implements it.

        Origin: Ashu
        """
        raise NotImplementedError

    def __repr__(self):
        """Handler name for logs.

        Origin: Ashu
        """
        return f"<{type(self).__name__} {self.name}>"


class ConsumptionHandler(MessageHandler):
    """Handler for consumption packets (duplicate packets skipped).

    Origin: Ashu
    """
    name = "consumption"
    dedupe = True

    def handle(self, site, site_id, gateway_id, message):
        """Saves a consumption packet and asks for recovery when it finds a gap.

        Origin: Ashu
        """
        return handle_consumption_message(
            site, site_id, gateway_id, message, publish_recovery=publish_recovery_request
        )


class SupplyTimeHandler(MessageHandler):
    """Handler for SupplyTime packets (run time per power source).

    Origin: Ashu
    """
    name = "SupplyTime"

    def handle(self, site, site_id, gateway_id, message):
        """Saves a SupplyTime packet and asks for recovery when hours are missing.

        Origin: Ashu
        """
        return handle_supply_time_message(
            None, site, site_id, gateway_id, message, publish_recovery=publish_recovery_request
        )


class LoadHandler(MessageHandler):
    """Handler for load packets (voltage, power factor, power source status).

    Origin: Ashu
    """
    name = "load"

    def handle(self, site, site_id, gateway_id, message):
        """Saves a load packet and raises voltage / power factor / DG alarms.

        Origin: Ashu
        """
        return handle_load_message(site, site_id, gateway_id, message)


class FireAlarmHandler(MessageHandler):
    """Handler for FIREALARM packets.

    Origin: Ashu
    """
    name = "FIREALARM"

    def handle(self, site, site_id, gateway_id, message):
        """Saves a fire pump packet and sends the fire alarm e-mails.

        Origin: Ashu
        """
        return handle_fire_alarm_message(site, site_id, gateway_id, message)


class HourlyConsumptionRecoveryHandler(MessageHandler):
    """Handler for recovery/hourlyConsumption packets (missed hours sent again).

    Origin: Ashu
    """
    name = "recovery/hourlyConsumption"

    def handle(self, site, site_id, gateway_id, message):
        """Writes the recovered hours of an aisle.

        Origin: Ashu
        """
        return handle_hourly_consumption_recovery_message(site, site_id, gateway_id, message)


class DailyConsumptionRecoveryHandler(MessageHandler):
    """Handler for recovery/dailyConsumption packets (missed days sent again).

    Origin: Ashu
    """
    name = "recovery/dailyConsumption"

    def handle(self, site, site_id, gateway_id, message):
        """Writes the recovered days of an aisle.

        Origin: Ashu
        """
        return handle_daily_consumption_recovery_message(site, site_id, gateway_id, message)


class LoadRuntimeRecoveryHandler(MessageHandler):
    """Handler for recovery/loadRuntime packets (missed run time sent again).

    Origin: Ashu
    """
    name = "recovery/loadRuntime"

    def handle(self, site, site_id, gateway_id, message):
        """Writes the recovered run time of a power source.

        Origin: Ashu
        """
        return handle_load_runtime_recovery_message(site, site_id, gateway_id, message)
