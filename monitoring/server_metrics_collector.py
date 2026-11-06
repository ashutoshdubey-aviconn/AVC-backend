#!/usr/bin/env python3
"""Collect Linux server load evidence over SSH and store it on this machine."""

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REMOTE_COMMAND = r"""
set -eu

cpu_snapshot() {
    awk '/^cpu / { total=0; for (i=2; i<=NF; i++) total += $i; idle=$5+$6; print total, idle; exit }' /proc/stat
}

set -- $(cpu_snapshot)
total_before=$1
idle_before=$2
sleep 0.5
set -- $(cpu_snapshot)
total_after=$1
idle_after=$2
cpu_percent=$(awk -v tb="$total_before" -v ta="$total_after" -v ib="$idle_before" -v ia="$idle_after" 'BEGIN {
    total=ta-tb; idle=ia-ib; if (total <= 0) print "0.00"; else printf "%.2f", (total-idle)*100/total
}')

set -- $(cat /proc/loadavg)
load_1=$1
load_5=$2
load_15=$3
running_tasks=${4%/*}
total_tasks=${4#*/}
cores=$(getconf _NPROCESSORS_ONLN)
memory_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
memory_available_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
task_count=$(ps -e -o pid= | wc -l | tr -d ' ')
runnable_count=$(ps -e -o stat= | awk '$1 ~ /^R/ {count++} END {print count+0}')

printf 'METRIC\thostname\t%s\n' "$(hostname)"
printf 'METRIC\tcores\t%s\n' "$cores"
printf 'METRIC\tcpu_percent\t%s\n' "$cpu_percent"
printf 'METRIC\tload_1\t%s\n' "$load_1"
printf 'METRIC\tload_5\t%s\n' "$load_5"
printf 'METRIC\tload_15\t%s\n' "$load_15"
printf 'METRIC\trunning_tasks\t%s\n' "$running_tasks"
printf 'METRIC\ttotal_tasks\t%s\n' "$total_tasks"
printf 'METRIC\ttask_count\t%s\n' "$task_count"
printf 'METRIC\trunnable_count\t%s\n' "$runnable_count"
printf 'METRIC\tmemory_total_kb\t%s\n' "$memory_total_kb"
printf 'METRIC\tmemory_available_kb\t%s\n' "$memory_available_kb"
ps -eo pid=,ppid=,stat=,pcpu=,pmem=,comm= --sort=-pcpu | head -n 10 | awk '{printf "PROCESS\t%s\t%s\t%s\t%s\t%s\t", $1, $2, $3, $4, $5; for (i=6; i<=NF; i++) printf "%s%s", (i==6 ? "" : " "), $i; printf "\n"}'
"""

SAMPLE_FIELDS = [
    "collected_at_utc",
    "label",
    "server_name",
    "host",
    "hostname",
    "cores",
    "cpu_percent",
    "load_1",
    "load_5",
    "load_15",
    "load_1_per_core",
    "running_tasks",
    "total_tasks",
    "task_count",
    "runnable_count",
    "memory_total_kb",
    "memory_available_kb",
    "memory_used_percent",
    "error",
]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("monitoring/servers.json"),
        help="Local JSON server configuration (default: monitoring/servers.json)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("monitoring/data"),
        help="Local directory for CSV and JSONL evidence",
    )
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between samples")
    parser.add_argument("--count", type=int, default=0, help="Samples to collect; 0 runs until interrupted")
    parser.add_argument("--label", default="after", help="Comparison label, for example before or after")
    parser.add_argument("--timeout", type=int, default=20, help="SSH timeout in seconds")
    return parser.parse_args()


