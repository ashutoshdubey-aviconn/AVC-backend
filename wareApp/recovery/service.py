import logging
import threading
import json

from .processor import process_http_recovery
from wareApp.models import Site
from django.conf import settings

from queue import Queue, Full

# Use dedicated recovery logger so settings logger `wareApp.recovery` applies
logger = logging.getLogger("wareApp.recovery")

# Optional Prometheus metrics (initialized if enabled in settings)
RECOVERY_PROCESSED_COUNTER = None
RECOVERY_PENDING_GAUGE = None
RECOVERY_QUEUE_GAUGE = None

try:
    if getattr(settings, "RECOVERY_ENABLE_METRICS", False):
        try:
            from prometheus_client import Counter, Gauge

            RECOVERY_PROCESSED_COUNTER = Counter(
                "recovery_processed_total", "Total processed recovery messages"
            )
            RECOVERY_PENDING_GAUGE = Gauge(
                "recovery_pending_payloads", "Number of pending recovery payloads"
            )
            RECOVERY_QUEUE_GAUGE = Gauge(
                "recovery_queue_length", "Redis recovery queue length"
            )
            logger.info("Prometheus metrics enabled for recovery")
        except Exception:
            logger.exception("Failed to initialize Prometheus metrics for recovery")
except Exception:
    RECOVERY_PROCESSED_COUNTER = None
    RECOVERY_PENDING_GAUGE = None
    RECOVERY_QUEUE_GAUGE = None


# Queue holds job keys. Actual job payloads are stored in `pending_jobs`.
recovery_queue = Queue(maxsize=5000)  # Limit the queue size to prevent memory issues

# Map of key -> latest job payload. Protected by `pending_lock`.
pending_jobs = {}
pending_lock = threading.Lock()

working_running = False  # Flag to indicate if the worker thread is running

# Optional Redis client for cross-process coalescing
redis_client = None
try:
    from django.conf import settings

    if getattr(settings, "RECOVERY_USE_REDIS", False):
        try:
            import redis as _redis

            redis_client = _redis.Redis.from_url(
                getattr(settings, "REDIS_URL"), decode_responses=True
            )
            redis_client.ping()
            logger.info("Connected to Redis for recovery coalescing")
        except Exception:
            logger.exception(
                "Could not connect to Redis for recovery; falling back to local queue"
            )
            redis_client = None
except Exception:
    redis_client = None


def recovery_worker():
    logger.info("Recovery worker started.")

    while True:
        # Block until an item (key) is available in the queue
        key = recovery_queue.get()

        try:
            with pending_lock:
                job = pending_jobs.pop(key, None)

            if not job:
                # Nothing to process for this key (might have been removed)
                logger.debug("No pending job found for key=%s", key)
                continue

            logger.info(
                "Processing Recovery | Key=%s | QueueSize=%s",
                key,
                recovery_queue.qsize(),
            )

            try:
                # Ensure 'site' is provided to the processor for in-process worker
                try:
                    site = Site.objects.get(id=job.get("location_id"))
                    job["site"] = site
                except Exception:
                    logger.exception(
                        "Failed to resolve Site for in-process job %s", key
                    )

                logger.info(
                    "Processing Recovery (in-process) | Key=%s | QueueSize=%s",
                    key,
                    recovery_queue.qsize(),
                )
                process_http_recovery(**job)  # Process the recovery data

                # record processed sidecar in Redis (if available) so tests/metrics can observe
                try:
                    if redis_client is not None:
                        processed_key = f"recovery:processed:{key}"
                        try:
                            redis_client.set(
                                processed_key, json.dumps(job, default=str), ex=60
                            )
                        except Exception:
                            logger.exception(
                                "Failed to write processed sidecar for in-process %s",
                                key,
                            )
                except Exception:
                    logger.exception(
                        "Error while writing processed sidecar for in-process %s", key
                    )

                try:
                    if (
                        "RECOVERY_PROCESSED_COUNTER" in globals()
                        and RECOVERY_PROCESSED_COUNTER
                    ):
                        RECOVERY_PROCESSED_COUNTER.inc()
                except Exception:
                    logger.exception(
                        "Failed to increment RECOVERY_PROCESSED_COUNTER for in-process %s",
                        key,
                    )
                # update pending/queue metrics for in-process path
                try:
                    if redis_client is not None and RECOVERY_QUEUE_GAUGE is not None:
                        try:
                            RECOVERY_QUEUE_GAUGE.set(
                                redis_client.llen(
                                    getattr(
                                        settings,
                                        "RECOVERY_QUEUE_NAME",
                                        "recovery:queue:v1",
                                    )
                                )
                            )
                        except Exception:
                            logger.exception(
                                "Failed to set RECOVERY_QUEUE_GAUGE (in-process)"
                            )
                    if redis_client is not None and RECOVERY_PENDING_GAUGE is not None:
                        try:
                            cur = 0
                            cnt = 0
                            while True:
                                cur, keys = redis_client.scan(
                                    cur, match="recovery:payload:*", count=1000
                                )
                                cnt += len(keys)
                                if cur == 0:
                                    break
                            RECOVERY_PENDING_GAUGE.set(cnt)
                        except Exception:
                            logger.exception(
                                "Failed to set RECOVERY_PENDING_GAUGE (in-process)"
                            )
                except Exception:
                    logger.exception("Error updating in-process metrics for %s", key)

            except Exception as e:
                logger.exception("Error processing recovery: %s", e)

        finally:
            recovery_queue.task_done()


