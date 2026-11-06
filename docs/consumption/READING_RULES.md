# Consumption reading rules

How hourly and daily consumption readings are cleaned and added up before they
are stored. Both rules live in one place, `wareApp/models.py`, and every write
path uses them.

| Rule | Function (`wareApp/models.py`) | Since |
|---|---|---|
| 1. 10,000 kWh glitch limit | `reading_capped`, `cap_reading`, `cap_reading_row` | 2026-11-03 |
| 2. Spike hours left out of the day total | `hour_counts_in_day` | 2026-11-05 |

## Site types

| `Site.site_type` | Name | What is metered | Rule 1 | Rule 2 |
|---|---|---|---|---|
| 1 | WH-metering | The whole warehouse (mains, DG, solar) | No | No |
| 2 | WH energy saving | Aisles with our product installed | Yes | Yes |
| 5 | WH submetering | Aisles without our product | Yes | Yes |
| 3, 4 | Fire, FEMS | No consumption readings | No | No |

On WH-metering sites a big value is genuine (a whole warehouse can use more
than 10,000 kWh), so neither rule applies there.

## Rule 1: 10,000 kWh glitch limit

**Rule.** On saving and submetering sites, an hourly or daily reading above
10,000 kWh (`MAX_READING_KWH`) is a meter glitch. It is stored as 0, and its
saving is set to the baseline (as the original code did).

**Why.** Meters and gateways sometimes send nonsense, for example
4,456,134,061,171 kWh in one hour (site 138, 3 Nov), or the meter's running
total instead of the hour's use (about 55,000 kWh, site 151).

**Before 2026-11-03** the limit was applied inconsistently. The model `save()`
capped every site type, which could zero genuine WH-metering totals. Live
packets and daily recovery capped only saving sites, so submetering was not
protected. Hourly recovery and batch updates did not cap at all.

**Write paths**

| Path | Code |
|---|---|
| Model `save()` (hourly and daily) | `CleanReadingMixin.clean_reading_values` |
| Live packet values (hour totals from the gateway) | `mqtt/consumption.py` `_cap_warehouse_saving_values` |
| Per-packet daily total update | `mqtt/consumption.py` `_daily_updates` |
| Batch path, every row before the bulk write | `mqtt/consumption_batch.py` (`cap_reading_row`) |
| Hourly recovery packets | `mqtt/hourly_consumption_recovery.py` |
| Daily recovery packets | `mqtt/daily_consumption_recovery.py` |
| `resync_daily_totals` command (glitch detection) | `management/commands/resync_daily_totals.py` |

**Example.** Hours 6,000 / 6,500 / 20,000 kWh on one day:

| | WH-metering | Saving / submetering |
|---|---|---|
| 20,000 hour | 20,000 (kept) | 0 |
| Day total | 32,500 | 12,500 is above 10,000, so 0 (saving = baseline) |

**Stored data.** Existing rows above 10,000 kWh (about 1,155 hourly and 83
daily, on test and main) were not changed, on hold until the manager decides.

## Rule 2: spike hours are left out of the day total

**Rule.** On saving and submetering sites, when an aisle's hours are added up
into its day total, an hour that is **bigger than the aisle's whole daily
baseline** is left out. All other hours count as normal.
- The hour row itself is kept as stored. It shows on the hourly chart, and the
  Consumption Spike alarm (type 17) still reports it.
- The day's saving = daily baseline - the counted total.
- Without a baseline (0 or none), every hour counts.

**Why.** Since the consumption fix on this branch, a day total is the sum of
its hourly rows. One bad hour below 10,000 kWh therefore inflated the whole
day. In the 30 days before 2026-11-05, main had 39 such aisle-days, all on
saving sites. The test is the same one the Consumption Spike alarm uses for a
"meter jump" (`find_spikes`), so the totals and the alarm agree on which hours
are spikes.

**Example.** Site 138, F1-C-Section-EL, daily baseline 57.7 kWh, 30 Oct:

| | kWh |
|---|---|
| All 24 hours | 6,456.66 |
| - 04:00 meter jump | - 3,290.3 |
| - 12:00 meter jump | - 3,162.2 |
| **Day total (22 normal hours)** | **4.17** |
| Day saving (57.7 - 4.17) | 53.53 |

**Catch-up hours** (the first hour after a gateway gap) carry the real energy of
the missed hours, so they are counted. Only if a gap is so long that the
catch-up hour is bigger than the whole daily baseline (about a day or more of
missed data) is it treated as a spike and left out.

**Paths that add up a day from its hours**

| Path | Code |
|---|---|
| Per-packet daily update and first packet of the day | `mqtt/consumption.py` `_counted_hours` |
| Batch path | `mqtt/consumption_batch.py` `_day_total` |
| HTTP recovery upload | `recovery/processor.py` `update_daily_from_hourly` |
| `resync_daily_totals` command | `management/commands/resync_daily_totals.py` |

The gateway's daily recovery packet sends a ready-made day total, not hours, so
rule 2 cannot apply there (rule 1 does).

**Alarms.** High Consumption and Bypassed already left spike hours out. They
now subtract only the spike hours that are still in the day total (catch-up
hours, and spikes on other site types), so a meter jump is never subtracted
twice (`mqtt/services/consumption_alarms.py` `_still_in_day_total`).

**Dashboard note.** On a day with a spike hour, the day total does not equal a
manual sum of the 24 hourly bars. The difference is exactly the spike hour(s),
which the Consumption Spike alarm lists.

**Past data.** Applies from now on. Past days are not recomputed. To apply the
rule to past days later:
`python manage.py resync_daily_totals --from YYYY-MM-DD --to YYYY-MM-DD [--site ID] --apply`
(dry run without `--apply`).

## Tests

- `wareApp/tests/test_reading_cap.py`: both rules for site types 1, 2 and 5;
  model save, live packet values, hourly / daily recovery, HTTP recovery day
  total.
- `wareApp/tests/test_consumption_batch.py`: the same packets through the
  per-packet and batch paths must store identical rows (glitch limit and spike
  hours per site type); `resync_daily_totals` on saving and WH-metering sites.
- `wareApp/tests/test_consumption_alarms.py` `SavingSiteSpikeTests`: Bypassed on
  a saving site counts the other hours and does not subtract the jump twice.

## Rolling back

Each rule is one commit (see [CHANGELOG](../CHANGELOG.md)); revert it and
redeploy. On the test server the previous files are kept in
`~/django_project/backups/deploy/` (named in the change log).
