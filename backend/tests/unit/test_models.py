from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401 - importing registers every ORM model
from app.core.database import Base
from app.domain.enums import SessionStatus


def test_all_models_are_registered_and_mappable() -> None:
    configure_mappers()

    assert len(Base.metadata.tables) == 17
    folders = Base.metadata.tables["file_folders"]
    files = Base.metadata.tables["files"]
    assert folders.c.name.type.length == 80
    assert next(iter(files.c.folder_id.foreign_keys)).ondelete == "SET NULL"


def test_auth_models_expose_public_ids_and_rotation_history() -> None:
    users = Base.metadata.tables["users"]
    sessions = Base.metadata.tables["user_sessions"]
    refresh_tokens = Base.metadata.tables["session_refresh_tokens"]
    login_throttles = Base.metadata.tables["auth_login_throttles"]
    audit_logs = Base.metadata.tables["audit_logs"]
    audit_chain_heads = Base.metadata.tables["audit_chain_heads"]

    assert users.c.user_uuid.nullable is False
    assert users.c.password_changed_at.nullable is False
    assert sessions.c.session_uuid.nullable is False
    assert sessions.c.access_token_hash.nullable is False
    assert sessions.c.access_expires_at.nullable is False
    assert sessions.c.absolute_expires_at.nullable is False
    assert sessions.c.status.type.enum_class is SessionStatus
    session_foreign_key = next(iter(refresh_tokens.c.session_id.foreign_keys))
    assert session_foreign_key.target_fullname == "user_sessions.id"

    unique_names = {
        constraint.name
        for table in (users, sessions, refresh_tokens)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert {
        "uq_users_user_uuid",
        "uq_user_sessions_session_uuid",
        "uq_user_sessions_access_token_hash",
        "uq_session_refresh_tokens_token_hash",
        "uq_session_refresh_tokens_session_generation",
    } <= unique_names
    assert [column.name for column in login_throttles.primary_key] == ["scope", "key_hash"]
    assert audit_logs.c.metadata_json.nullable is False
    assert audit_logs.c.metadata_json.type.none_as_null is True
    audit_user_foreign_keys = {
        constraint.name: constraint for constraint in audit_logs.foreign_key_constraints
    }
    assert audit_user_foreign_keys["fk_audit_logs_actor_user"].ondelete == "RESTRICT"
    assert audit_user_foreign_keys["fk_audit_logs_actor_user"].onupdate == "RESTRICT"
    assert audit_user_foreign_keys["fk_audit_logs_target_user"].ondelete == "RESTRICT"
    assert audit_user_foreign_keys["fk_audit_logs_target_user"].onupdate == "RESTRICT"
    assert audit_logs.c.created_at.type.fsp == 6
    assert audit_chain_heads.c.id.autoincrement is False
    assert audit_chain_heads.c.updated_at.type.fsp == 6
    assert audit_chain_heads.c.schema_revision.server_default.arg == "0011_must_change_password"


def test_client_key_custody_models_and_wrapping_invariants() -> None:
    user_keys = Base.metadata.tables["user_keys"]
    recovery_keys = Base.metadata.tables["recovery_keys"]
    profiles = Base.metadata.tables["user_key_protection_profiles"]
    bundles = Base.metadata.tables["encrypted_private_key_bundles"]
    wrappings = Base.metadata.tables["file_key_wrappings"]

    assert user_keys.c.key_uuid.nullable is False
    assert user_keys.c.custody_mode.server_default.arg == "LEGACY_EXTERNAL"
    assert recovery_keys.c.key_uuid.nullable is False
    assert profiles.c.kdf_memory_kib.type.unsigned is True
    assert profiles.c.wrapped_amk.type.length == 64
    assert bundles.c.encrypted_private_key.nullable is False

    unique_names = {
        constraint.name
        for table in (user_keys, recovery_keys, profiles, bundles, wrappings)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert {
        "uq_user_keys_key_uuid",
        "uq_user_keys_id_user_id",
        "uq_recovery_keys_key_uuid",
        "uq_user_key_protection_profiles_uuid",
        "uq_encrypted_private_key_bundles_user_key",
        "uq_file_key_wrappings_file_user_key",
        "uq_file_key_wrappings_file_recovery_key",
    } <= unique_names

    check_names = {
        constraint.name
        for table in (profiles, bundles, wrappings)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_user_key_protection_profiles_kdf_bounds",
        "ck_user_key_protection_profiles_amk_envelope",
        "ck_encrypted_private_key_bundles_envelope",
        "ck_file_key_wrappings_recipient_shape",
    } <= check_names

    wrapping_foreign_keys = {
        constraint.name: constraint for constraint in wrappings.foreign_key_constraints
    }
    owner_fk = wrapping_foreign_keys["fk_file_key_wrappings_user_key_owner"]
    assert owner_fk.ondelete == "RESTRICT"
    assert owner_fk.onupdate == "RESTRICT"
    assert [element.target_fullname for element in owner_fk.elements] == [
        "user_keys.id",
        "user_keys.user_id",
    ]
