"""Test files have the right signature and exact size; the numbers are computed correctly."""

from __future__ import annotations

import io
import zipfile

import pytest
from secureview_load import fixtures
from secureview_load.client import Op
from secureview_load.metrics import percentile, summarise, windows

SIGNATURES = {
    "pdf": b"%PDF-",
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff",
    "mp4": b"\x00\x00\x00\x18ftyp",
    "zip": b"PK\x03\x04",
    "exe": b"MZ",
}


@pytest.mark.parametrize("file_type", sorted(SIGNATURES))
@pytest.mark.parametrize("size", [4096, 1024 * 1024 + 7])
def test_every_type_has_its_signature_and_the_exact_size(file_type: str, size: int) -> None:
    data = fixtures.make(file_type, size)
    assert len(data) == size
    assert data.startswith(SIGNATURES[file_type])


def test_the_zip_is_a_real_archive() -> None:
    with zipfile.ZipFile(io.BytesIO(fixtures.make("zip", 200_000))) as archive:
        assert archive.testzip() is None and archive.namelist() == ["payload.bin"]


def test_sizes_parse_as_binary_units() -> None:
    assert fixtures.parse_size("1MiB") == fixtures.parse_size("1MB") == 1024 * 1024
    assert fixtures.parse_size("64KiB") == 65536
    assert fixtures.parse_size("500MiB") == 500 * 1024 * 1024
    assert fixtures.size_label(10 * 1024 * 1024) == "10MiB"
    with pytest.raises(ValueError):
        fixtures.parse_size("lots")


def test_percentiles_are_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert (
        percentile(values, 50) == 50
        and percentile(values, 95) == 95
        and percentile(values, 99) == 99
    )
    assert percentile([], 95) is None


def test_failed_operations_count_as_errors_and_stay_out_of_latency() -> None:
    ops = [Op("upload", 0.0, True, 201, request_ms=100.0, bytes=1024 * 1024) for _ in range(9)]
    ops.append(Op("upload", 0.0, False, 429, error="http_429", request_ms=1.0))
    ops.append(
        Op("download", 0.0, False, 200, error="sha256_mismatch", verified=False, request_ms=50.0)
    )

    result = summarise(ops, duration_s=10.0)

    upload = result["upload"]
    assert upload["count"] == 10 and upload["ok"] == 9 and upload["error_rate"] == 0.1
    assert upload["errors"] == {"http_429": 1}
    assert upload["request_ms"]["p50"] == 100.0  # the fast 429 does not flatter the latency
    assert upload["mib_per_s"] == 0.9 and upload["wire_mib_per_s_p50"] == 10.0
    assert result["download"]["verify_failed"] == 1
    assert result["_all"] == {"count": 11, "failed": 2, "error_rate": 0.1818, "duration_s": 10.0}


def test_windows_bucket_operations_by_start_time() -> None:
    ops = [Op("upload", float(t), True, request_ms=10.0 * (t + 1)) for t in range(10)]
    ops.append(Op("upload", 3.0, False, error="ReadTimeout"))

    series = windows(ops, width_s=5.0)

    assert [w["ops"] for w in series] == [6, 5]
    assert series[0]["errors"] == 1 and series[1]["p95_ms"] == 100.0