def load_servers(config_path: Path) -> list[dict[str, Any]]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Configuration not found: {config_path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid JSON in {config_path}: {error}") from error

    servers = config.get("servers") if isinstance(config, dict) else None
    if not isinstance(servers, list) or not servers:
        raise SystemExit("Configuration must contain a non-empty 'servers' list.")
    for server in servers:
        if not isinstance(server, dict) or not all(server.get(key) for key in ("name", "host", "user")):
            raise SystemExit("Each server needs non-empty name, host, and user fields.")
    return servers


def parse_remote_output(output: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    metrics: dict[str, str] = {}
    processes: list[dict[str, str]] = []
    for line in output.splitlines():
        columns = line.split("\t")
        if len(columns) == 3 and columns[0] == "METRIC":
            metrics[columns[1]] = columns[2]
        elif len(columns) == 7 and columns[0] == "PROCESS":
            processes.append(
                {
                    "pid": columns[1],
                    "ppid": columns[2],
                    "state": columns[3],
                    "cpu_percent": columns[4],
                    "memory_percent": columns[5],
                    "command": columns[6],
                }
            )
    return metrics, processes


def collect_server(server: dict[str, Any], timeout: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    destination = f"{server['user']}@{server['host']}"
    command = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}"]
    if server.get("port"):
        command.extend(["-p", str(server["port"])])
    if server.get("identity_file"):
        command.extend(["-i", str(server["identity_file"])])
    command.extend([destination, "sh", "-s"])

    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sample: dict[str, Any] = {
        "collected_at_utc": collected_at,
        "server_name": server["name"],
        "host": server["host"],
        "error": "",
    }
    try:
        completed = subprocess.run(
            command,
            input=REMOTE_COMMAND,
            text=True,
            capture_output=True,
            timeout=timeout + 5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        sample["error"] = str(error)
        return sample, []

    if completed.returncode != 0:
        sample["error"] = completed.stderr.strip() or f"ssh exited {completed.returncode}"
        return sample, []

    metrics, processes = parse_remote_output(completed.stdout)
    sample.update(metrics)
    try:
        cores = float(sample["cores"])
        memory_total = float(sample["memory_total_kb"])
        memory_available = float(sample["memory_available_kb"])
        sample["load_1_per_core"] = round(float(sample["load_1"]) / cores, 3)
        sample["memory_used_percent"] = round((1 - memory_available / memory_total) * 100, 2)
    except (KeyError, ValueError, ZeroDivisionError):
        sample["error"] = "Remote response was incomplete."
    for process in processes:
        process.update(
            {
                "collected_at_utc": collected_at,
                "server_name": server["name"],
                "host": server["host"],
            }
        )
    return sample, processes


def append_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def save_samples(output_dir: Path, samples: list[dict[str, Any]], processes: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    append_csv(output_dir / "server_samples.csv", SAMPLE_FIELDS, samples)
    process_fields = ["collected_at_utc", "server_name", "host", "pid", "ppid", "state", "cpu_percent", "memory_percent", "command"]
    append_csv(output_dir / "top_processes.csv", process_fields, processes)
    with (output_dir / "server_samples.jsonl").open("a", encoding="utf-8") as output:
        for sample in samples:
            output.write(json.dumps(sample, sort_keys=True) + "\n")


def main() -> int:
    arguments = parse_arguments()
    if arguments.interval <= 0 or arguments.count < 0:
        raise SystemExit("--interval must be positive and --count cannot be negative.")
    servers = load_servers(arguments.config)
    sample_number = 0
    try:
        while arguments.count == 0 or sample_number < arguments.count:
            started = time.monotonic()
            samples: list[dict[str, Any]] = []
            processes: list[dict[str, Any]] = []
            for server in servers:
                sample, server_processes = collect_server(server, arguments.timeout)
                sample["label"] = arguments.label
                samples.append(sample)
                processes.extend(server_processes)
                status = sample["error"] or f"cpu={sample.get('cpu_percent', '?')}% load/core={sample.get('load_1_per_core', '?')}"
                print(f"{sample['collected_at_utc']} {server['name']}: {status}")
            save_samples(arguments.output_dir, samples, processes)
            sample_number += 1
            remaining = arguments.interval - (time.monotonic() - started)
            if (arguments.count == 0 or sample_number < arguments.count) and remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("Collection stopped.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())