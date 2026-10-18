"""Seed a shared test account without an email round trip.

The frontend team needs a stable login to develop against. Registering through
the UI mints a new random key pair every time and needs a live verification
code, so a hand-made fixture would drift from the real enrolment format the
moment either side changes.

This script therefore does exactly what the browser does. It rebuilds the
client-side enrolment of `frontend/src/utils/account-crypto.ts` in Python
(RSA key pair, Argon2id-wrapped account master key, HKDF/AES-GCM-sealed private
key), plants the verification code the registration path expects, and then calls
`AuthService.register` — the same code path an ordinary signup takes, audit entry
included. The account it produces is indistinguishable from a browser-made one,
so the encryption passphrase really does open the envelope.

Run it from `backend/` with the deployment environment loaded:

    .venv/bin/python scripts/seed_test_account.py \
        --username admin --email admin@secureview.tech \
        --password '...' --passphrase '...'

The address needs a real domain. Reserved TLDs such as `.test` and `.local` are
rejected by EmailStr, so an account holding one would log in and then fail when
the response model tried to serialize it back.

Nothing here is meant for production. The point of the account is that everyone
on the team knows its credentials.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argon2.low_level import ARGON2_VERSION, Type, hash_secret_raw
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import PASSWORD_MIN_LENGTH, hash_auth_throttle_key
from app.core.time import to_database_utc, utc_now
from app.domain.auth import RequestContext
from app.domain.enums import VerificationCodeStatus, VerificationPurpose
from app.models.email_verification_code import EmailVerificationCode
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth_schema import UserRegisterRequest
from app.schemas.key_schema import ClientKeyRegistrationIn
from app.services.auth_service import AuthService

# Mirrors of frontend/src/utils/account-crypto.ts. These must stay in step with
# it: a mismatch produces an envelope the browser cannot open, and the failure
# only surfaces when someone tries to log in. The algorithm names and format
# versions are not here because they are not on the wire — the API pins them,
# and `ClientKeyRegistrationIn` rejects a request that tries to declare one.
RSA_KEY_SIZE_BITS = 3072
ARGON2_MEMORY_KIB = 65536
ARGON2_ITERATIONS = 3
ARGON2_PARALLELISM = 1
AES_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
AES_GCM_TAG_BYTES = 16
KDF_SALT_BYTES = 16
HKDF_SALT_BYTES = 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _amk_wrap_aad(profile_id: str) -> bytes:
    return f"secureview:amk-wrap:v1:{profile_id}".encode()


def _private_key_aad(bundle_id: str, key_id: str) -> bytes:
    return f"secureview:private-key:v1:{bundle_id}:{key_id}".encode()


def _derive_kek(passphrase: str, salt: bytes) -> bytes:
    """Argon2id, with the parameters hash-wasm uses in the browser."""
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_ITERATIONS,
        memory_cost=ARGON2_MEMORY_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=AES_KEY_BYTES,
        type=Type.ID,
        version=ARGON2_VERSION,
    )


def _derive_private_key_key(amk: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=AES_KEY_BYTES,
        salt=salt,
        info=info,
    ).derive(amk)


def _seal(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """AES-256-GCM with the tag detached, as the API schema expects it."""
    joined = AESGCM(key).encrypt(nonce, plaintext, aad)
    return joined[:-AES_GCM_TAG_BYTES], joined[-AES_GCM_TAG_BYTES:]


def _open(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext + tag, aad)


def build_key_material(passphrase: str) -> tuple[ClientKeyRegistrationIn, str]:
    """Enrol an account key exactly as the browser would, and prove it reopens."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_SIZE_BITS)
    private_key_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )

    key_id = str(uuid4())
    profile_id = str(uuid4())
    bundle_id = str(uuid4())

    # 1. Wrap a fresh random AMK under an Argon2id-derived KEK.
    amk = secrets.token_bytes(AES_KEY_BYTES)
    kdf_salt = secrets.token_bytes(KDF_SALT_BYTES)
    kek = _derive_kek(passphrase, kdf_salt)
    amk_nonce = secrets.token_bytes(AES_GCM_NONCE_BYTES)
    wrapped_amk, amk_tag = _seal(kek, amk_nonce, amk, _amk_wrap_aad(profile_id))

    # 2. Encrypt the PKCS#8 private key under an AMK/HKDF-derived key.
    hkdf_salt = secrets.token_bytes(HKDF_SALT_BYTES)
    bundle_aad = _private_key_aad(bundle_id, key_id)
    private_key_key = _derive_private_key_key(amk, hkdf_salt, bundle_aad)
    bundle_nonce = secrets.token_bytes(AES_GCM_NONCE_BYTES)
    sealed_private_key, bundle_tag = _seal(
        private_key_key, bundle_nonce, private_key_der, bundle_aad
    )

    key_material = ClientKeyRegistrationIn(
        key_id=key_id,
        public_key_pem=public_key_pem,
        key_size_bits=RSA_KEY_SIZE_BITS,
        protection={
            "profile_id": profile_id,
            "kdf_salt": _b64(kdf_salt),
            "kdf_memory_kib": ARGON2_MEMORY_KIB,
            "kdf_iterations": ARGON2_ITERATIONS,
            "kdf_parallelism": ARGON2_PARALLELISM,
            "wrapped_amk": _b64(wrapped_amk),
            "amk_nonce": _b64(amk_nonce),
            "amk_auth_tag": _b64(amk_tag),
        },
        private_key_bundle={
            "bundle_id": bundle_id,
            "derivation_salt": _b64(hkdf_salt),
            "encrypted_private_key": _b64(sealed_private_key),
            "nonce": _b64(bundle_nonce),
            "auth_tag": _b64(bundle_tag),
            "ciphertext_sha256": hashlib.sha256(sealed_private_key).hexdigest(),
        },
    )

    assert_envelopes_unlock(key_material, passphrase, private_key_der)
    return key_material, private_key_pem


