#!/usr/bin/env python3
"""
Lightweight load tester for recovery endpoint.
Sends N requests (optionally across threads) and polls Redis for queue/payload counts.

Usage:
  python scripts/spam_recovery.py --n 1000 --threads 10 --delay 0.01

Environment:
  SERVER_URL (default http://127.0.0.1:8001)
  REDIS_URL  (default redis://localhost:6379/1)
"""

import os
import sys
import time
import json
import argparse
import threading
from queue import Queue

import requests
import redis

SERVER = os.getenv("SERVER_URL", "http://127.0.0.1:8001")
UPLOAD_PATH = os.getenv("RECOVERY_UPLOAD_PATH", "/api/recovery/upload/")
UPLOAD_URL = SERVER.rstrip("/") + UPLOAD_PATH
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")

parser = argparse.ArgumentParser()
parser.add_argument("--n", type=int, default=1000)
parser.add_argument("--threads", type=int, default=10)
parser.add_argument("--delay", type=float, default=0.01)
parser.add_argument("--location", default="179")
parser.add_argument("--gateway", default="gw")
parser.add_argument("--subtype", default="hourlyConsumption")
parser.add_argument(
    "--poll", type=float, default=0.5, help="poll redis every X seconds"
)
args = parser.parse_args()

try:
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
except Exception as e:
    print("ERROR: cannot connect to redis:", e)
    sys.exit(2)

N = args.n
THREADS = max(1, args.threads)
DELAY = args.delay
LOCATION = args.location
GATEWAY = args.gateway
MSG_SUBTYPE = args.subtype
QUEUE_NAME = os.getenv("RECOVERY_QUEUE_NAME", "recovery:queue:v1")

q = Queue()
for i in range(N):
    q.put(i)

results = {
    "sent": 0,
    "ok": 0,
    "fail": 0,
}
res_lock = threading.Lock()

start_time = time.time()


def worker():
    while not q.empty():
        i = q.get()
        message = {"counter": i, "ts": time.time()}
        topic = (
            f"/Acclivate/iOmniControl/{LOCATION}/{GATEWAY}/in/recovery/{MSG_SUBTYPE}"
        )
        body = {"Recovery Payload": [topic, int(LOCATION), GATEWAY, message]}
        try:
            resp = requests.post(UPLOAD_URL, json=body, timeout=5)
            with res_lock:
                results["sent"] += 1
                if resp.status_code == 200:
                    results["ok"] += 1
                else:
                    results["fail"] += 1
        except Exception:
            with res_lock:
                results["sent"] += 1
                results["fail"] += 1
        time.sleep(DELAY)
        q.task_done()


threads = []
for _ in range(THREADS):
    t = threading.Thread(target=worker)
    t.daemon = True
    t.start()
    threads.append(t)

# poller thread
stop_poll = False
poll_stats = []


def poller():
    while not stop_poll:
        try:
            queue_len = None
            try:
                queue_len = r.llen(QUEUE_NAME)
            except Exception:
                queue_len = None
            # count payload keys
            cnt = 0
            cur = 0
            while True:
                cur, keys = r.scan(cur, match="recovery:payload:*", count=1000)
                cnt += len(keys)
                if cur == 0:
                    break
            poll_stats.append((time.time(), queue_len, cnt))
        except Exception:
            pass
        time.sleep(args.poll)


poll_thread = threading.Thread(target=poller)
poll_thread.daemon = True
poll_thread.start()

# wait for completion
for t in threads:
    t.join()

# allow a short window for worker to process
time.sleep(1.0)
stop_poll = True
poll_thread.join(timeout=1.0)

end_time = time.time()

duration = end_time - start_time
sent = results["sent"]
ok = results["ok"]
fail = results["fail"]

print(
    f"Sent: {sent} ok: {ok} fail: {fail} duration: {duration:.2f}s qps: {sent/duration:.1f}"
)
print("Recent Redis poll samples (timestamp, queue_len, pending_payloads):")
for ts, qlen, plen in poll_stats[-10:]:
    print(f"  {time.strftime('%H:%M:%S', time.localtime(ts))}  {qlen}  {plen}")

# final snapshot
try:
    final_queue = r.llen(QUEUE_NAME)
except Exception:
    final_queue = None
final_pending = 0
try:
    cur = 0
    while True:
        cur, keys = r.scan(cur, match="recovery:payload:*", count=1000)
        final_pending += len(keys)
        if cur == 0:
            break
except Exception:
    final_pending = None

print(f"Final queue length: {final_queue}  Final pending payloads: {final_pending}")

if final_pending and final_pending > 50:
    print("ALERT: many pending payloads")

sys.exit(0)
