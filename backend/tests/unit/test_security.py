import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from pwdlib.hashers.bcrypt import BcryptHasher

import app.core.security as security_module
from app.core.security import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_CHARACTER_CLASSES,
    PASSWORD_MIN_LENGTH,
    PasswordManager,
    PasswordOperationCapacityError,
    generate_session_token,
    hash_password,
    hash_session_token,
    normalize_password,
    password_character_classes,
    password_policy_error,
    verify_and_update_password,
    verify_password,
)


def test_argon2_password_hash_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", encoded) is True
    assert verify_password("wrong password", encoded) is False

    valid, replacement = verify_and_update_password(
        "correct horse battery staple",
        encoded,
    )
    assert valid is True
    assert replacement is None


def test_argon2id_raw_key_derivation_is_deterministic_and_normalizes_passwords() -> None:
    manager = PasswordManager()
    parameters = {
        "salt": b"s" * 16,
        "memory_cost_kib": 8,
        "iterations": 1,
        "parallelism": 1,
    }

    decomposed = "Cafe\u0301 encryption password"
    composed = "Caf\u00e9 encryption password"
    first = manager.derive_argon2id_key(decomposed, **parameters)
    second = manager.derive_argon2id_key(composed, **parameters)
    different = manager.derive_argon2id_key("different encryption password", **parameters)

    assert len(first) == 32
    assert first == second
    assert different != first


def test_legacy_bcrypt_password_is_verified_and_upgraded_to_argon2id() -> None:
    password = "A legacy but sufficiently long password!"
    legacy_hash = BcryptHasher().hash(normalize_password(password))

    valid, replacement = verify_and_update_password(password, legacy_hash)

    assert valid is True
    assert replacement is not None
    assert replacement.startswith("$argon2id$")
    assert verify_password(password, replacement) is True


def test_legacy_bcrypt_password_longer_than_72_bytes_can_still_be_migrated() -> None:
    password = "long legacy password " + "x" * 80
    legacy_bytes = normalize_password(password).encode("utf-8")[:72]
    legacy_hash = BcryptHasher().hash(legacy_bytes)

    valid, replacement = verify_and_update_password(password, legacy_hash)

    assert valid is True
    assert replacement is not None
    assert replacement.startswith("$argon2id$")
    assert verify_password(password, replacement) is True


def test_legacy_bcrypt_decomposed_unicode_is_accepted_once_and_normalized() -> None:
    decomposed = "Cafe\u0301 legacy password with enough length!"
    composed = normalize_password(decomposed)
    legacy_hash = BcryptHasher().hash(decomposed)

    valid, replacement = verify_and_update_password(decomposed, legacy_hash)

    assert valid is True
    assert replacement is not None
    assert replacement.startswith("$argon2id$")
    assert verify_password(composed, replacement) is True


def test_wrong_legacy_bcrypt_password_is_not_upgraded() -> None:
    legacy_hash = BcryptHasher().hash("A legacy but sufficiently long password!")

    valid, replacement = verify_and_update_password("wrong password", legacy_hash)

    assert valid is False
    assert replacement is None


@pytest.mark.parametrize(
    "stored_hash",
    [
        "not-a-password-hash",
        "$2b$12$malformed",
        "$argon2id$malformed",
    ],
)
def test_unknown_or_malformed_password_hash_is_an_invalid_credential(
    stored_hash: str,
) -> None:
    assert verify_password("A sufficiently long password!", stored_hash) is False
    assert verify_and_update_password(
        "A sufficiently long password!",
        stored_hash,
    ) == (False, None)


def test_structurally_valid_bcrypt_hash_with_invalid_cost_is_rejected() -> None:
    valid_hash = BcryptHasher().hash("A sufficiently long password!")
    invalid_cost_hash = f"{valid_hash[:4]}99{valid_hash[6:]}"

    assert verify_password("A sufficiently long password!", invalid_cost_hash) is False
    assert verify_and_update_password(
        "A sufficiently long password!",
        invalid_cost_hash,
    ) == (False, None)


def test_login_verification_treats_unknown_stored_hash_as_invalid() -> None:
    manager = PasswordManager()

    assert manager.verify_or_dummy(
        "A sufficiently long password!",
        "not-a-password-hash",
    ) == (False, None)


def test_password_hash_concurrency_is_explicit_and_must_be_positive() -> None:
    manager = PasswordManager(max_concurrent_operations=3)

    assert manager.max_concurrent_operations == 3
    with pytest.raises(ValueError, match="at least one"):
        PasswordManager(max_concurrent_operations=0)


class _BlockingPasswordHash:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def hash(self, password: str) -> str:
        if password.startswith("dummy password"):
            return "dummy-hash"
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test password operation was not released")
        return f"hash::{password}"


class _ExplodingPasswordHash:
    def hash(self, password: str) -> str:
        if password.startswith("dummy password"):
            return "dummy-hash"
        raise RuntimeError("hasher failed")


