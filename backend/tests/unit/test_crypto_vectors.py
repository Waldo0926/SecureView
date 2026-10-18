"""Known-answer tests over docs/crypto/test_vectors.json, from the server side.

The browser suite (frontend/src/crypto/primitives.test.ts) checks the TypeScript
implementations against these vectors. They were generated with python-cryptography, so until
now nothing on the Python side ever read the file back: a regenerated or hand-edited vector
would only be noticed when the frontend disagreed with it. This module closes that loop by
checking every primitive list against the library that produced it, plus the two derived
layouts the backend has an opinion about (the public-key fingerprint, which
``CryptoService`` computes, and the file-content AAD, which it must never compute but whose
layout ``docs/crypto/FILE_ENVELOPE.md`` fixes).

The file is read relative to this test rather than to the working directory, so it resolves
to ``../docs/crypto/test_vectors.json`` from ``backend/`` the way the frontend resolves it,
and the CI ``changes`` filter already treats ``docs/crypto/`` as test input.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESGCMSIV, ChaCha20Poly1305

from app.services.crypto_service import CryptoService

VECTORS_PATH = Path(__file__).resolve().parents[2].parent / "docs" / "crypto" / "test_vectors.json"
TAG_BYTES = 16

# Mirrors fileContentAad in frontend/src/crypto/file_envelope.ts and FILE_ENVELOPE.md section 4.
# Rebuilt here on purpose: the server never holds a DEK, so app/ has no AAD builder, and the
# point of the vector is to pin the layout a second implementation must reproduce.
AAD_LABEL = b"FYP-FILE-CONTENT"


def _load_vectors() -> dict[str, Any]:
    with VECTORS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


VECTORS = _load_vectors()


def _cases(group: str) -> list[Any]:
    cases = VECTORS[group]
    assert cases, f"{group} has no vectors"
    return [pytest.param(case, id=case["case"]) for case in cases]


def _frame(raw: bytes) -> bytes:
    return len(raw).to_bytes(4, "big") + raw


def _file_content_aad(case: dict[str, Any]) -> bytes:
    # The browser normalises before hashing: NFC for the filename, lower case for the media
    # type. The nfd-normalized and uppercase-mime cases exist to catch an implementation that
    # skips either step.
    filename = unicodedata.normalize("NFC", case["original_filename"])
    mime = case["mime_type"].lower()
    return b"".join(
        (
            AAD_LABEL,
            bytes([0]),
            bytes([case["aad_version"]]),
            UUID(case["file_id"]).bytes,
            int(case["envelope_version"]).to_bytes(4, "big"),
            _frame(case["encryption_algorithm"].encode("ascii")),
            int(case["plaintext_size"]).to_bytes(8, "big"),
            _frame(filename.encode("utf-8")),
            _frame(mime.encode("ascii")),
        )
    )


def _split(joined: bytes) -> tuple[bytes, bytes]:
    return joined[:-TAG_BYTES], joined[-TAG_BYTES:]


def _gcm_siv_available() -> bool:
    try:
        AESGCMSIV(bytes(32))
    except UnsupportedAlgorithm:
        return False
    return True


def test_vector_file_is_the_suite_the_frontend_reads() -> None:
    assert VECTORS["suite_version"] == 5
    assert "python-cryptography" in VECTORS["generated_with"]


@pytest.mark.parametrize("case", _cases("sha256"))
def test_sha256(case: dict[str, Any]) -> None:
    digest = hashlib.sha256(case["input_utf8"].encode("utf-8")).hexdigest()
    assert digest == case["digest_hex"]


@pytest.mark.parametrize("case", _cases("public_key_fingerprint"))
def test_public_key_fingerprint(case: dict[str, Any]) -> None:
    service = CryptoService()
    assert service.public_key_fingerprint(case["public_key_pem"]) == case["fingerprint_hex"]
    # The fingerprint is SHA-256 over the DER SubjectPublicKeyInfo and nothing else, so a
    # reflowed PEM must give the same answer.
    reflowed = case["public_key_pem"].strip() + "\n\n"
    assert service.public_key_fingerprint(reflowed) == case["fingerprint_hex"]


@pytest.mark.parametrize("case", _cases("file_content_aad"))
def test_file_content_aad(case: dict[str, Any]) -> None:
    aad = _file_content_aad(case)
    assert aad.hex() == case["aad_hex"]
    assert hashlib.sha256(aad).hexdigest() == case["aad_sha256"]


@pytest.mark.parametrize("case", _cases("aes_256_gcm_detached"))
def test_aes_256_gcm_detached(case: dict[str, Any]) -> None:
    key = bytes.fromhex(case["key_hex"])
    nonce = bytes.fromhex(case["nonce_hex"])
    aad = bytes.fromhex(case["aad_hex"])
    plaintext = bytes.fromhex(case["plaintext_hex"])
    assert len(key) == 32 and len(nonce) == 12

    ciphertext, tag = _split(AESGCM(key).encrypt(nonce, plaintext, aad))
    assert ciphertext.hex() == case["ciphertext_hex"]
    assert tag.hex() == case["auth_tag_hex"]
    assert len(ciphertext) == len(plaintext)

    joined = bytes.fromhex(case["ciphertext_hex"]) + bytes.fromhex(case["auth_tag_hex"])
    assert AESGCM(key).decrypt(nonce, joined, aad) == plaintext


@pytest.mark.parametrize("case", _cases("chacha20_poly1305_detached"))
def test_chacha20_poly1305_detached(case: dict[str, Any]) -> None:
    key = bytes.fromhex(case["key_hex"])
    nonce = bytes.fromhex(case["nonce_hex"])
    aad = bytes.fromhex(case["aad_hex"])
    plaintext = bytes.fromhex(case["plaintext_hex"])
    assert len(key) == 32 and len(nonce) == 12

    ciphertext, tag = _split(ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad))
    assert ciphertext.hex() == case["ciphertext_hex"]
    assert tag.hex() == case["auth_tag_hex"]

    joined = bytes.fromhex(case["ciphertext_hex"]) + bytes.fromhex(case["auth_tag_hex"])
    assert ChaCha20Poly1305(key).decrypt(nonce, joined, aad) == plaintext


# cryptography 50 ships AESGCMSIV, but only when the OpenSSL it was built against is 3.2 or
# newer; an older OpenSSL raises UnsupportedAlgorithm at construction. Skipped, not failed,
# in that case: the frontend suite still checks these vectors against @noble/ciphers.
@pytest.mark.skipif(not _gcm_siv_available(), reason="this OpenSSL has no AES-GCM-SIV")
@pytest.mark.parametrize("case", _cases("aes_256_gcm_siv_detached"))
def test_aes_256_gcm_siv_detached(case: dict[str, Any]) -> None:
    key = bytes.fromhex(case["key_hex"])
    nonce = bytes.fromhex(case["nonce_hex"])
    aad = bytes.fromhex(case["aad_hex"])
    plaintext = bytes.fromhex(case["plaintext_hex"])

    ciphertext, tag = _split(AESGCMSIV(key).encrypt(nonce, plaintext, aad))
    assert ciphertext.hex() == case["ciphertext_hex"]
    assert tag.hex() == case["auth_tag_hex"]

    joined = bytes.fromhex(case["ciphertext_hex"]) + bytes.fromhex(case["auth_tag_hex"])
    assert AESGCMSIV(key).decrypt(nonce, joined, aad) == plaintext


# python-cryptography has no XChaCha20-Poly1305 (the vectors came from libsodium via PyNaCl,
# which is not a backend dependency), so the HChaCha20 step below is written out and the AEAD
# itself is the library's ChaCha20-Poly1305.
@pytest.mark.parametrize("case", _cases("xchacha20_poly1305_detached"))
def test_xchacha20_poly1305(case: dict[str, Any]) -> None:
    key = bytes.fromhex(case["key_hex"])
    nonce = bytes.fromhex(case["nonce_hex"])
    aad = bytes.fromhex(case["aad_hex"])
    plaintext = bytes.fromhex(case["plaintext_hex"])
    ciphertext, tag = _split(_XChaCha20Poly1305(key).encrypt(nonce, plaintext, aad))
    assert ciphertext.hex() == case["ciphertext_hex"]
    assert tag.hex() == case["auth_tag_hex"]


@pytest.mark.parametrize("case", _cases("argon2id_kek"))
def test_argon2id_kek(case: dict[str, Any]) -> None:
    kek = hash_secret_raw(
        secret=case["passphrase_utf8"].encode("utf-8"),
        salt=bytes.fromhex(case["salt_hex"]),
        time_cost=case["iterations"],
        memory_cost=case["memory_kib"],
        parallelism=case["parallelism"],
        hash_len=32,
        type=Type.ID,
    )
    assert kek.hex() == case["kek_hex"]


def _rotl(value: int, shift: int) -> int:
    return ((value << shift) & 0xFFFFFFFF) | (value >> (32 - shift))


def _hchacha20(key: bytes, nonce16: bytes) -> bytes:
    """HChaCha20 from draft-irtf-cfrg-xchacha section 2.2, enough to build XChaCha20-Poly1305.

    python-cryptography has ChaCha20-Poly1305 but not the extended-nonce variant, so the subkey
    step is done here and the AEAD itself is still the library's.
    """
    state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
    state += [int.from_bytes(key[i : i + 4], "little") for i in range(0, 32, 4)]
    state += [int.from_bytes(nonce16[i : i + 4], "little") for i in range(0, 16, 4)]

    def quarter(a: int, b: int, c: int, d: int) -> None:
        state[a] = (state[a] + state[b]) & 0xFFFFFFFF
        state[d] = _rotl(state[d] ^ state[a], 16)
        state[c] = (state[c] + state[d]) & 0xFFFFFFFF
        state[b] = _rotl(state[b] ^ state[c], 12)
        state[a] = (state[a] + state[b]) & 0xFFFFFFFF
        state[d] = _rotl(state[d] ^ state[a], 8)
        state[c] = (state[c] + state[d]) & 0xFFFFFFFF
        state[b] = _rotl(state[b] ^ state[c], 7)

    for _ in range(10):
        quarter(0, 4, 8, 12)
        quarter(1, 5, 9, 13)
        quarter(2, 6, 10, 14)
        quarter(3, 7, 11, 15)
        quarter(0, 5, 10, 15)
        quarter(1, 6, 11, 12)
        quarter(2, 7, 8, 13)
        quarter(3, 4, 9, 14)
    words = state[0:4] + state[12:16]
    return b"".join(word.to_bytes(4, "little") for word in words)


class _XChaCha20Poly1305:
    """XChaCha20-Poly1305 as HChaCha20 subkey plus the library's ChaCha20-Poly1305."""

    def __init__(self, key: bytes) -> None:
        assert len(key) == 32
        self._key = key

    def encrypt(self, nonce: bytes, data: bytes, aad: bytes) -> bytes:
        assert len(nonce) == 24
        subkey = _hchacha20(self._key, nonce[:16])
        return ChaCha20Poly1305(subkey).encrypt(b"\x00" * 4 + nonce[16:], data, aad)


