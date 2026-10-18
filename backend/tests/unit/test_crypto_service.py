from uuid import UUID

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services.crypto_service import CryptoService

KEY_ID = UUID("11111111-1111-4111-8111-111111111111")
PROFILE_ID = UUID("22222222-2222-4222-8222-222222222222")
BUNDLE_ID = UUID("33333333-3333-4333-8333-333333333333")


def _public_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def test_public_key_fingerprint_is_stable_sha256_identity() -> None:
    service = CryptoService()
    first_public_key = _public_key_pem()
    second_public_key = _public_key_pem()

    first_fingerprint = service.public_key_fingerprint(first_public_key)

    assert service.public_key_fingerprint(first_public_key) == first_fingerprint
    assert len(first_fingerprint) == 64
    assert first_fingerprint == first_fingerprint.lower()
    int(first_fingerprint, 16)
    assert service.public_key_fingerprint(second_public_key) != first_fingerprint


def test_load_rsa_public_key_rejects_the_wrong_size_or_exponent() -> None:
    service = CryptoService()
    public_key_pem = _public_key_pem()

    assert service.load_rsa_public_key(public_key_pem, expected_key_size=2048).key_size == 2048
    with pytest.raises(ValueError, match="does not match the declared key size"):
        service.load_rsa_public_key(public_key_pem, expected_key_size=3072)

    small_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    small_pem = (
        small_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    with pytest.raises(ValueError, match="at least 2048 bits"):
        service.load_rsa_public_key(small_pem)


def test_wrapped_file_key_must_be_exactly_one_rsa_block() -> None:
    service = CryptoService()
    public_key_pem = _public_key_pem()

    service.validate_wrapped_file_key(b"\x00" * 256, public_key_pem)
    with pytest.raises(ValueError, match="does not match the recipient RSA key"):
        service.validate_wrapped_file_key(b"\x00" * 255, public_key_pem)


def test_aad_and_hkdf_info_follow_the_documented_byte_layout() -> None:
    # The layout is written out in backend/README.md so another client can reproduce it:
    # domain string, one 0x00 byte, unsigned 32-bit big-endian integers, raw 16-byte UUIDs,
    # and the fingerprint as its raw 32 bytes.
    fingerprint = "ab" * 32

    protection_aad = CryptoService.key_protection_aad(
        profile_id=PROFILE_ID, format_version=1, aad_version=1
    )
    assert protection_aad == (
        b"FYP-KEY-PROTECTION\x00" + (1).to_bytes(4, "big") * 2 + PROFILE_ID.bytes
    )

    bundle_aad = CryptoService.private_key_bundle_aad(
        key_id=KEY_ID,
        profile_id=PROFILE_ID,
        bundle_id=BUNDLE_ID,
        public_key_fingerprint=fingerprint,
        format_version=1,
        aad_version=2,
    )
    assert bundle_aad == (
        b"FYP-PRIVATE-KEY-BUNDLE\x00"
        + (1).to_bytes(4, "big")
        + (2).to_bytes(4, "big")
        + PROFILE_ID.bytes
        + KEY_ID.bytes
        + BUNDLE_ID.bytes
        + bytes.fromhex(fingerprint)
    )

    info = CryptoService.private_key_derivation_info(
        key_id=KEY_ID, profile_id=PROFILE_ID, bundle_id=BUNDLE_ID, format_version=1
    )
    assert info == (
        b"FYP-PRIVATE-KEY-DERIVATION\x00"
        + (1).to_bytes(4, "big")
        + PROFILE_ID.bytes
        + KEY_ID.bytes
        + BUNDLE_ID.bytes
    )


def test_rsa_pss_signature_authorizes_exact_payload_only() -> None:
    service = CryptoService()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    payload = b"canonical key mutation digest"
    signature = private_key.sign(
        payload,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256.digest_size,
        ),
        hashes.SHA256(),
    )

    service.verify_rsa_pss_sha256_signature(
        public_key_pem=public_key_pem,
        message=payload,
        signature=signature,
    )
    with pytest.raises(ValueError, match="invalid"):
        service.verify_rsa_pss_sha256_signature(
            public_key_pem=public_key_pem,
            message=payload + b"!",
            signature=signature,
        )
    with pytest.raises(ValueError, match="length does not match"):
        service.verify_rsa_pss_sha256_signature(
            public_key_pem=public_key_pem,
            message=payload,
            signature=signature[:-1],
        )
