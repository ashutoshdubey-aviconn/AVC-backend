import logging

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

    Origin: Ashu
    """

    @staticmethod
    def process(site, location_id, msg_subtype, message):

        """Sends an HTTP recovery upload to the hourly, daily or run-time handler by its subtype.

        Origin: Ashu
        """
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

        Origin: Ashu
        """

        pass

    @staticmethod
    def process_daily(site, location_id, message):

        """Daily recovery over HTTP: not built yet (does nothing).

        Origin: Ashu
        """
        pass

    @staticmethod
    def process_runtime(site, location_id, message):

        """Run-time recovery over HTTP: not built yet (does nothing).

        Origin: Ashu
        """
        pass
