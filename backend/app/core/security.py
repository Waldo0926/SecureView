from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore

from argon2.low_level import ARGON2_VERSION, Type, hash_secret_raw
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.bcrypt import BcryptHasher

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
# A shorter minimum only stays defensible if the password cannot be a single run of
# one character class, so composition carries the strength the extra length used to.
PASSWORD_MIN_CHARACTER_CLASSES = 2
# The shortest account detail worth matching as a substring. Below this, a fragment
# such as the "a" of "a@example.com" would appear in almost every honest password.
_MIN_CONTEXT_FRAGMENT_LENGTH = 3
SESSION_TOKEN_BYTES = 32
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")

# This local deny-list catches the highest-risk defaults and project-specific choices.
# Deployments can replace/extend it with a maintained breached-password corpus without
# changing password hashing or the application-service contract.
#
# Entries shorter than PASSWORD_MIN_LENGTH are unreachable, because the length check
# runs first. Keep the list at or above that bound when the minimum moves again.
_COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "123456789012345",
        "1234567890123456",
        "111111111111111",
        "1q2w3e4r",
        "1qaz2wsx",
        "abc12345",
        "admin123",
        "adminadmin",
        "adminadminadmin",
        "administrator123",
        "asdfghjkl",
        "changeme",
        "changemechangeme",
        "correct horse battery staple",
        "football",
        "iloveyou",
        "iloveyouiloveyou",
        "letmein123",
        "letmeinletmeinletmein",
        "master123",
        "monkey123",
        "passw0rd",
        "password",
        "password1",
        "password123",
        "password123456",
        "passwordpassword",
        "q1w2e3r4",
        "qazwsxedc",
        "qwerty123",
        "qwertyui",
        "qwertyqwertyqwerty",
        "secure123",
        "securefile",
        "securefileplatform",
        "sunshine",
        "trustno1",
        "welcome1",
        "welcome123",
        "welcome123456789",
        "zaq12wsx",
    }
)


class PasswordOperationCapacityError(RuntimeError):
    """The worker has no safe memory budget for another password operation."""


class _LegacyBcryptHasher(BcryptHasher):
    """Reproduce bcrypt's historical 72-byte input limit for existing hashes only."""

    def verify(self, password: str | bytes, hash: str | bytes) -> bool:
        password_bytes = password.encode("utf-8") if isinstance(password, str) else password
        return super().verify(password_bytes[:72], hash)


def _password_hash_with_legacy_support() -> PasswordHash:
    """Keep Argon2id current while accepting bcrypt hashes created by older releases."""
    recommended = PasswordHash.recommended()
    return PasswordHash((*recommended.hashers, _LegacyBcryptHasher()))


def normalize_password(password: str) -> str:
    """Apply the same Unicode normalization before every hash or comparison."""
    return unicodedata.normalize("NFC", password)


class PasswordManager:
    """Argon2id password capability with bcrypt migration and a dummy hash."""

    def __init__(
        self,
        hasher: PasswordHash | None = None,
        *,
        max_concurrent_operations: int = 2,
    ) -> None:
        if max_concurrent_operations < 1:
            raise ValueError("Password hash concurrency must be at least one")
        self._hasher = hasher or _password_hash_with_legacy_support()
        self._max_concurrent_operations = max_concurrent_operations
        self._operation_slots = BoundedSemaphore(max_concurrent_operations)
        self._dummy_hash = self._hasher.hash(
            "dummy password used only to equalize unknown account verification"
        )

    @property
    def dummy_hash(self) -> str:
        return self._dummy_hash

    @property
    def max_concurrent_operations(self) -> int:
        return self._max_concurrent_operations

    @contextmanager
    def _operation_slot(self) -> Iterator[None]:
        """Bound memory-hard work without waiting inside the shared sync thread pool."""
        acquired = self._operation_slots.acquire(blocking=False)
        if not acquired:
            raise PasswordOperationCapacityError(
                "Password operation capacity is temporarily exhausted"
            )
        try:
            yield
        finally:
            self._operation_slots.release()

    def hash(self, password: str) -> str:
        with self._operation_slot():
            return self._hasher.hash(normalize_password(password))

    def derive_argon2id_key(
        self,
        password: str,
        *,
        salt: bytes,
        memory_cost_kib: int,
        iterations: int,
        parallelism: int,
        length: int = 32,
    ) -> bytes:
        """Derive raw key bytes while sharing the password-operation memory budget."""
        if not 16 <= len(salt) <= 32:
            raise ValueError("Argon2id salt must contain between 16 and 32 bytes")
        if iterations < 1:
            raise ValueError("Argon2id iterations must be at least one")
        if parallelism < 1:
            raise ValueError("Argon2id parallelism must be at least one")
        if memory_cost_kib < 8 * parallelism:
            raise ValueError("Argon2id memory cost is too small for the selected parallelism")
        if length < 16:
            raise ValueError("Argon2id derived keys must contain at least 16 bytes")

        with self._operation_slot():
            return hash_secret_raw(
                secret=normalize_password(password).encode("utf-8"),
                salt=salt,
                time_cost=iterations,
                memory_cost=memory_cost_kib,
                parallelism=parallelism,
                hash_len=length,
                type=Type.ID,
                version=ARGON2_VERSION,
            )

    def verify(self, plain_password: str, password_hash: str) -> bool:
        try:
            with self._operation_slot():
                normalized_password = normalize_password(plain_password)
                if self._hasher.verify(normalized_password, password_hash):
                    return True
                return (
                    normalized_password != plain_password
                    and password_hash.startswith(_BCRYPT_PREFIXES)
                    and self._hasher.verify(plain_password, password_hash)
                )
        except (UnknownHashError, ValueError):
            return False

    def verify_and_update(
        self,
        plain_password: str,
        password_hash: str,
    ) -> tuple[bool, str | None]:
        try:
            with self._operation_slot():
                normalized_password = normalize_password(plain_password)
                valid, replacement = self._hasher.verify_and_update(
                    normalized_password,
                    password_hash,
                )
                if valid:
                    return valid, replacement
                if (
                    normalized_password != plain_password
                    and password_hash.startswith(_BCRYPT_PREFIXES)
                    and self._hasher.verify(plain_password, password_hash)
                ):
                    return True, self._hasher.hash(normalized_password)
                return False, None
        except (UnknownHashError, ValueError):
            # Stored hashes are untrusted persistence data. A corrupt or unsupported
            # value must behave like an invalid credential, not escape as a 500.
            return False, None

    def verify_or_dummy(
        self,
        plain_password: str,
        password_hash: str | None,
    ) -> tuple[bool, str | None]:
        """Always run one real Argon2 verification, including for unknown accounts."""
        target_hash = password_hash or self._dummy_hash
        valid, replacement = self.verify_and_update(plain_password, target_hash)
        if password_hash is None:
            return False, None
        return valid, replacement


