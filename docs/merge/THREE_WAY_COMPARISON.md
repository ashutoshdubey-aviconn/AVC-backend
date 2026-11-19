# Three-way comparison: main's code, our code, the colleague's code (19 Nov 2026)

| Name | What it is | Where it runs |
|---|---|---|
| **Main** | The code on main's server (copy taken 19 Nov, without `.env`): the legacy `origin/main`, plus our branches `task_optimization`, `loaddatav1`, `fully_optimization` and `dg_fuel_v2`, plus main's own hotfixes | main's server (production) |
| **Ours** | `full-optimization-v2` (tag `fov2-pre-merge-20261119`): main's line of code, plus the optimizations, fixes and new alarms since | test server; parts of it are on main |
| **Colleague** | `github.com/Daksh007-batman/New-asem-merger` @ `54313d5` (18 Nov): a rewrite started from an older (July) copy of main | not known to run anywhere; not run here |

The comparison is static (ast and file reads), and nothing was run. The details:
- [COLLEAGUE_VS_MAIN.md](COLLEAGUE_VS_MAIN.md): colleague vs main.
- [COLLEAGUE_CODE_REVIEW.md](COLLEAGUE_CODE_REVIEW.md): colleague vs ours.
- [MERGE_GUIDE.md](MERGE_GUIDE.md): ours vs main, including main's own edits.

Workbook: [`CODE_INVENTORY.xlsx`](CODE_INVENTORY.xlsx), sheet "Three-way comparison", plus one APIs sheet per pair.

## 1. Will the frontend keep working? (API contract)

`scripts/merge/api_contract_check.py` takes the code the frontend works with today and the code that would replace it. It compares, view by view, the request fields read and the response keys returned, and notes whether the frontend calls that API.

| If this replaced that | Views on both sides | Answer differently | ...of them called by the frontend | Placeholder downloads | Frontend APIs missing |
|---|---|---|---|---|---|
| **Ours replacing main** | 122 | 5 | **4, all deliberate fixes** (below) | 0 | none |
| **Colleague replacing main** | 106 | 65 | **42** | 9 (6 the frontend calls) | `gateway-status/` |
| **Colleague replacing ours** | 103 | 62 | **40** | 9 | `gateway-status/`, `baselineSetup/`, `catchUpSpread/`, `temp/dispatch/mail/` |

The 4 differences between ours and main that the frontend sees:
- `forgot/` no longer returns the OTP in the response. That was a security hole on main: anyone could reset any password. A setting, `PASSWORD_RESET_RETURN_OTP`, can turn it back on for old clients.
- `reset/` also accepts `Username`.
- `alarmapi/` and `alarmTypeApi/` no longer read an `id` / `user_id` field that main reads but never uses.

The response keys are the same, so the frontend screens work. Ours also adds three APIs the frontend now uses: baseline setup, catch-up spread, and gateway overheat mail.

CSVs:
- [`ours_vs_main_apis_20261119.csv`](ours_vs_main_apis_20261119.csv)
- [`colleague_vs_main_apis_20261119.csv`](colleague_vs_main_apis_20261119.csv)
- [`colleague_vs_ours_apis_20261119.csv`](colleague_vs_ours_apis_20261119.csv)

## 2. Side by side

