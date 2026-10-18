"""The client half of the file envelope, mirroring `frontend/src/crypto/file_envelope.ts`.

The server never sees a file key, so the load generator has to do what the browser does:
pick a random DEK, encrypt with AES-GCM or ChaCha20-Poly1305 under the AAD-3 binding, keep
the tag detached, and wrap the DEK with RSA-OAEP-SHA256 to the owner and to the recovery key.
`tests/test_envelope.py` pins the AAD against the backend's own test vector builder.
"""

from __future__ import annotations

import base64
import hashlib
import os
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

AAD_LABEL = b"FYP-FILE-CONTENT"
AAD_VERSION = 1
ENVELOPE_VERSION = 1
NONCE_BYTES = 12
TAG_BYTES = 16
ALGORITHMS = {
    "AES-128-GCM": 16,
    "AES-192-GCM": 24,
    "AES-256-GCM": 32,
    "ChaCha20-Poly1305": 32,
}
_OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def _frame(raw: bytes) -> bytes:
    return len(raw).to_bytes(4, "big") + raw


def file_content_aad(
    *, file_id: UUID, algorithm: str, plaintext_size: int, filename: str, mime_type: str
) -> bytes:
    """AAD-3: binds the ciphertext to the file's id, algorithm, size, name and type."""
    return b"".join(
        (
            AAD_LABEL,
            bytes([0]),
            bytes([AAD_VERSION]),
            file_id.bytes,
            ENVELOPE_VERSION.to_bytes(4, "big"),
            _frame(algorithm.encode("ascii")),
            plaintext_size.to_bytes(8, "big"),
            _frame(unicodedata.normalize("NFC", filename).encode("utf-8")),
            _frame(mime_type.lower().encode("ascii")),
        )
    )


def _cipher(algorithm: str, key: bytes) -> AESGCM | ChaCha20Poly1305:
    if algorithm == "ChaCha20-Poly1305":
        return ChaCha20Poly1305(key)
    return AESGCM(key)


def load_public_key(pem: str) -> rsa.RSAPublicKey:
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    assert isinstance(key, rsa.RSAPublicKey)
    return key


def load_private_key(pem: str) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


def wrap(public_key: rsa.RSAPublicKey, dek: bytes) -> bytes:
    return public_key.encrypt(dek, _OAEP)


def unwrap(private_key: rsa.RSAPrivateKey, wrapped: bytes) -> bytes:
    return private_key.decrypt(wrapped, _OAEP)


@dataclass(frozen=True, slots=True)
class SealedFile:
    """What an upload sends: the ciphertext, and the metadata envelope as the API wants it."""

    file_id: UUID
    ciphertext: bytes
    metadata: dict[str, object]


def seal(
    plaintext: bytes,
    *,
    file_id: UUID,
    filename: str,
    mime_type: str,
    algorithm: str,
    owner_key_id: str,
    owner_public_key: rsa.RSAPublicKey,
    recovery_key_id: str,
    recovery_public_key: rsa.RSAPublicKey,
) -> SealedFile:
    dek = os.urandom(ALGORITHMS[algorithm])
    nonce = os.urandom(NONCE_BYTES)
    aad = file_content_aad(
        file_id=file_id,
        algorithm=algorithm,
        plaintext_size=len(plaintext),
        filename=filename,
        mime_type=mime_type,
    )
    sealed = _cipher(algorithm, dek).encrypt(nonce, plaintext, aad)
    ciphertext, tag = sealed[:-TAG_BYTES], sealed[-TAG_BYTES:]
    metadata: dict[str, object] = {
        "file_id": str(file_id),
        "original_filename": filename,
        "plaintext_size": len(plaintext),
        "mime_type": mime_type.lower(),
        "encryption_algorithm": algorithm,
        "nonce": b64(nonce),
        "auth_tag": b64(tag),
        "owner_key_id": owner_key_id,
        "wrapped_file_key": b64(wrap(owner_public_key, dek)),
        "recovery_key_id": recovery_key_id,
        "recovery_wrapped_file_key": b64(wrap(recovery_public_key, dek)),
    }
    return SealedFile(file_id=file_id, ciphertext=ciphertext, metadata=metadata)


def open_file(ciphertext: bytes, *, file: dict, private_key: rsa.RSAPrivateKey) -> bytes:
    """Decrypt a download with the caller's key, from the metadata `GET /files/{id}` returns.

    Raises `cryptography.exceptions.InvalidTag` if a single byte, or any bound field, changed.
    """
    envelope = file["crypto_envelope"]
    algorithm = envelope["encryption_algorithm"]
    dek = unwrap(private_key, unb64(envelope["wrapped_file_key"]))
    aad = file_content_aad(
        file_id=UUID(file["file_id"]),
        algorithm=algorithm,
        plaintext_size=int(file["plaintext_size"]),
        filename=file["original_filename"],
        mime_type=file["mime_type"] or "application/octet-stream",
    )
    return _cipher(algorithm, dek).decrypt(
        unb64(envelope["nonce"]), ciphertext + unb64(envelope["auth_tag"]), aad
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
