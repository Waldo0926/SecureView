"""Create the throwaway accounts a load test signs in as, and write their credentials to a file.

A load test needs many real accounts, each with a real RSA key the test client holds, so that
every upload is wrapped and every download decrypted exactly as a browser would do it.
Registering them through the API needs an emailed code per account, so this reuses
`seed_test_account.py`: the same client-side enrolment, the same `AuthService.register` call,
audit entries included. Every account is an ordinary USER.

Names are `<prefix>-<run>-<n>` with `@example.com` addresses, so they are easy to spot in the
admin Users tab, and the load tool's `cleanup` command deletes them through the normal
delete-account route, which destroys their files too.

The output file holds passwords and private keys for these test accounts only. It is written
0600; keep it off shared drives and delete it after the cleanup.

Run from `backend/` with the deployment environment loaded:

    .venv/bin/python scripts/seed_load_users.py --count 100 --out /root/loadtest-accounts.json
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_test_account import build_key_material, plant_verification_code

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.domain.auth import RequestContext
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth_schema import UserRegisterRequest
from app.services.auth_service import AuthService


def _secret() -> str:
    # Upper, lower, digit and symbol satisfy the password policy.
    return "Aa1!" + secrets.token_urlsafe(24)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--prefix", default="loadtest")
    parser.add_argument("--out", type=Path, required=True, help="credentials file to write (0600)")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 500:
        parser.error("--count must be between 1 and 500")
    if args.out.exists():
        parser.error(
            f"{args.out} exists; refusing to overwrite credentials that may still be in use"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    run = secrets.token_hex(3)
    accounts: list[dict[str, str]] = []
    started = time.perf_counter()
    for index in range(1, args.count + 1):
        username = f"{args.prefix}-{run}-{index:03d}"
        email = f"{username}@example.com"
        password, passphrase = _secret(), "passphrase " + _secret()
        key_material, private_key_pem = build_key_material(passphrase)
        code = "".join(
            secrets.choice("0123456789") for _ in range(settings.VERIFICATION_CODE_LENGTH)
        )
        request = UserRegisterRequest(
            username=username,
            email=email,
            password=password,
            verification_code=code,
            key_material=key_material,
        )
        db = SessionLocal()
        try:
            if AuthRepository(db).identifier_exists(username, email):
                raise SystemExit(f"{username} already exists; nothing more was seeded")
            plant_verification_code(db, settings, email=email, code=code)
            result = AuthService(db=db, settings=settings).register(
                username=request.username,
                email=request.email,
                password=request.password,
                verification_code=request.verification_code,
                key_material=request.key_material.to_domain(),
                context=RequestContext(ip_address=None, user_agent="mcs21-seed-load-users"),
            )
        finally:
            db.close()
        accounts.append(
            {
                "username": username,
                "password": password,
                "key_id": str(result.key_id),
                "private_key_pem": private_key_pem,
            }
        )
        if index % 10 == 0 or index == args.count:
            print(f"seeded {index}/{args.count}")

    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"prefix": f"{args.prefix}-{run}", "accounts": accounts}, handle)
    print(
        f"{len(accounts)} accounts {args.prefix}-{run}-001..{len(accounts):03d} in "
        f"{time.perf_counter() - started:.0f}s; credentials in {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