| Area | Main | Ours | Colleague |
|---|---|---|---|
| History | git: none on the server; files equal our branches + hotfixes | git, on main's line; tag before merge | own repo, no shared git history |
| DB migrations | `0001`–`0076` | `0001`–`0076` (main's) + `0077`–`0114` | `0001` + his own `0002`–`0032` (can't run on main's or our DB) |
| Models | 47 | 52 (all of main's + alarm, outage, baseline and sync tables) | 46 (drops `HomeGatewayStatus` and the DG fuel fields) |
| API routes | 112 | 113 | 113 |
| Frontend contract | the reference | same, except the 4 fixes above | 42 of the 69 frontend APIs differ; 6 downloads return a fixed text |
| DG fuel | `dg_fuel/` v2 (Loconav / Roadcast, sessions, Fuel Drain) | same package + fixes (provider credentials from `.env`, session and fuel-view fixes) | old fuel scripts + `fuel_service.py`; no `dg_fuel/` |
| LoadData | `load_data/` (loaddatav1) | same + rollups only since the last rolled minute, failures kept as dead letters with a replay command | Redis `mqtt_pipeline` + 13 beat flush tasks (2–300 s) |
| MQTT ingestion | `mqtt/routing.py` → Celery queues | batched consumption writes, site partitions, idempotency, dead letters, catch-up / spike handling | Redis list → dispatcher every 2 s → 6 queues |
| Alarms raised | voltage, PF, consumption high / low, Fuel Drain, DG without load, legacy alarms | main's + **Meter Disconnected, Gateway Disconnected, Gateway Service / Modbus, Consumption Spike, Bypassed, Meter Reading Issue, Operation Hours, Gateway Overheat**; one alarm table, repeat rule, auto-close | main's types + **Mains Higher Consumption**; dashboard summary / live / **acknowledge** / daily digest; HIGH-only e-mail, 6 h cooldown |
| Alarm types defined but not raised | DG Overtime, Fuel Under Level, Mains Higher | the same three (N01 not started) | raises all 7 power / fuel types |
| Baseline / data tools | — | baseline setup screen API, catch-up spread, rebuild commands | — |
| Tests | 0 | **514** | 44 |
| Code layout | one 11k-line `views.py` + packages | `views/` split by area (no logic change), `mqtt/`, `dg_fuel/`, `load_data/` | `views/` by area, `services/`, typed `constants.py`, Docker |

## 3. Security

| Item | Main | Ours | Colleague |
|---|---|---|---|
| Password reset | **`forgot/` returns the OTP in the response** | OTP only by e-mail; random, single use, 10 min, rate-limited | **OTP is always `1234`**; `forgot/` needs only a username, `reset/` accepts `1234`: **anyone can take over any account** |
| Login | rate-limited | rate-limited; no password in logs | **no rate limit**; logging in **re-activates a deactivated user** |
| Secrets | SMTP password and Roadcast login hardcoded in code | from `.env` | committed to GitHub (in `ARCHITECTURE.md` and 5 code files) |
| `DEBUG` | from the environment (off on PROD) | from `.env` (off on PROD) | **`True` on PROD too** |
| Provisioning `create customer` | open API, fixed default password | same (inherited, still open: to fix) | takes the password from the request |

## 4. Function level

`scripts/merge/overlap_check.py`, against the legacy code and our branches that main took files from:

| Pair | Same | Only on the first side | Only on the second side | Changed on one side | Both changed |
|---|---|---|---|---|---|
| Ours vs main | (not counted) | Ours only 548 | Main only 21 | Only ours 166, only main 9 | 18 |
| Ours vs colleague | (not counted) | Ours only 582, not on his side 162 | His only 306 | Only ours 37, only his 167 | 111 |
| Main vs colleague | 277 | Main only 32, not on his side 138 | His only 260 | Only main 10, only his 62 | 5 |

Main has only 21 functions of its own that ours lacks, plus 18 that both changed. These are main's hotfixes and are listed with an action in the [merge guide](MERGE_GUIDE.md).
The colleague's code has 260–306 new functions, and lacks 138–162 of main's or ours.

## 5. Conclusion

- **Ours** is a superset of **main**:
  - the same DB history, the same frontend contract, DG fuel and LoadData included;
  - more alarms, 514 tests, and the security fixes;
  - still to do: bring in main's few hotfixes before the switch (merge guide).
- **The colleague's** code is a separate rewrite. Replacing either main or ours with it would:
  1. break 40+ frontend APIs;
  2. drop DG fuel v2;
  3. need a new DB history;
  4. open a password-reset hole that lets anyone take over any account.
- What it adds is still worth having: the alarm dashboard, acknowledge and digest, the notification policy, Mains Higher Consumption, the layout, Docker and tests. Port these onto ours one at a time.
- **Act now, whatever the merge decision:**
  - rotate the credentials committed in his repo;
  - don't deploy his `forgot/` / `reset/` anywhere;
  - close the open provisioning API on ours and main.

## Re-run

```bash
python3 scripts/merge/api_contract_check.py --ours .work/main_server_code_20261119 --theirs . --out docs/merge/ours_vs_main_apis_YYYYMMDD.csv
python3 scripts/merge/api_contract_check.py --ours .work/main_server_code_20261119 --theirs .work/colleague_repo --out docs/merge/colleague_vs_main_apis_YYYYMMDD.csv
python3 scripts/merge/api_contract_check.py --ours . --theirs .work/colleague_repo --out docs/merge/colleague_vs_ours_apis_YYYYMMDD.csv
virtualwarehouse/bin/python docs/merge/build_code_inventory.py
```