def test_password_capacity_fails_fast_instead_of_waiting_for_a_worker_thread() -> None:
    hasher = _BlockingPasswordHash()
    manager = PasswordManager(  # type: ignore[arg-type]
        hasher,
        max_concurrent_operations=1,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        active_operation = executor.submit(manager.hash, "First long password value!")
        assert hasher.started.wait(timeout=1)

        with pytest.raises(PasswordOperationCapacityError):
            manager.hash("Second long password value!")

        hasher.release.set()
        assert active_operation.result(timeout=1) == "hash::First long password value!"


def test_argon2id_raw_derivation_uses_the_shared_password_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()

    def blocking_raw_derivation(**parameters: object) -> bytes:
        started.set()
        if not release.wait(timeout=2):
            raise TimeoutError("test key derivation was not released")
        return b"k" * int(parameters["hash_len"])

    monkeypatch.setattr(security_module, "hash_secret_raw", blocking_raw_derivation)
    manager = PasswordManager(  # type: ignore[arg-type]
        _BlockingPasswordHash(),
        max_concurrent_operations=1,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        active_operation = executor.submit(
            manager.derive_argon2id_key,
            "First long password value!",
            salt=b"s" * 16,
            memory_cost_kib=8,
            iterations=1,
            parallelism=1,
        )
        assert started.wait(timeout=1)

        with pytest.raises(PasswordOperationCapacityError):
            manager.hash("Second long password value!")

        release.set()
        assert active_operation.result(timeout=1) == b"k" * 32


def test_password_hasher_exception_releases_capacity_slot() -> None:
    manager = PasswordManager(  # type: ignore[arg-type]
        _ExplodingPasswordHash(),
        max_concurrent_operations=1,
    )

    for _ in range(2):
        with pytest.raises(RuntimeError, match="hasher failed"):
            manager.hash("A sufficiently long password!")


def test_passwords_are_normalized_to_nfc_before_hashing() -> None:
    decomposed = "Cafe\u0301 has a long passphrase"
    composed = "Caf\u00e9 has a long passphrase"

    encoded = hash_password(decomposed)

    assert normalize_password(decomposed) == composed
    assert verify_password(composed, encoded) is True


def test_session_token_contains_configured_entropy() -> None:
    token = generate_session_token()
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))

    assert len(decoded) == 32
    assert generate_session_token() != token


def test_session_token_rejects_less_than_128_bits_of_entropy() -> None:
    with pytest.raises(ValueError, match="at least 128 bits"):
        generate_session_token(15)


def test_session_token_hash_is_stable_sha256_and_hides_raw_token() -> None:
    token = "opaque-session-token"
    digest = hash_session_token(token)

    assert digest == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert len(digest) == 64
    assert token not in digest


@pytest.mark.parametrize(
    "password",
    [
        "passwordpassword",
        "PASSWORDPASSWORD",
        "correct horse battery staple",
    ],
)
def test_password_policy_blocks_common_passwords(password: str) -> None:
    assert password_policy_error(password) == (
        "Choose a password that is not common or based on your account details"
    )


def test_password_policy_blocks_account_context_case_insensitively() -> None:
    assert (
        password_policy_error(
            "LongUsername1234",
            context_values=("longusername1234", "owner@example.com"),
        )
        == "Choose a password that is not common or based on your account details"
    )


def test_password_policy_blocks_account_details_used_as_a_fragment() -> None:
    """A short minimum only holds if the password cannot be built around the username."""
    assert (
        password_policy_error("Alice2024!", context_values=("alice", "alice@example.com"))
        == "Choose a password that is not common or based on your account details"
    )
    assert (
        password_policy_error("x9-owner-Qz", context_values=("someone", "owner@example.com"))
        == "Choose a password that is not common or based on your account details"
    )


def test_password_policy_ignores_account_fragments_too_short_to_be_meaningful() -> None:
    """The "a" of "a@example.com" appears in most honest passwords and must not block."""
    assert password_policy_error("Th1s-is-fine", context_values=("a@example.com",)) is None


def test_password_policy_enforces_length_boundaries() -> None:
    assert password_policy_error("Aa1" + "b" * (PASSWORD_MIN_LENGTH - 4)) == (
        f"Password must contain at least {PASSWORD_MIN_LENGTH} characters"
    )
    assert password_policy_error("Aa1" + "b" * (PASSWORD_MAX_LENGTH - 2)) == (
        f"Password must contain at most {PASSWORD_MAX_LENGTH} characters"
    )
    assert password_policy_error("A sufficiently long! passphrase") is None


@pytest.mark.parametrize(
    "password",
    [
        "Abcdefgh",  # upper + lower
        "abcd1234",  # lower + number
        "ABCD1234",  # upper + number
        "abcd!@#$",  # lower + symbol
        "1234!@#$",  # number + symbol
    ],
)
def test_password_policy_accepts_any_two_character_classes(password: str) -> None:
    assert password_policy_error(password) is None


@pytest.mark.parametrize(
    "password",
    [
        "abcdefghij",
        "ABCDEFGHIJ",
        "4835729164",
        "!@#$%^&*()",
        "密码密码密码密码",  # caseless letters all land in one class
    ],
)
def test_password_policy_rejects_a_single_character_class(password: str) -> None:
    assert password_policy_error(password) == (
        f"Password must combine at least {PASSWORD_MIN_CHARACTER_CLASSES} of these: "
        "uppercase letters, lowercase letters, numbers, symbols"
    )


def test_password_character_classes_buckets_unicode_by_category() -> None:
    assert password_character_classes("Ab1!") == {"uppercase", "lowercase", "number", "symbol"}
    assert password_character_classes("abc") == {"lowercase"}
    # A space is a symbol, which is what lets an all-lowercase passphrase qualify.
    assert password_character_classes("two words") == {"lowercase", "symbol"}
