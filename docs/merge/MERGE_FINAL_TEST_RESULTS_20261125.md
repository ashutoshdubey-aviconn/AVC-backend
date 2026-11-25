# merge-final on the test server: results (25 Nov 2026)

Branch `merge-final` (pushed to `origin/merge-final`), deployed on the test server
`43.204.53.81` on 25 Nov 2026 at 14:04 IST (`515ff6e7`), redeployed at 14:12 IST with the
gateway activity fix (`e29a672e`). Main was only read (no change there).

## What was deployed

| Step | Commit / tag | Content |
|---|---|---|
| 1 | `f1f2585c`, tag `merge-final-base-views-loaddata-dgfuel-recovery-features` | Our current code: views (with the 4 views merged from Daksh on 21 Nov), LoadData, DG fuel, HTTP recovery, features (sync status, catch-up spread, baseline setup, gateway status, alarm settings), `models/` package. |
| 2 | `7d3551d6`, tag `merge-final-origin-docs` | Description and `Origin:` line in all 981 functions / classes ([CODE_ORIGIN.md](CODE_ORIGIN.md)). |
| 3 | `a1ea9409`, tags `ours-before-daksh-mqtt-merge-20261125` / `daksh-mqtt-merge-20261125` | MQTT merge: his acks_late / task retry rebuilt in our 9 packet tasks; the rest of his MQTT code not taken ([decisions](mqtt_merge_decisions_20261125.csv)). |
| fix | `e29a672e` | Gateway activity flush reconnects after a database restart (found by test 2 below). |

Before this, test ran our code of 21 Nov (`ed717fa2`: single `models.py`, without the 4 merged views).

**How:** backup of the code on test (`backups/deploy/merge-final-20261125T083121Z/code-before.tar.gz`),
`git archive` bundle unpacked over the folder (`.env`, virtualenv, logs kept), old
`wareApp/models.py` removed, `manage.py check` (no issues), `migrate --plan` (nothing to apply),
`makemigrations --check` (no changes), 11 tests run on the server (OK), then restart of
processing workers, notifications, listeners, celerybeat and gunicorn. All 7 services active.

## Results

### 1. Normal traffic

| | Before (30 min before deploy) | After (since the last restart) |
|---|---|---|
| Queue 1 tasks | 1,652 received, 1,652 succeeded | all succeeded |
| Queue 2 tasks (LoadData) | 2,430 received, 2,432 succeeded | all succeeded |
| Failed / retried / dead letters | 0 / 0 / 0 | 0 / 0 / 0 (outside the planned tests) |
| Error lines | 0 | 0 (outside the planned tests) |
| RabbitMQ queues | all 0 | all 0 |
| acks_late / reject_on_worker_lost on the packet tasks | off / off | on / on (checked in the running code) |

### 2. Database outage (PostgreSQL stopped 20 s during traffic), twice

| | Outage 1 (14:07 IST) | Outage 2 (14:16 IST, after the fix) |
|---|---|---|
| In-place DB retries (0.5 / 1 / 2 s) | 17 + 18 | 18 + 18 |
| Task retries (new, 10 s later) | 10 | 10 |
| Retried tasks that then succeeded | 10 of 10 | all |
| Dead letters / failed tasks | 0 / 0 | 0 / 0 |
| LoadData rows vs main in the window | equal | equal (239 / 239) |
| Gateway activity written after the outage | **no** (every flush failed until the listener restart) | yes, within a minute |

Before this merge the 10 packets of each outage would have been lost (early ack, no dead
letter). The gateway activity problem was ours and older than the merge; it is fixed in
`e29a672e` (listener process now drops a broken connection).

### 3. Worker killed (`kill -9` of the LoadData worker)

RabbitMQ put the packet the worker held back in the queue at once (`queue2_processing`
1 ready, 0 consumers); systemd restarted the worker after 10 s and the queue drained to 0.
The kill fell between two tasks (they take ~4 ms), so this shows a clean recovery; a kill in the
middle of a task is covered by the task settings (`reject_on_worker_lost`) and the tests.

### 4. Data compared with main (LoadData rows, the 7 sites test receives)

| Window (IST) | Test | Main | Difference |
|---|---|---|---|
| 13:30-14:00 (before the deploy) | 2,406 | 2,406 | 0 |
| 14:00-14:15 (deploy, outage 1, kill, redeploy) | 1,183 | 1,199 | -16 |
| 14:15-14:18 (outage 2) | 239 | 239 | 0 |

The 16 missing rows are two gaps of ~6 s, exactly at the two listener restarts of the deploys
(14:05 and 14:12 server time; gateway clocks are ~1 min ahead). Cause: main's broker bridge to
test forwards with QoS 0 (`topic /Acclivate/iOmniControl/# out 0`), and Mosquitto never keeps
QoS 0 messages for a listener that is offline, even with a persistent session. This is a property
of the test bridge, not of the merge, and the database outages lost nothing. Possible fix on test
only: `queue_qos0_messages true` in test's mosquitto.conf (not done; needs approval).

### 5. APIs (in-process, as Super Admin, read only)

8 / 8 HTTP 200: `lightsDataApi/`, `FansDataApi/`, `submeteringMonthlyBarChart/`,
`submeteringSnapshot/` (the 4 merged views), `gateway-status/`, `syncStatus/`,
`alarmSettings/`, `alarmList/`. Frontend `http://43.204.53.81/` answers 200.

## Found, not changed

- Fire pump e-mail rule from main (in ours and his): "Manual-Mode to Off-Mode" checks Off -> Off,
  so it e-mails on every packet while the pump is off, and a real Manual -> Off never e-mails.
  Alarms are ours; needs a decision before changing.
- `REDIS_URL` is not set on test: each worker has its own cache (fine with one worker per queue).
- Not checked yet: hourly consumption totals of the 14:00 hour against main (the hour was still
  open when the tests ended).

## Files on the test server

`/home/ubuntu/django_project/backups/deploy/merge-final-20261125T083121Z/`: `code-before.tar.gz`
(rollback), the two bundles, `metrics-before.txt`, `metrics-after.txt`, `logs-before.txt`,
`logs-after.txt`, `outage-test-2.txt`, `api-smoke.txt`, and the scripts used
(`metrics.sql`, `logstats.sh`, `outage_test.sh`, `api_smoke.py`).

## Rollback

```bash
cd /home/ubuntu && tar xzf django_project/backups/deploy/merge-final-20261125T083121Z/code-before.tar.gz
rm -rf django_project/wareApp/models/      # the old code has models.py (restored by the tar)
sudo systemctl restart mqtt-processing-queue1 mqtt-processing-queue2 mqtt-notifications \
  mqtt-listener-queue1 mqtt-listener-queue2 celerybeat gunicorn
```

No migration was applied, so the database needs nothing.
