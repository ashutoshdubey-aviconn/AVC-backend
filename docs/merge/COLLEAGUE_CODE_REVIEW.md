# Colleague's code: read-only review (19 Nov 2026)

**Repo:** `github.com/Daksh007-batman/New-asem-merger`. Branches `main` and `Ashutosh` are the same commit, `54313d5` (18 Nov 2026).

**How it was reviewed:**
- Cloned into `.work/colleague_repo` and compared with our tag `fov2-pre-merge-20261119`.
- His code was **not run** (no `manage.py check`, no tests). Nothing was pushed or changed in his repo.

**Side by side:** workbook [`CODE_INVENTORY.xlsx`](CODE_INVENTORY.xlsx), sheet "Ours vs colleague".
**Function by function:** sheet "Merge overlap (colleague)", or [`overlap_colleague_20261119.csv`](overlap_colleague_20261119.csv).
**Every API, his vs ours, what each does (21 Nov):** [`API_COMPARISON_COLLEAGUE_VS_OURS.xlsx`](API_COMPARISON_COLLEAGUE_VS_OURS.xlsx) (built by `build_api_comparison.py`).
**Every API on main's server vs his code (25 Nov):** sheets "Main vs his" and "Main vs his - problems" in the same workbook: 109 routes on main, 104 in his code; 5 missing (recovery upload, gateway-status, 2 monitoring lists, hourly Excel V1), 3 the frontend would call with the wrong method (POST vs his GET), 21 with a different login rule.
**Views merge, step 1 (21 Nov):** one decision per API view in [`views_merge_decisions_20261121.csv`](views_merge_decisions_20261121.csv) (also sheet "Views merge" in the analysis workbook): 4 merged from his code, 3 already the same, 123 kept ours.
**Detailed analysis, his vs ours, with examples (21 Nov):** [`COLLEAGUE_CODE_ANALYSIS.xlsx`](COLLEAGUE_CODE_ANALYSIS.xlsx) (built by `build_colleague_analysis.py`).
**His code vs the code on main's server** (APIs the frontend calls, DG fuel, LoadData, DB): [COLLEAGUE_VS_MAIN.md](COLLEAGUE_VS_MAIN.md).

## What his code is

| Commit | Date | What |
|---|---|---|
| `2755027` | 24 Jul | first commit (2 lines) |
| `6ea3c2f` | 24 Jul | "optimized backend code": the whole project, already restructured (159k lines incl. backups) |
| `54313d5` | 18 Nov | "complete alarm analysis flow, monitoring dashboard APIs, and notification policy": 82 files, +9,462 / −25,467 (mostly deleted backup copies) |

His structure:
- `wareApp/models/` package (8 modules)
- `wareApp/views/` with 7 `*_views.py` modules
- `wareApp/services/` (alarm, baseline, e-mail, fuel)
- `wareApp/tasks/` package
- `constants.py` with typed Enums
- a separate `mqtt_pipeline/`: MQTT → Redis list → dispatcher every 2 s → 6 Celery queues
- Docker files

## What is good in his code (worth porting)

| Feature | Where | Port into ours |
|---|---|---|
| Alarm dashboard APIs: `dashboard/alarms/summary/`, `live/`, `acknowledge/`, `daily-digest/` | `views/alert_views.py`, `services/alarm_service.py` | Build them on our single alarm table, `AlarmNotifications` (add an "acknowledged" field) |
| Notification policy: immediate e-mail only for HIGH priority, 6 h cooldown per site and type, the rest in a daily digest | `constants.py`, `services/email_service.py`, `tasks/alarm_tasks.py` | As settings on top of our repeat rule and `AlarmSetting` |
| Fuel Drain and Mains Higher Consumption alarms | `AlarmService.raise_fuel_drain_alarm`, `raise_mains_higher_consumption_alarm` | Ours lists type 5 as "not started" (N01) |
| Redis cache (`django-redis`) | `settings.py` | The same setting is on main's server |
| `tokens/` API | `urls.py` | Check what the frontend needs |
| Typed constants (Enums) | `constants.py` | Optional |
| Docker files | root | Can be added as they are |
| His alarm tests (34) | `tests/test_alarms.py` | Port them with the features |

## Problems found

