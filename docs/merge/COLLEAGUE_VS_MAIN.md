# Colleague's code vs main's code (19 Nov 2026)

What would change if the colleague's code (`github.com/Daksh007-batman/New-asem-merger` @ `54313d5`) replaced the code
that runs on main's server today. Read-only and static: nothing was run, and nothing was changed in either code base.
For his code compared with **our branch**, see [COLLEAGUE_CODE_REVIEW.md](COLLEAGUE_CODE_REVIEW.md).

**Main's code:** a copy of `~/django_project` on asem.aviconncorp.com taken 19 Nov, without `.env`. It is:
- the legacy `origin/main`;
- plus our branches `task_optimization`, `loaddatav1`, `fully_optimization` and `dg_fuel_v2` (the DG fuel system and LoadData updates);
- plus main's own hotfixes (see [MERGE_GUIDE.md](MERGE_GUIDE.md));
- with DB migrations `0001`–`0076`.

**His code** started from an older copy of main (his first full commit, 24 Jul) and was rewritten from there.

| File | What |
|---|---|
| [`colleague_vs_main_apis_20261119.csv`](colleague_vs_main_apis_20261119.csv) | every API view: verdict, request fields and response keys on each side, whether the frontend calls it |
| [`overlap_colleague_vs_main_20261119.csv`](overlap_colleague_vs_main_20261119.csv) | every function, class, setting and URL route |
| [`CODE_INVENTORY.xlsx`](CODE_INVENTORY.xlsx) | sheets "Colleague vs main (APIs)" and "Colleague vs main (functions)" |
| [`API_COMPARISON_COLLEAGUE_VS_OURS.xlsx`](API_COMPARISON_COLLEAGUE_VS_OURS.xlsx) | sheets "Main vs his" and "Main vs his - problems" (25 Nov, main snapshot): every active route on main next to his code, with missing routes, HTTP method the frontend sends vs his, and login rule. 109 routes on main (commented-out routes not counted), 104 in his code |

## In short

| Area | Main's code (today) | His code | If his code replaced main's |
|---|---|---|---|
| **APIs the frontend uses** | 71 of main's 112 routes are called by the frontend | 113 routes; 4 new dashboard alarm APIs, `tokens/` | **42 of the 69 shared APIs the frontend calls answer differently** (other request fields or other response keys), 6 of them Excel downloads that return a fixed text; `gateway-status/` is gone |
| **DG fuel** | `dg_fuel/` package (8 modules) + `fuel_providers.py`: Loconav / Roadcast polling, sessions, dedupe, Fuel Drain alarm, per-aisle fuel | Older fuel scripts + `services/fuel_service.py`; no `dg_fuel/` package | The DG fuel v2 system stops: its models' fields (`dg_fuel_enabled`, `dg_fuel_provider`, `fuel_data_source`, ...) are not in his models, and `DgFuelConsumptionDataApi_new` goes from 241 lines to 8 (last 100 raw rows, no units per litre) |
| **LoadData** | `load_data/` package (parser, raw, rollups, monthly, handler) | Redis `mqtt_pipeline` handlers + 13 Celery beat flush tasks (every 2–300 s) | Main's LoadData update is replaced by his pipeline: a different design, not tested on main's load |
| **Recovery / MQTT routing** | `recovery/` package, `mqtt/routing.py`, `mqtt/topics.py`, `v1/recovery/`, `upload/` | Recovery inside his `mqtt_pipeline` | These go; `v1/recovery/` and `upload/` routes disappear |
| **Alarms** | Same alarm types; Fuel Drain raised by `dg_fuel/sessions.py` | Same alarm types; `AlarmService` raises all 7 incl. **Mains Higher Consumption**; dashboard summary / live / acknowledge / digest; HIGH-only e-mail, 6 h cooldown | Gains: Mains Higher Consumption, acknowledge, digest. Losses: none of the alarm types |
| **DB** | Migrations `0001`–`0076`, 48 models | Migrations `0001` + his own `0002`–`0032`, 47 models | His migrations can't run on main's DB (different `0002`...). His models drop `HomeGatewayStatus` and the DG fuel fields; `MeterDisconnectionEvent.meter_id` is no longer unique and `status` shrinks to 20 chars |
| **Login / passwords** | `LoginApi` with rate limit; change / reset / forgot use base64 passwords and `result` / `msg` | Login works with base64 or plain, but **no rate limit**, and logging in **re-activates a deactivated user**; change / reset / forgot use other fields and keys | The frontend's change-password, reset and forgot-password screens break; disabled users can get back in; **his `forgot/` stores the fixed OTP `1234` and `reset/` accepts it: anyone can take over any account** |
| **Code layout** | One `views.py` (legacy) + our packages | `views/` split by area, `services/`, `constants.py` Enums, Docker, 44 tests | Cleaner layout, but see the contract problems above |

## Function level (main's code vs his)

Bases: legacy `origin/main`, his 24 Jul commit, and our branches that main took files from.

