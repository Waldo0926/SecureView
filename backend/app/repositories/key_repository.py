from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import UserStatus
from app.models.encrypted_private_key_bundle import EncryptedPrivateKeyBundle
from app.models.user import User
from app.models.user_key import UserKey
from app.models.user_key_protection_profile import UserKeyProtectionProfile


class KeyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_my_key_bundle(
        self,
        user_id: int,
    ) -> tuple[User, UserKey, UserKeyProtectionProfile, EncryptedPrivateKeyBundle] | None:
        row = self.db.execute(
            select(User, UserKey, UserKeyProtectionProfile, EncryptedPrivateKeyBundle)
            .join(UserKey, UserKey.user_id == User.id)
            .join(UserKeyProtectionProfile, UserKeyProtectionProfile.user_id == User.id)
            .join(EncryptedPrivateKeyBundle, EncryptedPrivateKeyBundle.user_key_id == UserKey.id)
            .where(
                User.id == user_id,
                User.status == UserStatus.ACTIVE,
                UserKey.status == "ACTIVE",
                UserKey.custody_mode == "CLIENT_WRAPPED",
            )
            .order_by(UserKey.created_at.desc(), UserKey.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else tuple(row)

    def get_owned_key_bundle(
        self,
        user_id: int,
        key_id: UUID,
    ) -> tuple[User, UserKey, UserKeyProtectionProfile, EncryptedPrivateKeyBundle] | None:
        """Return an owned historical bundle even after its public key is retired."""
        row = self.db.execute(
            select(User, UserKey, UserKeyProtectionProfile, EncryptedPrivateKeyBundle)
            .join(UserKey, UserKey.user_id == User.id)
            .join(UserKeyProtectionProfile, UserKeyProtectionProfile.user_id == User.id)
            .join(EncryptedPrivateKeyBundle, EncryptedPrivateKeyBundle.user_key_id == UserKey.id)
            .where(
                User.id == user_id,
                User.status == UserStatus.ACTIVE,
                UserKey.key_uuid == str(key_id),
                UserKey.custody_mode == "CLIENT_WRAPPED",
            )
            .limit(1)
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else tuple(row)

    def get_active_public_key_by_user_uuid(
        self,
        user_uuid: UUID,
    ) -> tuple[User, UserKey] | None:
        row = self.db.execute(
            select(User, UserKey)
            .join(UserKey, UserKey.user_id == User.id)
            .where(
                User.user_uuid == str(user_uuid),
                User.status == UserStatus.ACTIVE,
                UserKey.status == "ACTIVE",
            )
            .order_by(UserKey.created_at.desc(), UserKey.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else tuple(row)

    def get_active_public_key_by_identifier(
        self,
        identifier: str,
    ) -> tuple[User, UserKey] | None:
        """The same row as `get_active_public_key_by_user_uuid`, addressed by identifier.

        Sharing needs this: a sender knows a username or email, but the share contract is
        expressed in ids. Matching is exact -- no prefix or substring search -- so this is
        not a user directory.
        """
        # Usernames cannot contain @, so email-shaped values can be resolved in their own
        # namespace without a username/email collision. The service canonicalises email.
        recipient_filter = (
            User.email == identifier if "@" in identifier else User.username == identifier
        )
        row = self.db.execute(
            select(User, UserKey)
            .join(UserKey, UserKey.user_id == User.id)
            .where(
                recipient_filter,
                User.status == UserStatus.ACTIVE,
                UserKey.status == "ACTIVE",
            )
            .order_by(UserKey.created_at.desc(), UserKey.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        ).one_or_none()
        return None if row is None else tuple(row)

    def lock_protection_profile(self, user_id: int) -> UserKeyProtectionProfile | None:
        return self.db.scalar(
            select(UserKeyProtectionProfile)
            .where(UserKeyProtectionProfile.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_current_client_key(self, user_id: int) -> UserKey | None:
        """Lock the newest active client key, which alone may authorize its successor."""
        return self.db.scalar(
            select(UserKey)
            .where(
                UserKey.user_id == user_id,
                UserKey.status == "ACTIVE",
                UserKey.custody_mode == "CLIENT_WRAPPED",
            )
            .order_by(UserKey.created_at.desc(), UserKey.id.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )

    def lock_private_key_bundles(self, user_id: int) -> list[EncryptedPrivateKeyBundle]:
        """Lock every private-key bundle the account owns, whatever its key's status.

        A passphrase reset replaces the one AMK every bundle is derived from, so the caller
        must see all of them -- a revoked key's bundle still opens files wrapped to it.
        """
        return list(
            self.db.scalars(
                select(EncryptedPrivateKeyBundle)
                .where(EncryptedPrivateKeyBundle.user_id == user_id)
                .order_by(EncryptedPrivateKeyBundle.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def add_user_key(self, key: UserKey) -> None:
        self.db.add(key)

    def add_private_key_bundle(self, bundle: EncryptedPrivateKeyBundle) -> None:
        self.db.add(bundle)

    def flush(self) -> None:
        self.db.flush()
