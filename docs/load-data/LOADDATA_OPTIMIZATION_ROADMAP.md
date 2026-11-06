# LoadData Optimization Roadmap

## Goal
Reduce MQTT callback latency for `LoadData` messages so `server_paho_client_2` stays connected and does not get disconnected by Mosquitto during bursts.

## What Has Been Changed
- Celery app usage in `wareApp/tasks.py` now points to the project-level Celery bootstrap in `warehouse/celery.py`.
- `wareApp/tasks.py` no longer creates its own Celery instance with a hardcoded broker.

## Current Problem Areas
- `LoadData` processing is handled synchronously inside the MQTT callback.
- The callback performs many ORM queries and writes before returning.
- The same worker thread must both process business logic and keep the MQTT connection alive.
- Heavy parsing and recovery logic increase the chance of broker timeout under repeated messages.

## Recommended Optimization Steps
1. Move `LoadData` parsing into a small pure function.
2. Push the parsed payload into a Celery task or queue instead of processing everything in `on_message`.
3. Keep the MQTT callback focused on validation, routing, and quick handoff.
4. Split hourly and daily write logic into dedicated helper services.
5. Reduce repeated database lookups by caching per-site and per-aisle metadata where safe.
6. Add guardrails for malformed payloads so one bad message does not block the loop.
7. Add timing logs around `LoadData` handling to measure callback duration before and after refactor.
8. Add targeted tests for payload parsing, hourly rollup, and daily rollup behavior.

## Suggested Execution Order
- Phase 1: isolate parsing and create timing metrics.
- Phase 2: move database writes into a background task.
- Phase 3: split hourly/daily rollup code into helpers.
- Phase 4: add tests and compare callback latency under load.

## Success Criteria
- MQTT callback returns quickly enough that Mosquitto does not time out `server_paho_client_2`.
- `LoadData` messages remain lossless during bursts.
- Hourly and daily rollups still match existing business rules.
- Future optimization work can be tracked against this roadmap.
