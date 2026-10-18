from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import to_api_utc, to_database_utc, to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.errors import (
    ConflictError,
    KeyBundleInvalidError,
    KeyBundleRevisionConflictError,
    KeyProtectionProfileNotFoundError,
    KeyProtectionResetUnavailableError,
    UserKeyNotFoundError,
)
from app.domain.keys import (
    ClientKeyAddition,
    EncryptedPrivateKeyBundleInput,
    KeyProtectionProfileInput,
    KeyProtectionReset,
)
from app.models.encrypted_private_key_bundle import EncryptedPrivateKeyBundle
from app.models.user import User
from app.models.user_key import UserKey
from app.models.user_key_protection_profile import UserKeyProtectionProfile
from app.repositories.key_repository import KeyRepository
from app.services.audit_log_service import AuditLogService
from app.services.crypto_service import CryptoService


class KeyService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        repository: KeyRepository | None = None,
        audit_service: AuditLogService | None = None,
        crypto_service: CryptoService | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repository = repository or KeyRepository(db)
        self.audit = audit_service or AuditLogService(db, clock=clock)
        self.crypto = crypto_service or CryptoService()
        self.clock = clock

    def get_my_bundle(
        self,
        *,
        actor: ActorContext,
    ) -> tuple[User, UserKey, UserKeyProtectionProfile, EncryptedPrivateKeyBundle]:
        result = self.repository.get_my_key_bundle(actor.user_id)
        if result is None:
            raise KeyProtectionProfileNotFoundError()
        return result

    def get_active_public_key(self, *, user_public_id: UUID) -> tuple[User, UserKey]:
        result = self.repository.get_active_public_key_by_user_uuid(user_public_id)
        if result is None:
            raise UserKeyNotFoundError()
        return result

    def get_active_public_key_by_identifier(self, *, identifier: str) -> tuple[User, UserKey]:
        """Resolve a share recipient by exact username or canonical email address.

        Raises the same `UserKeyNotFoundError` whether the account does not exist, is not
        ACTIVE, or has no active key, so the answer distinguishes "cannot be shared with"
        from "exists" no more than it has to.
        """
        normalized = identifier.strip()
        if "@" in normalized:
            normalized = normalized.lower()
        result = self.repository.get_active_public_key_by_identifier(normalized)
        if result is None:
            raise UserKeyNotFoundError()
        return result

    def get_owned_bundle(
        self,
        *,
        actor: ActorContext,
        key_id: UUID,
    ) -> tuple[User, UserKey, UserKeyProtectionProfile, EncryptedPrivateKeyBundle]:
        result = self.repository.get_owned_key_bundle(actor.user_id, key_id)
        if result is None:
            raise UserKeyNotFoundError()
        return result

    @staticmethod
    def _frame(value: bytes) -> bytes:
        return len(value).to_bytes(4, "big") + value

    def _addition_authorization_payload(
        self,
        *,
        actor: ActorContext,
        addition: ClientKeyAddition,
        public_key_fingerprint: str,
    ) -> bytes:
        """Build the 32-byte digest signed by the currently active private key.

        Length-prefixed binary fields avoid cross-language JSON canonicalization ambiguity.
        The one-time key and bundle UUIDs make a successful replay conflict harmlessly.
        """
        bundle = addition.private_key_bundle
        material = bytearray(b"FYP-CLIENT-KEY-ADDITION\x00\x01")
        material.extend(actor.user_public_id.bytes)
        material.extend(addition.authorizing_key_id.bytes)
        material.extend(addition.protection_profile_id.bytes)
        material.extend(addition.expected_profile_revision.to_bytes(8, "big"))
        material.extend(addition.key_id.bytes)
        material.extend(self._frame(addition.algorithm.encode("ascii")))
        material.extend(addition.key_size_bits.to_bytes(4, "big"))
        material.extend(bytes.fromhex(public_key_fingerprint))
        material.extend(bundle.bundle_id.bytes)
        material.extend(bundle.format_version.to_bytes(4, "big"))
        material.extend(self._frame(bundle.private_key_format.encode("ascii")))
        material.extend(self._frame(bundle.derivation_algorithm.encode("ascii")))
        material.extend(self._frame(bundle.derivation_salt))
        material.extend(self._frame(bundle.encryption_algorithm.encode("ascii")))
        material.extend(self._frame(bundle.encrypted_private_key))
        material.extend(self._frame(bundle.nonce))
        material.extend(self._frame(bundle.auth_tag))
        material.extend(bundle.aad_version.to_bytes(4, "big"))
        material.extend(bytes.fromhex(bundle.ciphertext_sha256))
        return hashlib.sha256(material).digest()

    def _prepare_addition(
        self,
        *,
        actor: ActorContext,
        addition: ClientKeyAddition,
    ) -> tuple[UserKeyProtectionProfile, UserKey, str, bytes]:
        profile = self.repository.lock_protection_profile(actor.user_id)
        if profile is None:
            raise KeyProtectionProfileNotFoundError()
        if (
            profile.profile_uuid != str(addition.protection_profile_id)
            or profile.revision != addition.expected_profile_revision
        ):
            raise KeyBundleRevisionConflictError()

        authorizing_key = self.repository.lock_current_client_key(actor.user_id)
        if authorizing_key is None or authorizing_key.key_uuid != str(addition.authorizing_key_id):
            raise KeyBundleRevisionConflictError(
                "The authorizing key is no longer the account's current key"
            )
        if addition.key_size_bits != self.settings.USER_RSA_KEY_SIZE:
            raise KeyBundleInvalidError(
                "The RSA key size does not match the configured account key size"
            )
        try:
            self.crypto.load_rsa_public_key(
                addition.public_key_pem,
                expected_key_size=addition.key_size_bits,
            )
            fingerprint = self.crypto.public_key_fingerprint(addition.public_key_pem)
        except (TypeError, ValueError) as exc:
            raise KeyBundleInvalidError() from exc
        payload = self._addition_authorization_payload(
            actor=actor,
            addition=addition,
            public_key_fingerprint=fingerprint,
        )
        return profile, authorizing_key, fingerprint, payload

    def get_addition_signing_payload(
        self,
        *,
        actor: ActorContext,
        addition: ClientKeyAddition,
    ) -> bytes:
        _profile, _authorizing_key, _fingerprint, payload = self._prepare_addition(
            actor=actor,
            addition=addition,
        )
        return payload

    def add_client_key(
        self,
        *,
        actor: ActorContext,
        addition: ClientKeyAddition,
        authorization_signature: bytes,
        context: RequestContext,
    ) -> tuple[UserKey, EncryptedPrivateKeyBundle, UserKeyProtectionProfile]:
        """Add a successor key while retaining old keys and their file wrappings."""
        try:
            profile, authorizing_key, fingerprint, payload = self._prepare_addition(
                actor=actor,
                addition=addition,
            )
            try:
                self.crypto.verify_rsa_pss_sha256_signature(
                    public_key_pem=authorizing_key.public_key_pem,
                    message=payload,
                    signature=authorization_signature,
                )
            except (TypeError, ValueError) as exc:
                raise KeyBundleInvalidError(
                    "The current-key authorization signature is invalid"
                ) from exc

            # `user_keys` is a plain DATETIME, which MySQL rounds into; the bundle is
            # DATETIME(6) and keeps what it is given. One instant, two precisions.
            now = to_second_resolution_utc(self.clock())
            bundle_now = to_database_utc(self.clock())
            key = UserKey(
                key_uuid=str(addition.key_id),
                user_id=actor.user_id,
                public_key_pem=addition.public_key_pem,
                algorithm=addition.algorithm,
                key_size_bits=addition.key_size_bits,
                custody_mode="CLIENT_WRAPPED",
                fingerprint=fingerprint,
                status="ACTIVE",
                created_at=now,
            )
            self.repository.add_user_key(key)
            self.repository.flush()

            source = addition.private_key_bundle
            bundle = EncryptedPrivateKeyBundle(
                bundle_uuid=str(source.bundle_id),
                user_id=actor.user_id,
                user_key_id=key.id,
                format_version=source.format_version,
                private_key_format=source.private_key_format,
                derivation_algorithm=source.derivation_algorithm,
                derivation_salt=source.derivation_salt,
                encryption_algorithm=source.encryption_algorithm,
                encrypted_private_key=source.encrypted_private_key,
                nonce=source.nonce,
                auth_tag=source.auth_tag,
                aad_version=source.aad_version,
                ciphertext_sha256=source.ciphertext_sha256,
                revision=1,
                created_at=bundle_now,
                updated_at=bundle_now,
            )
            self.repository.add_private_key_bundle(bundle)
            self.audit.append(
                action="USER_KEY_ADDED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=actor.user_id,
                resource_type="AUTH",
                resource_id=str(addition.key_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "authorizing_key_id": str(addition.authorizing_key_id),
                    "profile_revision": profile.revision,
                },
            )
            self.db.commit()
            return key, bundle, profile
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(
                "The key or encrypted private-key bundle is already registered"
            ) from exc
        except Exception:
            self.db.rollback()
            raise

    def _rewrap_authorization_payload(
        self,
        *,
        actor: ActorContext,
        authorizing_key_id: UUID,
        expected_revision: int,
        protection: KeyProtectionProfileInput,
    ) -> bytes:
        """Build the canonical digest authorized by the current client private key."""
        material = bytearray(b"FYP-KEY-PROTECTION-REWRAP\x00\x01")
        material.extend(actor.user_public_id.bytes)
        material.extend(authorizing_key_id.bytes)
        material.extend(protection.profile_id.bytes)
        material.extend(expected_revision.to_bytes(8, "big"))
        material.extend(protection.format_version.to_bytes(4, "big"))
        material.extend(self._frame(protection.kdf_algorithm.encode("ascii")))
        material.extend(protection.kdf_version.to_bytes(4, "big"))
        material.extend(self._frame(protection.kdf_salt))
        material.extend(protection.kdf_memory_kib.to_bytes(8, "big"))
        material.extend(protection.kdf_iterations.to_bytes(4, "big"))
        material.extend(protection.kdf_parallelism.to_bytes(4, "big"))
        material.extend(protection.derived_key_length.to_bytes(4, "big"))
        material.extend(self._frame(protection.amk_wrapping_algorithm.encode("ascii")))
        material.extend(self._frame(protection.wrapped_amk))
        material.extend(self._frame(protection.amk_nonce))
        material.extend(self._frame(protection.amk_auth_tag))
        material.extend(protection.aad_version.to_bytes(4, "big"))
        return hashlib.sha256(material).digest()

    def _prepare_rewrap(
        self,
        *,
        actor: ActorContext,
        authorizing_key_id: UUID,
        expected_revision: int,
        protection: KeyProtectionProfileInput,
    ) -> tuple[UserKeyProtectionProfile, UserKey, bytes]:
        profile = self.repository.lock_protection_profile(actor.user_id)
        if profile is None:
            raise KeyProtectionProfileNotFoundError()
        if profile.format_version != 1:
            raise KeyBundleRevisionConflictError(
                "Login-password-bound key protection must be changed through /auth/change-password"
            )
        if profile.revision != expected_revision or profile.profile_uuid != str(
            protection.profile_id
        ):
            raise KeyBundleRevisionConflictError()

        authorizing_key = self.repository.lock_current_client_key(actor.user_id)
        if authorizing_key is None or authorizing_key.key_uuid != str(authorizing_key_id):
            raise KeyBundleRevisionConflictError(
                "The authorizing key is no longer the account's current key"
            )
        payload = self._rewrap_authorization_payload(
            actor=actor,
            authorizing_key_id=authorizing_key_id,
            expected_revision=expected_revision,
            protection=protection,
        )
        return profile, authorizing_key, payload

    def get_rewrap_signing_payload(
        self,
        *,
        actor: ActorContext,
        authorizing_key_id: UUID,
        expected_revision: int,
        protection: KeyProtectionProfileInput,
    ) -> bytes:
        _profile, _authorizing_key, payload = self._prepare_rewrap(
            actor=actor,
            authorizing_key_id=authorizing_key_id,
            expected_revision=expected_revision,
            protection=protection,
        )
        return payload

    def rewrap_protection_profile(
        self,
        *,
        actor: ActorContext,
        authorizing_key_id: UUID,
        expected_revision: int,
        protection: KeyProtectionProfileInput,
        authorization_signature: bytes,
        context: RequestContext,
    ) -> UserKeyProtectionProfile:
        try:
            profile, authorizing_key, payload = self._prepare_rewrap(
                actor=actor,
                authorizing_key_id=authorizing_key_id,
                expected_revision=expected_revision,
                protection=protection,
            )
            try:
                self.crypto.verify_rsa_pss_sha256_signature(
                    public_key_pem=authorizing_key.public_key_pem,
                    message=payload,
                    signature=authorization_signature,
                )
            except (TypeError, ValueError) as exc:
                raise KeyBundleInvalidError(
                    "The current-key authorization signature is invalid"
                ) from exc

            profile.format_version = protection.format_version
            profile.kdf_algorithm = protection.kdf_algorithm
            profile.kdf_version = protection.kdf_version
            profile.kdf_salt = protection.kdf_salt
            profile.kdf_memory_kib = protection.kdf_memory_kib
            profile.kdf_iterations = protection.kdf_iterations
            profile.kdf_parallelism = protection.kdf_parallelism
            profile.derived_key_length = protection.derived_key_length
            profile.amk_wrapping_algorithm = protection.amk_wrapping_algorithm
            profile.wrapped_amk = protection.wrapped_amk
            profile.amk_nonce = protection.amk_nonce
            profile.amk_auth_tag = protection.amk_auth_tag
            profile.aad_version = protection.aad_version
            profile.revision += 1
            profile.updated_at = to_database_utc(self.clock())

            self.audit.append(
                action="KEY_PROTECTION_REWRAPPED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=actor.user_id,
                resource_type="AUTH",
                resource_id=str(actor.user_public_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "authorizing_key_id": str(authorizing_key_id),
                    "previous_revision": expected_revision,
                    "revision": profile.revision,
                },
            )
            self.db.commit()
            return profile
        except Exception:
            self.db.rollback()
            raise

    def _reset_authorization_payload(
        self,
        *,
        actor: ActorContext,
        reset: KeyProtectionReset,
    ) -> bytes:
        """Build the digest the account private key signs to authorize a passphrase reset.

        Covers every field of both envelopes and both expected revisions, under its own domain
        label so a rewrap or addition signature can never be replayed as a reset.
        """
        protection = reset.protection
        bundle = reset.private_key_bundle
        material = bytearray(b"FYP-KEY-PROTECTION-RESET\x00\x01")
        material.extend(actor.user_public_id.bytes)
        material.extend(reset.authorizing_key_id.bytes)
        material.extend(reset.expected_profile_revision.to_bytes(8, "big"))
        material.extend(reset.expected_bundle_revision.to_bytes(8, "big"))

        material.extend(protection.profile_id.bytes)
        material.extend(protection.format_version.to_bytes(4, "big"))
        material.extend(self._frame(protection.kdf_algorithm.encode("ascii")))
        material.extend(protection.kdf_version.to_bytes(4, "big"))
        material.extend(self._frame(protection.kdf_salt))
        material.extend(protection.kdf_memory_kib.to_bytes(8, "big"))
        material.extend(protection.kdf_iterations.to_bytes(4, "big"))
        material.extend(protection.kdf_parallelism.to_bytes(4, "big"))
        material.extend(protection.derived_key_length.to_bytes(4, "big"))
        material.extend(self._frame(protection.amk_wrapping_algorithm.encode("ascii")))
        material.extend(self._frame(protection.wrapped_amk))
        material.extend(self._frame(protection.amk_nonce))
        material.extend(self._frame(protection.amk_auth_tag))
        material.extend(protection.aad_version.to_bytes(4, "big"))

        material.extend(bundle.bundle_id.bytes)
        material.extend(bundle.format_version.to_bytes(4, "big"))
        material.extend(self._frame(bundle.private_key_format.encode("ascii")))
        material.extend(self._frame(bundle.derivation_algorithm.encode("ascii")))
        material.extend(self._frame(bundle.derivation_salt))
        material.extend(self._frame(bundle.encryption_algorithm.encode("ascii")))
        material.extend(self._frame(bundle.encrypted_private_key))
        material.extend(self._frame(bundle.nonce))
        material.extend(self._frame(bundle.auth_tag))
        material.extend(bundle.aad_version.to_bytes(4, "big"))
        material.extend(bytes.fromhex(bundle.ciphertext_sha256))
        return hashlib.sha256(material).digest()

    def _prepare_reset(
        self,
        *,
        actor: ActorContext,
        reset: KeyProtectionReset,
    ) -> tuple[UserKeyProtectionProfile, EncryptedPrivateKeyBundle, UserKey, bytes]:
        profile = self.repository.lock_protection_profile(actor.user_id)
        if profile is None:
            raise KeyProtectionProfileNotFoundError()
        if profile.format_version != 1:
            raise KeyBundleRevisionConflictError(
                "Login-password-bound key protection must be changed through /auth/change-password"
            )
        if (
            profile.profile_uuid != str(reset.protection.profile_id)
            or profile.revision != reset.expected_profile_revision
        ):
            raise KeyBundleRevisionConflictError()

        authorizing_key = self.repository.lock_current_client_key(actor.user_id)
        if authorizing_key is None or authorizing_key.key_uuid != str(reset.authorizing_key_id):
            raise KeyBundleRevisionConflictError(
                "The authorizing key is no longer the account's current key"
            )

        # One AMK seals every bundle. With a single private key in hand, only a single-bundle
        # account can be reset without stranding the rest.
        bundles = self.repository.lock_private_key_bundles(actor.user_id)
        if len(bundles) != 1:
            raise KeyProtectionResetUnavailableError()
        bundle = bundles[0]
        if (
            bundle.user_key_id != authorizing_key.id
            or bundle.bundle_uuid != str(reset.private_key_bundle.bundle_id)
            or bundle.revision != reset.expected_bundle_revision
        ):
            raise KeyBundleRevisionConflictError()

        payload = self._reset_authorization_payload(actor=actor, reset=reset)
        return profile, bundle, authorizing_key, payload

    def get_reset_signing_payload(
        self,
        *,
        actor: ActorContext,
        reset: KeyProtectionReset,
    ) -> bytes:
        _profile, _bundle, _key, payload = self._prepare_reset(actor=actor, reset=reset)
        return payload

    def reset_protection_with_private_key(
        self,
        *,
        actor: ActorContext,
        reset: KeyProtectionReset,
        authorization_signature: bytes,
        context: RequestContext,
    ) -> tuple[UserKeyProtectionProfile, EncryptedPrivateKeyBundle]:
        """Replace the AMK envelope and re-seal the private key under the new AMK.

        The signature is what makes this safe to expose. The server cannot check that the new
        envelopes open -- it never holds the passphrase, the AMK, or the private key -- so
        without proof of possession a stolen session could overwrite them with garbage and
        lock the owner out. With it, the only caller who can reset is one who already holds
        the private key, and that key alone decrypts every file the account can reach: the
        passphrase protects a stored copy of it, nothing more, so resetting grants no
        capability the caller did not already have.
        """
        try:
            profile, bundle, authorizing_key, payload = self._prepare_reset(
                actor=actor, reset=reset
            )
            try:
                self.crypto.verify_rsa_pss_sha256_signature(
                    public_key_pem=authorizing_key.public_key_pem,
                    message=payload,
                    signature=authorization_signature,
                )
            except (TypeError, ValueError) as exc:
                raise KeyBundleInvalidError(
                    "The private-key authorization signature is invalid"
                ) from exc

            now = to_database_utc(self.clock())
            self._apply_protection(profile, reset.protection)
            profile.revision += 1
            profile.updated_at = now
            self._apply_bundle(bundle, reset.private_key_bundle)
            bundle.revision += 1
            bundle.updated_at = now

            self.audit.append(
                action="KEY_PROTECTION_RESET_WITH_PRIVATE_KEY",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=actor.user_id,
                resource_type="AUTH",
                resource_id=str(actor.user_public_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "authorizing_key_id": str(reset.authorizing_key_id),
                    "previous_profile_revision": reset.expected_profile_revision,
                    "profile_revision": profile.revision,
                    "previous_bundle_revision": reset.expected_bundle_revision,
                    "bundle_revision": bundle.revision,
                },
            )
            self.db.commit()
            return profile, bundle
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def _apply_protection(
        profile: UserKeyProtectionProfile, protection: KeyProtectionProfileInput
    ) -> None:
        profile.format_version = protection.format_version
        profile.kdf_algorithm = protection.kdf_algorithm
        profile.kdf_version = protection.kdf_version
        profile.kdf_salt = protection.kdf_salt
        profile.kdf_memory_kib = protection.kdf_memory_kib
        profile.kdf_iterations = protection.kdf_iterations
        profile.kdf_parallelism = protection.kdf_parallelism
        profile.derived_key_length = protection.derived_key_length
        profile.amk_wrapping_algorithm = protection.amk_wrapping_algorithm
        profile.wrapped_amk = protection.wrapped_amk
        profile.amk_nonce = protection.amk_nonce
        profile.amk_auth_tag = protection.amk_auth_tag
        profile.aad_version = protection.aad_version

    @staticmethod
    def _apply_bundle(
        bundle: EncryptedPrivateKeyBundle, sealed: EncryptedPrivateKeyBundleInput
    ) -> None:
        bundle.format_version = sealed.format_version
        bundle.private_key_format = sealed.private_key_format
        bundle.derivation_algorithm = sealed.derivation_algorithm
        bundle.derivation_salt = sealed.derivation_salt
        bundle.encryption_algorithm = sealed.encryption_algorithm
        bundle.encrypted_private_key = sealed.encrypted_private_key
        bundle.nonce = sealed.nonce
        bundle.auth_tag = sealed.auth_tag
        bundle.aad_version = sealed.aad_version
        bundle.ciphertext_sha256 = sealed.ciphertext_sha256

    @staticmethod
    def api_time(value: datetime) -> datetime:
        return to_api_utc(value)
