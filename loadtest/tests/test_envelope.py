"""The load client must produce exactly the bytes a browser would, or the numbers mean nothing.

Pinned against `docs/crypto/test_vectors.json`, the known-answer vectors the browser
library's own tests use.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from secureview_load import envelope

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "docs" / "crypto" / "test_vectors.json").read_text()
)


@pytest.mark.parametrize("case", VECTORS["file_content_aad"], ids=lambda c: c["case"])
def test_the_aad_matches_the_browser_vectors(case: dict) -> None:
    aad = envelope.file_content_aad(
        file_id=UUID(case["file_id"]),
        algorithm=case["encryption_algorithm"],
        plaintext_size=case["plaintext_size"],
        filename=case["original_filename"],
        mime_type=case["mime_type"],
    )
    assert aad.hex() == case["aad_hex"]


#: The load tool implements AES-GCM and ChaCha20-Poly1305 only (see loadtest/README.md). The shared
#: vector file also has GCM-SIV and XChaCha20 envelopes, which this test used to seal as AES-GCM.
IMPLEMENTED_ENVELOPES = [
    case for case in VECTORS["file_envelope"] if case["encryption_algorithm"] in envelope.ALGORITHMS
]


def test_every_suite_the_tool_implements_has_a_vector() -> None:
    covered = {case["encryption_algorithm"] for case in IMPLEMENTED_ENVELOPES}
    assert covered >= {"AES-256-GCM", "ChaCha20-Poly1305"}


@pytest.mark.parametrize("case", IMPLEMENTED_ENVELOPES, ids=lambda c: c["case"])
def test_the_ciphertext_matches_the_browser_vectors(case: dict) -> None:
    aad = envelope.file_content_aad(
        file_id=UUID(case["file_id"]),
        algorithm=case["encryption_algorithm"],
        plaintext_size=case["plaintext_size"],
        filename=case["original_filename"],
        mime_type=case["mime_type"],
    )
    assert aad.hex() == case["aad_hex"]
    cipher = (ChaCha20Poly1305 if case["encryption_algorithm"] == "ChaCha20-Poly1305" else AESGCM)(
        bytes.fromhex(case["dek_hex"])
    )
    sealed = cipher.encrypt(
        bytes.fromhex(case["nonce_hex"]), bytes.fromhex(case["plaintext_hex"]), aad
    )
    assert sealed[:-16].hex() == case["ciphertext_hex"]
    assert sealed[-16:].hex() == case["auth_tag_hex"]


@pytest.fixture(scope="module")
def keys():
    owner = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    recovery = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return owner, recovery


def _as_served(sealed: envelope.SealedFile, wrapped_key: str) -> dict:
    """The shape `GET /files/{id}` returns, built from what the upload sent."""
    meta = sealed.metadata
    return {
        "file_id": meta["file_id"],
        "original_filename": meta["original_filename"],
        "plaintext_size": meta["plaintext_size"],
        "mime_type": meta["mime_type"],
        "crypto_envelope": {
            "encryption_algorithm": meta["encryption_algorithm"],
            "nonce": meta["nonce"],
            "auth_tag": meta["auth_tag"],
            "wrapped_file_key": wrapped_key,
        },
    }


@pytest.mark.parametrize("algorithm", sorted(envelope.ALGORITHMS))
def test_seal_then_open_round_trips_for_owner_and_recovery(keys, algorithm: str) -> None:
    owner, recovery = keys
    plaintext = b"quarterly numbers, confidential" * 100
    sealed = envelope.seal(
        plaintext,
        file_id=uuid4(),
        filename="Report Q3.PDF",
        mime_type="Application/PDF",
        algorithm=algorithm,
        owner_key_id=str(uuid4()),
        owner_public_key=owner.public_key(),
        recovery_key_id=str(uuid4()),
        recovery_public_key=recovery.public_key(),
    )
    assert len(sealed.ciphertext) == len(plaintext)  # detached tag: equal sizes, by design
    assert sealed.ciphertext != plaintext
    assert sealed.metadata["mime_type"] == "application/pdf"
    for private, field in ((owner, "wrapped_file_key"), (recovery, "recovery_wrapped_file_key")):
        served = _as_served(sealed, str(sealed.metadata[field]))
        assert envelope.open_file(sealed.ciphertext, file=served, private_key=private) == plaintext


def test_one_flipped_byte_or_a_renamed_file_fails_authentication(keys) -> None:
    owner, recovery = keys
    sealed = envelope.seal(
        b"x" * 1000,
        file_id=uuid4(),
        filename="a.bin",
        mime_type="application/octet-stream",
        algorithm="AES-256-GCM",
        owner_key_id=str(uuid4()),
        owner_public_key=owner.public_key(),
        recovery_key_id=str(uuid4()),
        recovery_public_key=recovery.public_key(),
    )
    served = _as_served(sealed, str(sealed.metadata["wrapped_file_key"]))
    tampered = bytearray(sealed.ciphertext)
    tampered[500] ^= 1
    with pytest.raises(InvalidTag):
        envelope.open_file(bytes(tampered), file=served, private_key=owner)
    with pytest.raises(InvalidTag):
        envelope.open_file(
            sealed.ciphertext, file={**served, "original_filename": "b.bin"}, private_key=owner
        )
