# Server Performance Evidence Collector

`monitoring/server_metrics_collector.py` runs on the laptop. It uses normal SSH access to
read Linux metrics from each server and writes the evidence only under the local
`monitoring/data/` directory. It does not install an agent, modify either
server, or write data remotely.

## Setup

Create the local configuration, then replace the placeholder SSH key path if
needed:

```bash
cp monitoring/servers.example.json monitoring/servers.json
chmod 600 monitoring/servers.json
```

The laptop user must already be able to run this without a password prompt for
each configured host:

```bash
ssh -i ~/.ssh/your-server-key.pem ubuntu@asem.aviconncorp.com true
```

## Collect A Comparison Window

Use the same interval and duration for each comparison. A five-minute sample
interval over a representative business window is generally more useful than a
single peak sample.

```bash
# One quick connectivity and format check for both servers.
python3 monitoring/server_metrics_collector.py --count 1 --label validation

# Collect 8 hours: 96 samples at five-minute intervals.
python3 monitoring/server_metrics_collector.py --interval 300 --count 96 --label after-optimization
```

Run the collector during comparable workload windows before and after a change.
Keep the resulting local `server_samples.csv`, `server_samples.jsonl`, and
`top_processes.csv` as the raw evidence.

## Process CSV Rotation

`top_processes.csv` has a checked-in logrotate policy at
`monitoring/logrotate/top_processes.conf`. It rotates weekly, or sooner at
25 MiB, retains 12 compressed archives, and creates a fresh CSV for the next
collector sample.

Install it once on the machine that runs the collector:

```bash
sudo install -m 644 monitoring/logrotate/top_processes.conf /etc/logrotate.d/top_processes-monitoring
sudo logrotate --force /etc/logrotate.d/top_processes-monitoring
```

The collector opens the CSV on each sample, so standard rename-and-create
rotation is safe and no collector restart is required.

## Metrics

Each sample records:

| Metric | Interpretation |
| --- | --- |
| `cpu_percent` | CPU busy percentage calculated from two `/proc/stat` snapshots. |
| `load_1`, `load_5`, `load_15` | Linux runnable/uninterruptible work averages. |
| `load_1_per_core` | Best cross-server load comparison: 1-minute load divided by logical CPU cores. |
| `running_tasks`, `total_tasks`, `task_count`, `runnable_count` | Scheduler-visible task pressure. |
| `memory_used_percent` | `MemTotal` minus `MemAvailable`; it does not treat cache as fully used memory. |
| `top_processes.csv` | Up to ten processes with the highest instantaneous CPU use per sample. |

For a credible optimization claim, compare label-specific distributions such as
median and 95th percentile `load_1_per_core` and `cpu_percent`, and keep the
same traffic/load context. Lower CPU/load during a quieter workload alone is not
proof that the code change caused the improvement.

## Failure Handling

An SSH or remote-command failure is saved as a row with an `error` value rather
than stopping collection from the other server. Resolve those rows before using
the period as evidence.