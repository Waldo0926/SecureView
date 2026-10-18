from __future__ import annotations

import hashlib
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_KEY_PROTECTION_AAD_DOMAIN = b"FYP-KEY-PROTECTION\x00"
_PRIVATE_KEY_AAD_DOMAIN = b"FYP-PRIVATE-KEY-BUNDLE\x00"
_PRIVATE_KEY_HKDF_DOMAIN = b"FYP-PRIVATE-KEY-DERIVATION\x00"


class CryptoService:
    """Low-level cryptographic operations.

    This class should only handle crypto primitives. Business logic such as
    access control, file metadata, and audit logging should stay in other services.

    The server never generates, unwraps or re-wraps an account key: the client holds the
    passphrase, the AMK and the plaintext private key, and the API only stores what it is
    given. The server-side key generation that once lived here (the "format 2" experiment)
    was removed; what remains is validation of client-supplied public material and the
    public AAD and HKDF layouts, kept as the documented byte format.
    """

    @staticmethod
    def key_protection_aad(
        *,
        profile_id: UUID,
        format_version: int,
        aad_version: int,
    ) -> bytes:
        """Build the public, cross-client AAD for the password-wrapped account key."""
        return (
            _KEY_PROTECTION_AAD_DOMAIN
            + format_version.to_bytes(4, "big")
            + aad_version.to_bytes(4, "big")
            + profile_id.bytes
        )

    @staticmethod
    def private_key_bundle_aad(
        *,
        key_id: UUID,
        profile_id: UUID,
        bundle_id: UUID,
        public_key_fingerprint: str,
        format_version: int,
        aad_version: int,
    ) -> bytes:
        """Build AAD binding a private-key ciphertext to its public identities."""
        return (
            _PRIVATE_KEY_AAD_DOMAIN
            + format_version.to_bytes(4, "big")
            + aad_version.to_bytes(4, "big")
            + profile_id.bytes
            + key_id.bytes
            + bundle_id.bytes
            + bytes.fromhex(public_key_fingerprint)
        )

    @staticmethod
    def private_key_derivation_info(
        *,
        key_id: UUID,
        profile_id: UUID,
        bundle_id: UUID,
        format_version: int,
    ) -> bytes:
        """Build the public HKDF context used for a private-key bundle."""
        return (
            _PRIVATE_KEY_HKDF_DOMAIN
            + format_version.to_bytes(4, "big")
            + profile_id.bytes
            + key_id.bytes
            + bundle_id.bytes
        )

    def public_key_fingerprint(self, public_key_pem: str) -> str:
        public_key = self.load_rsa_public_key(public_key_pem)
        canonical_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(canonical_der).hexdigest()

    def load_rsa_public_key(
        self,
        public_key_pem: str,
        *,
        expected_key_size: int | None = None,
    ) -> rsa.RSAPublicKey:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
            raise ValueError("A supported RSA public key of at least 2048 bits is required")
        if public_key.public_numbers().e != 65537:
            raise ValueError("RSA public exponent 65537 is required")
        if expected_key_size is not None and public_key.key_size != expected_key_size:
            raise ValueError("RSA public key size does not match the declared key size")
        return public_key

    def validate_wrapped_file_key(
        self,
        wrapped_file_key: bytes,
        public_key_pem: str,
    ) -> None:
        public_key = self.load_rsa_public_key(public_key_pem)
        if len(wrapped_file_key) != public_key.key_size // 8:
            raise ValueError("Wrapped file key length does not match the recipient RSA key")

    def verify_rsa_pss_sha256_signature(
        self,
        *,
        public_key_pem: str,
        message: bytes,
        signature: bytes,
    ) -> None:
        public_key = self.load_rsa_public_key(public_key_pem)
        if len(signature) != public_key.key_size // 8:
            raise ValueError("RSA signature length does not match the authorizing key")
        try:
            public_key.verify(
                signature,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=hashes.SHA256.digest_size,
                ),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise ValueError("RSA-PSS authorization signature is invalid") from exc
