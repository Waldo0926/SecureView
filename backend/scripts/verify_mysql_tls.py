"""Prove a MySQL connection actually negotiated TLS, not merely that it could.

The mysql:8.4 server image enables SSL and auto-generates a self-signed CA at
first start, but an ordinary client connection is not required to use it --
plain TCP still works unless the account or the server demand otherwise. A CI
release gate that only checks "can I connect" would pass identically whether
TLS was used or silently skipped. This script instead makes a connection that
requires and verifies the server certificate, then reads back
`Ssl_cipher` from the session: a non-empty cipher name is the server's own
confirmation that this specific connection is encrypted.

Reads connection details from environment variables so the caller never has
to put a credential on the command line or in a log line:

    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSL_CA

Exits non-zero and prints a host/user (never password) on any failure.
"""

from __future__ import annotations

import os
import sys

import pymysql


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"verify_mysql_tls: missing required environment variable {name}", file=sys.stderr)
        sys.exit(2)
    return value


def main() -> int:
    host = _required_env("DB_HOST")
    port = int(os.environ.get("DB_PORT", "3306"))
    user = _required_env("DB_USER")
    password = _required_env("DB_PASSWORD")
    database = _required_env("DB_NAME")
    ssl_ca = _required_env("DB_SSL_CA")

    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        ssl_ca=ssl_ca,
        ssl_verify_cert=True,
        ssl_verify_identity=False,  # disposable CI host has no matching CN/SAN
        connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW STATUS LIKE 'Ssl_cipher'")
            row = cursor.fetchone()
    finally:
        connection.close()

    cipher = row[1] if row else ""
    if not cipher:
        print(
            f"verify_mysql_tls: connection to {host}:{port} as {user!r} negotiated "
            "no cipher -- TLS was not actually used",
            file=sys.stderr,
        )
        return 1

    print(f"verify_mysql_tls: connection to {host}:{port} as {user!r} used TLS cipher {cipher}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
