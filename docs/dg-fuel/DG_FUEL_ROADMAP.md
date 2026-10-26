# DG Fuel Refactor and Rollout Roadmap

## Scope and Safety Rules

- Scope is limited to DG fuel collection, DG fuel sessions, provider adapters,
  DG fuel alerts, DG fuel API output, and their tests.
- Git promotion target: `ashutoshdubey-aviconn/AVC-backend`, branch `dg-fuel`.
- Do not modify load-data processing, recovery processing, unrelated API routes,
  or unrelated MQTT behavior.
- Production changes are promoted only after the same revision passes the local
  and test-server gates in this document.
- All provider probes are read-only. All backfills default to dry-run. No
  historical cleanup runs on the main server without an approved backup and a
  recorded rollback command.
- Do not move, rotate, or otherwise change provider credentials until the
  final deployment-preparation step. Until then, refactor behavior behind
  injected provider clients and keep existing credential locations unchanged.

## Branch Synchronization

- [x] DG-fuel Git branch identified: `dg-fuel` in
  `ashutoshdubey-aviconn/AVC-backend`.
- [ ] Clone or connect this workspace to that repository and check out
  `dg-fuel` before the first functional refactor commit.
- [ ] Push each completed, validated DG-fuel implementation step to `dg-fuel`
  with its matching roadmap/test-log update.
- [ ] Open the test-server deployment only from a known `dg-fuel` commit.

Current local status: this downloaded workspace has no `.git` directory and a
Git executable is not currently available. The roadmap is being maintained
locally until the workspace is cloned/connected and Git authentication is set
up.

## Confirmed Provider Map

| Provider | Site ID | Site / device label | Provider fuel ID | Status |
| --- | ---: | --- | --- | --- |
| Roadcast | 118 | DHL B500 Lohari Mains EB & DG Fuel | `353691840557010` | mapped |
| Roadcast | 124 | DHL-ABFRL Bilaspur Mains EB & DG Fuel | `353201353997221` | mapped |
| Roadcast | 140 | site label to confirm | `353691846842382` | mapped |
| Roadcast | 153 | DHL-B302 Healthkart | `353691846234838` | mapped |
| Roadcast | 156 | DHL Kalpatru Mains EB & DG Fuel | `353691846235546` | mapped |
| Roadcast | 169 | DHL-Fazilpur | `353691846842234` | mapped |
| Roadcast | none | unknown site | `353691845102705` | do not ingest until mapped |
| LocoNav | 35 | site label to confirm | `PBDN450` | mapped |
| LocoNav | 76 | DHL Bhiwandi MCS-4 Mains EB & DG Fuel | `DCGenerator-01` | mapped |
| LocoNav | 92 | site label to confirm | `DCGENERATORLucknow` | mapped |

## Data Contract

The dashboard plots five distinct series. The backend must preserve their
separate meanings:

| Dashboard series | Source model | Meaning | Timestamp contract |
| --- | --- | --- | --- |
| Fuel Level | `DgFuelConsumptionData` | Provider-reported tank level in liters | Unix milliseconds |
| Refuel | `DGFuelAlertsData` | Provider-reported refill quantity in liters | Unix milliseconds |
| Fuel Drain | `DGFuelAlertsData` | Provider-reported theft/drain quantity in liters | Unix milliseconds |
| DG Unit Consumption | `DgUnitConsumption` | Electricity consumed during a completed DG run, in kWh | Unix milliseconds |
| DG Fuel Consumed | `DgUnitConsumption` | Fuel consumed during that DG run, in liters | Unix milliseconds |
| DG Unit Per Ltr | derived API value | `DG Unit Consumption / DG Fuel Consumed` | Unix milliseconds |

`None` means unavailable. `0` is valid data and must never be converted into a
failed provider fetch.

## Confirmed Roadcast Contract

The current implementation has two separate Roadcast concerns and they must
not be mixed:

| Purpose | Endpoint | Required request values | Response fields | Refactor status |
| --- | --- | --- | --- | --- |
| Tank level sample | `pull_api` | provider credentials | `data[].deviceImei`, `data[].fuel`, `data[].lastUpdate` | authoritative for Roadcast fuel level |
| DG-run fuel consumed | `pull_fuel_report` | `device_imei`, `from_time`, `to_time` | `fuel_consumed` | authoritative; accepts IMEI, not Roadcast `deviceId` |
| Refuel event | `dashboard/fuel/last_filled/sensor` | device ID and selected user ID | `data.quantity_filled`, `data.timestamp` | legacy: currently hardcoded to one device |
| Drain/theft value | `alerts_dashboard` | selected user ID | `data.drainage` | legacy aggregate value; no per-device event contract verified |

The old `reports/fuel` endpoint in `tasks.py` is legacy code. It hardcodes a
single Roadcast device and must not be used for the six mapped Roadcast sites.

Live `pull_fuel_report` validation for site 118 confirms this parseable
response shape:

- Scalars: `initial_fuel_level`, `fuel_level_at_end`, `fuel_consumed`,
  `total_fuel_filled`, `total_fuel_stolen`, `fuel_fill_count`, and
  `fuel_stolen_count`.
- Historical level samples: `fuel_data[]` with `fuel` and `time`.
- Refuel events: `fuel_fillings` dictionary with `fuel_amounts`,
  `fuel_levels_before_refill`, `locations`, and `refill_time`.
- Theft events: `fuel_stolen_details` dictionary with `stolen_amounts`,
  `locations`, and `theft_time`.

The new parser must handle `fuel_fillings` and `fuel_stolen_details` as
dictionaries of parallel arrays, not lists of event dictionaries.

## Runtime and Logging

- `fetch_fuel_data.py` is managed as a systemd service on both servers. The
  refactor retains this model; it does not move fuel polling to Celery Beat.
- Django logging writes dedicated DG-fuel module events to
  `logges/dg_fuel.log` using a 5 MiB rotating file handler with 10 retained
  files. Current compatibility module namespaces are routed there during the
  staged migration.
- The new poller must log provider, site ID, vehicle ID, response outcome,
  normalized timestamp, inserted/skipped counts, alert counts, and exceptions.
  It must not log credentials or complete raw provider payloads in normal mode.

## Current `fetch_fuel_data.py` Assessment

Status: **needs replacement by the staged DG-fuel poller; do not treat the
current implementation as correct for the nine mapped sites.**

- It calls Roadcast for all devices and then calls LocoNav for every site with
  `dg_fuel_system_installed=True`. The six Roadcast sites therefore make
  incorrect LocoNav calls, and the LocoNav alert flow also runs for them.
- Roadcast level ingestion uses the local poll time and `int(fuel)` instead of
  `lastUpdate` and the numeric provider value. Unchanged provider data can
  become repeated five-minute samples, fractional litres are lost, and chart
  timestamps do not reflect the provider measurement time.
- The LocoNav level path writes directly with `objects.create()` rather than
  the centralized idempotent helper. It can duplicate samples under concurrent
  poller/service execution.
- Deferred `DgUnitConsumption` retries always call LocoNav, including for
  Roadcast sites. This makes Roadcast fuel-consumption backfill incorrect.
- Legacy `fetchDataAndUpdate`, `checkRefuel`, and `checkTheft` functions are
  hardcoded to one Roadcast device and are not called by `_run_once`; they must
  not be reused for the mapped site set.
- Loconav alert records use raw seconds while dashboard series expect Unix
  milliseconds. This can plot refuel/theft events at the wrong time.
- The script relies on `print`, broad exception catches, and ad-hoc raw files.
  It does not provide one structured per-cycle result in `dg_fuel.log`.

The active systemd service may keep running the current script until the new
poller passes test-server validation. No service unit is changed during local
refactor work.

## Implementation Checklist

### Phase 0: Capture and Agree Provider Contracts

