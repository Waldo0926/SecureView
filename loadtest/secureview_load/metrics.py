"""Turn timed operations into the numbers a performance report needs."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from .client import Op


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100). None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return round(ordered[rank - 1], 1)


def _latency(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": round(max(values), 1) if values else None,
        "mean": round(sum(values) / len(values), 1) if values else None,
    }


def summarise(ops: Iterable[Op], *, duration_s: float) -> dict[str, object]:
    """Per operation kind: counts, error breakdown, latency percentiles and throughput.

    Latency covers successful operations only; failed ones are counted in `errors`. A 429 or
    a timeout that came back fast would otherwise make a struggling server look quicker.
    """
    by_kind: dict[str, list[Op]] = defaultdict(list)
    for op in ops:
        by_kind[op.kind].append(op)
    out: dict[str, object] = {}
    total = failed = 0
    for kind, items in sorted(by_kind.items()):
        good = [op for op in items if op.ok]
        moved = sum(op.bytes for op in good)
        total += len(items)
        failed += len(items) - len(good)
        out[kind] = {
            "count": len(items),
            "ok": len(good),
            "error_rate": round((len(items) - len(good)) / len(items), 4) if items else 0.0,
            "errors": dict(Counter(op.error or "unknown" for op in items if not op.ok)),
            "request_ms": _latency([op.request_ms for op in good]),
            "crypto_ms": _latency([op.crypto_ms for op in good if op.crypto_ms]),
            "ops_per_s": round(len(good) / duration_s, 2) if duration_s else None,
            "mib_per_s": round(moved / 1024 / 1024 / duration_s, 2) if duration_s else None,
            # Per operation, bytes over time on the wire: the speed one transfer saw.
            "wire_mib_per_s_p50": percentile(
                [
                    op.bytes / 1024 / 1024 / (op.request_ms / 1000)
                    for op in good
                    if op.bytes and op.request_ms
                ],
                50,
            ),
            "verified": sum(1 for op in good if op.verified),
            "verify_failed": sum(1 for op in items if op.verified is False),
        }
    out["_all"] = {
        "count": total,
        "failed": failed,
        "error_rate": round(failed / total, 4) if total else 0.0,
        "duration_s": round(duration_s, 1),
    }
    return out


def windows(ops: Sequence[Op], *, width_s: float) -> list[dict[str, object]]:
    """Time series for a soak test: per window, throughput, p95 and errors."""
    if not ops:
        return []
    start = min(op.started for op in ops)
    buckets: dict[int, list[Op]] = defaultdict(list)
    for op in ops:
        buckets[int((op.started - start) // width_s)].append(op)
    series = []
    for index in sorted(buckets):
        items = buckets[index]
        good = [op.request_ms for op in items if op.ok]
        series.append(
            {
                "t_s": round(index * width_s, 1),
                "ops": len(items),
                "errors": sum(1 for op in items if not op.ok),
                "p95_ms": percentile(good, 95),
                "ops_per_s": round(len(good) / width_s, 2),
            }
        )
    return series