password_manager = PasswordManager()


def password_character_classes(password: str) -> frozenset[str]:
    """Report which of the four character classes a password draws on.

    Unicode is bucketed by general category so a non-Latin password is judged the
    same way a Latin one is: cased letters land in "uppercase"/"lowercase", any
    numeric character in "number", and everything else - punctuation, symbols,
    whitespace, and caseless scripts - in "symbol".
    """
    found: set[str] = set()
    for character in normalize_password(password):
        category = unicodedata.category(character)
        if category in ("Lu", "Lt"):
            found.add("uppercase")
        elif category == "Ll":
            found.add("lowercase")
        elif category in ("Nd", "Nl", "No"):
            found.add("number")
        else:
            found.add("symbol")
    return frozenset(found)


def _account_detail_fragments(context_values: Iterable[str]) -> set[str]:
    """Expand account details into the fragments a password must not be built on."""
    fragments: set[str] = set()
    for value in context_values:
        normalized_value = unicodedata.normalize("NFC", value).strip().casefold()
        if not normalized_value:
            continue
        fragments.add(normalized_value)
        if "@" in normalized_value:
            fragments.add(normalized_value.split("@", maxsplit=1)[0])
    return {fragment for fragment in fragments if len(fragment) >= _MIN_CONTEXT_FRAGMENT_LENGTH}


def password_policy_error(
    password: str,
    *,
    context_values: Iterable[str] = (),
) -> str | None:
    normalized = normalize_password(password)
    if len(normalized) < PASSWORD_MIN_LENGTH:
        return f"Password must contain at least {PASSWORD_MIN_LENGTH} characters"
    if len(normalized) > PASSWORD_MAX_LENGTH:
        return f"Password must contain at most {PASSWORD_MAX_LENGTH} characters"

    # The guessability checks run before the composition rule on purpose. "password1"
    # satisfies two character classes, so reporting the class rule first would send the
    # user off to add a digit to a password that is guessed in the first thousand tries.
    candidate = normalized.casefold()
    if candidate in _COMMON_PASSWORDS:
        return "Choose a password that is not common or based on your account details"
    # Account details are matched as substrings, not whole values: at eight characters
    # "alice2024!" is as guessable for user "alice" as "alice" alone would be.
    if any(fragment in candidate for fragment in _account_detail_fragments(context_values)):
        return "Choose a password that is not common or based on your account details"

    if len(password_character_classes(normalized)) < PASSWORD_MIN_CHARACTER_CLASSES:
        return (
            f"Password must combine at least {PASSWORD_MIN_CHARACTER_CLASSES} of these: "
            "uppercase letters, lowercase letters, numbers, symbols"
        )
    return None


def generate_session_token(token_bytes: int = SESSION_TOKEN_BYTES) -> str:
    if token_bytes < 16:
        raise ValueError("Session tokens must contain at least 128 bits of entropy")
    return secrets.token_urlsafe(token_bytes)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_auth_throttle_key(secret_key: str, scope: str, value: str) -> str:
    """Create a keyed, non-reversible identifier for a login throttle bucket."""
    message = f"{scope}\0{value}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def hash_password(password: str) -> str:
    return password_manager.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return password_manager.verify(plain_password, password_hash)


def verify_and_update_password(
    plain_password: str,
    password_hash: str,
) -> tuple[bool, str | None]:
    """Verify a password and return a replacement hash when parameters become stale."""
    return password_manager.verify_and_update(plain_password, password_hash)
