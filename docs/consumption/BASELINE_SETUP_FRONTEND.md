# Baseline setup: frontend spec

For the frontend developer. Backend rules and workflow:
[BASELINE_SETUP.md](BASELINE_SETUP.md). The API is live on the test server
(`http://43.204.53.81/api/baselineSetup/`).

## Goal

One screen that replaces the manual baseline steps. The admin picks the sample
days, checks the calculated baseline per aisle, adjusts if needed, and sets it.
The backend then sets everything else (aisles active, site live, baseline date,
site manager, and all daily and hourly values from the start date to today).

## Who sees it

Super_Admin users only (`UserType` 1). Hide the screen / button for others; the
API answers them with HTTP 403.

## Where

On the site's **Baseline** page (where the per-aisle "Set Baseline" buttons
are today), add a button **"Automatic baseline"** that opens this screen. Keep
the old per-aisle buttons for single corrections.

## Screen layout

```
┌ Automatic baseline - <site name> ─────────────────────────────────────────┐
│ Sample days   [from: 2026/10/29]  [to: 2026/10/31]                         │
│ Baseline from [2026/11/01]  (optional; default = day after "to")           │
│                                                     [ Calculate ]          │
├────────────────────────────────────────────────────────────────────────────┤
│ Aisle          │ 29 Oct │ 30 Oct │ 31 Oct │ Average │ Baseline   │ Notes   │
│ MTS-FANS(G+3)  │ 149.20 │ 152.90 │ 153.17 │ 151.76  │ [151.76 ]  │         │
│ MTS-EL         │  45.40 │   -    │  44.96 │  45.18  │ [ 45.18 ]  │ ⚠ 30 Oct: no data (left out) │
│ ...                                                                        │
│                                         Site total: 788.40 kWh/day         │
├────────────────────────────────────────────────────────────────────────────┤
│ Site manager  [name]   [contact]   [e-mail]      (optional)                │
│                                                                            │
│ ⚠ Applies from 2026/11/01 to today: daily and hourly baseline and saving   │
│   are recalculated; aisles set active; site set live.                      │
│                                       [ Cancel ]   [ Set baseline ]        │
└────────────────────────────────────────────────────────────────────────────┘
```

- One column per sample day (up to 31). `-` when the day value is `null`.
- **Baseline** is an editable number, pre-filled with the API's `baseline`.
  If the user changes it, send it in `overrides` (see below).
- **Notes** shows the aisle's `warnings` (yellow). Errors (red) are shown above
  the table and disable **Set baseline**.
- **Site total** = sum of the Baseline column (recalculate when edited).
- Pre-fill the site manager fields from the site, if you already load it.

## Flow

1. User fills the sample days (and optional start date) and clicks
   **Calculate** → `POST /api/baselineSetup/` with `"apply": false`.
2. Show the table from `plan.aisles`, the warnings and `plan.errors`.
3. User edits values / site manager. Any change to the dates → back to step 1
   (the table must be recalculated).
4. **Set baseline** (enabled only when `plan.errors` is empty) → confirm dialog
   ("Set baseline from 2026/11/01 for 6 aisles of <site>?") → the same request
   with `"apply": true`, the edited values in `overrides` and the site manager.
5. Show the result: "Baseline set from 2026/11/01: 6 aisles, 30 daily and 720
   hourly readings updated." Then reload the Baseline page data.

Preview never changes anything, so **Calculate** can be clicked any number of
times. Apply is all-or-nothing: on an error nothing is saved.

## API

`POST /api/baselineSetup/`
Headers: `Authorization: Token <key>` (from `/api/login/`), `Content-Type: application/json`.

### Request

| Field | Type | Required | Notes |
|---|---|---|---|
| `site_id` | int | yes | |
| `sample_from` | string `YYYY/MM/DD` | yes | first sample day |
| `sample_to` | string `YYYY/MM/DD` | yes | last sample day; must be before today; at most 31 days |
| `effective_from` | string `YYYY/MM/DD` | no | default = day after `sample_to`; not in the future |
| `legs` | list of string | no | only these aisles (`leg_id`); default = all aisles of the site |
| `overrides` | object `{leg_id: number}` | no | baseline per aisle the user changed |
| `site_manager` | object `{name, contact, email}` | no | only non-empty fields are saved |
| `apply` | bool | no | `false` (default) = preview; `true` = save |

Preview:

```json
{"site_id": 198, "sample_from": "2026/10/29", "sample_to": "2026/10/31", "apply": false}
```

Apply (user changed MTS-EL to 45.0):

```json
{"site_id": 198, "sample_from": "2026/10/29", "sample_to": "2026/10/31",
 "effective_from": "2026/11/01", "overrides": {"1273": 45.0},
 "site_manager": {"name": "...", "contact": "...", "email": "..."}, "apply": true}
```

Send in `overrides` only the aisles the user changed (sending all is also fine).

### Response: preview (HTTP 200)

```json
{
  "status": 200,
  "applied": false,
  "plan": {
    "site_id": 198,
    "site_name": "Yusen Logistics Inventory-Savings Indore",
    "sample_from": "2026/10/29",
    "sample_to": "2026/10/31",
    "effective_from": "2026/11/01",
    "aisles": [
      {
        "leg_id": "1268",
        "aisle_name": "MTS-FANS(G+3)",
        "is_active": true,
        "days": {"2026/10/29": 149.2, "2026/10/30": 152.9, "2026/10/31": 153.17},
        "average": 151.76,
        "override": null,
        "baseline": 151.76,
        "warnings": []
      }
    ],
    "site_total": 788.4,
    "errors": []
  }
}
```

| Field | Use in the UI |
|---|---|
| `plan.effective_from` | Show "applies from"; send it back on apply |
| `plan.aisles[].days` | One cell per sample day; `null` = no data |
| `plan.aisles[].average` | Average column (`null` when no usable day) |
| `plan.aisles[].baseline` | Pre-fill of the editable Baseline cell |
| `plan.aisles[].warnings` | Notes column (yellow) |
| `plan.aisles[].is_active` | Optional badge "will be activated" when `false` |
| `plan.site_total` | Site total line |
| `plan.errors` | Red list above the table; disable **Set baseline** while not empty |

### Response: apply (HTTP 200)

Same as preview plus:

```json
{
  "applied": true,
  "result": {
    "baselines": {"1268": "created", "1273": "updated"},
    "backfill": {"daily": 30, "hourly": 720},
    "site": {"is_live": true, "live_date": "2026-09-28T16:18:00", "baseline_date": "2026-11-01T00:00:00",
             "site_manager": "...", "site_manager_contact": "...", "site_manager_email": "..."}
  }
}
```

`created` = new baseline from this date; `updated` = a baseline from the same
date already existed and got the new value.

### Errors

| HTTP | Body | Show |
|---|---|---|
| 400 | `{"status": 400, "error": "sample_to: expected YYYY/MM/DD, got '31-10-2026'"}` | the `error` text next to the form |
| 400 | `{"status": 400, "error": "sample days must be complete days before today"}` | " |
| 400 | `{"status": 400, "error": "MTS-NEW (1290): no usable sample day - give an override"}` | on apply with unresolved `plan.errors` (preview returns them in `plan.errors` with HTTP 200) |
| 400 | `{"status": 400, "error": "unknown site_id"}` | " |
| 403 | `{"detail": "Only Super_Admin users can set baselines."}` | "Not allowed" |
| 401 | `{"detail": "Authentication credentials were not provided."}` | login again |

Possible `warnings` texts (per aisle, informational):
`"30 Oct: no data (left out)"`, `"31 Oct: 0 kWh (left out)"`,
`"30 Oct: only 23 of 24 hours stored"`, `"30 Oct: Meter Reading Issue that day"`.

Possible `plan.errors` texts (block apply):
`"<aisle> (<leg>): no usable sample day - give an override"` → let the user
type a value (it is sent as an override and the error disappears on the next
Calculate); `"<aisle> (<leg>): a later baseline starts YYYY/MM/DD; choose an
effective_from on or after it"` → change the start date.

## Validation in the form (before calling)

- Both sample dates set, `from` ≤ `to`, `to` before today, at most 31 days.
- `effective_from` not in the future.
- Baseline cells: numbers ≥ 0.
- E-mail field: valid e-mail when filled.

The backend checks all of these again.

## Test it

```bash
curl -s -X POST http://43.204.53.81/api/baselineSetup/ \
  -H "Authorization: Token <key>" -H "Content-Type: application/json" \
  -d '{"site_id": 198, "sample_from": "2026/10/29", "sample_to": "2026/10/31"}'
```

Use preview (`"apply": false`, the default) freely. Apply changes real data on
the server it is sent to.
