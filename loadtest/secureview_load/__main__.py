"""Command line: `python -m secureview_load --base-url ... --accounts ... <scenario> [options]`.

See docs/PERFORMANCE_TESTING.md for the plan, and `<scenario> --help` for each one's options.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from . import fixtures, runner
from .client import Account, VirtualUser

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _ints(text: str) -> list[int]:
    return [int(part) for part in text.split(",") if part.strip()]


def _sizes(text: str) -> list[int]:
    return [fixtures.parse_size(part) for part in text.split(",") if part.strip()]


def _load_accounts(path: Path) -> list[Account]:
    data = json.loads(path.read_text())
    return [
        Account(a["username"], a["password"], a["key_id"], a["private_key_pem"])
        for a in data["accounts"]
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m secureview_load", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--base-url", required=True, help="API root, e.g. http://127.0.0.1:18000/api/v1"
    )
    parser.add_argument(
        "--accounts", type=Path, required=True, help="JSON from scripts/seed_load_users.py"
    )
    parser.add_argument("--out", type=Path, default=Path("results"), help="results directory")
    parser.add_argument("--timeout", type=float, default=600.0, help="per-request timeout, seconds")
    parser.add_argument(
        "--algorithm", default="AES-256-GCM", choices=sorted(runner.envelope.ALGORITHMS)
    )
    parser.add_argument(
        "--login-concurrency",
        type=int,
        default=2,
        help="sign-ins in flight during setup; the server verifies 2 passwords at a time by default",
    )
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks")
    parser.add_argument(
        "--confirm-remote",
        action="store_true",
        help="required for any host that is not this machine: a load test against a shared server "
        "is a decision, not a default",
    )
    sub = parser.add_subparsers(dest="scenario", required=True)

    s = sub.add_parser("smoke", help="one upload, download, share and recipient download")
    s.add_argument("--size", type=fixtures.parse_size, default=fixtures.parse_size("64KiB"))

    s = sub.add_parser(
        "steps", help="concurrent users, stepped up (and down, for overload/recovery)"
    )
    s.add_argument("--users", type=_ints, default=_ints("1,5,10,20,50,100"))
    s.add_argument("--duration", type=float, default=60.0, help="seconds per step")
    s.add_argument("--size", type=fixtures.parse_size, default=fixtures.parse_size("1MiB"))
    s.add_argument("--tasks-per-user", type=int, default=1)
    s.add_argument("--cooldown", type=float, default=10.0)
    s.add_argument(
        "--stop-error-rate", type=float, default=None, help="e.g. 0.2 stops after a step over 20%%"
    )

    s = sub.add_parser("parallel", help="fixed users, more parallel file tasks per user")
    s.add_argument("--users", type=int, default=5)
    s.add_argument("--tasks", type=_ints, default=_ints("1,2,5,10"))
    s.add_argument("--duration", type=float, default=60.0)
    s.add_argument("--size", type=fixtures.parse_size, default=fixtures.parse_size("1MiB"))
    s.add_argument("--cooldown", type=float, default=10.0)

    s = sub.add_parser("mixed", help="70/20/10 upload/download/share+list; long duration = soak")
    s.add_argument("--users", type=int, default=20)
    s.add_argument("--duration", type=float, default=300.0)
    s.add_argument("--size", type=fixtures.parse_size, default=fixtures.parse_size("1MiB"))
    s.add_argument("--weights", type=_ints, default=_ints("70,20,10"))
    s.add_argument("--window", type=float, default=30.0, help="time-series window, seconds")
    s.add_argument("--seed", type=int, default=None)

    s = sub.add_parser("sizes", help="every file type at every size, verified end to end")
    s.add_argument("--sizes", type=_sizes, default=_sizes("1MiB,10MiB,50MiB,100MiB,200MiB,500MiB"))
    s.add_argument("--types", default="pdf,png,jpg,mp4,zip,exe")
    s.add_argument("--repeat", type=int, default=1)

    s = sub.add_parser(
        "logins", help="simultaneous sign-ins with no retry: the Argon2id concurrency cap"
    )
    s.add_argument("--users", type=_ints, default=_ints("1,2,4,8,16"))
    s.add_argument("--rounds", type=int, default=3)

    sub.add_parser("cleanup", help="delete every account in the accounts file, and all their files")
    return parser


def _print_step(step: runner.Step) -> None:
    results = step.summary()["results"]
    print(f"\n== {step.label}  ({step.duration_s:.1f}s)")
    print(
        f"   {'op':<20}{'n':>6}{'ok':>6}{'err%':>7}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'ops/s':>8}{'MiB/s':>8}"
    )
    for kind, r in results.items():  # type: ignore[union-attr]
        if kind == "_all":
            continue
        lat = r["request_ms"]
        print(
            f"   {kind:<20}{r['count']:>6}{r['ok']:>6}{r['error_rate'] * 100:>6.1f}%"
            f"{lat['p50'] or 0:>10.0f}{lat['p95'] or 0:>10.0f}{lat['p99'] or 0:>10.0f}"
            f"{r['ops_per_s'] or 0:>8.2f}{r['mib_per_s'] or 0:>8.2f}"
        )
        if r["errors"]:
            print(f"   {'':<20}errors: {r['errors']}")


CLEANUP_ATTEMPTS = 8


async def _cleanup(args: argparse.Namespace, accounts: list[Account]) -> int:
    """Delete every account. Sign-in and delete-account are both credential checks, which nginx
    allows 60 a minute per address, so a 429 here means wait and try again, not "gone". On the
    first staging run through the public URL, giving up on 429 left 32 of 100 accounts behind."""
    failures = 0
    for account in accounts:
        user = VirtualUser(
            account, base_url=args.base_url, timeout=args.timeout, verify_tls=not args.insecure
        )
        try:
            for attempt in range(CLEANUP_ATTEMPTS):
                login = await user.login()
                if login.status != 429:
                    break
                await asyncio.sleep(2 * 2**attempt)
            if not login.ok:
                print(f"{account.username}: sign-in {login.error} (already deleted?)", flush=True)
                failures += login.status == 429
                continue
            for attempt in range(CLEANUP_ATTEMPTS):
                status = await user.delete_account()
                if status != 429:
                    break
                await asyncio.sleep(2 * 2**attempt)
            print(f"{account.username}: delete-account HTTP {status}", flush=True)
            failures += status != 200
        finally:
            await user.close()
        # Two credential checks per account; this keeps a full cleanup under nginx's 60 a minute.
        await asyncio.sleep(2.0)
    return 1 if failures else 0


async def _main(args: argparse.Namespace) -> int:
    accounts = _load_accounts(args.accounts)
    if args.scenario == "cleanup":
        return await _cleanup(args, accounts)

    run_dir = args.out / f"{args.scenario}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    fleet = runner.Fleet(
        accounts, base_url=args.base_url, timeout=args.timeout, verify_tls=not args.insecure
    )
    common = {
        "algorithm": args.algorithm,
        "login_concurrency": args.login_concurrency,
        "report": _print_step,
    }
    started = time.time()
    try:
        if args.scenario == "smoke":
            steps = await runner.sizes(fleet, sizes_=[args.size], types=["pdf"], repeat=1, **common)
        elif args.scenario == "steps":
            steps = await runner.steps(
                fleet,
                users=args.users,
                duration_s=args.duration,
                size=args.size,
                tasks_per_user=args.tasks_per_user,
                cooldown_s=args.cooldown,
                stop_error_rate=args.stop_error_rate,
                **common,
            )
        elif args.scenario == "parallel":
            steps = await runner.parallel(
                fleet,
                users=args.users,
                tasks=args.tasks,
                duration_s=args.duration,
                size=args.size,
                cooldown_s=args.cooldown,
                **common,
            )
        elif args.scenario == "mixed":
            steps = await runner.mixed(
                fleet,
                users=args.users,
                duration_s=args.duration,
                size=args.size,
                weights=tuple(args.weights),
                window_s=args.window,
                seed=args.seed,
                **common,
            )
        elif args.scenario == "logins":
            steps = await runner.logins(fleet, users=args.users, rounds=args.rounds, **common)
        else:
            steps = await runner.sizes(
                fleet, sizes_=args.sizes, types=args.types.split(","), repeat=args.repeat, **common
            )
    except runner.SignInFailed as exc:
        print(f"setup failed: {exc}", file=sys.stderr)
        return 3
    finally:
        await fleet.close()

    config = {k: v for k, v in vars(args).items() if k not in {"accounts", "out"}}
    config = {k: (str(v) if isinstance(v, Path) else v) for k, v in config.items()}
    summary = {
        "scenario": args.scenario,
        "config": config,
        "started_utc": started,
        "ended_utc": time.time(),
        "login": runner.summarise(fleet.login_ops, duration_s=1.0).get("login"),
        "steps": [step.summary() for step in steps],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    with (run_dir / "ops.jsonl").open("w") as handle:
        for step in steps:
            for op in step.ops:
                handle.write(json.dumps({"step": step.label, **dataclasses.asdict(op)}) + "\n")
    print(f"\nresults: {run_dir}")
    failed = sum(s["results"]["_all"]["failed"] for s in summary["steps"])  # type: ignore[index]
    verify_failed = sum(
        r.get("verify_failed", 0)
        for s in summary["steps"]
        for k, r in s["results"].items()  # type: ignore[union-attr]
        if k != "_all"
    )
    if verify_failed:
        print(
            f"INTEGRITY: {verify_failed} download(s) did not decrypt to the original bytes",
            file=sys.stderr,
        )
        return 2
    return 1 if args.scenario in {"smoke", "sizes"} and failed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = urlparse(args.base_url).hostname or ""
    if host not in LOCAL_HOSTS and not args.confirm_remote:
        print(
            f"{host} is not this machine. Add --confirm-remote once the server is free for testing.",
            file=sys.stderr,
        )
        return 2
    if host not in LOCAL_HOSTS and args.base_url.startswith("https://"):
        print(
            "note: through nginx each source IP is limited to 30 API requests/s (burst 60), "
            "60 credential checks/min and 50 uploads in flight, so expect HTTP 429 from one "
            "generator; count it as the limiter working, not as a server error. "
            "See docs/PERFORMANCE_TESTING.md.",
            file=sys.stderr,
        )
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
