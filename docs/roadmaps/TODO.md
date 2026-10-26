Project TODOs (updated 2026-08-18)

Summary:
- This file tracks high-level tasks, status, and ownership for the repo.

Completed
- Fix test discovery collision and provide `run_tests.py` to run unit + Django tests sequentially. (2026-08-18)
- Added provider parsing unit tests (`unit_tests/test_fuel_providers*.py`). (2026-08-18)
- Hardened DG logic: preserve None `dg_fuel_tank_capacity` and avoid false alerts. (2026-08-18)
- Hardened `NewAlarmsNotifications.save()` to handle None/invalid phase values. (2026-08-18)
- Made migrations idempotent for `baseline_date` fields (wareApp/migrations/0003*, 0004*). (2026-08-18)
- Persist `fuel_data_source` on `DgFuelConsumptionData` rows and normalize `epoch_time` to strings across ingestion code (fetch_fuel_data). (2026-08-18)

- Centralized DG ingestion helper `wareApp/dg_ingest.py` and replaced ad-hoc
	`DgUnitConsumption` creation sites in main task modules and `dg_session.py` to
	normalize epoch handling and standardize behavior. Tests updated and all
	existing tests pass. (2026-08-18)

- Replaced ad-hoc `DgFuelConsumptionData` inserts in `fetch_fuel_data.py` to
	call `wareApp.dg_ingest.ingest_fuel_row`, ensuring epoch normalization,
	provenance (`fuel_data_source`) persistence, and deterministic dedupe.
	Tests pass after change. (2026-08-18)


In Progress (DG-fuel focused)
- Integrate `DGFuelAlertsData` dedup logic with normalized epoch strings (partial: epoch strings now consistent). Owner: ingester
- Add test harness / backfill runner for DGFuel ingestion (site-level backfill). Owner: data-engineer — Implemented: `tools/dg_backfill.py` (dry-run-first)
- Further coalescing improvements for `DgUnitConsumption` (consider Redis coalescing for high-rate ON packets) — design phase. Owner: backend

Note: Per project constraints, recovery-related tasks are deferred (see Backlog). Do NOT modify recovery code unless explicitly requested.

Backlog / Nice-to-have
- Harden third-party providers (Loconav/Roadcaste): defensive parsing, vehicle variants, raw-response logging, retry/backoff improvements.

- Credential cleanup: remove hard-coded tokens from code and rotate credentials; centralize provider credentials in env/config store.

- Observability: add `alertmanager` webhook example, health-check for recovery queue, and record Prometheus rule tuning notes.

- Recovery tasks (DEFERRED): moving MQTT runtime block into `process_runtime` and adding `/api/recovery/metrics/` are deferred and should not be edited without explicit approval.

How to use
- Small fixes: implement code, run `./virtualwarehouse/bin/python3 run_tests.py`, open a PR referencing this TODO entry.
- Larger tasks: propose design in an issue or RFC, link to this file and mark ownership.

If you'd like, I can:
- move the MQTT runtime runtime block into `process_runtime` (minimal change),
- implement the `/api/recovery/metrics/` endpoint, or
- create a CI workflow to run `run_tests.py`.


DG Fix Tasks (created 2026-08-18)

- Legacy duplicate DG processing — RED (🔴) — Priority: High
	- Owner: data-engineer
	- Steps:
		1. Inventory where duplicate processing can originate (legacy processors, cron, Celery tasks, recovery replay).
		2. Create a reproducible unit/integration test that demonstrates duplicate ingestion using a small sample of raw messages.
		3. Add a feature flag to disable suspected legacy path(s); deploy to staging and re-run the test.
		4. Remove or safely deprecate duplicate processor(s) once staging proves clean; monitor metrics for regressions.
	- Acceptance: no duplicate `DgFuelConsumptionData` rows appear in staging tests; unit/integration tests cover the case; production rollback plan exists.
	- Tests: add `unit_tests/test_dg_duplicates.py` and integration scenario in `wareApp/tests`.

- Historical bad records — RED (🔴) — Priority: High
	- Owner: data-engineer / ops
	- Steps:
		1. Run classification queries to surface bad records (invalid epochs, negative fuel, duplicate epochs, missing OFF events).
		2. Design a reconciliation/backfill script with `--dry-run`, chunking, transaction safety, and an audit table that stores pre/post snapshots.
		3. Validate fixes in staging on a replay dataset; produce a revert script.
		4. Run in production during a maintenance window, monitor, and confirm via spot-checks.
	- Acceptance: reconciliation script marks or fixes all classified anomalies and produces an audit log; tests validate expected transforms.

- 11‑Aug actual discrepancy — ORANGE (🟠) — Priority: Medium-High
	- Owner: data-engineer + product
	- Steps:
		1. Collect raw provider payloads, `DGFuelAlertsData`, and `DgFuelConsumptionData` rows for the 11‑Aug window.
		2. Reproduce the discrepancy locally and write a regression test capturing the scenario.
		3. Implement targeted reconciliation (e.g., compute missing OFF using `last_entry` or dedupe overlapping ON packets) and run tests.
		4. Document the root cause and prevention steps.
	- Acceptance: 11‑Aug discrepancy resolved in DB snapshots and covered by an automated regression test.

- Production DG ON→RUN→OFF coalescing — ORANGE (🟠) — Priority: Medium
	- Owner: backend + data-engineer
	- Steps:
		1. Define canonical transition semantics and acceptable time-windows for ON→RUN→OFF.
		2. Implement coalescing at the DG ingestion layer only (two options):
			 - lightweight in-process windowed coalescer (no recovery changes), or
			 - Redis-backed coalescer with short TTL windows (DG-only feature flag).
		3. Add integration tests simulating high-rate ON packets and confirm single RUN per event and correct OFF timestamps.
		4. Roll out behind a feature flag; monitor run/alert counts.
	- Acceptance: staging shows correct single-run behavior; tests pass; monitoring shows reduced duplicate runs.

- Full production API validation — ORANGE (🟠) — Priority: Medium
	- Owner: QA + backend
	- Steps:
		1. Create a provider test harness that can replay Loconav and Roadcaste payload variants (edge cases, missing fields, string timestamps).
		2. Validate that ingestion maps to internal schema, epoch normalization, and `fuel_data_source` are set for each case.
		3. Add canary runs in staging to run the harness nightly and alert on mapping regressions.
	- Acceptance: provider mapping validation green; canary reports run without failures.

- Automated regression suite — GREEN (🟢) — Status: Ready
	- Owner: QA
	- Steps: expand coverage to include reconciliation/backfill and coalescing tests; add CI workflow to run `run_tests.py` on PRs and nightly.
	- Acceptance: CI runs included tests and reports failures before merge.

- Django warnings — YELLOW (🟡) — Low priority
	- Owner: tech-debt squad
	- Steps: enumerate warnings, create separate issues, assign owners, and plan cleanup sprints.
	- Acceptance: warnings are triaged and tracked in issues.

Safety & Rollback
- Always run any backfill with `--dry-run` and snapshot affected records.
- Apply fixes behind feature flags where possible and promote to production only after staging validation.

Quick commands
- Run full test suite: `./virtualwarehouse/bin/python3 run_tests.py`
- Example dry-run backfill command (implement script at `tools/dg_backfill.py`):
	`./virtualwarehouse/bin/python3 tools/dg_backfill.py --dry-run --site 35`

Next step
- I can start with the highest-priority item: create a reproducible test for legacy duplicate DG processing and add it to `unit_tests`. Confirm and I'll implement it.
