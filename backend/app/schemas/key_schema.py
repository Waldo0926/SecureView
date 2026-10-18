from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.domain.keys import (
    ClientKeyAddition,
    ClientKeyRegistration,
    EncryptedPrivateKeyBundleInput,
    KeyProtectionProfileInput,
    KeyProtectionReset,
)

Base64Value = Annotated[str, StringConstraints(min_length=4, max_length=12000)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def decode_base64(value: str, *, field_name: str, exact_length: int | None = None) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{field_name} must be canonical base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{field_name} must be canonical base64")
    if exact_length is not None and len(decoded) != exact_length:
        raise ValueError(f"{field_name} must decode to exactly {exact_length} bytes")
    return decoded


# The one shape a client key envelope is allowed to have.
#
# Every value below had exactly one legal setting on the wire, so a caller could
# only ever repeat them back or get a 422 for trying anything else. They are
# pinned here instead: requests carry the material, the server supplies the
# labels, and the stored rows and API responses stay just as self-describing as
# before — the columns and the `*Out` models still record which algorithm sealed
# each envelope, which is what makes adding a second one later possible.
CLIENT_KEY_ALGORITHM = "RSA-OAEP-SHA256"
PROTECTION_FORMAT_VERSION = 1
PROTECTION_AAD_VERSION = 1
KDF_ALGORITHM = "ARGON2ID"
KDF_VERSION = 19
DERIVED_KEY_LENGTH = 32
AMK_WRAPPING_ALGORITHM = "AES-256-GCM"
BUNDLE_FORMAT_VERSION = 1
BUNDLE_AAD_VERSION = 1
PRIVATE_KEY_FORMAT = "PKCS8-DER"
PRIVATE_KEY_DERIVATION_ALGORITHM = "HKDF-SHA256"
PRIVATE_KEY_ENCRYPTION_ALGORITHM = "AES-256-GCM"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyProtectionProfileIn(_StrictModel):
    """The passphrase-derived wrapping of the account master key.

    The KDF cost parameters stay on the wire because they are a per-account
    choice: they are what lets the cost be raised later without locking out an
    account enrolled under the old ones.
    """

    profile_id: UUID
    kdf_salt: Base64Value
    kdf_memory_kib: int = Field(ge=65_536, le=1_048_576)
    kdf_iterations: int = Field(ge=1, le=10)
    kdf_parallelism: int = Field(ge=1, le=16)
    wrapped_amk: Base64Value
    amk_nonce: Base64Value
    amk_auth_tag: Base64Value

    @model_validator(mode="after")
    def validate_binary_fields(self) -> KeyProtectionProfileIn:
        salt = decode_base64(self.kdf_salt, field_name="kdf_salt")
        if not 16 <= len(salt) <= 32:
            raise ValueError("kdf_salt must decode to between 16 and 32 bytes")
        decode_base64(self.wrapped_amk, field_name="wrapped_amk", exact_length=32)
        decode_base64(self.amk_nonce, field_name="amk_nonce", exact_length=12)
        decode_base64(self.amk_auth_tag, field_name="amk_auth_tag", exact_length=16)
        return self

    def to_domain(self) -> KeyProtectionProfileInput:
        return KeyProtectionProfileInput(
            profile_id=self.profile_id,
            format_version=PROTECTION_FORMAT_VERSION,
            kdf_algorithm=KDF_ALGORITHM,
            kdf_version=KDF_VERSION,
            kdf_salt=decode_base64(self.kdf_salt, field_name="kdf_salt"),
            kdf_memory_kib=self.kdf_memory_kib,
            kdf_iterations=self.kdf_iterations,
            kdf_parallelism=self.kdf_parallelism,
            derived_key_length=DERIVED_KEY_LENGTH,
            amk_wrapping_algorithm=AMK_WRAPPING_ALGORITHM,
            wrapped_amk=decode_base64(self.wrapped_amk, field_name="wrapped_amk"),
            amk_nonce=decode_base64(self.amk_nonce, field_name="amk_nonce"),
            amk_auth_tag=decode_base64(self.amk_auth_tag, field_name="amk_auth_tag"),
            aad_version=PROTECTION_AAD_VERSION,
        )


class EncryptedPrivateKeyBundleIn(_StrictModel):
    """The private key sealed under an AMK/HKDF-derived key.

    `ciphertext_sha256` stays on the wire despite the AES-GCM tag already
    covering the ciphertext: it is the compact commitment the current-key
    authorization signature carries, so dropping it would weaken what that
    signature actually attests to.
    """

    bundle_id: UUID
    derivation_salt: Base64Value
    encrypted_private_key: Base64Value
    nonce: Base64Value
    auth_tag: Base64Value
    ciphertext_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_binary_fields(self) -> EncryptedPrivateKeyBundleIn:
        salt = decode_base64(self.derivation_salt, field_name="derivation_salt")
        if not 16 <= len(salt) <= 32:
            raise ValueError("derivation_salt must decode to between 16 and 32 bytes")
        ciphertext = decode_base64(self.encrypted_private_key, field_name="encrypted_private_key")
        if not 256 <= len(ciphertext) <= 8192:
            raise ValueError("encrypted_private_key has an invalid decoded length")
        decode_base64(self.nonce, field_name="nonce", exact_length=12)
        decode_base64(self.auth_tag, field_name="auth_tag", exact_length=16)
        if not hashlib.sha256(ciphertext).hexdigest() == self.ciphertext_sha256:
            raise ValueError("ciphertext_sha256 does not match encrypted_private_key")
        return self

    def to_domain(self) -> EncryptedPrivateKeyBundleInput:
        return EncryptedPrivateKeyBundleInput(
            bundle_id=self.bundle_id,
            format_version=BUNDLE_FORMAT_VERSION,
            private_key_format=PRIVATE_KEY_FORMAT,
            derivation_algorithm=PRIVATE_KEY_DERIVATION_ALGORITHM,
            derivation_salt=decode_base64(self.derivation_salt, field_name="derivation_salt"),
            encryption_algorithm=PRIVATE_KEY_ENCRYPTION_ALGORITHM,
            encrypted_private_key=decode_base64(
                self.encrypted_private_key, field_name="encrypted_private_key"
            ),
            nonce=decode_base64(self.nonce, field_name="nonce"),
            auth_tag=decode_base64(self.auth_tag, field_name="auth_tag"),
            aad_version=BUNDLE_AAD_VERSION,
            ciphertext_sha256=self.ciphertext_sha256,
        )


class ClientKeyRegistrationIn(_StrictModel):
    """Account key material generated and sealed by the client.

    `key_size_bits` stays: it is the one declared value with more than a single
    legal setting, and the server cross-checks it against the modulus of the
    uploaded key rather than taking it on trust.
    """

    key_id: UUID
    public_key_pem: str = Field(min_length=200, max_length=8000)
    key_size_bits: Literal[2048, 3072, 4096] = 3072
    protection: KeyProtectionProfileIn
    private_key_bundle: EncryptedPrivateKeyBundleIn

    @field_validator("public_key_pem")
    @classmethod
    def reject_padded_public_key(cls, value: str) -> str:
        normalized = value.strip()
        if "PRIVATE KEY" in normalized:
            raise ValueError("public_key_pem must contain only a public key")
        return f"{normalized}\n"

    def to_domain(self) -> ClientKeyRegistration:
        return ClientKeyRegistration(
            key_id=self.key_id,
            public_key_pem=self.public_key_pem,
            algorithm=CLIENT_KEY_ALGORITHM,
            key_size_bits=self.key_size_bits,
            protection=self.protection.to_domain(),
            private_key_bundle=self.private_key_bundle.to_domain(),
        )


class ClientKeyAdditionIn(_StrictModel):
    """Unsigned key-addition fields covered by the current-key authorization signature."""

    authorizing_key_id: UUID
    protection_profile_id: UUID
    expected_profile_revision: int = Field(ge=1)
    key_id: UUID
    public_key_pem: str = Field(min_length=200, max_length=8000)
    key_size_bits: Literal[2048, 3072, 4096] = 3072
    private_key_bundle: EncryptedPrivateKeyBundleIn

    @field_validator("public_key_pem")
    @classmethod
    def require_public_key_only(cls, value: str) -> str:
        normalized = value.strip()
        if "PRIVATE KEY" in normalized:
            raise ValueError("public_key_pem must contain only a public key")
        return f"{normalized}\n"

    def to_domain(self) -> ClientKeyAddition:
        return ClientKeyAddition(
            authorizing_key_id=self.authorizing_key_id,
            protection_profile_id=self.protection_profile_id,
            expected_profile_revision=self.expected_profile_revision,
            key_id=self.key_id,
            public_key_pem=self.public_key_pem,
            algorithm=CLIENT_KEY_ALGORITHM,
            key_size_bits=self.key_size_bits,
            private_key_bundle=self.private_key_bundle.to_domain(),
        )


class AddClientKeyRequest(ClientKeyAdditionIn):
    authorization_algorithm: Literal["RSA-PSS-SHA256"] = "RSA-PSS-SHA256"
    authorization_signature: Base64Value = Field(repr=False)

    @field_validator("authorization_signature")
    @classmethod
    def validate_authorization_signature(cls, value: str) -> str:
        signature = decode_base64(value, field_name="authorization_signature")
        if len(signature) not in {256, 384, 512}:
            raise ValueError("authorization_signature must be an RSA signature")
        return value

    def signature_bytes(self) -> bytes:
        return decode_base64(
            self.authorization_signature,
            field_name="authorization_signature",
        )


class KeyAdditionSigningPayloadOut(_StrictModel):
    authorization_algorithm: Literal["RSA-PSS-SHA256"] = "RSA-PSS-SHA256"
    authorization_payload: str = Field(repr=False)


class AddClientKeyResponse(_StrictModel):
    key_id: UUID
    bundle_id: UUID
    protection_profile_id: UUID
    protection_revision: int = Field(ge=1)
    public_key_fingerprint: Sha256Hex
    created_at: datetime
    previous_keys_retained: Literal[True] = True


class KeyProtectionProfileOut(_StrictModel):
    profile_id: UUID
    format_version: int
    kdf_algorithm: str
    kdf_version: int
    kdf_salt: str
    kdf_memory_kib: int
    kdf_iterations: int
    kdf_parallelism: int
    derived_key_length: int
    amk_wrapping_algorithm: str
    wrapped_amk: str
    amk_nonce: str
    amk_auth_tag: str
    aad_version: int
    revision: int
    updated_at: datetime


class EncryptedPrivateKeyBundleOut(_StrictModel):
    bundle_id: UUID
    format_version: int
    private_key_format: str
    derivation_algorithm: str
    derivation_salt: str
    encryption_algorithm: str
    encrypted_private_key: str
    nonce: str
    auth_tag: str
    aad_version: int
    ciphertext_sha256: str
    revision: int
    updated_at: datetime


class PublicEncryptionKeyOut(_StrictModel):
    key_id: UUID
    user_id: UUID
    algorithm: str
    key_size_bits: int
    public_key_pem: str
    fingerprint: str
    created_at: datetime


class MyKeyBundleResponse(_StrictModel):
    key: PublicEncryptionKeyOut
    protection: KeyProtectionProfileOut
    private_key_bundle: EncryptedPrivateKeyBundleOut


class RewrapKeyProtectionIn(KeyProtectionProfileIn):
    authorizing_key_id: UUID
    expected_revision: int = Field(ge=1)


class RewrapKeyProtectionRequest(RewrapKeyProtectionIn):
    authorization_algorithm: Literal["RSA-PSS-SHA256"] = "RSA-PSS-SHA256"
    authorization_signature: Base64Value = Field(repr=False)

    @field_validator("authorization_signature")
    @classmethod
    def validate_authorization_signature(cls, value: str) -> str:
        signature = decode_base64(value, field_name="authorization_signature")
        if len(signature) not in {256, 384, 512}:
            raise ValueError("authorization_signature must be an RSA signature")
        return value

    def signature_bytes(self) -> bytes:
        return decode_base64(
            self.authorization_signature,
            field_name="authorization_signature",
        )


class RewrapKeyProtectionSigningPayloadOut(_StrictModel):
    authorization_algorithm: Literal["RSA-PSS-SHA256"] = "RSA-PSS-SHA256"
    authorization_payload: str = Field(repr=False)


class RewrapKeyProtectionResponse(_StrictModel):
    profile_id: UUID
    revision: int
    updated_at: datetime


class ResetKeyProtectionIn(_StrictModel):
    """Replace the AMK envelope and re-seal the private key, proven by that private key.

    Both envelopes travel together because neither is useful alone: a new AMK that the old
    bundle is not sealed under would lock the account out, and a re-sealed bundle under an
    AMK the profile does not wrap could never be opened.
    """

    authorizing_key_id: UUID
    expected_profile_revision: int = Field(ge=1)
    expected_bundle_revision: int = Field(ge=1)
    protection: KeyProtectionProfileIn
    private_key_bundle: EncryptedPrivateKeyBundleIn

    def to_domain(self) -> KeyProtectionReset:
        return KeyProtectionReset(
            authorizing_key_id=self.authorizing_key_id,
            expected_profile_revision=self.expected_profile_revision,
            expected_bundle_revision=self.expected_bundle_revision,
            protection=self.protection.to_domain(),
            private_key_bundle=self.private_key_bundle.to_domain(),
        )


class ResetKeyProtectionRequest(ResetKeyProtectionIn):
    authorization_algorithm: Literal["RSA-PSS-SHA256"] = "RSA-PSS-SHA256"
    authorization_signature: Base64Value = Field(repr=False)

    @field_validator("authorization_signature")
    @classmethod
    def validate_authorization_signature(cls, value: str) -> str:
        signature = decode_base64(value, field_name="authorization_signature")
        if len(signature) not in {256, 384, 512}:
            raise ValueError("authorization_signature must be an RSA signature")
        return value

    def signature_bytes(self) -> bytes:
        return decode_base64(
            self.authorization_signature,
            field_name="authorization_signature",
        )


class ResetKeyProtectionSigningPayloadOut(_StrictModel):
    authorization_algorithm: Literal["RSA-PSS-SHA256"] = "RSA-PSS-SHA256"
    authorization_payload: str = Field(repr=False)


class ResetKeyProtectionResponse(_StrictModel):
    profile_id: UUID
    profile_revision: int
    bundle_id: UUID
    bundle_revision: int
    updated_at: datetime


def encode_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def first_attr(value: Any, *names: str) -> Any:
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    raise AttributeError(f"None of {names!r} exist")
