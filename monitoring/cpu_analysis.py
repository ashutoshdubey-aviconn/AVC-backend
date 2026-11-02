#!/usr/bin/env python3
"""Per-core CPU analysis of the servers in servers.json, stored on this machine.

Every --interval seconds (default 60) each server is sampled over SSH, read-only:
a small Python script reads /proc twice, --window seconds apart (default 5), so
every number is the CPU actually used in that window (like top), not the
lifetime average that `ps` shows.

Files (one set per day, local time, in --output-dir = monitoring/data/cpu):
* cpu_summary_YYYY-MM-DD.csv   one row per server per minute: total busy %,
  user / system / iowait / steal %, load, memory, busiest process.
* cpu_cores_YYYY-MM-DD.csv     one row per core per minute: busy %, its split,
  and the top 3 processes that ran on that core (who is using it).
* cpu_processes_YYYY-MM-DD.csv the processes using CPU in that minute: CPU %
  (100 % = one full core), share of the whole server, the cores they ran on,
  systemd service, user, threads, memory, command.

Run:   python3 monitoring/cpu_analysis.py                 # every minute, forever
       python3 monitoring/cpu_analysis.py --count 1       # one sample
       python3 monitoring/cpu_analysis.py --report [DATE] # day summary from the CSVs
"""

import argparse
import csv
import json
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOP_PER_CORE = 3
MIN_PROCESS_CPU = 0.5  # % of one core; smaller processes are left out of the CSV
MAX_PROCESSES = 25

# Runs on the server with `python3 -`; only reads /proc. Prints one JSON line.
REMOTE_SCRIPT = r'''
import json, os, pwd, socket, sys, time
WINDOW = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
TICK = os.sysconf("SC_CLK_TCK")

def cpu_times():
    out = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu"):
                parts = line.split()
                out[parts[0]] = [int(x) for x in parts[1:9]]
    return out

def threads():
    """{(pid, tid): (ticks, last core)} for every thread."""
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            tids = os.listdir(f"/proc/{pid}/task")
        except OSError:
            continue
        for tid in tids:
            try:
                with open(f"/proc/{pid}/task/{tid}/stat") as f:
                    raw = f.read()
            except OSError:
                continue
            fields = raw[raw.rfind(")") + 2:].split()
            out[(int(pid), int(tid))] = (int(fields[11]) + int(fields[12]), int(fields[36]))
    return out

def describe(pid):
    info = {"pid": pid}
    try:
        with open(f"/proc/{pid}/stat") as f:
            raw = f.read()
        info["name"] = raw[raw.find("(") + 1:raw.rfind(")")]
        fields = raw[raw.rfind(")") + 2:].split()
        info["state"] = fields[0]
        info["threads"] = int(fields[17])
        info["rss_mb"] = round(int(fields[21]) * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            info["command"] = f.read().replace(b"\0", b" ").decode(errors="replace").strip()[:300] or f"[{info['name']}]"
        try:
            info["user"] = pwd.getpwuid(os.stat(f"/proc/{pid}").st_uid).pw_name
        except KeyError:
            info["user"] = str(os.stat(f"/proc/{pid}").st_uid)
        service = ""
        with open(f"/proc/{pid}/cgroup") as f:
            for part in f.read().strip().split("/"):
                if part.endswith((".service", ".scope")):
                    service = part
        info["service"] = service
    except OSError:
        info.setdefault("name", "?")
        info.setdefault("command", "(exited)")
    return info

cpu_before, threads_before = cpu_times(), threads()
started = time.monotonic()
time.sleep(WINDOW)
cpu_after, threads_after = cpu_times(), threads()
elapsed = time.monotonic() - started

cores = {}
for name, after in cpu_after.items():
    before = cpu_before.get(name, after)
    d = [a - b for a, b in zip(after, before)]
    total = sum(d) or 1
    # user nice system idle iowait irq softirq steal
    cores[name] = {
        "user": round((d[0] + d[1]) * 100 / total, 2),
        "system": round((d[2] + d[5] + d[6]) * 100 / total, 2),
        "iowait": round(d[4] * 100 / total, 2),
        "steal": round(d[7] * 100 / total, 2),
        "idle": round(d[3] * 100 / total, 2),
        "busy": round((total - d[3] - d[4]) * 100 / total, 2),
    }

usage = {}  # pid -> {core: % of one core}
for key, (ticks, core) in threads_after.items():
    # A thread missing from the first read started in the window: all its time counts.
    used = ticks - threads_before.get(key, (0, core))[0]
    if used <= 0:
        continue
    per = usage.setdefault(key[0], {})
    per[core] = per.get(core, 0) + used * 100 / (TICK * elapsed)

processes = []
usage.pop(os.getpid(), None)  # not this sampler itself
for pid, per_core in usage.items():
    info = describe(pid)
    info["cpu"] = round(sum(per_core.values()), 2)
    info["cores"] = {str(c): round(v, 2) for c, v in sorted(per_core.items(), key=lambda x: -x[1])}
    processes.append(info)
processes.sort(key=lambda p: -p["cpu"])

mem = {}
with open("/proc/meminfo") as f:
    for line in f:
        k, v = line.split(":", 1)
        mem[k] = int(v.split()[0])
load = open("/proc/loadavg").read().split()
print(json.dumps({
    "hostname": socket.gethostname(), "window": round(elapsed, 2), "ncores": os.cpu_count(),
    "cores": cores, "processes": processes,
    "load": [float(x) for x in load[:3]], "tasks": load[3],
    "mem_used_percent": round((1 - mem["MemAvailable"] / mem["MemTotal"]) * 100, 2),
    "swap_used_mb": round((mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) / 1024, 1),
}))
'''

