# Root MQTT LoadData Rollout

## Phase 1: LoadData Isolation

- [x] Route only business MQTT types to root `mqtt_client1` / `queue1`.
- [x] Route only `LoadData` MQTT topics to root `mqtt_client2` / `queue2`.
- [x] Replace active root queue2 inline LoadData persistence and rollups with `wareApp.load_data.handle_load_data_message`.
- [x] Preserve existing queue1 callback behavior and `print` output.
- [ ] Deploy this phase to the main server with a dedicated queue2 worker.
- [ ] Verify queue1 receives no `LoadData` traffic and queue2 receives no business topics.
- [ ] Monitor raw readings, monthly min/max, hourly rollups, and daily rollups for one complete day.

## DG-Fuel Compatibility

- [x] Route root Roadcast and LocoNav helpers through retrying provider clients.
- [x] Route the legacy root DG-session helper through normalized reconciliation and retryable fuel fetches.
- [ ] Remove the remaining inline DG-fuel request blocks from queue1 after phase-1 production verification; preserve their existing `print` output until then.

## Phase 2: Queue1 Optimization

- [ ] Move queue1 database, email, and recovery work out of the Paho callback into processing tasks.
- [ ] Replace legacy callback parsing with validated topic and payload parsers.
- [ ] Add listener retry, duplicate-listener protection, and worker ownership checks.
- [ ] Retire the inactive root `_retired_mqtt_client2_inline_load_data` reference after the phase-1 rollout is verified.

## Deployment Contract

- Start exactly one root queue1 listener worker for business topics.
- Start exactly one root queue2 listener worker for `LoadData` only.
- Keep queue2 LoadData processing serial until database idempotency/uniqueness is enforced.

## Main-Server Runbook

1. Stop existing root MQTT listener workers so the wildcard subscriptions are removed.
2. Deploy this code, then run `./virtualwarehouse/bin/python manage.py migrate` before starting workers. This applies DG-fuel configuration (`0085`), queue-one indexes (`0086`), and callable datetime defaults (`0087`).
3. Start the business listener worker:
	`./virtualwarehouse/bin/celery -A tasks worker --hostname=worker.queue1@%h --queues=queue1 --loglevel=INFO`
4. Start the serial LoadData listener worker:
	`./virtualwarehouse/bin/celery -A tasks worker --hostname=worker.queue2@%h --queues=queue2 --concurrency=1 --loglevel=INFO`
5. Enqueue exactly one `mqtt_client1` task on `queue1` and one `mqtt_client2` task on `queue2`; do not run two instances of either listener.
6. Start the DG-fuel runner separately:
	`./virtualwarehouse/bin/python fetch_fuel_data.py`

## Smoke Checks

- Confirm queue1 logs business messages and never `LoadData`.
- Confirm queue2 logs only `LoadData` and creates raw-load readings.
- Confirm `logges/dg_fuel.log` records provider result, daily reconciliation, and retry outcomes.
- Run `./virtualwarehouse/bin/python manage.py showmigrations wareApp` and confirm `0085`, `0086`, and `0087` are applied.