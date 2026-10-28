Project recovery coalescing — run & monitoring notes

Files added:
- monitoring/prometheus/recovery_alerts.yml — Prometheus alerting rules for recovery metrics

Quick run (dev)

1. Start Redis (Docker):

```bash
docker run -d --name redis-test -p 6380:6379 redis:8
```

2. Activate the project's virtualenv and install deps (if needed):

```bash
source virtualwarehouse/bin/activate
pip install -r requirements.txt
pip install prometheus_client redis requests
```

3. Enable metrics in Django settings (edit `warehouse/settings.py`):

- set `RECOVERY_ENABLE_METRICS = True`
- ensure `REDIS_URL` points to your Redis instance (example: `redis://localhost:6380/1`)

4. Run the Django dev server (example):

```bash
REDIS_URL=redis://localhost:6380/1 python manage.py runserver 8001
```

5. Scrape the metrics endpoint from Prometheus using this scrape config snippet in `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'django-recovery'
    metrics_path: /api/recovery/metrics/
    static_configs:
      - targets: ['127.0.0.1:8001']
```

6. Load the alert rules (example Prometheus CLI or config):

Add the rule file to your Prometheus config:

```yaml
rule_files:
  - 'monitoring/prometheus/recovery_alerts.yml'
```

Then restart Prometheus.

Alert tuning suggestions
- `RecoveryPendingHigh` — default threshold 50 pending payloads for 2m. Tune to your SLA and worker concurrency.
- `RecoveryQueueGrowing` — alerts on Redis queue length > 10 for 1m.

Local test (load generator)

Use the provided spam loader script to simulate high-rate posts (example):

```bash
source virtualwarehouse/bin/activate
python scripts/spam_recovery.py --n 1000 --threads 20
```

## Documentation

All documentation is in [`docs/`](docs/):

| Folder | Contents |
| --- | --- |
| [`docs/mqtt-flows/`](docs/mqtt-flows/README.md) | Every MQTT topic and alarm flow, with draw.io diagrams |
| [`docs/deploy/`](docs/deploy/README.md) | Systemd units, test and main server rollouts |
| [`docs/operations/`](docs/operations/) | Server operations, production change logs, incident notes |
| [`docs/load-data/`](docs/load-data/) | LoadData flow and optimization |
| [`docs/dg-fuel/`](docs/dg-fuel/) | DG fuel architecture, multi-unit flow, roadmap |
| [`docs/roadmaps/`](docs/roadmaps/) | Refactor plans and TODO |
| [`docs/monitoring/`](docs/monitoring/README.md) | Server metrics collector |
| `docs/*.md` | Alarm feature plan, Celery monitoring, MQTT / Celery architecture |
