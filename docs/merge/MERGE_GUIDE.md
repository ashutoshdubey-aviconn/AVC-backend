# Merging this branch with the colleague's code

Written 2026-11-19, before the merge. Two code bases started from the same legacy code:

- **ours**: `full-optimization-v2`, tagged `fov2-pre-merge-20261119`.
- **theirs**: the colleague's optimized version of the legacy code (`origin/main`). Main's server runs that legacy code plus our earlier DG fuel and LoadData rollouts.

Files here:

| File | What |
|---|---|
| [`CODE_INVENTORY.xlsx`](CODE_INVENTORY.xlsx) | Everything this branch has: features, alarms, APIs, Celery tasks, commands, DB models, migrations, modules, every function (what it does, new / changed / moved, tests, fingerprint), tests, and why it is better than the legacy code. Built by `build_code_inventory.py`. |
| [`overlap_main_server_20261119.csv`](overlap_main_server_20261119.csv) | Function-level comparison of ours against main's current code, copied read-only on 19 Nov. It is also the "Merge overlap (main)" sheet. |
| [`COLLEAGUE_CODE_REVIEW.md`](COLLEAGUE_CODE_REVIEW.md) | Read-only review of the colleague's repo (`Daksh007-batman/New-asem-merger` @ `54313d5`): what to port, problems found, recommendation. Overlap: [`overlap_colleague_20261119.csv`](overlap_colleague_20261119.csv). |
| [`../../scripts/merge/overlap_check.py`](../../scripts/merge/overlap_check.py) | Makes that comparison against any code base (a folder or a git ref). |

## Marking our code before the merge

1. **Git tag, not comments in the code.** `fov2-pre-merge-20261119` marks exactly what we had before the merge. Use it to compare, review or go back. Do not add `# ours` markers to functions: every marker is a changed line, which means more conflicts, not fewer.
2. **Fingerprints.** Every function and class in the Functions sheet has a fingerprint, a hash of its source with comments and formatting ignored. After the merge, the check below shows which of our functions changed.
3. **Ownership comes from the inventory.** Each function's "Origin" (New / Changed / Moved, unchanged) says what this branch wrote. The overlap sheet says what the other side touched.

## Where each code base lives

| Code | Where | State (19 Nov) |
|---|---|---|
| Legacy code (the common base) | `origin/main` | Unchanged since 23 Dec 2025 (`7d2dacde`); no commits from the colleague there yet |
| Ours | `full-optimization-v2` / `-next`, tag `fov2-pre-merge-20261119` | This inventory |
| Main's server | `~/django_project` on main (not a git checkout) | Legacy code + our two earlier rollouts + a few hotfixes made on the server |

Main's DG fuel and LoadData files are **exact copies** of our own branches (`dg_fuel_v2`, `fully_optimization`, `task_optimization`, `loaddatav1`). They are not new code, so they are compared against those branches (the default bases of `overlap_check.py`).

Main's **own edits**, the only code there that is in none of our branches:

| Edit on main | File | In ours? | Action |
|---|---|---|---|
| Customer 74 (YusenLogistics) in the super-admin customer lists | views.py (`CustomerSnapshotApi.post`, `LoadGraphApi*.post` ...) | Yes (17 Nov) | Keep ours |
| User type 6 `AVC_Super_admin` | models.py `User.user_type` | No | Port (choices only, no migration needed for data) |
| `MonitoringCustomerSitesInfo` API: `monitoringCustomerSites/`, `monitoringSitesList/` (sites that send consumption pings) | views.py, urls.py | No | Port into `wareApp/views/monitoring.py` + urls |
| Redis cache `CACHES` | settings.py | No (ours uses the default cache setting) | Port; our cooldown / site cache / idempotency then use Redis |
| Admin pages for HomeGatewayStatus and MeterDisconnectionEvent | admin.py | No | Port |
| AisleGroup `dg_fuel_enabled` / `dg_fuel_provider` / `dg_fuel_vehicle_number` and more | models.py, migrations 0075 / 0076 (applied 31 Oct) | Partly (ours has DG fuel per aisle differently) | Compare fields, map in the migration reconciliation |
| `_deferred_task`: a no-op decorator that turns the later duplicate task definitions in tasks.py into plain functions | tasks.py | Not needed (ours has one definition per task) | Keep ours |
| A commented-out MQTT login in tasks.py | tasks.py | No | Do not port; part of the credential clean-up (F09) |

## Why conflicts are expected

