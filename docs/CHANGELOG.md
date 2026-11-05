# Change log

Every change that implements, modifies or removes behaviour is recorded here,
newest first, with a link to its detailed doc. (Started 2026-11-05; earlier
changes are in the git history and in `docs/alarms/ALARM_CATALOGUE.xlsx`.)

| Date | Change | Type | Detail | Commit | Test server | Main |
|---|---|---|---|---|---|---|
| 2026-11-05 | Spike hours left out of the day total: on saving and submetering sites an hour above the aisle's whole daily baseline does not count in the day; the other hours do. Alarms no longer subtract such hours twice. | Modify | [Consumption reading rules, rule 2](consumption/READING_RULES.md#rule-2-spike-hours-are-left-out-of-the-day-total) | "Spike hours left out of the day total…" | Deployed 5 Nov 12:46 (backup `pre_spike_hours_in_day_20261105.tgz`) | Not deployed |
| 2026-11-03 | 10,000 kWh glitch limit only on saving (2) and submetering (5) sites, on every write path; never on WH-metering (1). | Modify | [Consumption reading rules, rule 1](consumption/READING_RULES.md#rule-1-10000-kwh-glitch-limit) | `f63fc814` | Deployed 3 Nov 13:14 (backup `pre_cap_by_site_type_20261103.tgz`) | Not deployed |
| 2026-11-03 | Gateway check can skip sites (`GATEWAY_HEALTH_SKIP_SITES`); test skips site 35, whose data main does not forward to test. | Add | `wareApp/mqtt/services/gateway_health.py` `skipped_sites` | `39451340` | Deployed (`.env` backup `env_before_skip_sites_20261103`) | Not deployed |
