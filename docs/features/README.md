# Feature tracker

`FEATURE_TRACKER.xlsx` (and `FEATURE_TRACKER.csv`) lists every feature of this
work: what is done, in progress, waiting, planned, on hold or out of scope, with
its state on the test and main servers, the next step and who it waits on.

Built by `build_feature_tracker.py`; edit the `add(...)` rows there, never the
.xlsx by hand, then run:

```bash
python3 docs/features/build_feature_tracker.py
```

| Sheet | Contents |
|---|---|
| Summary | Count and IDs per status |
| Features | One row per feature, open ones first |
| How to update | The steps below |

IDs: `F` open (in progress / waiting / planned), `H` on hold, `N` not started,
`O` out of scope, `D` done. An ID is never reused; a feature keeps its ID when
its status changes.

When a feature is planned, started, changed, finished, put on hold or dropped,
update its row (status, last update, servers, next step, waiting on). When it
is done, also add a row to [CHANGELOG](../CHANGELOG.md). Alarm details stay in
[ALARM_CATALOGUE.xlsx](../alarms/ALARM_CATALOGUE.xlsx).
