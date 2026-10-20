# Main-server rollout: `full-optimization-v2` — checklist

Status: **not started**. Main (`asem.aviconncorp.com`) is production; everything below
needs an agreed maintenance window. Facts gathered read-only on 2026-10-20.
The test-server rollout this follows is in `TEST_SERVER_ROLLOUT.md`.

## Where main is today

| Item | Main now | After rollout (as on test) |
| --- | --- | --- |
| Code | old tree, not a git checkout | `full-optimization-v2` |
| `wareApp` migrations | last `0074_alter_monthlyloadsharepercentage_created_on_and_more` (main's own lineage) | repo `0098` |
| MQTT services | `root-mqtt-queue1`, `root-mqtt-queue2`, `celerybeat`, `fetch-fuel-data`, `gunicorn` | `mqtt-listener-queue1/2`, `mqtt-processing-queue1/2`, `mqtt-notifications`, `recovery-status-sweep.timer`, `celerybeat` (now runs the 60 s consumption flush), `fetch-fuel-data`, `gunicorn` |
| RabbitMQ | `queue1`/`queue2` hold 10 messages each, 0 consumers | + `queue1_processing`, `queue2_processing`, `notifications`, `mqtt.consumption.batch` |
| Logrotate | `celery`, `celery-logs2`, `celery_logs`, `celery_monitor` | + `celerylogs1`, `django-debuglog` |

## 1. `.env` (before any restart)

Compare with `warehouse/.env.example`. Required for this release (values are never in the code):

- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, **`EMAIL_HOST_PASSWORD`**, `DEFAULT_FROM_EMAIL`
  — `sendmail.py` no longer contains the SMTP password; without these no alarm/OTP e-mail is sent.
- **`ROADCAST_PULL_USERNAME`, `ROADCAST_PULL_PASSWORD`, `LOCONAV_API_TOKEN`** — DG fuel pulls
  (`fetch_fuel_data.py`, `wareApp/fuel_providers.py`) skip a provider whose credentials are empty.
- `ALARM_EMAIL_OVERRIDE_TO` — **set it empty on main** to send alarms to the real recipients
  (the default sends every alarm only to the tester), and set `ALARM_EMAIL_DEFAULT_TO`.
- Must stay unset/False: `USE_SECONDARY_DATABASE` (see `wareApp/routers.py`; a working router
  sends the load-data tables to a database that does not exist).
- Optional (defaults fine): `PASSWORD_RESET_*`, `DEBUG_LOG_LEVEL`, `MQTT_CONSUMPTION_BATCH_SECONDS=60`.

Rotate first: the SMTP app password, Roadcast password and Loconav token are in git history.

**Frontend check:** `forgot/` no longer returns the OTP in its response. If the web UI relied
on it, set `PASSWORD_RESET_RETURN_OTP=True` until the UI is changed.

## 2. Backups

`pg_dump -Fc` of `warehouse` (or at least schema + `django_migrations`), copy of the code
tree and of `/etc/systemd/system/*.service`, `/etc/mosquitto/mosquitto.conf`, `.env`.

## 3. Migrations — needs a main-specific reconciliation script

A plain `manage.py migrate` will **fail**: main applied its own
`0073_alter_meterdisconnectionevent_options_and_more` and
`0074_alter_monthlyloadsharepercentage_created_on_and_more`, while the repo's `0073`/`0074`
have other names (`InconsistentMigrationHistory`). Main also lists 56 historical migration
names that are not in the repo (harmless, they are only rows).

To do (like `test_server_migrate.sh` did for test), **checked against main's schema**:

1. For each repo migration `0073`–`0098`, decide: schema already present on main
   (record with `--fake`), partly present (rename/adjust, then fake), or missing (run).
   Main's `0073`/`0074` likely cover part of repo `0083`/`0087` (`created_on` defaults) and the
   meter-disconnection options — verify column by column, do not assume.
2. Index migrations on large tables must be built `CONCURRENTLY` by hand, then faked:

   | Migration | Table | Rows / size on main |
   | --- | --- | --- |
   | `0084` | `rawloaddata`, `hourlyloaddata`, `dailyloaddata` | 24.5 M / 3.6 GB, 14.3 M / 2.7 GB, 0.3 M |
   | `0086` | `supplyloadtimeshare`, `newalarmsnotifications`, `email_history`, … | ≤ 0.6 M |
   | `0088` | `dailyloaddata` | 0.3 M |
   | `0089`, `0090` | small | — |
   | `0091`, `0092` | `alarmnotifications`, new table | small |

3. `0097` (UserType default) and `0098` (alarm-type choice) change no table; run normally.
4. Write and dry-run the script against a **copy of main's schema** (`pg_dump --schema-only`
   restored on test or locally) before the window.

## 4. Services (in this order)

1. Stop `root-mqtt-queue1/2`; let queued work finish (`rabbitmqctl list_queues`).
2. Run the migration script (step 3).
3. Install `deploy/systemd/*` units and `recovery-status-sweep.timer`, `deploy/logrotate/*`.
4. Start: processing workers → `mqtt-notifications` → `celerybeat` → `gunicorn` →
   `fetch-fuel-data` → listeners (a listener stop takes ~60 s).
5. Do not start `root-mqtt-queue1/2` again (disable them).

## 5. Verify (same checks as on test)

- `celerylogs1/2`: tasks succeeding, `consumption batch:` lines every minute, no `Traceback`.
- `python manage.py replay_dead_letters` lists 0 (or known) dead letters.
- SMTP login with `.env` values; one test alarm e-mail.
- `fetch-fuel-data` journal shows `API: SUCCESS`.
- `/api/temp/dispatch/mail/` returns 200 (gateway overheat alerts are stored as alarm type 13).
- The 30-minute inspection script used on test (`scratchpad inspect10.sh`) for load/CPU/queues.

## 6. Rollback

Stop the new units, restore code tree and `.env`, start `root-mqtt-queue1/2` and the old
`gunicorn`/`celerybeat`. Schema changes of this release are additive (new tables, columns
with defaults, indexes), so the old code keeps working on the migrated database; restore the
`pg_dump` only if a migration itself failed half-way.