def enqueue_recovery(job):
    """Enqueue a recovery job, coalescing duplicates.

    Duplicates are determined by a key derived from the job. If a job
    for the same key is already pending, the payload is replaced with the
    latest one (coalescing frequent messages).

    Raises `queue.Full` if the internal key queue is full.
    Returns True on success.
    """

    # If Redis is configured, use Redis-backed coalescing and queue
    if redis_client is not None:
        return _redis_enqueue(job)

    # Define the dedupe key. Use site, gateway and subtype so similar recoveries
    # for the same site/gateway/subtype are coalesced.
    key = f"{job.get('location_id')}:{job.get('gateway_id')}:{job.get('msg_subtype')}"

    with pending_lock:
        # If key already pending, replace payload and return (no new queue entry)
        if key in pending_jobs:
            pending_jobs[key] = job
            logger.debug("Coalesced recovery job for key=%s", key)
            return True

        # New key: store payload and enqueue the key
        pending_jobs[key] = job

    # Enqueue the key (this can raise Full)
    recovery_queue.put_nowait(key)
    logger.debug("Enqueued recovery key=%s", key)
    return True


def start_recovery_worker():
    global working_running

    if working_running:
        return  # Worker is already running

    # If Redis is configured, start Redis-backed workers that BLPOP keys
    if getattr(settings, "RECOVERY_USE_REDIS", False) and redis_client is not None:
        concurrency = getattr(settings, "RECOVERY_WORKER_CONCURRENCY", 1)
        for i in range(max(1, concurrency)):
            worker = threading.Thread(
                target=_redis_worker,
                daemon=True,
                name=f"RecoveryRedisWorker-{i}",
            )
            worker.start()
        working_running = True
        logger.info("Recovery Redis worker threads started (count=%s).", concurrency)
        return

    # Fallback to in-process queue workers
    concurrency = getattr(settings, "RECOVERY_WORKER_CONCURRENCY", 1)
    for i in range(max(1, concurrency)):
        worker_thread = threading.Thread(
            target=recovery_worker, daemon=True, name=f"RecoveryWorkerThread-{i}"
        )
        worker_thread.start()
    working_running = True
    logger.info("Recovery in-process worker threads started (count=%s).", concurrency)


def _redis_enqueue(job, payload_ttl=24 * 3600, pending_ttl=60 * 60 * 24):
    """Store latest payload in Redis and push key to Redis queue only once.

    TTLs and queue name are read from settings if available.
    """
    import json

    from django.conf import settings

    payload_ttl = getattr(settings, "RECOVERY_PAYLOAD_TTL", payload_ttl)
    pending_ttl = getattr(settings, "RECOVERY_PENDING_TTL", pending_ttl)
    queue_name = getattr(settings, "RECOVERY_QUEUE_NAME", "recovery:queue:v1")

    key = f"{job.get('location_id')}:{job.get('gateway_id')}:{job.get('msg_subtype')}"
    payload_key = f"recovery:payload:{key}"
    pending_flag = f"recovery:pending:{key}"

    try:
        # Save/replace payload
        redis_client.set(payload_key, json.dumps(job, default=str), ex=payload_ttl)

        # Set pending flag only if not exists; if set, push key to queue
        was_set = redis_client.set(pending_flag, 1, nx=True, ex=pending_ttl)
        if was_set:
            redis_client.rpush(queue_name, key)
            logger.info("Redis enqueued recovery key=%s to %s", key, queue_name)
        else:
            logger.debug("Redis coalesced recovery key=%s", key)

        # update metrics if enabled
        try:
            if RECOVERY_QUEUE_GAUGE is not None:
                try:
                    RECOVERY_QUEUE_GAUGE.set(redis_client.llen(queue_name))
                except Exception:
                    logger.exception("Failed to set RECOVERY_QUEUE_GAUGE")
            if RECOVERY_PENDING_GAUGE is not None:
                try:
                    cur = 0
                    cnt = 0
                    while True:
                        cur, keys = redis_client.scan(
                            cur, match="recovery:payload:*", count=1000
                        )
                        cnt += len(keys)
                        if cur == 0:
                            break
                    RECOVERY_PENDING_GAUGE.set(cnt)
                except Exception:
                    logger.exception("Failed to set RECOVERY_PENDING_GAUGE")
        except Exception:
            logger.exception("Error updating recovery metrics after enqueue")

        return True
    except Exception:
        logger.exception("Redis enqueue failed for key=%s", key)
        raise


