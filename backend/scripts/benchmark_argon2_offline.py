"""Measure offline guessing speed against a stolen account envelope.

Evidence for the threat model (Issue #60, threat T-I2). An attacker holding a database dump has
every account's Argon2id salt and parameters and can guess passphrases offline, checking each
guess by trying to open the wrapped AMK. This measures how many such guesses per second one
machine manages at the enrolled cost, using argon2-cffi -- the native C reference
implementation, which `docs/crypto/test_vectors.json` proves computes byte-for-byte the same
KEK as the browser's hash-wasm.

    .venv/bin/python scripts/benchmark_argon2_offline.py

It measures a CPU. Dedicated GPU or ASIC rigs change the constant, not the method, and the
threat model states that assumption rather than hiding it. Only a derivation is timed: the
AES-GCM check that follows each guess costs microseconds and is ignored.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime

from argon2.low_level import Type, hash_secret_raw

# Must match frontend/src/utils/account-crypto.ts.
MEMORY_KIB = 65_536
ITERATIONS = 3
PARALLELISM = 1
HASH_LEN = 32
SALT_BYTES = 16

SINGLE_CORE_RUNS = 10
GUESSES_PER_WORKER = 30


def derive(guess: bytes, salt: bytes) -> bytes:
    return hash_secret_raw(
        guess,
        salt,
        time_cost=ITERATIONS,
        memory_cost=MEMORY_KIB,
        parallelism=PARALLELISM,
        hash_len=HASH_LEN,
        type=Type.ID,
        version=19,
    )


def worker(count: int) -> int:
    salt = secrets.token_bytes(SALT_BYTES)
    for i in range(count):
        derive(f"guess-{i}".encode(), salt)
    return count


def main() -> None:
    salt = secrets.token_bytes(SALT_BYTES)
    derive(b"warm-up", salt)

    single_ms = []
    for i in range(SINGLE_CORE_RUNS):
        started = time.perf_counter()
        derive(f"guess-{i}".encode(), salt)
        single_ms.append((time.perf_counter() - started) * 1000)

    # Memory-hard: each worker needs 64 MiB, so parallel throughput is bounded by memory
    # bandwidth as well as cores. Measure it rather than multiply the single-core figure.
    workers = os.cpu_count() or 1
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        done = sum(pool.map(worker, [GUESSES_PER_WORKER] * workers))
    elapsed = time.perf_counter() - started

    median_ms = statistics.median(single_ms)
    print(
        json.dumps(
            {
                "benchmark": "secureview-argon2id-offline-attacker",
                "version": 1,
                "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "machine": {
                    "platform": platform.platform(),
                    "processor": platform.processor() or platform.machine(),
                    "logical_cpus": workers,
                    "python": platform.python_version(),
                },
                "parameters": {
                    "memory_kib": MEMORY_KIB,
                    "iterations": ITERATIONS,
                    "parallelism": PARALLELISM,
                },
                "single_core": {
                    "median_ms": round(median_ms, 1),
                    "min_ms": round(min(single_ms), 1),
                    "max_ms": round(max(single_ms), 1),
                    "guesses_per_second": round(1000 / median_ms, 2),
                },
                "all_cores": {
                    "workers": workers,
                    "guesses": done,
                    "seconds": round(elapsed, 2),
                    "guesses_per_second": round(done / elapsed, 2),
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
