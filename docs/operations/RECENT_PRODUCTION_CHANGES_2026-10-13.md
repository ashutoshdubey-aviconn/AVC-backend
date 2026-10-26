# Recent Production Changes

Date: 2026-10-13

## Database Routing

Main Django now uses only its local PostgreSQL `default` database.

- Disabled `SecondaryDBRouter` in main `warehouse/settings.py`.
- Removed the main application's `secondary` test-database configuration.
- Updated LoadData API queries to use `default`.
- Updated DG-fuel database helper/session reads to use `default`.
- Restarted Gunicorn.

Validated through Django shell: LoadData and DG-fuel model managers resolve to `default`.

## Historical Data On Main

The requested historical interval was migrated and verified on main:

`2025-10-12 00:00:00+05:30` through `2026-10-13 00:00:00+05:30`.

Verified migrated tables:

- `wareApp_mainsdgloaddata`
- `wareApp_rawloaddata`
- `wareApp_hourlyloaddata`
- `wareApp_dailyloaddata`
- `wareApp_monthlyminmaxloaddata`
- `wareApp_dgfuelconsumptiondata`
- `wareApp_dgfuelalertsdata`
- `wareApp_dgunitconsumption`

## PostgreSQL Performance Changes

Added the following main-server indexes with `CREATE INDEX CONCURRENTLY`:

| Index | Table | Columns |
| --- | --- | --- |
| `idx_rawload_site_created` | `wareApp_rawloaddata` | `site_id, created` |
| `idx_load_site_created` | `wareApp_hourlyloaddata` | `site_id, created` |
| `idx_hourlyload_rollup` | `wareApp_hourlyloaddata` | `site_id, aisle_group_id, created` |
| `idx_dailyload_site_created` | `wareApp_dailyloaddata` | `site_id, created` |
| `idx_monthlyload_site_src_time` | `wareApp_monthlyminmaxloaddata` | `site_id, supply_source, created` |
| `idx_mainsdgload_site_aisle_created` | `wareApp_mainsdgloaddata` | `site_id, aisle_group_id, created` |

The Mains/DG graph query was changed from `created__date` to an indexable timestamp range. `EXPLAIN` confirms it uses `idx_mainsdgload_site_aisle_created`.

## API Changes

| Endpoint | Change |
| --- | --- |
| `/api/liveDataEverySecond/` | Reads RawLoadData from main `default` DB. |
| `/api/hourlyLoadGraph/` | Reads HourlyLoadData from main `default` DB. |
| `/api/dailyLoadGraph/` | Reads DailyLoadData from main `default` DB; range is now the exact selected calendar month. |
| `/api/loadDataMainsDgDaily/` | Reads MainsDgLoadData from main `default` DB; uses indexed one-day range. |
| `/api/downloadExcelLoadData/` | Monthly/daily LoadData export uses the exact selected calendar month. |
| DG-fuel APIs | Use the main `default` database through the centralized helper. |

Calendar-month behavior:

- Selecting September returns September 1 through September 30.
- Selecting October returns October 1 through October 31.
- The first day of the next month is excluded.

## MQTT And Queue Changes

- Queue 1 and Queue 2 listener services are active and separate.
- Cleared stale RabbitMQ task envelopes identified as duplicate `mqtt_client1` / `mqtt_client2` listener commands; no telemetry payload messages were intentionally purged.
- Queue 2 continues to receive and persist LoadData locally.

### Important Remaining Configuration

Main Mosquitto still has an active bidirectional bridge to test server `43.204.53.81:1883` for:

```text
/Acclivate/iOmniControl/+/+/in/LoadData/#
```

The bridge directive is `both`, so LoadData continues to be mirrored between the main and test MQTT brokers. This does not change main Django database persistence, which is local-only, but it means test still receives MQTT LoadData.

No Mosquitto bridge configuration was changed.

### How To Stop The Test MQTT Bridge

This is an operational change. It stops only MQTT mirroring to test; it does not stop main's local Mosquitto broker, Queue 1, Queue 2, or local PostgreSQL persistence.

1. Back up `/etc/mosquitto/mosquitto.conf`.
2. Remove the complete `whmetering_dhl` bridge stanza, including the `topic ... LoadData/# both ...` line. Do not remove the broker-wide listener settings.
3. Validate the changed configuration before restarting Mosquitto.
4. Restart Mosquitto and confirm Queue 2 reconnects to the local broker.
5. Verify that no TCP connection remains from main to `43.204.53.81:1883` and that new logs do not contain `Sending PUBLISH to local.bridge-dhl`.   ~

Example commands for an approved maintenance window:

```bash
sudo cp -a /etc/mosquitto/mosquitto.conf \
	/etc/mosquitto/mosquitto.conf.backup-$(date +%Y%m%d-%H%M%S)

sudoedit /etc/mosquitto/mosquitto.conf
sudo mosquitto -c /etc/mosquitto/mosquitto.conf -t
sudo systemctl restart mosquitto

sudo ss -tnp | grep '43.204.53.81:1883' || true
sudo grep 'Sending PUBLISH to local.bridge-dhl' /var/log/mosquitto/mosquitto.log | tail
systemctl is-active mosquitto root-mqtt-queue2
```

Rollback: restore the timestamped backup file, validate it with `mosquitto -t`, and restart Mosquitto.

## Validation Summary

- Gunicorn restarted and active after each API deployment.
- Main LoadData and DG-fuel ORM paths resolve to `default`.
- PostgreSQL plans use the new composite indexes.
- No long-running active PostgreSQL application queries were present in the final check.
- Main Queue 1 and Queue 2 were empty in the final queue snapshot.
- HTTPS API calls reached the application; protected endpoints correctly return `401` without credentials instead of timing out.

## Rollback Backups On Main

- `/home/ubuntu/django_project/backups/default-db-routing-20261013-183900`
- `/home/ubuntu/django_project/backups/mainsdg-query-fix-20261013-190500`
- `/home/ubuntu/django_project/backups/monthly-load-window-fix-20261013-192200`
- `/home/ubuntu/django_project/backups/calendar-month-load-fix-20261013-193000`

## Related Documentation

- [MAIN_SERVER_OPERATIONS.md](MAIN_SERVER_OPERATIONS.md)
- [TEST_SERVER_OPERATIONS.md](TEST_SERVER_OPERATIONS.md)
- [MQTT_LOAD_DATA_FULL_FLOW.md](../load-data/MQTT_LOAD_DATA_FULL_FLOW.md)
- [LOAD_DATA_FLOW_AND_OPTIMIZATION.md](../load-data/LOAD_DATA_FLOW_AND_OPTIMIZATION.md)