def assert_envelopes_unlock(
    key_material: ClientKeyRegistrationIn,
    passphrase: str,
    expected_private_key_der: bytes,
) -> None:
    """Re-derive both envelopes from the passphrase alone, as the unlock does.

    An account whose envelope cannot be reopened looks fine until someone tries
    to use it, so refuse to seed one.
    """
    protection = key_material.protection
    bundle = key_material.private_key_bundle
    decode = base64.b64decode

    kek = _derive_kek(passphrase, decode(protection.kdf_salt))
    recovered_amk = _open(
        kek,
        decode(protection.amk_nonce),
        decode(protection.wrapped_amk),
        decode(protection.amk_auth_tag),
        _amk_wrap_aad(str(protection.profile_id)),
    )

    bundle_aad = _private_key_aad(str(bundle.bundle_id), str(key_material.key_id))
    recovered_der = _open(
        _derive_private_key_key(recovered_amk, decode(bundle.derivation_salt), bundle_aad),
        decode(bundle.nonce),
        decode(bundle.encrypted_private_key),
        decode(bundle.auth_tag),
        bundle_aad,
    )
    if recovered_der != expected_private_key_der:
        raise SystemExit("Account key self-test failed; nothing was seeded")


def plant_verification_code(db, settings, *, email: str, code: str) -> None:
    """Insert the challenge registration is about to consume.

    Registration will not proceed without one, and issuing it the normal way
    would send mail to an address that does not exist.
    """
    now = to_database_utc(utc_now())
    db.add(
        EmailVerificationCode(
            code_uuid=str(uuid4()),
            purpose=VerificationPurpose.REGISTRATION,
            email=email,
            user_id=None,
            code_hash=hash_auth_throttle_key(
                settings.SECRET_KEY,
                f"verification:{VerificationPurpose.REGISTRATION.value}:{email}",
                code,
            ),
            status=VerificationCodeStatus.PENDING,
            attempt_count=0,
            max_attempts=settings.VERIFICATION_CODE_MAX_ATTEMPTS,
            ip_address=None,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.VERIFICATION_CODE_TTL_SECONDS),
        )
    )
    db.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password",
        required=True,
        help=f"At least {PASSWORD_MIN_LENGTH} characters, from two or more character classes",
    )
    parser.add_argument("--passphrase", required=True, help="Unlocks the account key envelope")
    parser.add_argument(
        "--private-key-out",
        type=Path,
        default=None,
        help="Write the plaintext private key PEM here. The passphrase recovers it "
        "anyway, so this is only a convenience for offline tests.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.password == args.passphrase:
        raise SystemExit("The password and the encryption passphrase must differ")

    settings = get_settings()
    key_material, private_key_pem = build_key_material(args.passphrase)
    code = "".join(secrets.choice("0123456789") for _ in range(settings.VERIFICATION_CODE_LENGTH))

    # `AuthService.register` takes plain strings, so nothing would otherwise hold
    # this fixture to the rules the HTTP layer enforces. A reserved domain such
    # as `.test` registers cleanly and then breaks every login with a 500 when
    # the response model refuses to serialize it back. Validate through the real
    # request model, before anything is written.
    try:
        request = UserRegisterRequest(
            username=args.username,
            email=args.email,
            password=args.password,
            verification_code=code,
            key_material=key_material,
        )
    except ValidationError as exc:
        problems = "\n".join(
            f"  {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise SystemExit(f"The API would reject these details:\n{problems}") from None

    db = SessionLocal()
    try:
        if AuthRepository(db).identifier_exists(request.username, request.email):
            raise SystemExit(
                f"An account already uses {request.username!r} or {request.email!r}. "
                "Remove it first, or pick another identifier."
            )

        plant_verification_code(db, settings, email=request.email, code=code)

        result = AuthService(db=db, settings=settings).register(
            username=request.username,
            email=request.email,
            password=request.password,
            verification_code=request.verification_code,
            key_material=request.key_material.to_domain(),
            # No IP, so this seeding run is not charged against a rate-limit
            # bucket a real client would later land in.
            context=RequestContext(ip_address=None, user_agent="mcs21-seed-test-account"),
        )
    finally:
        db.close()

    if args.private_key_out is not None:
        args.private_key_out.write_text(private_key_pem)
        args.private_key_out.chmod(0o600)

    print(f"Seeded {result.user.username} <{result.user.email}>")
    print(f"  user uuid:   {result.user.id}")
    print(f"  role:        {result.user.role.value}")
    print(f"  key id:      {result.key_id}")
    print(f"  fingerprint: {result.public_key_fingerprint}")
    if args.private_key_out is not None:
        print(f"  private key: {args.private_key_out}")


if __name__ == "__main__":
    main()
