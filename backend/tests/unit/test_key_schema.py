"""The client key contract carries material, not labels.

Twelve fields once rode along on every enrolment request with exactly one legal
value each. They are pinned server-side now. These tests hold both halves of
that: the labels still reach the domain layer unchanged — so stored rows and the
current-key authorization payload are byte-for-byte what they were — and the
wire refuses to accept them again, which is what stops the boilerplate from
creeping back one field at a time.
"""

from __future__ import annotations

import base64
import hashlib
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.keys import (
    ClientKeyAddition,
    ClientKeyRegistration,
    EncryptedPrivateKeyBundleInput,
    KeyProtectionProfileInput,
)
from app.schemas.key_schema import ClientKeyAdditionIn, ClientKeyRegistrationIn

KEY_ID = UUID("11111111-1111-4111-8111-111111111111")
PROFILE_ID = UUID("22222222-2222-4222-8222-222222222222")
BUNDLE_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTHORIZING_KEY_ID = UUID("44444444-4444-4444-8444-444444444444")
CIPHERTEXT = b"client-encrypted-pkcs8" * 20
PUBLIC_KEY_PEM = "-----BEGIN PUBLIC KEY-----\n" + "A" * 200 + "\n-----END PUBLIC KEY-----\n"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _protection_json() -> dict[str, object]:
    return {
        "profile_id": str(PROFILE_ID),
        "kdf_salt": _b64(b"s" * 16),
        "kdf_memory_kib": 65_536,
        "kdf_iterations": 3,
        "kdf_parallelism": 1,
        "wrapped_amk": _b64(b"w" * 32),
        "amk_nonce": _b64(b"n" * 12),
        "amk_auth_tag": _b64(b"t" * 16),
    }


def _bundle_json() -> dict[str, object]:
    return {
        "bundle_id": str(BUNDLE_ID),
        "derivation_salt": _b64(b"d" * 16),
        "encrypted_private_key": _b64(CIPHERTEXT),
        "nonce": _b64(b"i" * 12),
        "auth_tag": _b64(b"a" * 16),
        "ciphertext_sha256": hashlib.sha256(CIPHERTEXT).hexdigest(),
    }


def _expected_protection() -> KeyProtectionProfileInput:
    return KeyProtectionProfileInput(
        profile_id=PROFILE_ID,
        format_version=1,
        kdf_algorithm="ARGON2ID",
        kdf_version=19,
        kdf_salt=b"s" * 16,
        kdf_memory_kib=65_536,
        kdf_iterations=3,
        kdf_parallelism=1,
        derived_key_length=32,
        amk_wrapping_algorithm="AES-256-GCM",
        wrapped_amk=b"w" * 32,
        amk_nonce=b"n" * 12,
        amk_auth_tag=b"t" * 16,
        aad_version=1,
    )


def _expected_bundle() -> EncryptedPrivateKeyBundleInput:
    return EncryptedPrivateKeyBundleInput(
        bundle_id=BUNDLE_ID,
        format_version=1,
        private_key_format="PKCS8-DER",
        derivation_algorithm="HKDF-SHA256",
        derivation_salt=b"d" * 16,
        encryption_algorithm="AES-256-GCM",
        encrypted_private_key=CIPHERTEXT,
        nonce=b"i" * 12,
        auth_tag=b"a" * 16,
        aad_version=1,
        ciphertext_sha256=hashlib.sha256(CIPHERTEXT).hexdigest(),
    )


def test_registration_wire_form_rebuilds_the_fully_labelled_domain_object() -> None:
    registration = ClientKeyRegistrationIn(
        key_id=KEY_ID,
        public_key_pem=PUBLIC_KEY_PEM,
        key_size_bits=3072,
        protection=_protection_json(),
        private_key_bundle=_bundle_json(),
    )

    assert registration.to_domain() == ClientKeyRegistration(
        key_id=KEY_ID,
        public_key_pem=PUBLIC_KEY_PEM,
        algorithm="RSA-OAEP-SHA256",
        key_size_bits=3072,
        protection=_expected_protection(),
        private_key_bundle=_expected_bundle(),
    )


def test_key_addition_wire_form_rebuilds_the_fully_labelled_domain_object() -> None:
    """Equality here is what keeps the RSA-PSS authorization payload unchanged.

    `_addition_authorization_payload` reads every one of these fields, so an
    addition that reconstitutes identically also signs identically.
    """
    addition = ClientKeyAdditionIn(
        authorizing_key_id=AUTHORIZING_KEY_ID,
        protection_profile_id=PROFILE_ID,
        expected_profile_revision=3,
        key_id=KEY_ID,
        public_key_pem=PUBLIC_KEY_PEM,
        key_size_bits=3072,
        private_key_bundle=_bundle_json(),
    )

    assert addition.to_domain() == ClientKeyAddition(
        authorizing_key_id=AUTHORIZING_KEY_ID,
        protection_profile_id=PROFILE_ID,
        expected_profile_revision=3,
        key_id=KEY_ID,
        public_key_pem=PUBLIC_KEY_PEM,
        algorithm="RSA-OAEP-SHA256",
        key_size_bits=3072,
        private_key_bundle=_expected_bundle(),
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "format_version",
        "kdf_algorithm",
        "kdf_version",
        "derived_key_length",
        "amk_wrapping_algorithm",
        "aad_version",
    ],
)
def test_protection_profile_rejects_a_pinned_label(field_name: str) -> None:
    with pytest.raises(ValidationError) as error:
        ClientKeyRegistrationIn(
            key_id=KEY_ID,
            public_key_pem=PUBLIC_KEY_PEM,
            protection={**_protection_json(), field_name: "anything"},
            private_key_bundle=_bundle_json(),
        )
    assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    "field_name",
    [
        "format_version",
        "private_key_format",
        "derivation_algorithm",
        "encryption_algorithm",
        "aad_version",
    ],
)
def test_private_key_bundle_rejects_a_pinned_label(field_name: str) -> None:
    with pytest.raises(ValidationError) as error:
        ClientKeyRegistrationIn(
            key_id=KEY_ID,
            public_key_pem=PUBLIC_KEY_PEM,
            protection=_protection_json(),
            private_key_bundle={**_bundle_json(), field_name: "anything"},
        )
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_registration_rejects_a_declared_key_algorithm() -> None:
    with pytest.raises(ValidationError) as error:
        ClientKeyRegistrationIn(
            key_id=KEY_ID,
            public_key_pem=PUBLIC_KEY_PEM,
            algorithm="RSA-OAEP-SHA256",
            protection=_protection_json(),
            private_key_bundle=_bundle_json(),
        )
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_key_size_remains_a_declared_choice() -> None:
    """The one survivor: three legal values, cross-checked against the modulus."""
    registration = ClientKeyRegistrationIn(
        key_id=KEY_ID,
        public_key_pem=PUBLIC_KEY_PEM,
        key_size_bits=4096,
        protection=_protection_json(),
        private_key_bundle=_bundle_json(),
    )
    assert registration.to_domain().key_size_bits == 4096

    with pytest.raises(ValidationError):
        ClientKeyRegistrationIn(
            key_id=KEY_ID,
            public_key_pem=PUBLIC_KEY_PEM,
            key_size_bits=1024,
            protection=_protection_json(),
            private_key_bundle=_bundle_json(),
        )