- [ ] Run a read-only diagnostic for all mapped LocoNav sites: 35, 76, and 92.
- [ ] Run a read-only diagnostic for all mapped Roadcast sites: 118, 124, 140,
  153, 156, and 169.
- [ ] Record sanitized response-field samples, timestamp units, and which
  endpoint is authoritative for each provider.
- [x] LocoNav current-level probe confirmed for site 76: `data[0]` includes
  `fuel_in_liters`, `value_in_percentage`, `fuel_capacity`, and millisecond
  `timestamp`.
- [x] Roadcast aggregate `pull_fuel_report` returned HTTP 404 for the initial
  site-76 diagnostic; do not infer its parsing contract from that endpoint.
- [x] Confirm Roadcast `pull_api` as the tank-level source:
  `data[].deviceImei`, `data[].fuel`, and `data[].lastUpdate`.
- [x] Confirm Roadcast `pull_fuel_report` as the DG-run consumption source:
  `fuel_consumed`; live success must be captured for a mapped Roadcast device.
- [ ] Capture sanitized per-device Roadcast `pull_api` samples for sites 118,
  124, 140, 153, 156, and 169.
- [x] Capture successful live `pull_api` samples for sites 118, 153, 156, and
  169. `fuel` is numeric and `lastUpdate` is an ISO timestamp string.
- [ ] Resolve the Roadcast device-map discrepancy for sites 124 and 140. Their
  configured IMEIs were absent from the live `pull_api` device list on
  2026-08-31; the new poller must log and skip them, never insert zero fuel.
- [ ] Verify whether Roadcast has per-device refuel and drain events. Until
  then, do not ingest the legacy hardcoded refuel/drain endpoints.
- [x] Capture the per-device Roadcast report contract for site 118. It includes
  fill and theft event arrays as well as consumption and historical fuel data.

### Phase 1: Modernize the DG Fuel Module Boundary

- [x] Create the `wareApp/dg_fuel/` package boundary.
- [x] Add pure value/timestamp normalization in
  `wareApp/dg_fuel/normalization.py`.
- [x] Add pure LocoNav and Roadcast payload parsers in
  `wareApp/dg_fuel/providers.py`; they are not wired into runtime yet.
- [x] Add centralized idempotent level and alert helpers in
  `wareApp/dg_fuel/ingestion.py`; they are not wired into runtime yet.
- [x] Add a read-only provider collection layer in
  `wareApp/dg_fuel/collection.py` that maps normalized samples to configured
  sites and reports unavailable provider IDs.
- [x] Add a one-cycle no-write poller in `wareApp/dg_fuel/poller.py` and
  `scripts/dg_fuel_dry_run.py`. It reports proposed samples, unavailable
  sites/devices, and provider request failures without writing to PostgreSQL.
- [x] Label missing provider rows as device expiry/unavailable cases so the
  poller skips them without inserting zero fuel.
- [ ] Move provider configuration and response parsing into
  `wareApp/dg_fuel/providers.py`.
- [ ] Move timestamp and value normalization into
  `wareApp/dg_fuel/normalization.py`.
- [ ] Move `DgFuelConsumptionData` persistence and idempotency into
  `wareApp/dg_fuel/ingestion.py`.
- [ ] Move DG ON, update, and OFF lifecycle logic into
  `wareApp/dg_fuel/sessions.py`.
- [ ] Keep compatibility modules (`fuel_providers.py`, `dg_ingest.py`,
  `dg_session.py`, and `dg_dedupe.py`) as thin re-exports during rollout.
- [ ] Move only DG-fuel code paths in `fetch_fuel_data.py` and `tasks.py` to
  the new package. Do not refactor other task logic.

### Phase 2: Correctness Rules

- [ ] Make `Site.partner_dg_provider` the only provider selector for mapped
  sites; retain the numeric-ID heuristic only as logged fallback for unmapped
  legacy sites.
