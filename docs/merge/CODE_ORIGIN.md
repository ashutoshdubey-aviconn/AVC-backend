# Whose code is it: ours or Daksh's

Written 2026-11-21, at the first merge from Daksh's (the colleague's) code, his repo
`github.com/Daksh007-batman/New-asem-merger` @ `54313d5`. Nothing is uploaded to his repo.

How to tell, in our repo, which code is ours and which came from him, now and after later merges
(MQTT, LoadData, DG fuel, alarms, anything).

## The tags

Annotated git tags, local (pushed only when we push tags).

| Tag | Commit | Meaning |
|---|---|---|
| `fov2-pre-merge-20261119` | `387ce4e7` | Our code before any merge work started (19 Nov). |
| `ours-before-daksh-views-merge-20261121` | `ed717fa2` | Our code just before his views came in. Everything up to here is ours, apart from main's own hotfixes listed in [MERGE_GUIDE.md](MERGE_GUIDE.md). |
| `daksh-views-merge-20261121` | `55017069` | His 4 API views merged: `LightsDataApi`, `FansDataApi`, `SubmeteringMonthlyBarChart_new`, `SubmeteringSnapshotAPI`. |

## Where each area comes from today

| Area | Our code | Daksh's equivalent | Merged from him? |
|---|---|---|---|
| MQTT listeners, routing, processing | `wareApp/mqtt/`, `wareApp/tasks.py` | `mqtt_pipeline/` (Redis bridge, dispatcher, buffers) | No. Ours only. His pipeline drops data (see the analysis workbook). |
| LoadData | `wareApp/load_data/`, `wareApp/views/load.py` | `mqtt_pipeline/handlers/load_data_handler.py`, `views/load_views.py` | No. Ours only. |
| DG fuel | `wareApp/dg_fuel/`, `fetch_fuel_data.py`, `wareApp/views/dg_fuel.py` | `services/fuel_service.py`, `views/dg_fuel_views.py` | No. Ours only. |
| Alarms | `wareApp/mqtt/services/` (alarms, closer, policy, gateway health, spikes), `wareApp/views/alarms.py`, `alarm_settings.py`, `monitoring.py` | `services/alarm_service.py`, `email_service.py`, `views/alert_views.py` | No. His dashboard / acknowledge / digest are on the port list, not merged yet. |
| Recovery, sync status, catch-up spread, baseline | `wareApp/recovery/`, `wareApp/catch_up_spread.py`, `views/sync_status.py`, `views/catch_up.py`, `views/baseline.py` | none | Ours only. |
| Models, migrations, settings | `wareApp/models.py`, `wareApp/migrations/`, `warehouse/settings.py` | `wareApp/models/`, his own `0002`–`0032`, his `settings.py` | No. Never take his migrations or his `models/` / `tasks/` packages. |
| Other API views | `wareApp/views/*.py` | `wareApp/views/*_views.py` | 4 views (above). Decision for every view: [views_merge_decisions_20261121.csv](views_merge_decisions_20261121.csv). |

So: **everything in `wareApp/mqtt/`, `load_data/`, `dg_fuel/`, `recovery/`, the alarm services and
the feature views is ours.** Until a commit says otherwise (below), nothing in those places came
from his code.

## Rules for every later merge from his code

1. **Tag before**: `ours-before-daksh-<area>-merge-YYYYMMDD` on our last commit before the merge.
2. **One commit per merge**, nothing else in it, with these trailers:
   ```
   Source: daksh@<his commit> <his files>
   Co-authored-by: Daksh Khatri <daksh.khatri@aviconncorp.com>
   ```
3. **Tag after**: `daksh-<area>-merge-YYYYMMDD` on that commit (areas: `views`, `mqtt`, `loaddata`,
   `dgfuel`, `alarms`, ...).
4. **One comment line** above each class or function taken from him (not on our code: markers
   on every function only create merge conflicts):
   ```python
   # Merged from the colleague's code (<his commit>, <his file>), <date>: <what changed>
   ```
5. **Decision file**: one row per item (taken / kept ours, why), like the views CSV, plus a
   CHANGELOG row.
6. **Our changes to a merged piece** are our own commits without the `Source:` trailer, so they
   stay ours.

If one of his ideas is rebuilt by us (for example batched LoadData writes on RabbitMQ instead of his
Redis buffers), it is our code: no `Source:` trailer, but say "idea from Daksh's code" in the
commit message.

## How to check

```bash
# Every merge from his code, and the tags
git log --grep="Source: daksh" --oneline
git tag -l 'daksh-*' 'ours-*'

# What one merge changed
git diff ours-before-daksh-views-merge-20261121 daksh-views-merge-20261121 --stat

# Classes / functions in the code that came from him
grep -rn "Merged from the colleague" wareApp/

# Who last changed a line (a merged line points to the Source: commit)
git blame wareApp/views/submetering.py

# Which functions changed since a tag? (function by function, comments ignored)
# "Only ours changed" rows = changed since the tag. On 21 Nov it lists exactly the 4 merged views.
virtualwarehouse/bin/python scripts/merge/overlap_check.py \
    --theirs ours-before-daksh-views-merge-20261121 --base ours-before-daksh-views-merge-20261121 \
    --out .work/origin_check.csv
```

The function list in [CODE_INVENTORY.xlsx](CODE_INVENTORY.xlsx) has a fingerprint for each of our
functions (built at `fov2-pre-merge-20261119`). Rebuilding it after a merge shows which of ours changed.