def test_hchacha20_matches_the_draft_vector() -> None:
    # draft-irtf-cfrg-xchacha-03 section 2.2.1, so the helper above is itself checked.
    key = bytes(range(32))
    nonce = bytes.fromhex("000000090000004a0000000031415927")
    expected = "82413b4227b27bfed30e42508a877d73a0f9e4d58a74a853c12ec41326d3ecdc"
    assert _hchacha20(key, nonce).hex() == expected


def _envelope_cipher(
    algorithm: str, dek: bytes
) -> AESGCM | ChaCha20Poly1305 | AESGCMSIV | _XChaCha20Poly1305 | None:
    if algorithm in {"AES-128-GCM", "AES-192-GCM", "AES-256-GCM"}:
        assert len(dek) == {"AES-128-GCM": 16, "AES-192-GCM": 24, "AES-256-GCM": 32}[algorithm]
        return AESGCM(dek)
    if algorithm == "ChaCha20-Poly1305":
        return ChaCha20Poly1305(dek)
    if algorithm == "XChaCha20-Poly1305":
        return _XChaCha20Poly1305(dek)
    if algorithm == "AES-256-GCM-SIV" and _gcm_siv_available():
        return AESGCMSIV(dek)
    return None


@pytest.mark.parametrize("case", _cases("file_envelope"))
def test_file_envelope(case: dict[str, Any]) -> None:
    """The whole envelope: the AAD layout, then the seal under the named suite."""
    assert _file_content_aad(case).hex() == case["aad_hex"]
    cipher = _envelope_cipher(case["encryption_algorithm"], bytes.fromhex(case["dek_hex"]))
    if cipher is None:
        # Only AES-256-GCM-SIV on an OpenSSL older than 3.2: the AAD above is still checked,
        # the seal is checked by the frontend suite. CI's OpenSSL has it, so nothing skips there.
        pytest.skip(f"python-cryptography cannot perform {case['encryption_algorithm']} here")
    nonce = bytes.fromhex(case["nonce_hex"])
    aad = bytes.fromhex(case["aad_hex"])
    plaintext = bytes.fromhex(case["plaintext_hex"])
    ciphertext, tag = _split(cipher.encrypt(nonce, plaintext, aad))
    assert ciphertext.hex() == case["ciphertext_hex"]
    assert tag.hex() == case["auth_tag_hex"]
