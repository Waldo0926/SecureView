"""Generate a recovery key pair and register only its public half.

Every upload wraps its file key twice: once to the owner's public key and once to the
active recovery public key. Without a registered recovery key the API answers
"No active recovery public key is configured" and no file can be uploaded at all.

This script talks to the API over HTTP rather than the database, so it works against a
local backend or a deployed one, and it goes through the same ADMIN-only route an
operator would use.

    .venv/bin/python scripts/register_recovery_key.py \
        --api-base https://secureview.tech/api/v1 \
        --username <admin> --password '...' \
        --out ../recovery_keys/recovery-private.pem

The private key is written locally and never transmitted. Whoever holds it can decrypt
every file ever uploaded under the matching public key, which is exactly why
docs/SECURITY_FLOWS.md places it outside the application trust boundary. On a real
deployment it belongs in offline or HSM custody; for a demonstration deployment, keep it
out of version control -- `recovery_keys/` is already gitignored -- and record the
fingerprint somewhere the team can check it against what the upload page displays.

Registering a new key revokes the previous active one for new uploads. It does NOT
rewrap existing files, so the old private key must be retained for as long as any file
wrapped to it still exists. The script refuses to overwrite an existing private key file
for that reason.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SUPPORTED_KEY_SIZES = (2048, 3072, 4096)


def tls_context() -> ssl.SSLContext:
    """Build a verifying TLS context that works on a stock macOS Python.

    Python installed from python.org does not read the system keychain; it expects a CA
    bundle at a path its "Install Certificates" step creates, and without that step every
    HTTPS call fails with CERTIFICATE_VERIFY_FAILED. certifi ships the same bundle, so
    prefer it when present. Verification stays on either way: disabling it would let anyone
    on the path substitute the recovery public key this script is about to trust.
    """
    if ssl.get_default_verify_paths().cafile is None:
        try:
            import certifi
        except ImportError:
            pass
        else:
            return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True, help="e.g. https://secureview.tech/api/v1")
    parser.add_argument("--username", required=True, help="An ADMIN account")
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--out",
        required=True,
        help="Where to write the private key. Never uploaded; keep it out of git.",
    )
    parser.add_argument("--key-size", type=int, default=3072, choices=SUPPORTED_KEY_SIZES)
    parser.add_argument(
        "--key-id",
        default=None,
        help="Optional UUID for the key record. A random v4 UUID is used by default.",
    )
    return parser.parse_args()


def call(api_base: str, path: str, payload: dict | None = None, token: str | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(f"{api_base}{path}", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30, context=tls_context()) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise SystemExit(f"{path} failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Cannot reach {api_base}: {error.reason}") from error


def main() -> int:
    args = parse_args()

    out = Path(args.out)
    if out.exists():
        # Overwriting would orphan every file already wrapped to the previous key.
        raise SystemExit(
            f"{out} already exists. Registering a new key does not rewrap existing files, "
            f"so the current private key must be retained. Move it aside deliberately."
        )
    out.parent.mkdir(parents=True, exist_ok=True)

    login = call(
        args.api_base,
        "/auth/login",
        {"username": args.username, "password": args.password},
    )
    user = login["data"]["user"]
    token = login["data"]["access_token"]
    if user["role"] != "ADMIN":
        raise SystemExit(
            f"{args.username} has role {user['role']}; registering a recovery key requires ADMIN."
        )
    print(f"Signed in as {user['username']} ({user['role']})")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=args.key_size)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    local_fingerprint = hashlib.sha256(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()

    # Write the private half before registering. If the API call fails after a successful
    # registration, an unsaved key would leave uploads wrapped to a key nobody holds.
    out.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    out.chmod(0o600)
    print(f"Private key written to {out} (mode 600). It was not transmitted.")

    result = call(
        args.api_base,
        "/recovery/public-key/register",
        {
            "key_id": args.key_id or str(uuid.uuid4()),
            "public_key_pem": public_pem,
            "algorithm": "RSA-OAEP-SHA256",
        },
        token=token,
    )
    key = result["data"]["key"]
    rotated = result["data"].get("rotated_keys", 0)

    if key["fingerprint"] != local_fingerprint:
        raise SystemExit(
            "The API reported a fingerprint that does not match the key generated here. "
            "Do not use this key; investigate before uploading anything."
        )

    print()
    print(f"  key id:      {key['key_id']}")
    print(f"  status:      {key['status']}")
    print(f"  size:        {key['key_size_bits']} bits")
    print(f"  fingerprint: {key['fingerprint']}")
    if rotated:
        print(
            f"\n  {rotated} previously active key(s) were revoked for new uploads. "
            f"Their private halves must be kept: existing files are still wrapped to them."
        )
    print("\nThe upload page shows this fingerprint. Publish it so users can check it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
