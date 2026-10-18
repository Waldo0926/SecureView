"""Test files of a given type and exact size.

The server only ever sees ciphertext, so the type cannot change how it behaves; what the
type matrix proves is that the whole client-to-server-to-client path is byte-exact for the
kinds of file people actually store. Each file therefore starts with its real signature
(`%PDF`, the PNG magic, `MZ` and so on) and has a valid enough structure to be recognised,
with random bytes filling it out to the requested size. Random content also defeats any
compression on the way, so the sizes moved are the sizes measured.
"""

from __future__ import annotations

import io
import os
import re
import struct
import zipfile
import zlib
from collections.abc import Callable

MIB = 1024 * 1024

MIME_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "mp4": "video/mp4",
    "zip": "application/zip",
    "exe": "application/vnd.microsoft.portable-executable",
    "bin": "application/octet-stream",
}


def parse_size(text: str) -> int:
    """'1MiB', '500MB' (taken as MiB), '64KiB' or a plain byte count."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMG]i?B?)?\s*", text, flags=re.I)
    if not match:
        raise ValueError(f"not a size: {text!r}")
    number, unit = float(match.group(1)), (match.group(2) or "").upper()
    factor = {"": 1, "K": 1024, "M": MIB, "G": 1024 * MIB}[unit[:1]]
    return int(number * factor)


def size_label(size: int) -> str:
    if size % MIB == 0:
        return f"{size // MIB}MiB"
    if size % 1024 == 0:
        return f"{size // 1024}KiB"
    return f"{size}B"


def _pad(head: bytes, tail: bytes, size: int) -> bytes:
    filler = size - len(head) - len(tail)
    if filler < 0:
        raise ValueError(f"{size} bytes is too small for this file type")
    return head + os.urandom(filler) + tail


def _pdf(size: int) -> bytes:
    head = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n2 0 obj\n<< /Length 0 >>\nstream\n"
    tail = b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    return _pad(head, tail, size)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png(size: int) -> bytes:
    head = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    idat = _png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    iend = _png_chunk(b"IEND", b"")
    # A private ancillary chunk ("raNd") carries the filler; decoders skip it.
    overhead = len(head) + len(idat) + len(iend) + 12
    filler = size - overhead
    if filler < 0:
        raise ValueError(f"{size} bytes is too small for a PNG")
    return head + _png_chunk(b"raNd", os.urandom(filler)) + idat + iend


def _jpg(size: int) -> bytes:
    head = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return _pad(head, b"\xff\xd9", size)


def _mp4(size: int) -> bytes:
    ftyp = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
    mdat_payload = size - len(ftyp) - 8
    if mdat_payload < 0:
        raise ValueError(f"{size} bytes is too small for an MP4")
    return ftyp + struct.pack(">I", mdat_payload + 8) + b"mdat" + os.urandom(mdat_payload)


def _zip(size: int) -> bytes:
    """A real archive with one stored member, trimmed to exactly `size` bytes."""
    name = "payload.bin"

    def build(member: int) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(name, os.urandom(member))
        return buffer.getvalue()

    overhead = len(build(0))
    data = build(max(size - overhead, 0))
    if len(data) != size:
        raise ValueError(f"{size} bytes is too small for a ZIP")
    return data


def _exe(size: int) -> bytes:
    return _pad(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00", b"", size)


def _bin(size: int) -> bytes:
    return os.urandom(size)


BUILDERS: dict[str, Callable[[int], bytes]] = {
    "pdf": _pdf,
    "png": _png,
    "jpg": _jpg,
    "mp4": _mp4,
    "zip": _zip,
    "exe": _exe,
    "bin": _bin,
}


def make(file_type: str, size: int) -> bytes:
    data = BUILDERS[file_type](size)
    assert len(data) == size, (file_type, size, len(data))
    return data
