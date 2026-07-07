import re
import logging

from datetime import datetime

from wareApp.models import *

logger = logging.getLogger(__name__)


class RecoveryService:
    """
    Shared Recovery Service.

    This service is transport independent.

    MQTT
        ↓
    RecoveryService

    HTTP
        ↓
    RecoveryService
    """

    @staticmethod
    def process(site, location_id, msg_subtype, message):

        if "hourlyConsumption" in msg_subtype:
            return RecoveryService.process_hourly(site, location_id, message)

        elif "dailyConsumption" in msg_subtype:
            return RecoveryService.process_daily(site, location_id, message)

        elif "loadRuntime" in msg_subtype:
            return RecoveryService.process_runtime(site, location_id, message)

        return {"success": False, "reason": "Unknown recovery type"}

    @staticmethod
    def process_hourly(site, location_id, message):
        """
        Hourly Recovery

        (Implementation will be moved from tasks.py)
        """

        pass

    @staticmethod
    def process_daily(site, location_id, message):

        pass

    @staticmethod
    def process_runtime(site, location_id, message):

        pass