SUMMARY_FIELDS = [
    "time", "server", "ncores", "busy_percent", "user_percent", "system_percent", "iowait_percent",
    "steal_percent", "load_1", "load_5", "load_15", "load_per_core", "tasks", "mem_used_percent",
    "swap_used_mb", "top_process", "top_process_cpu", "error",
]
CORE_FIELDS = ["time", "server", "core", "busy_percent", "user_percent", "system_percent", "iowait_percent",
               "steal_percent", "idle_percent"] + [f"top{i}" for i in range(1, TOP_PER_CORE + 1)]
PROCESS_FIELDS = ["time", "server", "rank", "pid", "name", "cpu_percent", "server_share_percent", "cores",
                  "service", "user", "threads", "rss_mb", "state", "command"]


def label(process):
    """Short name: the systemd service when it says more than the binary."""
    service = process.get("service", "")
    if service and not service.startswith(("session-", "user@", "init.scope")):
        return f"{process.get('name', '?')} [{service.removesuffix('.service')}]"
    return process.get("name", "?")


def sample(server, window, timeout):
    command = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
               "-o", "ControlMaster=auto", "-o", "ControlPersist=5m",
               "-o", f"ControlPath={HERE.parent / '.work'}/ssh-cpu-%C"]
    if server.get("port"):
        command += ["-p", str(server["port"])]
    identity = server.get("identity_file", "")
    if identity and "your-server-key" not in identity:
        command += ["-i", str(Path(identity).expanduser())]
    command += [f"{server['user']}@{server['host']}", "python3", "-", str(window)]
    done = subprocess.run(command, input=REMOTE_SCRIPT, text=True, capture_output=True,
                          timeout=timeout + window + 20, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:] or f"ssh exited {done.returncode}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def rows(server_name, now, data):
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    total = data["cores"]["cpu"]
    processes = data["processes"]
    ncores = data["ncores"]
    top = processes[0] if processes else {}
    summary = {
        "time": stamp, "server": server_name, "ncores": ncores,
        "busy_percent": total["busy"], "user_percent": total["user"], "system_percent": total["system"],
        "iowait_percent": total["iowait"], "steal_percent": total["steal"],
        "load_1": data["load"][0], "load_5": data["load"][1], "load_15": data["load"][2],
        "load_per_core": round(data["load"][0] / ncores, 3), "tasks": data["tasks"],
        "mem_used_percent": data["mem_used_percent"], "swap_used_mb": data["swap_used_mb"],
        "top_process": label(top) if top else "", "top_process_cpu": top.get("cpu", ""), "error": "",
    }
    by_core = defaultdict(list)
    for process in processes:
        for core, value in process["cores"].items():
            by_core[core].append((value, process))
    cores = []
    for name in sorted((n for n in data["cores"] if n != "cpu"), key=lambda n: int(n[3:])):
        core, values = name[3:], data["cores"][name]
        top_here = sorted(by_core.get(core, []), key=lambda x: -x[0])[:TOP_PER_CORE]
        row = {"time": stamp, "server": server_name, "core": core, "busy_percent": values["busy"],
               "user_percent": values["user"], "system_percent": values["system"],
               "iowait_percent": values["iowait"], "steal_percent": values["steal"], "idle_percent": values["idle"]}
        for i, (value, process) in enumerate(top_here, 1):
            row[f"top{i}"] = f"{label(process)} pid {process['pid']}: {value:.1f}%"
        cores.append(row)
    procs = []
    for rank, process in enumerate(processes[:MAX_PROCESSES], 1):
        if process["cpu"] < MIN_PROCESS_CPU and rank > 5:
            break
        procs.append({
            "time": stamp, "server": server_name, "rank": rank, "pid": process["pid"], "name": process.get("name"),
            "cpu_percent": process["cpu"], "server_share_percent": round(process["cpu"] / ncores, 2),
            "cores": " ".join(f"{c}:{v:.1f}" for c, v in process["cores"].items()),
            "service": process.get("service", ""), "user": process.get("user", ""),
            "threads": process.get("threads", ""), "rss_mb": process.get("rss_mb", ""),
            "state": process.get("state", ""), "command": process.get("command", ""),
        })
    return summary, cores, procs