| # | Problem | Detail |
|---|---|---|
| 1 | **Live credentials committed to GitHub** | Provider credentials (Loconav, Roadcast) appear in plain text in `ARCHITECTURE.md`, and there are hardcoded credentials in `warehouse/settings.py`, `fetch_fuel_data.py`, `fetch_fuel.py`, `loconav.py` and `reset_password.py`. Values are not repeated here. They should be rotated and removed from the repo, including its history. |
| 2 | **10 placeholder APIs** | These return a fixed message instead of data or a file: `downloadExcelLoadData/`, `loadDataExcel/test`, `dgFuelDataExcelExport/`, `hourly/data/excel/test`, `download/excel/test`, plus the PF, min/max, monthly-trend and `DownloadExcel_new` downloads, and `DemoApi`. Every Excel download on the frontend would break. |
| 3 | **Simplified views** | 60 of the 103 views we both have are less than half the size of ours. For example, `CustomerSnapshotApi` returns `alarms: 0` (the bug we fixed 6 Nov), and `SiteCeleryPingApi` went from 114 lines to 8. Each needs a functional check before it can replace ours. |
| 4 | **Migrations** | `0001_initial` is the same as main's, but then come his own `0002`–`0032`. Main's DB has `0001`–`0076`, so his migrations can't run on main's DB. Next to ours they form two leaf nodes, and Django refuses to migrate. |
| 5 | **Layout collisions** | His `wareApp/models/` and `wareApp/tasks/` packages would hide our `models.py` and `tasks.py` without any error. |
| 6 | **No outage alarms** | No Gateway Disconnected or Service / Modbus Issue alarm, no spike or catch-up handling, no idempotency or dead letters, no baseline setup or catch-up spread API. |
| 7 | **Two alarm tables** | `NewAlarmsNotifications` and the legacy `AlarmNotifications`. Our frontend alarm screens read the single table. |
| 8 | **Settings** | `DEBUG = True` also for PROD. `ALLOWED_HOSTS = ['*']` and allow-all CORS are hardcoded (ours reads them from `.env`, though our defaults are open too). |
| 9 | **Repo hygiene** | 72 `.pyc` / `__pycache__` files committed. One large commit with no history of what changed and why. |
| 10 | **Not verified** | We don't know whether it runs or passes its 44 tests: it was not run here. |
| 11 | **Anyone can take over any account** | Found 19 Nov (see [THREE_WAY_COMPARISON.md](THREE_WAY_COMPARISON.md)). `forgot/` needs only a username (no login, e-mail or mobile check, no rate limit), stores the fixed OTP `1234` and sends nothing; `reset/` accepts `1234` and sets the new password. The OTP never expires and is never used up. Login also has no rate limit and re-activates deactivated users. |

## Function-level overlap (his code vs ours)

Bases: legacy `origin/main` plus our branches that main's server took files from.

| Risk | Count | Meaning |
|---|---|---|
| HIGH | 111 | Both changed: mostly the same view classes rewritten differently on each side |
| HIGH | 306 | Theirs only: his new functions (`mqtt_pipeline`, `services`, `constants`, dashboard views) |
| MEDIUM | 167 | Only theirs changed |
| MEDIUM | 25 + 14 | They removed it, or different base versions |
| LOW | 830 | Ours only, or only ours changed |

As files: 21 files exist on both sides with the same path, and 18 of them differ. Apart from that, everything else is in different files or layouts. A git merge cannot resolve that; it has to be done by porting.

## Recommendation for the team lead

1. **Base = ours** (`full-optimization-v2`). It is deployed and verified on the test server, partly on main, has 514 tests, and its migrations follow main's history.
2. **Port his features onto it**, each as its own change, with tests and docs:
   - the alarm dashboard APIs and acknowledge;
   - the notification policy and digest;
   - Fuel Drain and Mains Higher Consumption;
   - Redis cache;
   - Docker.
3. **Leave out:** his placeholder or simplified views, his `0002`–`0032` migrations, his `models/` and `tasks/` layout, and the credentials.
4. **MQTT pipeline:** both designs solve the same problem. Keep ours for now, since it is in production. His Redis bridge can be evaluated later as a separate change, with a load test.
5. **Rotate the exposed credentials** whatever is decided (feature F09).
6. **Never deploy his `forgot/` / `reset/` / `login/`** as they are (problem 11).
