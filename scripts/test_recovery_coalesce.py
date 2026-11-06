#!/usr/bin/env python3
"""
Simple test script to exercise recovery coalescing.

Sends N rapid POSTs with the same (location_id, gateway_id, msg_subtype)
and then checks Redis to ensure the stored payload equals the last sent payload.

Usage:
  python scripts/test_recovery_coalesce.py

Environment variables:
  SERVER_URL (default: http://127.0.0.1:8001)
  REDIS_URL  (default: redis://localhost:6379/1)
  TEST_LOCATION (default: 179)
  TEST_GATEWAY (default: gw)
  N (number of messages, default: 5)
  DELAY (seconds between posts, default: 0.05)
  RECOVERY_QUEUE_NAME (default: recovery:queue:v1)
"""

import os
import sys
import time
import json

import requests
import redis

SERVER = os.getenv("SERVER_URL", "http://127.0.0.1:8001")
UPLOAD_PATH = os.getenv("RECOVERY_UPLOAD_PATH", "/api/recovery/upload/")
UPLOAD_URL = SERVER.rstrip("/") + UPLOAD_PATH
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")
LOCATION = os.getenv("TEST_LOCATION", "179")
GATEWAY = os.getenv("TEST_GATEWAY", "gw")
N = int(os.getenv("N", "5"))
DELAY = float(os.getenv("DELAY", "0.05"))
QUEUE_NAME = os.getenv("RECOVERY_QUEUE_NAME", "recovery:queue:v1")

MSG_SUBTYPE = "hourlyConsumption"


def main():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        r.ping()
    except Exception as e:
        print("ERROR: cannot connect to redis:", e)
        return 2

    processed_key = f"recovery:processed:{LOCATION}:{GATEWAY}:{MSG_SUBTYPE}"

    last_sent = None
    for i in range(N):
        # message can be any JSON-serializable object; include counter
        message = {"counter": i, "ts": time.time()}
        topic = (
            f"/Acclivate/iOmniControl/{LOCATION}/{GATEWAY}/in/recovery/{MSG_SUBTYPE}"
        )
        body = {"Recovery Payload": [topic, int(LOCATION), GATEWAY, message]}

        try:
            resp = requests.post(UPLOAD_URL, json=body, timeout=5)
        except Exception as e:
            print("POST error:", e)
            return 3

        print(f"POST {i}: status={resp.status_code}")
        last_sent = message
        time.sleep(DELAY)

    # wait for the worker to process and write the processed sidecar
    timeout = 5.0
    waited = 0.0
    interval = 0.1
    raw = None
    while waited < timeout:
        raw = r.get(processed_key)
        if raw:
            break
        time.sleep(interval)
        waited += interval

    if not raw:
        print("FAIL: no processed marker found in redis for key", processed_key)
        print("Queue length (raw):", safe_llen(r, QUEUE_NAME))
        print("Pending payloads:", safe_payload_count(r))
        return 4

    try:
        job = json.loads(raw)
    except Exception as e:
        print("FAIL: invalid JSON processed payload in redis:", e)
        return 5

    stored_message = job.get("message") if isinstance(job, dict) else None

    if stored_message == last_sent:
        print("OK: Worker processed the latest payload as expected.")
        print("Queue length:", safe_llen(r, QUEUE_NAME))
        print("Pending payloads:", safe_payload_count(r))
        return 0
    else:
        print("MISMATCH: processed stored_message=", stored_message)
        print("expected=", last_sent)
        print("Queue length:", safe_llen(r, QUEUE_NAME))
        print("Pending payloads:", safe_payload_count(r))
        return 6


def safe_llen(redis_client, qname):
    try:
        return redis_client.llen(qname)
    except Exception:
        return None


def safe_payload_count(redis_client):
    try:
        cnt = 0
        cur = 0
        while True:
            cur, keys = redis_client.scan(cur, match="recovery:payload:*", count=1000)
            cnt += len(keys)
            if cur == 0:
                break
        return cnt
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
