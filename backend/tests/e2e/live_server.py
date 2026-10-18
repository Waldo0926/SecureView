"""Serve the real API for the live end-to-end suite, and bootstrap its first admin.

`frontend/src/e2e/live-stack.integration.test.ts` drives the product the way the browser
does, over HTTP, against this server and a disposable MySQL database. The application is
the unmodified `create_app()` with exactly one substitution: verification email goes to a
directory instead of a mail provider, so the suite can complete a real registration by
reading its own code back.

Why a mailbox directory rather than `EMAIL_PROVIDER=console`: the console provider prints
the message body -- verification code included -- into the server log, and in CI that log
is kept. A file under the runner's temporary directory is read by the suite and discarded
with the runner, never published.

    # Promote an already-seeded account; there is deliberately no API for this.
    .venv/bin/python tests/e2e/live_server.py promote-admin --username e2e-admin

    # Serve on 127.0.0.1:8000 with the mailbox in $E2E_MAILBOX_DIR.
    .venv/bin/python tests/e2e/live_server.py serve --port 8000

Both refuse to run unless `APP_ENV=test` and `DB_NAME` carries a distinct `_test` segment,
the same guard the MySQL integration fixtures use, so neither can be pointed at a real
database by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_auth_service, get_request_db
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.domain.enums import SystemRole
from app.main import create_app
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.email_service import OutboundEmail


class MailboxEmailService:
    """Write each message to its own JSON file, atomically, for the suite to read back."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def send(self, message: OutboundEmail) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns()}-{uuid4().hex}"
        staging = self.directory / f"{name}.tmp"
        staging.write_text(
            json.dumps(
                {
                    "to": message.to_address,
                    "subject": message.subject,
                    "text": message.text_body,
                }
            ),
            encoding="utf-8",
        )
        # A reader polling the directory must never see a half-written message.
        staging.replace(self.directory / f"{name}.json")


def _require_disposable(settings: Settings) -> None:
    if settings.APP_ENV != "test":
        raise SystemExit("live_server.py only runs with APP_ENV=test")
    if re.search(r"(?:^|_)test(?:$|_)", settings.DB_NAME.casefold()) is None:
        raise SystemExit(
            "live_server.py only runs against a database whose name has a _test segment"
        )


def build_app(settings: Settings, mailbox: Path):
    application = create_app(settings)
    email = MailboxEmailService(mailbox)

    def auth_service_with_mailbox(
        request: Request,
        db: Annotated[Session, Depends(get_request_db)],
    ) -> AuthService:
        service = AuthService(
            db=db,
            settings=request.app.state.settings,
            passwords=request.app.state.password_manager,
        )
        service.verification.email = email
        return service

    application.dependency_overrides[get_auth_service] = auth_service_with_mailbox
    return application


def promote_admin(username: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username).with_for_update())
        if user is None:
            raise SystemExit(f"No account named {username!r}; seed it first")
        user.role = SystemRole.ADMIN
        db.commit()
    print(f"{username} is now ADMIN")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    promote = commands.add_parser("promote-admin")
    promote.add_argument("--username", required=True)
    args = parser.parse_args()

    settings = get_settings()
    _require_disposable(settings)

    if args.command == "promote-admin":
        promote_admin(args.username)
        return 0

    mailbox = os.environ.get("E2E_MAILBOX_DIR")
    if not mailbox:
        raise SystemExit("Set E2E_MAILBOX_DIR to the directory verification mail is written to")
    uvicorn.run(build_app(settings, Path(mailbox)), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
