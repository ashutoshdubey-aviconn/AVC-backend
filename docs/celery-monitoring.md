# Celery Monitoring Script

## Location and Schedule

Production script:

```text
/home/ubuntu/django_project/celery_monitoring.py
```

Root cron runs it every hour:

```cron
0 * * * * cd /home/ubuntu/django_project/ && /home/ubuntu/django_project/virtualwarehouse/bin/python celery_monitoring.py >> /var/log/celery_monitoring_cron.log 2>&1
```

## Purpose

The script parses Queue 1 consumption MQTT entries from:

```text
/home/ubuntu/django_project/celerylogs1/celery_logs_of_server.log
```

It retains entries from the previous hour containing:

```text
/Acclivate/iOmniControl/<site_id>/<homegateway_id>/in/consumption/state
```

For each matching entry, it extracts the site ID, HomeGatewayId string, timestamp,
leg ID, aisle group, and unit consumption. It stores the result in
`SiteCeleryPing`.

## Current Processing Flow

1. Scan the full Queue 1 log file and write matching entries from the last hour to
   `temp_celery_hour.log`.
2. Parse the temporary file into an in-memory list.
3. Delete every existing `SiteCeleryPing` row.
4. For every parsed entry, fetch the site and call `SiteCeleryPing.get_or_create()`.
5. Remove the temporary file.

## Observed Runtime and Load

On 2026-10-15, an active run had already consumed more than 5 minutes and was using
about 56% of one CPU core. The main Queue 1 log was about 465 MB at that time.

The cron log records a start timestamp but does not timestamp `Cron job completed.`,
so exact historical durations cannot be derived from the current log format.

## Operational Risks

- Every hourly execution scans the complete, growing Queue 1 log rather than only new
  bytes since the prior run.
- All `SiteCeleryPing` rows are deleted and rebuilt every run.
- Each parsed ping triggers a site lookup and a `get_or_create()` database operation.
- Per-ping `print()` statements create a large `/var/log/celery_monitoring_cron.log`.
- The fixed temporary filename can conflict if a run overlaps another execution.
- The delete occurs before the atomic write block, so an interrupted run can leave
  `SiteCeleryPing` empty.

## Current State

This note describes the production behavior observed on 2026-10-15. No changes to
the script or cron schedule were made while collecting this information.