| Status | Count | Meaning |
|---|---|---|
| Same | 277 | identical |
| Theirs only | 260 | his new code: `mqtt_pipeline`, `services`, `constants`, dashboard views |
| Not on their side yet | 138 | main has it (from our branches: DG fuel, LoadData, routing, recovery), his code doesn't |
| They removed it | 43 | in legacy main and in main today, not in his code |
| Ours only | 32 | main's own hotfixes, not in his code |
| Different base versions | 212 | main has the legacy / our-branch version, he has his July version |
| Only theirs changed | 62 | main still has the base version, he changed it |
| Both changed | 5 | both changed it differently |
| Only ours changed / We replaced it | 10 / 38 | main changed it, he didn't / he has a base version main no longer uses |

By file, what main has and his code lacks: `views.py` 70, `tasks.py` 21, `dg_fuel/` 38, `load_data/` 20, `fuel_providers.py` 12,
`mqtt/` 14, `recovery/` 15, `models.py` 5, `routers.py` 5, `urls.py` 5.

## APIs: what breaks for the frontend

From `api_contract_check.py` (static: request fields read, keys returned). 106 view classes exist on both sides:

| Verdict | Views | Frontend calls |
|---|---|---|
| Response keys differ | 49 | most of the 42 below |
| Placeholder (fixed text, no data / file) | 9 | 6 |
| Calls another view instead | 19 | check the target |
| Same response keys / same plus extras | 29 | ok if request fields match |

Examples the frontend calls today:
- `login/` works, but `change-pwd/`, `reset/` and `forgot/` don't. Main takes base64 passwords and returns `result` / `msg`; his take plain fields and return `error` / `message`.
- `alarmList/`: main reads `siteId` and returns counts by type (`data`, `total_alarm`, `high_priority`, ...). His reads `site_id` and returns the last 50 alarms as `alarms`.
- `snapshot/`, `snapShotApi/`, `siteSnapShotEnergySavingApi/`: main returns energy and alarm totals. His returns other keys (for example no `total_energy_saved`, `alarms`, `percentage_saved`).
- `getSiteCurrLoadInfo/`: main returns phase values (`R_Voltage`, `R_Current`, `R_Power_Factor`, ...). His returns other keys.
- `liveDataLoadGraph/`, `dailyLoadGraph/`, `loadDataMainsDgDaily/`, `avgData/`: different request fields and response keys.
- `fetchDGFuelDataCustomeRange/`: main reads `from_date`, his reads `start_date`. The DG fuel keys (`dg_unit_per_litre`, ...) are gone.
- `meter-disconnections/`: main pages the results (`count`, `limit`, `offset`, `results`). His returns a plain list.
- `DownloadExcel/`, `downloadExcelLoadData/`, `dgFuelDataExcelExport/`, `downloadExcelPFData/`, `downloadExcelMonthlyMinMaxData/`: these return a fixed message instead of a file.
- Provisioning (`create...UsingProvisioning`), fire equipment and the password APIs read different request fields.
- `gateway-status/` (main's `HomeGatewayStatusApi`) doesn't exist in his code.

A static check can miss a response built in a helper. Treat this as the list to test against the frontend, not as proof.
The quickest real test would be his code against a copy of main's DB, with the frontend pointed at it. That has not been done.

## What his code does better than main's

- Alarms:
  - dashboard summary / live / acknowledge / daily digest APIs;
  - notification policy (HIGH-only immediate e-mail, 6 h cooldown, digest);
  - Mains Higher Consumption raised;
  - `acknowledged` fields.
- Code layout: views split by area, `services/`, typed constants, Docker files, 44 tests.
- Redis cache and a buffered MQTT pipeline (fewer DB writes per packet). Not load-tested.

## Conclusion

His code can't replace main's code as it is:
1. 42 of the APIs the frontend calls answer differently, and 6 downloads return no file.
2. Main's DG fuel v2 and LoadData updates aren't in it.
3. His migrations don't fit main's DB.
4. Login has no rate limit and re-activates disabled users.
5. Credentials are committed in his repo (see [COLLEAGUE_CODE_REVIEW.md](COLLEAGUE_CODE_REVIEW.md)).

What he added (alarms dashboard, notification policy, Mains Higher Consumption, layout, Docker, tests) is worth having.
It should be ported onto main's line of code, which is our `full-optimization-v2`: main's code plus the fixes since.
It should not go the other way round. Same recommendation as in the review.

## Re-run

```bash
virtualwarehouse/bin/python scripts/merge/overlap_check.py --ours .work/main_server_code_20261119 --theirs .work/colleague_repo \
  --base origin/main --base .work/colleague_base --base origin/task_optimization --base origin/loaddatav1 \
  --base origin/fully_optimization --base origin/dg_fuel_v2 --dirs mqtt_pipeline bridge \
  --out docs/merge/overlap_colleague_vs_main_YYYYMMDD.csv
python3 scripts/merge/api_contract_check.py --ours .work/main_server_code_20261119 --theirs .work/colleague_repo \
  --out docs/merge/colleague_vs_main_apis_YYYYMMDD.csv
virtualwarehouse/bin/python docs/merge/build_code_inventory.py
```
`.work/colleague_base` = his commit `6ea3c2f` (`git -C .work/colleague_repo archive 6ea3c2f | tar -x -C .work/colleague_base`).
