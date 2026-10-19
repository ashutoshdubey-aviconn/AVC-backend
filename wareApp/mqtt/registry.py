"""Which handler processes which queue-1 gateway message.

``recovery`` packets are dispatched on their subtype; every other queue-1 type
on the type alone. Handlers are created lazily so this module stays cheap to
import (the listener only needs to know whether a type is handled).
"""

from functools import lru_cache

QUEUE_ONE_HANDLER_NAMES = {
    "consumption": "ConsumptionHandler",
    "FIREALARM": "FireAlarmHandler",
    "load": "LoadHandler",
    "SupplyTime": "SupplyTimeHandler",
}
RECOVERY_HANDLER_NAMES = {
    "dailyConsumption": "DailyConsumptionRecoveryHandler",
    "hourlyConsumption": "HourlyConsumptionRecoveryHandler",
    "loadRuntime": "LoadRuntimeRecoveryHandler",
}

# Per-type Celery tasks kept registered while messages queued by an older
# listener may still be waiting in RabbitMQ (see wareApp/tasks.py).
LEGACY_TASK_NAMES = {
    ("consumption", None): "process_consumption_message",
    ("FIREALARM", None): "process_fire_alarm_message",
    ("load", None): "process_load_message",
    ("SupplyTime", None): "process_supply_time_message",
    ("recovery", "dailyConsumption"): "process_daily_consumption_recovery_message",
    ("recovery", "hourlyConsumption"): "process_hourly_consumption_recovery_message",
    ("recovery", "loadRuntime"): "process_load_runtime_recovery_message",
}


def _handler_name(message_type, message_subtype):
    if message_type == "recovery":
        return RECOVERY_HANDLER_NAMES.get(message_subtype)
    return QUEUE_ONE_HANDLER_NAMES.get(message_type)


def is_handled(message_type, message_subtype):
    """True when a queue-1 handler exists for this type/subtype."""
    return _handler_name(message_type, message_subtype) is not None


@lru_cache(maxsize=None)
def _handler(name):
    from wareApp.mqtt import handlers

    return getattr(handlers, name)()


def handler_for(message_type, message_subtype):
    """Return the handler instance for a message, or ``None``."""
    name = _handler_name(message_type, message_subtype)
    return _handler(name) if name else None