- [ ] Enforce the provided site-to-provider map and skip unknown Roadcast
  device `353691845102705` with an explicit warning.
- [ ] Normalize all stored and API-returned fuel timestamps to Unix
  milliseconds.
- [ ] Route every fuel-level write through one ingestion function.
- [ ] Add database-backed uniqueness or conflict-safe idempotency for fuel
  samples on `(site, vehicle_number, epoch_time)`.
- [ ] Preserve source provenance (`loconav` or `roadcast`) on every sample.
- [ ] Ensure all alert writes are idempotent by site, vehicle, alert name, and
  normalized timestamp.
- [ ] Remove duplicate DG-session updates from the DG-only part of `tasks.py`
  after regression tests prove delegation is complete.
- [ ] Treat a valid provider value of `0` as a success.

### Phase 2.5: Credential Finalization (Last Step)

- [ ] After all code, tests, and test-server behavior are approved, move the
  provider values from the legacy source locations into the systemd service
  environment or a protected environment file.
- [ ] Rotate provider credentials after the new service configuration is
  confirmed, then verify no credentials remain in DG-fuel source files.

### Phase 3: Tests and Diagnostics

- [x] Add focused unit tests for numeric values, seconds, milliseconds, and
  Roadcast ISO timestamp normalization.
- [x] Add focused unit tests for LocoNav levels, Roadcast levels, Roadcast
  report history, and Roadcast parallel-array refill/theft events.
- [x] Add isolated Django tests for idempotent level/alert persistence and
  normalized epoch storage.
- [x] Add isolated collection tests for LocoNav vehicle matching and Roadcast
  missing-device handling.
- [ ] Add fixtures from sanitized live LocoNav responses for sites 35, 76, 92.
- [ ] Add fixtures from sanitized live Roadcast responses for sites 118, 124,
  140, 153, 156, 169.
- [ ] Test each provider parser for valid data, empty data, invalid values,
  seconds, milliseconds, and failed HTTP responses.
- [ ] Test one fuel sample insert twice and assert exactly one database row.
- [ ] Test refuel and theft alert idempotency with milliseconds.
- [ ] Test DG ON -> updates -> OFF -> immediate provider fetch.
- [ ] Test DG OFF provider failure -> deferred retry -> successful update.
- [ ] Test MQTT DG handling delegates once and cannot double-count a session.
- [ ] Add a read-only `--provider` / `--site` diagnostic command that redacts
  credentials and never writes to the database.

### Phase 4: Local Validation Gate

- [ ] Run provider parser unit tests.
- [ ] Run Django DG-fuel tests on an isolated test database.
- [ ] Run the read-only diagnostics for all nine mapped sites.
- [ ] Run a one-cycle poller dry-run and compare proposed records with live
  provider data. It must not write rows or alarms.
- [ ] Run the one-cycle poller dry-run with an injected legacy-compatible
  provider client. Credential relocation is deferred to Phase 2.5.
- [ ] Run `python manage.py check` and `python manage.py migrate --plan`.
- [ ] Record test results and known provider failures below.

### Phase 5: Test Server Deployment Gate

- [ ] Back up the test-server database and record the restore command.
- [ ] Deploy only the tested DG-fuel revision to the test server.
- [ ] Update and restart only the `fetch_fuel_data.py` systemd service after
  confirming the unit file points to the intended virtual environment and
  project directory.
- [ ] Apply migrations with `migrate --plan`, then `migrate`.
- [ ] Run the poller in dry-run mode for one full provider cycle.
- [ ] Enable a single controlled write cycle for the nine mapped sites.
- [ ] Verify dashboard series: Fuel Level, Refuel, Fuel Drain, DG Unit
  Consumption, DG Fuel Consumed, and DG Unit Per Ltr.
- [ ] Verify no duplicate rows, no unrecognized device ingestion, and no
  doubled DG sessions.
- [ ] Observe retries, logs, and alert counts for an agreed soak period.
- [ ] Approve production only after the checks above pass.

