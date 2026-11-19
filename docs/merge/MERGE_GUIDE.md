# Merging this branch with the colleague's code

Written 2026-11-19, before the merge. Two code bases started from the same legacy code:

- **ours**: `full-optimization-v2`, tagged `fov2-pre-merge-20261119`.
- **theirs**: the colleague's optimized version of the code that runs on main.

Files here:

| File | What |
|---|---|
| [`CODE_INVENTORY.xlsx`](CODE_INVENTORY.xlsx) | Everything this branch has: features, alarms, APIs, Celery tasks, commands, DB models, migrations, modules, every function (what it does, new / changed / moved, tests, fingerprint), tests, and why it is better than the legacy code. Built by `build_code_inventory.py`. |
| [`overlap_main_server_20261119.csv`](overlap_main_server_20261119.csv) | Function-level comparison of ours against main's current code, copied read-only on 19 Nov. It is also the "Merge overlap (main)" sheet. |
| [`../../scripts/merge/overlap_check.py`](../../scripts/merge/overlap_check.py) | Makes that comparison against any code base (a folder or a git ref). |

## Marking our code before the merge

1. **Git tag, not comments in the code.** `fov2-pre-merge-20261119` marks exactly what we had before the merge. Use it to compare, review or go back. Do not add `# ours` markers to functions: every marker is a changed line, which means more conflicts, not fewer.
2. **Fingerprints.** Every function and class in the Functions sheet has a fingerprint, a hash of its source with comments and formatting ignored. After the merge, the check below shows which of our functions changed.
3. **Ownership comes from the inventory.** Each function's "Origin" (New / Changed / Moved, unchanged) says what this branch wrote. The overlap sheet says what the other side touched.

## Why conflicts are expected

Git can only merge well when both sides share history. The colleague's code comes from main's server, which is not a git checkout, so git has no common base for it.

What the comparison with main's current code (19 Nov) shows:

| Area | Ours | Main's code now | Effect |
|---|---|---|---|
| `wareApp/views.py` | split into `wareApp/views/` (18 modules) | one file, about 11,000 lines, changed on 16 Nov | Every change of theirs in `views.py` must be applied to the matching file of ours. The overlap sheet names that file ("Our file"). |
| `wareApp/tasks.py` | MQTT handling moved to `wareApp/mqtt/` | the 14 Oct release plus changes | 8 processing tasks changed on both sides (HIGH) |
| Migrations | our `0059`–`0114` | main's DB applied its **own** `0073`–`0076` (`0075` adds AisleGroup `dg_fuel_enabled` / `dg_fuel_provider` / `dg_fuel_vehicle_number`, applied 31 Oct) | Same numbers, different migrations. A plain `migrate` fails, so a reconciliation step is needed (see [MAIN_SERVER_ROLLOUT.md section 3](../deploy/MAIN_SERVER_ROLLOUT.md)). |
| `models.py`, `urls.py`, `serializers.py`, `admin.py` | changed | changed on main 31 Oct – 18 Nov | merge by hand, item by item |

Overlap counts (main's code vs ours):

| Risk | Count | What it means |
|---|---|---|
| HIGH | 22 | **Both changed**, so merge by hand. Examples: `process_*_message` tasks, `handle_load_data_message`, the load-data rollups, `CustomerSnapshotApi.post`, `LoadGraphApiForDailyData.post`, `SiteCeleryPingApi.post`, models `User` and `DgUnitConsumption`, `urlpatterns`. |
| HIGH | 23 | **Theirs only**: exists on main, not in ours, so port it. Examples: APIs `monitoringCustomerSites/` and `monitoringSitesList/` (`MonitoringCustomerSitesInfo`), `CACHES` setting, Roadcaste / Loconav fuel tasks, admin pages for HomeGatewayStatus and MeterDisconnectionEvent. |
| MEDIUM | 16 | **Only theirs changed**, so port their change into our file. Examples: AisleGroup model fields, `mqtt_client1/2`, `parse_gateway_topic`, `MeterDisconnectionIngestView.post`, `DATABASE_ROUTERS`. |
| MEDIUM | 53 | They removed it (42), or both sides are unchanged copies of different base versions (11). |
| LOW | 230 | Only we changed it, or we replaced it: keep ours. |

Main's code is not necessarily the colleague's code. **Run the check again on the colleague's actual code** before merging.

## Steps

1. **Get the colleague's code into git** as a branch made from the legacy commit, so git has a common base:

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
