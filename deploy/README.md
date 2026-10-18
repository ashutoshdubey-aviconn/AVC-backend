# Deployment units (Phase M)

All workers use the single Celery app `warehouse` (`celery -A warehouse`).
The legacy units started `celery -A tasks` (root `tasks.py`, app `root_mqtt`)
and also enqueued the listener with `ExecStartPost ... call tasks.mqtt_client1`.
That second start is gone: the listener task is enqueued exactly once by the
`worker_ready` signal in `wareApp/tasks.py`, so no duplicate MQTT subscribers.

| Unit | Queue | Concurrency | Notes |
| --- | --- | --- | --- |
| `mqtt-listener-queue1` | `queue1` | 1 | Long-running paho listener for consumption, SupplyTime, load, FIREALARM, recovery |
| `mqtt-listener-queue2` | `queue2` | 1 | Long-running paho listener for LoadData (unchanged logic) |
| `mqtt-processing-queue1` | `queue1_processing` | 1 | Used while `MQTT_SITE_PARTITIONS=0` (default) |
| `mqtt-site-worker@N` | `mqtt.site.N` | 1 | Used when `MQTT_SITE_PARTITIONS>0`; enable `@0` .. `@N-1` |
| `mqtt-processing-queue2` | `queue2_processing` | 1 | LoadData persistence (unchanged logic) |
| `mqtt-notifications` | `notifications` | 2 | Alarm emails, sent after the DB commit |

## Enabling site partitions

1. Set `MQTT_SITE_PARTITIONS=4` in `warehouse/.env` (or the environment).
2. `sudo systemctl enable --now mqtt-site-worker@{0..3} mqtt-notifications`
3. Restart `mqtt-listener-queue1` so new messages are routed to `mqtt.site.*`.
4. When `queue1_processing` is empty (`sudo rabbitmqctl list_queues`), stop
   `mqtt-processing-queue1`.

Change the partition count only while the `mqtt.site.*` queues are empty, so a
site's packets are never split across two queues.

## Settings introduced in Phase M

| Setting | Default | Purpose |
| --- | --- | --- |
| `MQTT_SITE_PARTITIONS` | `0` | Number of `mqtt.site.*` partitions (0 = legacy single queue) |
| `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` | `127.0.0.1` / `1883` | Broker used by listeners and the publisher |
| `MQTT_RECOVERY_REQUEST_COOLDOWN_SECONDS` | `600` | One recovery request per gap per window |
| `MQTT_ASYNC_NOTIFICATIONS` | `True` | Send alarm emails via the `notifications` queue |
| `REDIS_URL` | empty | Shared cache (config cache, cooldowns, sync-status cache); LocMem if empty |
| `EMAIL_TIMEOUT` | `10` | SMTP timeout in seconds |