### Phase 6: Main Server Promotion Gate

- [ ] Take a fresh main-server PostgreSQL backup.
- [ ] Stop only the DG-fuel poller / DG-fuel worker during deployment; leave
  load-data processing untouched.
- [ ] Update and restart only the `fetch_fuel_data.py` systemd service after
  test-server approval; do not restart the load-data processing service.
- [ ] Deploy the already-tested revision and apply reviewed migrations.
- [ ] Run a dry-run provider diagnostic for all mapped sites.
- [ ] Enable the DG-fuel poller and monitor the first cycle.
- [ ] Verify dashboard values and row counts against provider samples.
- [ ] Keep a rollback revision and database restore command available until
  the soak period is complete.

## Test Result Log

| Date | Environment | Check | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-08-30 | local | LocoNav live current-level probe, site 76 | pass | `fuel_in_liters=356.28`, `fuel_capacity=450`, timestamp was milliseconds. |
| 2026-08-30 | local | Roadcast `pull_fuel_report` probe using the site-76 ID | blocked | HTTP 404; test a mapped Roadcast device before implementing Roadcast parsing. |
| 2026-08-31 | local | Dedicated DG-fuel logging configuration | pass | `wareApp.dg_fuel` writes to rotating `logges/dg_fuel.log`. |
| 2026-08-31 | local | LocoNav mapped-site contract capture | pass | Sites 35, 76, and 92 returned the same level schema and millisecond timestamps. Site 35's returned timestamp was stale and requires a freshness rule. |
| 2026-08-31 | local | Roadcast mapped-site `pull_api` capture | partial | Sites 118, 153, 156, and 169 returned numeric `fuel` and ISO `lastUpdate`; configured IMEIs for sites 124 and 140 were absent. |
| 2026-08-31 | local | Roadcast site-118 `pull_fuel_report` capture | pass | IMEI request returned consumption, level history, refuel, and theft structures; Roadcast `deviceId` request returned HTTP 404. |
| 2026-08-31 | local | DG-fuel normalization and provider parser tests | pass | 11 tests passed. New modules are pure transformations and are not wired into the systemd poller. |
| 2026-08-31 | local | Complete isolated DG-fuel/provider unit suite | pass | 19 tests passed, including the existing legacy provider tests. |
| 2026-08-31 | local | DG-fuel ingestion Django tests | pass | 3 tests passed on a disposable test database with migration labels disabled. This verifies the new helpers without touching restored data. |
| 2026-08-31 | local | Standard Django test-database migration | blocked | Historical `wareApp.0004_auto_20221219_1233` adds an existing `updatedBy` column. This is outside DG-fuel scope and is not modified. |
| 2026-08-31 | local | DG-fuel read-only collection tests | pass | 3 tests passed. The new collector maps provider samples to sites and skips missing Roadcast IDs without creating records. |
| 2026-08-31 | local | DG-fuel dry-run poller unit tests | pass | 3 tests passed, including no-write proposed-sample output, missing-device output, and a separate Roadcast request-failure result. |
| 2026-08-31 | local | Real DG-fuel dry-run | blocked | Stopped before API calls and writes because `LOCONAV_API_KEY` is not configured. `ROADCAST_USERNAME` and `ROADCAST_PASSWORD` are also required. |
| pending | local | provider fixtures and parser suite | pending | |
| pending | test server | controlled write cycle | pending | |
| pending | main server | production promotion | pending | |

## Open Decisions Needed

1. How should sites 124 and 140 be handled until their configured Roadcast
  IMEIs appear in `pull_api`: skip with an operational alert, or update the
  IDs after confirmation from Roadcast?
2. What freshness threshold should reject a provider level sample? The live
  LocoNav value for site 35 and several Roadcast values were older than the
  collection cycle.
3. What soak duration and acceptable difference from provider values are needed
  before test-server approval?
4. Should Roadcast tank-level samples be collected at the same five-minute
  cadence as LocoNav, or at the provider's native update cadence?