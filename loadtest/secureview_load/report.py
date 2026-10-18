"""Write a Markdown performance report (and PNG charts) from one or more result directories.

    python -m secureview_load.report results/ --server-metrics loadtest-metrics.csv --out REPORT.md

Each `summary.json` under the given directory becomes a section. With `--server-metrics` (the
CSV from `server_sampler.py`), every step also gets the server's CPU, memory, disk, network and
connection figures for exactly the time that step ran, which is what locates the bottleneck.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean

SERVER_COLUMNS = {
    "cpu_pct": "CPU %",
    "iowait_pct": "iowait %",
    "mem_used_mib": "RAM used MiB",
    "backend_cpu_pct": "API proc CPU %",
    "backend_rss_mib": "API RSS MiB",
    "mysqld_cpu_pct": "MySQL CPU %",
    "db_connections": "DB conns",
    "disk_write_mbs": "disk write MB/s",
    "net_rx_mbs": "net rx MB/s",
    "net_tx_mbs": "net tx MB/s",
}


def _fmt(value, digits: int = 0) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def load_server_metrics(path: Path | None) -> list[dict[str, float]]:
    if path is None:
        return []
    with path.open() as handle:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def server_during(
    rows: list[dict[str, float]], start: float, end: float
) -> dict[str, tuple[float, float]]:
    """Mean and peak of each server column while a step ran."""
    window = [r for r in rows if start <= r["time"] <= end]
    if not window:
        return {}
    return {
        col: (round(mean(r[col] for r in window), 1), round(max(r[col] for r in window), 1))
        for col in SERVER_COLUMNS
        if col in window[0]
    }


def _step_table(summary: dict, server: list[dict[str, float]]) -> list[str]:
    lines = [
        "| Step | Op | n | ok | error % | p50 ms | p95 ms | p99 ms | ops/s | MiB/s | crypto p50 ms | errors |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    server_lines: list[str] = []
    for step in summary["steps"]:
        for kind, r in step["results"].items():
            if kind == "_all":
                continue
            lat = r["request_ms"]
            errors = ", ".join(f"{k} x{v}" for k, v in r["errors"].items()) or ""
            lines.append(
                f"| {step['label']} | {kind} | {r['count']} | {r['ok']} | {r['error_rate'] * 100:.1f} | "
                f"{_fmt(lat['p50'])} | {_fmt(lat['p95'])} | {_fmt(lat['p99'])} | {_fmt(r['ops_per_s'], 2)} | "
                f"{_fmt(r['mib_per_s'], 2)} | {_fmt(r['crypto_ms']['p50'])} | {errors} |"
            )
        during = server_during(server, step["started_utc"], step["ended_utc"])
        if during:
            server_lines.append(
                f"| {step['label']} | "
                + " | ".join(
                    f"{during[c][0]} / {during[c][1]}" for c in SERVER_COLUMNS if c in during
                )
                + " |"
            )
    if server_lines:
        lines += [
            "",
            "Server during each step (mean / peak):",
            "",
            "| Step | " + " | ".join(SERVER_COLUMNS[c] for c in SERVER_COLUMNS) + " |",
            "|---|" + "---:|" * len(SERVER_COLUMNS),
            *server_lines,
        ]
    return lines


def _charts(summary: dict, out_dir: Path, name: str) -> list[str]:
    """p95 and throughput against the step, for stepped scenarios. Needs matplotlib."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    steps = summary["steps"]
    kinds = sorted({k for s in steps for k in s["results"] if k != "_all"})
    if len(steps) < 2 or not kinds:
        return []
    labels = [s["label"] for s in steps]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4))
    for kind in kinds:
        p95 = [s["results"].get(kind, {}).get("request_ms", {}).get("p95") for s in steps]
        ops = [s["results"].get(kind, {}).get("ops_per_s") for s in steps]
        left.plot(
            labels, [v if v is not None else float("nan") for v in p95], marker="o", label=kind
        )
        right.plot(
            labels, [v if v is not None else float("nan") for v in ops], marker="o", label=kind
        )
    errors = [s["results"]["_all"]["error_rate"] * 100 for s in steps]
    left.set_title("p95 latency (ms)")
    right.set_title("successful operations per second")
    for axis in (left, right):
        axis.tick_params(axis="x", rotation=30)
        axis.grid(alpha=0.3)
        axis.legend()
    if any(errors):
        twin = right.twinx()
        twin.bar(labels, errors, alpha=0.2, color="red")
        twin.set_ylabel("error %")
    fig.tight_layout()
    path = out_dir / f"{name}.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return [f"![{name}]({path.name})"]


def build(results: Path, server_csv: Path | None, out: Path) -> str:
    server = load_server_metrics(server_csv)
    summaries = sorted(results.rglob("summary.json"))
    lines = ["# SecureView load test report", ""]
    if not summaries:
        lines.append("No summary.json found.")
    for path in summaries:
        summary = json.loads(path.read_text())
        cfg = summary["config"]
        name = path.parent.name
        lines += [
            f"## {summary['scenario']} — `{name}`",
            "",
            f"Target `{cfg.get('base_url')}`, algorithm {cfg.get('algorithm')}. "
            f"Request times are measured at the client and include the network; crypto times are "
            f"the client's own encryption or decryption (the server never decrypts).",
            "",
        ]
        if summary.get("login"):
            lat = summary["login"]["request_ms"]
            lines += [
                f"Sign-in (Argon2id on the server): p50 {_fmt(lat['p50'])} ms, p95 {_fmt(lat['p95'])} ms over {summary['login']['count']} sign-ins.",
                "",
            ]
        lines += _step_table(summary, server)
        lines += ["", *_charts(summary, out.parent, name), ""]
        for step in summary["steps"]:
            if step.get("series"):
                lines += [
                    f"Time series for {step['label']} (per window):",
                    "",
                    "| t (s) | ops | errors | p95 ms | ops/s |",
                    "|---:|---:|---:|---:|---:|",
                ]
                lines += [
                    f"| {w['t_s']} | {w['ops']} | {w['errors']} | {_fmt(w['p95_ms'])} | {w['ops_per_s']} |"
                    for w in step["series"]
                ]
                lines.append("")
    text = "\n".join(lines) + "\n"
    out.write_text(text)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--server-metrics", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("REPORT.md"))
    args = parser.parse_args(argv)
    build(args.results, args.server_metrics, args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
