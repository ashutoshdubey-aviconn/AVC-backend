# Catch-up spread

Since 2026-11-16. Code: `wareApp/catch_up_spread.py`, API view
`CatchUpSpreadApi` in `wareApp/views/catch_up.py`, models `CatchUpSpread` and
`HourlySiteReading.is_estimated` (migration 0114). **Triggered from the
frontend only**; nothing is spread automatically.

## Why

When a gateway stores nothing for a while and then comes back, its first hour
carries the whole gap's consumption (the meter kept counting). Example: site
114 Myntra BGLR Inventory, F1-Outward&Hub area: hours until 14 Nov 19:00,
nothing on 15 Nov, then **16 Nov 09:00 = 43.60 kWh** (≈ 37 missing hours ×
1.18 kWh). The energy is real but lands on the wrong day: 15 Nov shows 0, and
16 Nov looked like a Bypassed day. The Consumption Spike alarm reports such an
hour; this tool moves its energy to the hours it belongs to.

## What it does

```
before   14 Nov … 19:00 1.2 │ 20:00 … 15 Nov … 16 Nov 08:00: no rows │ 09:00 43.60 │ 10:00 1.2 …
after    14 Nov … 19:00 1.2 │ 20:00 … 08:00: 37 rows of 1.147 (estimated) │ 09:00 1.147 (estimated) │ 10:00 1.2 …
share = 43.60 / (37 missing + 1) = 1.147 kWh
```

1. **Find** (preview): on the chosen day, per aisle, an hour that comes right
   after a gap (no reading the hour before) and is more than 3 × the aisle's
   normal hour (median of the last 7 days). Gap = from the hour after the last
   reading to the hour before the catch-up.
2. **Spread** (apply, one transaction per catch-up):
   - the catch-up hour becomes the share; every missing hour is created with
     the share; all of them `is_estimated = True`, with the aisle's hourly
     baseline and saving;
   - the daily totals of every touched day are recomputed from the hours
     (created where missing, e.g. 15 Nov);
   - that day's Consumption Spike alarm is closed: "Spread: 09:00 43.60 kWh
     over 38 h from 14 Nov 20:00 (catch-up)";
   - a `CatchUpSpread` row records site, aisle, hour, original kWh, gap,
     share, who and when.
3. **Undo**: removes the created estimated hours, restores the catch-up hour's
   original value and recomputes the days.

The total energy does not change (no kWh lost or added).

## Rules and limits

| Case | Result |
|---|---|
| Big hour right after a gap of ≤ 7 days | Spreadable |
| Share still > 3 × the normal hour | Spreadable, with a warning: probably more than a catch-up (meter jump?) |
| Normal-sized hour after a gap (e.g. our own server was down) | Not a catch-up: not listed |
| Big first hour with **no reading in the 7 days before** | Listed under `not_spreadable` (gap start unknown) |
| Catch-up hour changed since the preview | Refused, nothing written |
| Missing hour that already has a row | Kept; only real gaps are filled |

Limitation: if the gateway later re-sends real readings for the gap (hourly
recovery), they overwrite the estimated rows, but the catch-up hour keeps its
share. Undo the spread first if real recovery is expected.

No alarms or e-mails are raised for the recomputed past days.

## API

`POST /api/catchUpSpread/` (token, Super_Admin; others get 403)

| Request | Meaning |
|---|---|
| `{"site_id": 114, "day": "2026/11/16"}` | Preview all aisles of the site |
| `{"site_id": 114, "day": "2026/11/16", "legs": ["692"]}` | Preview some aisles (leg ids) |
| `… "apply": true` | Spread what the preview shows |
| `{"undo": 12}` | Undo spread 12 |

Response (preview):

```json
{
  "status": 200,
  "applied": false,
  "catch_ups": [
    {"leg_id": "692", "aisle_name": "F1-Outward&Hub area", "catch_up_at": "2026/11/16 09:00", "kwh": 43.6,
     "gap_from": "2026/11/14 20:00", "gap_to": "2026/11/16 08:00", "missing_hours": 37,
     "share_kwh": 1.147, "normal_hour_kwh": 1.2,
     "days": [{"day": "2026/11/14", "before": 24.0, "after": 28.59},
              {"day": "2026/11/15", "before": 0.0, "after": 27.54},
              {"day": "2026/11/16", "before": 54.4, "after": 22.27}],
     "warnings": []}
  ],
  "not_spreadable": [
    {"leg_id": "...", "aisle_name": "...", "at": "2026/11/16 09:00", "kwh": 31.17, "normal_hour_kwh": 0.9,
     "reason": "no reading in the 7 days before it: the gap's start is unknown"}
  ]
}
```

Apply adds `"applied": true, "spreads": [{"id": 12, "leg_id": "692", "catch_up_at": "...", "hours": 38, "share_kwh": 1.147}]`.
Undo returns `{"status": 200, "undone": 12, "estimated_hours_removed": 37}`.
Errors: HTTP 400 `{"status": 400, "error": "..."}` (bad day, unknown site / leg / spread, nothing to spread, changed since preview, already undone).

## Frontend (suggested)

On the site page, next to the Consumption Spike alarms or the daily chart:

1. **"Spread catch-up"** → pick the day (pre-filled with the spike's day) →
   preview table: aisle, catch-up hour, kWh, gap from → to, missing hours,
   share, normal hour, and per touched day the total before → after; warnings
   in yellow; `not_spreadable` in a grey list with the reason.
2. Tick the aisles to spread (sent as `legs`) → **Apply** (confirm dialog).
3. Show the result and keep the spread id; offer **Undo** for it.
4. Charts may show `is_estimated` hours differently (e.g. hatched) once the
   hourly API returns the flag.

## Tests

`wareApp/tests/test_catch_up_spread.py`: preview of the site 114 case (gap,
share, day totals) changes nothing; apply creates 37 estimated hours, keeps
the total energy, recomputes 14 / 15 / 16 Nov (15 Nov created), closes the
spike, records the spread; undo restores everything and refuses a second undo;
changed since preview is refused; a normal hour after a gap is not a catch-up;
a huge jump gets a warning; a big first hour without earlier readings is
reported as not spreadable; API preview / apply / undo, Super_Admin only, bad
input.

## Rolling back

Undo each applied spread (API or `catch_up_spread.undo`); then revert the
commit. Migration 0114 adds the `is_estimated` column (instant) and the
`CatchUpSpread` table.
