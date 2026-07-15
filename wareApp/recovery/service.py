import logging
import threading

from .processor import process_http_recovery

from queue import Queue

logger = logging.getLogger(__name__)


recovery_queue = Queue(maxsize=5000)  # Limit the queue size to prevent memory issues

working_running = False  # Flag to indicate if the worker thread is running


def recovery_worker():
    logger.info("Recovery worker started.")

    while True:

        data = recovery_queue.get()
        logger.info(
            "Processing Recovery | Remaining=%s",
            data["gateway_id"],
            recovery_queue.qsize(),
        )  # Block until an item is available in the queue

        try:

            process_http_recovery(**data)  # Process the recovery data

        except Exception as e:
            logger.exception(f"Error processing recovery: {e}")

        finally:
            recovery_queue.task_done()


def start_recovery_worker():
    global working_running

    if working_running:
        return  # Worker is already running

    if not working_running:

        worker_thread = threading.Thread(
            target=recovery_worker, daemon=True, name="RecoveryWorkerThread"
        )
        worker_thread.start()
        working_running = True
        logger.info("Recovery worker thread started.")
        # t = threading.Thread(target=recovery_worker, daemon=True)
        # t.start()

    working_running = True


# class RecoveryService:
#     """
#     Shared Recovery Service.

#     This service is transport independent.

#     MQTT
#         ↓
#     RecoveryService

#     HTTP
#         ↓
#     RecoveryService
#     """

#     @staticmethod
#     def process(site, location_id, msg_subtype, message):

#         if "hourlyConsumption" in msg_subtype:
#             return RecoveryService.process_hourly(site, location_id, message)

#         elif "dailyConsumption" in msg_subtype:
#             return RecoveryService.process_daily(site, location_id, message)

#         elif "loadRuntime" in msg_subtype:
#             return RecoveryService.process_runtime(site, location_id, message)

#         return {"success": False, "reason": "Unknown recovery type"}

#     @staticmethod
#     def process_hourly(site, location_id, message):
#         """
#         Hourly Recovery

#         (Implementation will be moved from tasks.py)
#         """

#         pass

#     @staticmethod
#     def process_daily(site, location_id, message):

#         pass

#     @staticmethod
#     def process_runtime(site, location_id, message):

#         pass
