"""Which processing task handles which gateway message type.

``recovery`` packets are dispatched on their subtype; every other queue-1 type
on the type alone. Tasks are looked up by name on ``wareApp.tasks`` so this
module stays importable without Celery.
"""

QUEUE_ONE_TASK_NAMES = {
    "consumption": "process_consumption_message",
    "FIREALARM": "process_fire_alarm_message",
    "load": "process_load_message",
    "SupplyTime": "process_supply_time_message",
}
RECOVERY_TASK_NAMES = {
    "dailyConsumption": "process_daily_consumption_recovery_message",
    "hourlyConsumption": "process_hourly_consumption_recovery_message",
    "loadRuntime": "process_load_runtime_recovery_message",
}


def task_name_for(message_type, message_subtype):
    """Return the processing task name, or ``None`` when nothing handles the type."""
    if message_type == "recovery":
        return RECOVERY_TASK_NAMES.get(message_subtype)
    return QUEUE_ONE_TASK_NAMES.get(message_type)


def processing_task_for(message_type, message_subtype):
    """Return the Celery task object for a message, or ``None``."""
    from wareApp import tasks

    task_name = task_name_for(message_type, message_subtype)
    return getattr(tasks, task_name) if task_name else None
