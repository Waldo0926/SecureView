"""The test scenarios. Each returns a list of steps; each step is a summary plus its raw ops.

The scenarios follow the matrix agreed at the 2026-10-01 supervisor meeting
(docs/PERFORMANCE_TESTING.md): concurrent users, file size and type, parallel tasks per
user, mixed load, sustained load, and overload followed by recovery (a `steps` run whose
user list goes past the stable limit and back down).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from . import envelope, fixtures
from .client import Account, Op, RecoveryKey, VirtualUser
from .metrics import summarise, windows

__all__ = ["Fleet", "Step", "envelope", "summarise"]


SIGN_IN_ATTEMPTS = 12


class SignInFailed(RuntimeError):
    pass


@dataclass(slots=True)
class Step:
    label: str
    params: dict[str, object]
    started_utc: float
    ops: list[Op] = field(default_factory=list)
    duration_s: float = 0.0
    series: list[dict[str, object]] | None = None

    def summary(self) -> dict[str, object]:
        out: dict[str, object] = {
            "label": self.label,
            "params": self.params,
            "started_utc": self.started_utc,
            "ended_utc": self.started_utc + self.duration_s,
            "results": summarise(self.ops, duration_s=self.duration_s),
        }
        if self.series is not None:
            out["series"] = self.series
        return out


class Fleet:
    """The signed-in virtual users and the deployment's recovery key."""

    def __init__(
        self, accounts: Sequence[Account], *, base_url: str, timeout: float, verify_tls: bool
    ):
        self.accounts = list(accounts)
        self.base_url, self.timeout, self.verify_tls = base_url, timeout, verify_tls
        self.users: list[VirtualUser] = []
        self.recovery: RecoveryKey | None = None
        self.login_ops: list[Op] = []

    async def sign_in(self, count: int, *, concurrency: int) -> list[VirtualUser]:
        """Make sure `count` users are signed in. Sign-in is paced on purpose: every login
        is an Argon2id verification at 64 MiB on the server, and the server caps how many run
        at once. A thundering herd of logins would measure that cap, not the file path."""
        if count > len(self.accounts):
            raise SystemExit(f"{count} users needed but the accounts file has {len(self.accounts)}")
        gate = asyncio.Semaphore(concurrency)

        async def one(account: Account) -> VirtualUser:
            user = VirtualUser(
                account, base_url=self.base_url, timeout=self.timeout, verify_tls=self.verify_tls
            )
            for attempt in range(SIGN_IN_ATTEMPTS):
                async with gate:
                    op = await user.login()
                self.login_ops.append(op)
                if op.ok:
                    return user
                if op.status != 429 and not (op.status or 0) >= 500:
                    break
                # 429 is the server's cap on concurrent Argon2id verifications (or nginx's sign-in
                # limit); a 500 has been a MySQL deadlock between two simultaneous sign-ins (see
                # docs/PERFORMANCE_TESTING.md). Sign-in is setup, not what a step measures, so
                # wait and retry; every failure is still recorded and reported, and the `logins`
                # scenario measures both without retrying.
                await asyncio.sleep(min(0.25 * 2**attempt, 8.0) * (0.5 + random.random()))
            await user.close()
            raise SignInFailed(f"sign-in failed for {account.username}: {op.error}")

        missing = self.accounts[len(self.users) : count]
        results = await asyncio.gather(*(one(a) for a in missing), return_exceptions=True)
        signed_in = [r for r in results if isinstance(r, VirtualUser)]
        failures = [r for r in results if isinstance(r, BaseException)]
        self.users.extend(signed_in)
        if failures:
            raise SignInFailed(str(failures[0]))
        if self.recovery is None:
            self.recovery = await self.users[0].recovery_key()
        return self.users[:count]

    async def close(self) -> None:
        await asyncio.gather(*(user.close() for user in self.users))


