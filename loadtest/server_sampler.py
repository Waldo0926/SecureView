#!/usr/bin/env python3
"""Record the server's resource use during a load test, one CSV row per interval.

Runs on the server under test, with the system Python and nothing installed: it only reads
/proc and asks `ss` for socket counts. It never writes anywhere but its output file, and
never touches the application or the database.

    python3 server_sampler.py --interval 2 --out /root/loadtest-metrics.csv
    # ... run the load test from another machine ...
    # Ctrl-C to stop, then copy the CSV back for the report.

Columns: time, whole-machine CPU %, iowait %, load average, memory used and available,
disk read/write MB/s, network rx/tx MB/s, the backend process's CPU % and RSS, mysqld's CPU %
and RSS, and established connections to MySQL (port 3306) and to the API (port 8000).
"""

from __future__ import annotations

import argparse
import csv
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
PAGE_KIB = os.sysconf("SC_PAGE_SIZE") // 1024


def cpu_times() -> tuple[int, int, int]:
    """(total, idle, iowait) jiffies across all CPUs."""
    fields = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
    idle, iowait = fields[3], fields[4]
    return sum(fields[:8]), idle + iowait, iowait


def meminfo() -> tuple[float, float]:
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, rest = line.split(":", 1)
        values[key] = int(rest.split()[0])
    total, available = values["MemTotal"], values["MemAvailable"]
    return (total - available) / 1024, available / 1024


def disk_sectors() -> tuple[int, int]:
    """Sectors read and written on whole disks (not partitions, not loop or ram devices)."""
    read = written = 0
    for line in Path("/proc/diskstats").read_text().splitlines():
        parts = line.split()
        name = parts[2]
        if name.startswith(("loop", "ram", "dm-", "sr")) or (
            name[-1].isdigit() and not name.startswith("nvme")
        ):
            continue
        if name.startswith("nvme") and "p" in name[4:]:
            continue
        read += int(parts[5])
        written += int(parts[9])
    return read, written


def net_bytes() -> tuple[int, int]:
    rx = tx = 0
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        name, data = line.split(":", 1)
        name = name.strip()
        if name == "lo" or name.startswith(("docker", "br-", "veth")):
            continue
        fields = data.split()
        rx += int(fields[0])
        tx += int(fields[8])
    return rx, tx


def find_pid(predicate) -> int | None:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if predicate(cmdline):
            return int(entry.name)
    return None


def proc_usage(pid: int | None) -> tuple[int, float]:
    """(utime+stime jiffies, RSS MiB) for one process, or (0, 0) if it is gone."""
    if pid is None:
        return 0, 0.0
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat[stat.rindex(")") + 2 :].split()
        rss_pages = int(fields[21])
        return int(fields[11]) + int(fields[12]), rss_pages * PAGE_KIB / 1024
    except (OSError, ValueError, IndexError):
        return 0, 0.0


def established(port: int) -> int:
    try:
        out = subprocess.run(
            ["ss", "-Htn", "state", "established", f"( dport = :{port} or sport = :{port} )"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1
    return sum(1 for line in out.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--db-port", type=int, default=3306)
    args = parser.parse_args()

    backend = find_pid(lambda c: "uvicorn app.main:app" in c and f"--port {args.api_port}" in c)
    mysqld = find_pid(lambda c: c.startswith("mysqld") or "/mysqld " in c)
    print(
        f"backend pid {backend}, mysqld pid {mysqld}; writing {args.out} every {args.interval}s",
        file=sys.stderr,
    )

    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    prev_cpu, prev_disk, prev_net = cpu_times(), disk_sectors(), net_bytes()
    prev_backend, prev_mysqld = proc_usage(backend)[0], proc_usage(mysqld)[0]
    prev_t = time.monotonic()
    with args.out.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "time",
                "cpu_pct",
                "iowait_pct",
                "load1",
                "mem_used_mib",
                "mem_available_mib",
                "disk_read_mbs",
                "disk_write_mbs",
                "net_rx_mbs",
                "net_tx_mbs",
                "backend_cpu_pct",
                "backend_rss_mib",
                "mysqld_cpu_pct",
                "mysqld_rss_mib",
                "db_connections",
                "api_connections",
            ]
        )
        while not stop:
            time.sleep(args.interval)
            now_t = time.monotonic()
            dt = now_t - prev_t
            cpu, disk, net = cpu_times(), disk_sectors(), net_bytes()
            b_jiffies, b_rss = proc_usage(backend)
            m_jiffies, m_rss = proc_usage(mysqld)
            total = max(cpu[0] - prev_cpu[0], 1)
            used, available = meminfo()
            writer.writerow(
                [
                    round(time.time(), 1),
                    round(100 * (1 - (cpu[1] - prev_cpu[1]) / total), 1),
                    round(100 * (cpu[2] - prev_cpu[2]) / total, 1),
                    os.getloadavg()[0],
                    round(used),
                    round(available),
                    round((disk[0] - prev_disk[0]) * 512 / 1e6 / dt, 2),
                    round((disk[1] - prev_disk[1]) * 512 / 1e6 / dt, 2),
                    round((net[0] - prev_net[0]) / 1e6 / dt, 2),
                    round((net[1] - prev_net[1]) / 1e6 / dt, 2),
                    # Per-process CPU is in "one core = 100%", so 8 busy cores read 800.
                    round(100 * (b_jiffies - prev_backend) / CLOCK_TICKS / dt, 1),
                    round(b_rss),
                    round(100 * (m_jiffies - prev_mysqld) / CLOCK_TICKS / dt, 1),
                    round(m_rss),
                    established(args.db_port),
                    established(args.api_port),
                ]
            )
            handle.flush()
            prev_t, prev_cpu, prev_disk, prev_net = now_t, cpu, disk, net
            prev_backend, prev_mysqld = b_jiffies, m_jiffies
    print("stopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