- `wareApp/views.py`: ours is split into `wareApp/views/` (18 modules), while main keeps one file of about 11,000 lines. A change in `views.py` must be applied to our matching file, and the overlap sheet names that file ("Our file").
- `wareApp/tasks.py`: ours moved MQTT handling to `wareApp/mqtt/`.
- **Migrations:** ours are `0059`–`0114`, but main's DB applied its **own** `0073`–`0076`. Same numbers, different migrations, so a plain `migrate` fails. A reconciliation step is needed (see [MAIN_SERVER_ROLLOUT.md section 3](../deploy/MAIN_SERVER_ROLLOUT.md)).

Overlap counts (main's code vs ours, all our branches as bases):

| Risk | Count | What it means |
|---|---|---|
| HIGH | 18 | **Both changed**. Mostly our rewrite against a small hotfix on main (e.g. customer 74, user type 6), or main's `_deferred_task` copies of the `process_*_message` tasks. Check each one; usually keep ours and add the hotfix. |
| HIGH | 21 | **Theirs only**: on main, not in ours. These are the main-only edits in the table above, plus legacy fuel helpers in tasks.py (`DG_fuel_for_Roadcaste`, `get_loconav_fuel_data`, `roadcasteAPIUpdated`) that ours replaced with `wareApp/dg_fuel/`. |
| MEDIUM | 9 | **Only theirs changed**, so port it (AisleGroup / MeterDisconnectionEvent fields, `_dg_fuel_db_alias`, `DATABASE_ROUTERS`, `SiteCeleryPingApi`, `MeterDisconnectionIngestView.post`). |
| MEDIUM | 18 | **Different base versions**: main has an older copy of one of our branches (load-data rollups, topics, models). Keep ours, which is newer. |
| MEDIUM | 1 | They removed it: `CustomerSnapshotApiOld`. |
| LOW | 277 | Only ours changed, we replaced it, or main has an older copy without it. Keep ours. |

**The colleague's code** is in its own repo, `github.com/Daksh007-batman/New-asem-merger` (branches `main` and `Ashutosh`, both `54313d5`). It has no git history in common with ours, so it is merged by porting, not with `git merge`. See [COLLEAGUE_CODE_REVIEW.md](COLLEAGUE_CODE_REVIEW.md).

## Steps

1. **Get the colleague's code into git.** If he pushes it to `main` (on top of `7d2dacde`), it already shares history with ours. Otherwise make a branch from the legacy commit, so git has a common base:

   ```bash
   git switch -c colleague-code origin/main
   ```

   Copy their files over the checkout, then `git add -A && git commit`. Leave out `.env` and any file with secrets.
2. **Compare at function level:**

   ```bash
   virtualwarehouse/bin/python scripts/merge/overlap_check.py --theirs colleague-code --out .work/merge_overlap_colleague.csv
   ```

   Work through HIGH, then MEDIUM. The CSV says what to do for each item (column "Action").
3. **Merge on an integration branch**, never directly on either side:

   ```bash
   git switch -c merge/fov2-colleague fov2-pre-merge-20261119
   ```

   ```bash
   git merge --no-commit colleague-code
   ```

   For `wareApp/views.py` (deleted on our side): keep our split. Apply their changed view methods in the files the overlap CSV names.
4. **Migrations:** keep one lineage, ours. For each of their migrations: if the schema change is already in ours, nothing to do. Otherwise add it as a new migration after `0114`. On main's DB, fake our migrations whose schema already exists (reconciliation script, checked against main's schema).
5. **Check that nothing of ours was lost**, by comparing the merged branch with our tag:

   ```bash
   virtualwarehouse/bin/python scripts/merge/overlap_check.py --ours . --theirs fov2-pre-merge-20261119 --out .work/merge_verify.csv
   ```

   Rows "Same" are untouched. Every other row for one of our functions is a change made during the merge: check it.
6. **Run the tests.** All tests must pass (520 before the merge); add tests for the features that came from their side.

   ```bash
   virtualwarehouse/bin/python manage.py test wareApp.tests
   ```

7. **Deploy to the test server first**, using the daily checks in [TEST_SERVER_OPERATIONS.md](../operations/TEST_SERVER_OPERATIONS.md). Main only with permission.
8. **Update the inventory:**

   ```bash
   virtualwarehouse/bin/python docs/merge/build_code_inventory.py
   ```

## Rebuilding the files

```bash
virtualwarehouse/bin/python docs/merge/build_code_inventory.py
```

The workbook is read from the code, except for the hand-written "Why ours is better" rows, the module notes, and the features and alarms (which come from their own builders). To refresh the overlap with main, copy main's code read-only into `.work/` (excluding `.env`), then run:

```bash
virtualwarehouse/bin/python scripts/merge/overlap_check.py --theirs <copy> --out docs/merge/overlap_main_server_<date>.csv
```