async def _run_for(
    users: Sequence[VirtualUser],
    tasks_per_user: int,
    duration_s: float,
    task: Callable[[VirtualUser], Awaitable[list[Op]]],
) -> tuple[list[Op], float]:
    """Every user runs `tasks_per_user` loops of `task` until the deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration_s
    ops: list[Op] = []

    async def worker(user: VirtualUser) -> None:
        while loop.time() < deadline:
            ops.extend(await task(user))

    t0 = time.perf_counter()
    await asyncio.gather(*(worker(user) for user in users for _ in range(tasks_per_user)))
    return ops, time.perf_counter() - t0


def _round_trip(
    plaintext: bytes, digest: str, *, label: str, algorithm: str, recovery: RecoveryKey
):
    """Upload a file, then download, decrypt and verify it: the core user journey."""

    async def task(user: VirtualUser) -> list[Op]:
        up = await user.upload(
            plaintext,
            digest=digest,
            filename=f"load-{label}.bin",
            mime_type="application/octet-stream",
            algorithm=algorithm,
            recovery=recovery,
            size_label=label,
            file_type="bin",
        )
        if not up.ok:
            return [up]
        file_id, _ = user.files[-1]
        down = await user.download(file_id, digest, size_label=label, file_type="bin")
        return [up, down]

    return task


async def steps(
    fleet: Fleet,
    *,
    users: Sequence[int],
    duration_s: float,
    size: int,
    tasks_per_user: int,
    algorithm: str,
    cooldown_s: float,
    login_concurrency: int,
    stop_error_rate: float | None,
    report: Callable[[Step], None],
) -> list[Step]:
    """Concurrent users, stepped: 1, 5, 10, ... each for `duration_s`."""
    plaintext = fixtures.make("bin", size)
    digest, label = envelope.sha256(plaintext), fixtures.size_label(size)
    out: list[Step] = []
    for count in users:
        active = await fleet.sign_in(count, concurrency=login_concurrency)
        assert fleet.recovery is not None
        step = Step(
            f"{count} users",
            {"users": count, "tasks_per_user": tasks_per_user, "size": label},
            time.time(),
        )
        step.ops, step.duration_s = await _run_for(
            active,
            tasks_per_user,
            duration_s,
            _round_trip(
                plaintext, digest, label=label, algorithm=algorithm, recovery=fleet.recovery
            ),
        )
        out.append(step)
        report(step)
        rate = step.summary()["results"]["_all"]["error_rate"]  # type: ignore[index]
        if stop_error_rate is not None and rate > stop_error_rate:
            print(f"stopping: error rate {rate:.1%} is over {stop_error_rate:.0%}")
            break
        await asyncio.sleep(cooldown_s)
    return out


async def parallel(
    fleet: Fleet,
    *,
    users: int,
    tasks: Sequence[int],
    duration_s: float,
    size: int,
    algorithm: str,
    cooldown_s: float,
    login_concurrency: int,
    report: Callable[[Step], None],
) -> list[Step]:
    """A fixed number of users, each running 1, 2, 5, 10 file tasks at once."""
    plaintext = fixtures.make("bin", size)
    digest, label = envelope.sha256(plaintext), fixtures.size_label(size)
    active = await fleet.sign_in(users, concurrency=login_concurrency)
    assert fleet.recovery is not None
    out: list[Step] = []
    for per_user in tasks:
        step = Step(
            f"{per_user} tasks/user",
            {"users": users, "tasks_per_user": per_user, "size": label},
            time.time(),
        )
        step.ops, step.duration_s = await _run_for(
            active,
            per_user,
            duration_s,
            _round_trip(
                plaintext, digest, label=label, algorithm=algorithm, recovery=fleet.recovery
            ),
        )
        out.append(step)
        report(step)
        await asyncio.sleep(cooldown_s)
    return out


async def mixed(
    fleet: Fleet,
    *,
    users: int,
    duration_s: float,
    size: int,
    weights: tuple[int, int, int],
    algorithm: str,
    window_s: float,
    login_concurrency: int,
    seed: int | None,
    report: Callable[[Step], None],
) -> list[Step]:
    """Realistic traffic: upload / download / share-and-list by weight. A long duration is
    the sustained-load (soak) test; the per-window series shows drift over time."""
    if users < 2:
        raise SystemExit("mixed load needs at least 2 users, so there is someone to share with")
    rng = random.Random(seed)
    plaintext = fixtures.make("bin", size)
    digest, label = envelope.sha256(plaintext), fixtures.size_label(size)
    active = await fleet.sign_in(users, concurrency=login_concurrency)
    recovery = fleet.recovery
    assert recovery is not None

    # Everyone starts with one file, so the first download has something to fetch.
    warm = await asyncio.gather(
        *(
            u.upload(
                plaintext,
                digest=digest,
                filename=f"load-{label}.bin",
                mime_type="application/octet-stream",
                algorithm=algorithm,
                recovery=recovery,
                size_label=label,
                file_type="bin",
            )
            for u in active
        )
    )
    if not all(op.ok for op in warm):
        raise SystemExit(f"warm-up upload failed: {[op.error for op in warm if not op.ok]}")

    upload_w, download_w, _ = weights

    async def task(user: VirtualUser) -> list[Op]:
        roll = rng.uniform(0, sum(weights))
        if roll < upload_w:
            return [
                await user.upload(
                    plaintext,
                    digest=digest,
                    filename=f"load-{label}.bin",
                    mime_type="application/octet-stream",
                    algorithm=algorithm,
                    recovery=recovery,
                    size_label=label,
                    file_type="bin",
                )
            ]
        file_id, file_digest = rng.choice(user.files)
        if roll < upload_w + download_w:
            return [await user.download(file_id, file_digest, size_label=label, file_type="bin")]
        if rng.random() < 0.5:
            recipient = rng.choice([u for u in active if u is not user])
            return [await user.share(file_id, recipient)]
        return [await user.list_files()]

    step = Step(
        f"mixed {users} users",
        {"users": users, "size": label, "weights": list(weights), "duration_s": duration_s},
        time.time(),
    )
    step.ops, step.duration_s = await _run_for(active, 1, duration_s, task)
    step.series = windows(step.ops, width_s=window_s)
    report(step)
    return [step]


async def sizes(
    fleet: Fleet,
    *,
    sizes_: Sequence[int],
    types: Sequence[str],
    repeat: int,
    algorithm: str,
    login_concurrency: int,
    report: Callable[[Step], None],
) -> list[Step]:
    """Each type at each size: upload, download and verify, share, recipient downloads and
    verifies with their own key. One at a time, so a time is the time for that file alone.

    Each type has its own owner account and every file is deleted once it is verified. The
    whole matrix is about 5 GiB, more than one account's 2 GiB storage and 5 GiB daily upload
    allowance, and those limits stay on during a run against staging."""
    signed_in = await fleet.sign_in(len(types) + 1, concurrency=login_concurrency)
    owners = dict(zip(types, signed_in[: len(types)], strict=True))
    recipient = signed_in[len(types)]
    recovery = fleet.recovery
    assert recovery is not None
    out: list[Step] = []
    for size in sizes_:
        label = fixtures.size_label(size)
        step = Step(label, {"size": label, "types": list(types), "repeat": repeat}, time.time())
        t0 = time.perf_counter()
        for file_type in types:
            owner = owners[file_type]
            for _ in range(repeat):
                plaintext = fixtures.make(file_type, size)
                digest = envelope.sha256(plaintext)
                up = await owner.upload(
                    plaintext,
                    digest=digest,
                    filename=f"load-{label}.{file_type}",
                    mime_type=fixtures.MIME_TYPES[file_type],
                    algorithm=algorithm,
                    recovery=recovery,
                    size_label=label,
                    file_type=file_type,
                )
                step.ops.append(up)
                if not up.ok:
                    continue
                file_id, _ = owner.files[-1]
                step.ops.append(
                    await owner.download(file_id, digest, size_label=label, file_type=file_type)
                )
                shared = await owner.share(file_id, recipient)
                shared.size_label, shared.file_type = label, file_type
                step.ops.append(shared)
                if shared.ok:
                    got = await recipient.download(
                        file_id, digest, size_label=label, file_type=file_type
                    )
                    got.kind = "recipient_download"
                    step.ops.append(got)
                removed = await owner.delete_file(file_id)
                removed.size_label, removed.file_type = label, file_type
                step.ops.append(removed)
                del plaintext
        step.duration_s = time.perf_counter() - t0
        out.append(step)
        report(step)
    return out


async def logins(
    fleet: Fleet, *, users: Sequence[int], rounds: int, report: Callable[[Step], None], **_ignored
) -> list[Step]:
    """Simultaneous sign-ins, with no retry: how many the server accepts at once.

    Every sign-in is an Argon2id verification at 64 MiB, and the server runs at most
    AUTH_PASSWORD_HASH_CONCURRENCY of them at a time (2 by default), refusing the rest with 429
    rather than queueing them. This step measures that limit directly.
    """
    if max(users) > len(fleet.accounts):
        raise SystemExit(
            f"{max(users)} users needed but the accounts file has {len(fleet.accounts)}"
        )
    out: list[Step] = []
    for count in users:
        clients = [
            VirtualUser(
                a, base_url=fleet.base_url, timeout=fleet.timeout, verify_tls=fleet.verify_tls
            )
            for a in fleet.accounts[:count]
        ]
        step = Step(f"{count} at once", {"users": count, "rounds": rounds}, time.time())
        t0 = time.perf_counter()
        try:
            for _ in range(rounds):
                step.ops.extend(await asyncio.gather(*(c.login() for c in clients)))
                await asyncio.sleep(1.0)
        finally:
            await asyncio.gather(*(c.close() for c in clients))
        step.duration_s = time.perf_counter() - t0
        out.append(step)
        report(step)
    return out
