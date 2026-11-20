# Catch-up spread

Since 2026-11-16, reworked 2026-11-20 (rules agreed with the user). Code: `wareApp/catch_up_spread.py`,
API `CatchUpSpreadApi` in `wareApp/views/catch_up.py`, Celery task `auto_spread_catch_ups`,
models `CatchUpSpread` (migrations 0114, 0115) and `RecoveryMonitor.error_hours` (0115).
Frontend: site page → **Spread catch-up** (`catch-up-spread.component`).

## Why

A gateway service (pymodbus / PostgreSQL / Celery) stops and nothing is saved for some hours. When it
starts again its first reading is "new meter reading − last saved one", so the whole gap's energy lands
in **one hour**. Example: site 114 Myntra BGLR Inventory, F1-Outward&Hub area: hours until 14 Nov
19:00, nothing on 15 Nov, then **16 Nov 09:00 = 43.60 kWh** (≈ 37 missing hours × 1.18 kWh). The
energy is real but on the wrong hours and days: 15 Nov shows 0, 16 Nov looks like a Bypassed day.

Site 114 on main, 1 Sep – 20 Nov: 863 such catch-up hours on its 38 aisles (469 gaps ≤ 6 h, 264 of
7–24 h, 130 of 1–7 days); in 798 the share per hour is 0.5–2 × the aisle's normal hour, i.e. the hour
really carries the missing hours' energy (analysis: `.work/spread_114_analysis/`).

## What is a catch-up (the proof)

* The hour before the gap has **real data**.
* The gap is hours **without a row**, or hours stored as **0 because the gateway answered ERROR404**
  during recovery (no data on the gateway). Which hours were ERROR404 is kept on the recovery request
  (`RecoveryMonitor.error_hours`, since 20 Nov; for older requests: the run of 0 kWh hours right before
  the recorded catch-up hour, at most `error_slots` long). **Real 0 kWh hours are never taken.**
* The first hour after the gap is more than **3 × the aisle's normal hour** (median of the non-zero
  hours of the 7 days before the gap).
* A normal-sized first hour after a gap is **genuine**: nothing is spread (the gap stays as it is).

The Consumption Spike alarm (17) uses the same proof: since 20 Nov a big hour after a gap is a catch-up
even when it is above the whole daily baseline (before, it was called a "meter jump"), and ERROR404
hours count as gap. A big hour **without** a gap is a meter jump: never spread, e-mailed as a
Consumption Spike alarm.

## When it is offered

Only when all of these hold (else it is listed under **Waiting for sync / recovery** with the reason):

1. the aisle is **synced** again (`AisleSyncRecoveryStatus`: healthy or recovered);
2. the **hour after** the catch-up has arrived;
3. **recovery** of the gap has ended (no open request for the aisle).

The gap start must be known: a real reading in the 31 days before (else **not spreadable**).

## Clear case or manual spread required

| Check | Clear (automatic allowed) | Otherwise |
|---|---|---|
| Share per hour | ≤ 3 × the normal hour | "probably more than a catch-up (meter jump?)" |
| Spread day (share × 24) vs the aisle's daily average (median of the non-zero days in the 14 days before the gap) | 0.5–1.5 × | "a spread day would be X kWh, the aisle's daily average is Y kWh" |
| Daily average known | yes | "no daily average before the gap" |

There is no fixed gap-length limit: a long gap is fine when its spread days match the daily average.
A case with a reason is shown with **Manual spread required**, is not ticked by default, and is never
spread automatically.

## What a spread does

```
before   14 Nov … 19:00 1.2 │ 20:00 … 16 Nov 08:00: no rows (or ERROR404 0) │ 09:00 43.60 │ 10:00 1.2 …
after    14 Nov … 19:00 1.2 │ 20:00 … 08:00: 37 hours of 1.147            │ 09:00 1.147 │ 10:00 1.2 …
share = 43.60 / (37 gap hours + 1) = 1.147 kWh (flat)
```

One transaction per catch-up:

* every gap hour (created where there is no row, updated where it is an ERROR404 0) and the catch-up
  hour get the share, with the aisle's hourly baseline and saving; they are **real readings** (no
  estimated mark);
* **hourly and daily** of every touched day are recalculated (a missing day such as 15 Nov is created);
* that day's Consumption Spike alarm is closed: "Spread (manual|automatic): 09:00 43.60 kWh over 38 h
  from 14 Nov 20:00 (catch-up)";
* a `CatchUpSpread` row records site, aisle, catch-up hour, original kWh, gap, hours, share, **mode**
  (manual with the user / automatic), when, and **one line per hour** (`hours_detail`: hour, kind
  `empty` / `no_data` / `catch_up`, kWh before, kWh after).

Total energy does not change.

**After a spread the values are the stored data.** Hourly and daily recovery replies leave the spread
hours and days alone (`spread_hours` / `spread_days`); only a future manual sync could change them.

## Undo (5 days)

Possible for **5 days** after the spread (`undo_until`), then the link shows "closed" and the API
refuses. Undo uses the per-hour record: created hours removed, ERROR404 hours back to 0, the catch-up
hour back to its original kWh, days recalculated.