def append(path, fields, items):
    if not items:
        return
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerows(items)


def collect_once(servers, out_dir, window, timeout):
    now = datetime.now()
    results = {}

    def run(server):
        try:
            results[server["name"]] = rows(server["name"], now, sample(server, window, timeout))
        except Exception as error:  # one server down must not stop the other
            results[server["name"]] = ({"time": now.strftime("%Y-%m-%d %H:%M:%S"), "server": server["name"],
                                        "error": str(error)[:300]}, [], [])

    workers = [threading.Thread(target=run, args=(s,)) for s in servers]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    day = now.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    for server in servers:
        summary, cores, procs = results[server["name"]]
        append(out_dir / f"cpu_summary_{day}.csv", SUMMARY_FIELDS, [summary])
        append(out_dir / f"cpu_cores_{day}.csv", CORE_FIELDS, cores)
        append(out_dir / f"cpu_processes_{day}.csv", PROCESS_FIELDS, procs)
        if summary.get("error"):
            print(f"{summary['time']} {server['name']}: ERROR {summary['error']}", flush=True)
        else:
            per_core = " ".join(f"c{c['core']}={float(c['busy_percent']):.0f}%" for c in cores)
            print(f"{summary['time']} {server['name']}: busy={summary['busy_percent']}% {per_core} "
                  f"load={summary['load_1']} top={summary['top_process']} {summary['top_process_cpu']}%", flush=True)


def report(out_dir, day):
    """Print a day summary per server from the stored CSVs."""
    def read(kind):
        path = out_dir / f"cpu_{kind}_{day}.csv"
        if not path.exists():
            raise SystemExit(f"No data: {path}")
        with path.open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    summary, cores, procs = read("summary"), read("cores"), read("processes")
    for server in sorted({r["server"] for r in summary}):
        good = [r for r in summary if r["server"] == server and not r["error"]]
        if not good:
            print(f"\n== {server}: no successful samples")
            continue
        busy = [float(r["busy_percent"]) for r in good]
        peak = max(good, key=lambda r: float(r["busy_percent"]))
        print(f"\n== {server} ({len(good)} samples, {good[0]['time'][11:16]}-{good[-1]['time'][11:16]})")
        print(f"CPU busy: avg {sum(busy) / len(busy):.1f}%  max {peak['busy_percent']}% at {peak['time'][11:16]} "
              f"(top: {peak['top_process']} {peak['top_process_cpu']}%)")
        print(f"iowait avg {sum(float(r['iowait_percent']) for r in good) / len(good):.1f}%  "
              f"steal avg {sum(float(r['steal_percent']) for r in good) / len(good):.1f}%  "
              f"load_1 max {max(float(r['load_1']) for r in good)}")
        per_core = defaultdict(list)
        for r in cores:
            if r["server"] == server:
                per_core[r["core"]].append(float(r["busy_percent"]))
        print("Cores avg/max busy: " + "  ".join(
            f"core{c} {sum(v) / len(v):.1f}/{max(v):.0f}%" for c, v in sorted(per_core.items(), key=lambda x: int(x[0]))))
        users = defaultdict(lambda: [0.0, set(), ""])
        for r in procs:
            if r["server"] == server:
                key = f"{r['name']} [{r['service'].removesuffix('.service')}]" if r["service"] else r["name"]
                users[key][0] += float(r["cpu_percent"])
                users[key][1].add(r["time"])  # postgres etc. run several processes per minute
                users[key][2] = r["command"][:90]
        print(f"Who used the CPU (average % of one core over {len(good)} samples):")
        for key, (total, seen, command) in sorted(users.items(), key=lambda x: -x[1][0])[:12]:
            print(f"  {total / len(good):6.1f}%  in {len(seen):4d} samples  {key}  {command}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=HERE / "servers.json")
    parser.add_argument("--output-dir", type=Path, default=HERE / "data" / "cpu")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between samples (default 60)")
    parser.add_argument("--window", type=float, default=5.0, help="measuring window on the server (default 5 s)")
    parser.add_argument("--count", type=int, default=0, help="samples to take; 0 = run until stopped")
    parser.add_argument("--timeout", type=int, default=20, help="SSH connect timeout")
    parser.add_argument("--server", action="append", help="only this server name (repeatable)")
    parser.add_argument("--report", nargs="?", const=date.today().isoformat(), metavar="DATE",
                        help="print the day summary (default today) instead of sampling")
    args = parser.parse_args()
    if args.report:
        report(args.output_dir, args.report)
        return 0
    servers = json.loads(args.config.read_text(encoding="utf-8"))["servers"]
    if args.server:
        servers = [s for s in servers if s["name"] in args.server]
    (HERE.parent / ".work").mkdir(exist_ok=True)
    taken = 0
    try:
        while args.count == 0 or taken < args.count:
            started = time.monotonic()
            collect_once(servers, args.output_dir, args.window, args.timeout)
            taken += 1
            if args.count == 0 or taken < args.count:
                time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