def _redis_worker():
    """Worker that listens on Redis queue and processes latest payloads."""
    import json
    import time
    from django.conf import settings

    queue_name = getattr(settings, "RECOVERY_QUEUE_NAME", "recovery:queue:v1")
    logger.info("Starting Redis recovery worker BLPOP on %s", queue_name)
    try:
        logger.info(
            "Redis client connection: %s",
            getattr(redis_client, "connection_pool", None)
            and getattr(redis_client.connection_pool, "connection_kwargs", None),
        )
    except Exception:
        logger.exception("Failed to log redis client connection info")
    while True:
        try:
            item = redis_client.blpop(queue_name, timeout=0)
            if not item:
                continue

            _, key = item
            payload_key = f"recovery:payload:{key}"
            pending_flag = f"recovery:pending:{key}"

            raw = redis_client.get(payload_key)
            if not raw:
                logger.debug("No payload found in Redis for key=%s", key)
                redis_client.delete(pending_flag)
                continue

            try:
                job = json.loads(raw)
            except Exception:
                logger.exception("Failed to decode recovery payload for key=%s", key)
                redis_client.delete(payload_key)
                redis_client.delete(pending_flag)
                continue

            try:
                logger.info("Processing recovery key=%s", key)
                # Ensure the 'site' object is provided to the processor
                try:
                    site = Site.objects.get(id=job.get("location_id"))
                    job["site"] = site
                except Exception:
                    logger.exception("Failed to resolve Site for job %s", key)
                process_http_recovery(**job)

                try:
                    # write a short-lived sidecar key so tests / metrics can observe processing
                    processed_key = f"recovery:processed:{key}"
                    try:
                        redis_client.set(
                            processed_key, json.dumps(job, default=str), ex=60
                        )
                    except Exception:
                        # non-fatal; log and continue
                        logger.exception(
                            "Failed to write processed sidecar for %s", key
                        )

                    # update metrics after processing
                    try:
                        if RECOVERY_PROCESSED_COUNTER is not None:
                            RECOVERY_PROCESSED_COUNTER.inc()
                    except Exception:
                        logger.exception(
                            "Failed to increment RECOVERY_PROCESSED_COUNTER"
                        )

                    try:
                        if RECOVERY_QUEUE_GAUGE is not None:
                            RECOVERY_QUEUE_GAUGE.set(redis_client.llen(queue_name))
                    except Exception:
                        logger.exception(
                            "Failed to update RECOVERY_QUEUE_GAUGE after processing"
                        )

                    try:
                        if RECOVERY_PENDING_GAUGE is not None:
                            cur = 0
                            cnt = 0
                            while True:
                                cur, keys = redis_client.scan(
                                    cur, match="recovery:payload:*", count=1000
                                )
                                cnt += len(keys)
                                if cur == 0:
                                    break
                            RECOVERY_PENDING_GAUGE.set(cnt)
                    except Exception:
                        logger.exception(
                            "Failed to update RECOVERY_PENDING_GAUGE after processing"
                        )
                except Exception:
                    logger.exception("Error setting processed sidecar for %s", key)
            except Exception:
                logger.exception("Processing recovery job failed for key=%s", key)
            finally:
                try:
                    redis_client.delete(payload_key)
                    redis_client.delete(pending_flag)
                except Exception:
                    logger.exception("Failed to cleanup redis keys for %s", key)

        except Exception:
            logger.exception("Redis worker encountered an error, retrying in 1s")
            time.sleep(1)


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
