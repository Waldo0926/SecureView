"""Public-key envelope for backup artifacts: RSA-OAEP-SHA256 key wrap + AES-256-GCM.

The host that takes a backup holds only the backup **public** key, so a compromise of that
host, or of the off-server destination, yields ciphertext it cannot open. The matching
private key lives offline with the key custodian (see docs/BACKUP_AND_RECOVERY.md) and is
only brought to the machine performing a restore.

`age` or `gpg` would be the usual tools, but neither is installed on the staging host or
in CI, while `cryptography` is already a pinned backend dependency. `openssl enc` was
rejected because it offers no authenticated mode, so a flipped byte would decrypt silently.

File layout (all integers big-endian):

    magic               8 bytes   b"FYPBAK1\\n"
    key fingerprint    32 bytes   SHA-256 of the recipient public key (DER SubjectPublicKeyInfo)
    wrapped key length  2 bytes
    wrapped key         n bytes   RSA-OAEP(SHA-256) of a fresh 32-byte data key
    nonce              12 bytes
    ciphertext          ...       AES-256-GCM, streamed
    tag                16 bytes

The GCM associated data is the whole header plus a caller-supplied context string -- the
backup's manifest id and the artifact's role -- so an artifact moved into a different
backup set, or swapped for another role, fails authentication instead of restoring. Every
file gets its own random data key, so nonce reuse across files is impossible.
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"FYPBAK1\n"
MIN_RSA_BITS = 3072
_CHUNK = 1024 * 1024
_TAG_BYTES = 16
_NONCE_BYTES = 12
_OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


class EnvelopeError(Exception):
    """Raised for any envelope failure; the message never includes key material."""


def load_public_key(path: Path) -> rsa.RSAPublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, rsa.RSAPublicKey):
        raise EnvelopeError("backup public key must be an RSA key")
    if key.key_size < MIN_RSA_BITS:
        raise EnvelopeError(f"backup public key must be at least {MIN_RSA_BITS} bits")
    return key


def load_private_key(path: Path, passphrase: bytes | None) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=passphrase)
    except (TypeError, ValueError) as exc:
        # Deliberately generic: do not echo parser detail that could include key bytes.
        raise EnvelopeError(
            "could not load the backup private key (wrong passphrase or not a PEM key)"
        ) from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise EnvelopeError("backup private key must be an RSA key")
    return key


def public_key_fingerprint(key: rsa.RSAPublicKey) -> str:
    der = key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()


def encrypt_file(source: Path, destination: Path, key: rsa.RSAPublicKey, context: str) -> None:
    data_key = os.urandom(32)
    nonce = os.urandom(_NONCE_BYTES)
    wrapped = key.encrypt(data_key, _OAEP)
    header = (
        MAGIC
        + bytes.fromhex(public_key_fingerprint(key))
        + struct.pack(">H", len(wrapped))
        + wrapped
        + nonce
    )
    encryptor = Cipher(algorithms.AES(data_key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header + context.encode("utf-8"))
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out, source.open("rb") as src:
        out.write(header)
        while chunk := src.read(_CHUNK):
            out.write(encryptor.update(chunk))
        out.write(encryptor.finalize())
        out.write(encryptor.tag)


def _read_header(handle) -> tuple[bytes, bytes, bytes, bytes]:
    magic = handle.read(len(MAGIC))
    if magic != MAGIC:
        raise EnvelopeError("not a backup envelope (bad magic)")
    fingerprint = handle.read(32)
    (wrapped_length,) = struct.unpack(">H", handle.read(2))
    wrapped = handle.read(wrapped_length)
    nonce = handle.read(_NONCE_BYTES)
    if len(fingerprint) != 32 or len(wrapped) != wrapped_length or len(nonce) != _NONCE_BYTES:
        raise EnvelopeError("truncated backup envelope header")
    header = MAGIC + fingerprint + struct.pack(">H", wrapped_length) + wrapped + nonce
    return header, fingerprint, wrapped, nonce


def envelope_key_fingerprint(path: Path) -> str:
    with path.open("rb") as handle:
        _, fingerprint, _, _ = _read_header(handle)
    return fingerprint.hex()


def decrypt_file(source: Path, destination: Path, key: rsa.RSAPrivateKey, context: str) -> None:
    """Decrypt `source` to `destination`, leaving nothing behind unless the tag verifies."""
    expected_fingerprint = public_key_fingerprint(key.public_key())
    total = source.stat().st_size
    partial = destination.with_name(destination.name + ".partial")
    with source.open("rb") as src:
        header, fingerprint, wrapped, nonce = _read_header(src)
        if fingerprint.hex() != expected_fingerprint:
            raise EnvelopeError(
                "artifact was encrypted to a different backup key "
                f"(artifact {fingerprint.hex()[:16]}, key {expected_fingerprint[:16]})"
            )
        remaining = total - len(header) - _TAG_BYTES
        if remaining < 0:
            raise EnvelopeError("truncated backup envelope")
        try:
            data_key = key.decrypt(wrapped, _OAEP)
        except ValueError as exc:
            raise EnvelopeError("could not unwrap the artifact's data key") from exc
        decryptor = Cipher(algorithms.AES(data_key), modes.GCM(nonce)).decryptor()
        decryptor.authenticate_additional_data(header + context.encode("utf-8"))
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                while remaining > 0:
                    chunk = src.read(min(_CHUNK, remaining))
                    if not chunk:
                        raise EnvelopeError("truncated backup envelope")
                    remaining -= len(chunk)
                    out.write(decryptor.update(chunk))
                tag = src.read(_TAG_BYTES)
                try:
                    out.write(decryptor.finalize_with_tag(tag))
                except InvalidTag as exc:
                    raise EnvelopeError(
                        "authentication failed: the artifact was modified, or belongs to a "
                        "different backup set or role"
                    ) from exc
            partial.replace(destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