## Automatic spread (night job)

Celery beat task `auto_spread_catch_ups` every `CATCH_UP_AUTO_SECONDS` (1800). It works only
**19:00–11:00 every day and all day on Sunday** (`CATCH_UP_AUTO_FROM_HOUR` / `_UNTIL_HOUR`), when nobody
is on duty, over the last `CATCH_UP_AUTO_DAYS` (3) days of every monitored site:

* clear cases are spread with mode **automatic**;
* cases needing a manual spread are left, and the **software team** gets one e-mail per site per run
  listing the new ones with their reason ("Catch-up spread: manual spread required"); each catch-up is
  e-mailed once (14 days).

First run on test (20 Nov 23:52): 49 catch-ups of site 114 spread (18–20 Nov), 4 e-mailed (spread days
1.6–1.8 × the daily average), 18 waiting.

## API

`POST /api/catchUpSpread/` (token, Super_Admin; others get 403)

| Request | Meaning |
|---|---|
| `{"site_id": 114, "day": "2026/11/16"}` | Preview all aisles of the site |
| `{"site_id": 114, "day": "2026/11/16", "legs": ["692"]}` | Preview some aisles (leg ids) |
| `… "apply": true` | Spread what the preview shows (manual) |
| `{"undo": 12}` | Undo spread 12 (within 5 days) |
| `{"site_id": 114, "history": true, "from": "2026/11/01", "to": "2026/11/20"}` | The site's spreads (≤ 92 days), with their hours |

Preview response (shortened):

```json
{
  "status": 200, "applied": false,
  "catch_ups": [
    {"leg_id": "692", "aisle_name": "F1-Outward&Hub area", "catch_up_at": "2026/11/16 09:00", "kwh": 43.6,
     "gap_from": "2026/11/14 20:00", "gap_to": "2026/11/16 08:00", "missing_hours": 37,
     "empty_hours": 37, "no_data_hours": 0, "share_kwh": 1.147, "normal_hour_kwh": 1.2,
     "spread_day_kwh": 27.54, "daily_average_kwh": 27.5,
     "days": [{"day": "2026/11/14", "before": 24.0, "after": 28.59}, {"day": "2026/11/15", "before": 0.0, "after": 27.54}],
     "manual_required": false, "warnings": []}
  ],
  "waiting": [{"leg_id": "680", "aisle_name": "F2-E~G Block", "at": "2026/11/20 10:00", "kwh": 5.1,
               "missing_hours": 5, "reason": "recovery of the gap is still running (asked from the gateway)"}],
  "not_spreadable": [],
  "applied_spreads": [{"id": 12, "mode": "automatic", "applied_by": "automatic", "applied_at": "2026/11/20 23:52",
                       "can_undo": true, "undo_until": "2026/11/25 23:52", "empty_hours": 5, "no_data_hours": 0, "...": "..."}]
}
```

Apply adds `"applied": true, "spreads": [{"id", "leg_id", "catch_up_at", "hours", "share_kwh", "mode"}]`.
Undo returns `{"status": 200, "undone": 12, "hours_reverted": 37}`. Errors: HTTP 400 `{"error": ...}`
(bad day, unknown site / leg / spread, nothing to spread, changed since the preview, already undone,
undo after 5 days, history longer than 92 days).

## Frontend

Site page → **Spread catch-up** (or **Spread…** on a Consumption Spike row):

1. Day picker → table of catch-ups to spread: gap (with "N without data · M ERROR404"), share, normal
   hour, day totals before → after; **Manual spread required** tag and reason on doubtful rows (not
   ticked).
2. **Waiting for sync / recovery** and **cannot be spread** lists with the reason.
3. Tick → **Spread N catch-up hour(s)…** → inline confirmation.
4. **Spread on this day**: each spread as **Manual · user** or **Automatic**, Undo with "until …" for 5
   days, then "closed (5 days passed)".
5. **History**: date range, every spread (manual / automatic, undo state); click the hours to see each
   hour before → after.

## Tests

`wareApp/tests/test_catch_up_spread.py` (18): preview of the site 114 case changes nothing; apply makes
real hours, recalculates 14 / 15 / 16 Nov, keeps the total energy, closes the spike, records every
hour; undo within 5 days and refused after; ERROR404 hours are the gap (and the older-request
fallback); real 0 kWh hours are not a gap; waiting until synced / recovered / next hour in; daily-
average and meter-jump doubts; recovery leaves spread hours and days alone; a big hour after a gap is a
catch-up, not a meter jump; night window; automatic spread of a clear case; doubtful case e-mailed
once; API preview / apply / undo / history, permissions and errors. Frontend:
`catch-up-spread.component.spec.ts`.

## Rolling back

Undo the spreads within 5 days (API or `catch_up_spread.undo`), set `CATCH_UP_AUTO_SECONDS=0` to stop
the night job, then revert the commit. Before migration 0115 on test, the spreads and their hours were
saved in `fov2_backup_catchupspread_20261120` and `fov2_backup_spread_hours_20261120`.
