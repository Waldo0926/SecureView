"""One virtual user: signs in, uploads, downloads, shares, exactly over the public API.

Each operation is timed and returned as an `Op`, whether it succeeded or not, so the caller
can count errors by kind instead of losing them in an exception. The client never retries:
a retry would hide precisely the failures a load test exists to find.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import rsa

from . import envelope

# An access token lives 30 minutes on the server. Renew a little before, so a soak test
# never measures a burst of 401s at the half-hour mark.
TOKEN_RENEW_AFTER_SECONDS = 25 * 60


@dataclass(frozen=True, slots=True)
class Account:
    username: str
    password: str
    key_id: str
    private_key_pem: str = field(repr=False)


@dataclass(slots=True)
class Op:
    """One timed operation. `kind` is upload / download / share / list / login."""

    kind: str
    started: float  # time.time() when it began
    ok: bool
    status: int | None = None  # HTTP status of the request that decided the outcome
    error: str | None = None  # short machine-friendly reason when not ok
    request_ms: float = 0.0  # time on the wire, request sent to response read
    crypto_ms: float = 0.0  # client-side encrypt or decrypt, not server time
    bytes: int = 0  # plaintext size moved
    verified: bool | None = None  # download: SHA-256 of the decrypted file matched
    user: str = ""
    size_label: str = ""
    file_type: str = ""


class RecoveryKey:
    """The deployment's active recovery key: every upload wraps its DEK to it as well."""

    def __init__(self, key_id: str, public_key_pem: str) -> None:
        self.key_id = key_id
        self.public_key = envelope.load_public_key(public_key_pem)


class VirtualUser:
    def __init__(
        self,
        account: Account,
        *,
        base_url: str,
        timeout: float,
        verify_tls: bool = True,
    ) -> None:
        self.account = account
        self.private_key: rsa.RSAPrivateKey = envelope.load_private_key(account.private_key_pem)
        self.public_key = self.private_key.public_key()
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=10.0),
            verify=verify_tls,
            headers={"User-Agent": "secureview-loadtest/1.0"},
        )
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_at = 0.0
        self.user_id: str | None = None
        self.files: list[tuple[str, str]] = []  # (file_id, sha256 of plaintext) this user owns
        self._renew = asyncio.Lock()

    async def close(self) -> None:
        await self.http.aclose()

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _op(self, kind: str, **values) -> Op:
        return Op(kind=kind, user=self.account.username, **values)

    # --- session ------------------------------------------------------------------------

    async def login(self) -> Op:
        started, t0 = time.time(), time.perf_counter()
        try:
            res = await self.http.post(
                "/auth/login",
                json={"username": self.account.username, "password": self.account.password},
            )
        except httpx.HTTPError as exc:
            return self._op("login", started=started, ok=False, error=type(exc).__name__)
        elapsed = (time.perf_counter() - t0) * 1000
        if res.status_code != 200:
            return self._op(
                "login",
                started=started,
                ok=False,
                status=res.status_code,
                error=f"http_{res.status_code}",
                request_ms=elapsed,
            )
        data = res.json()["data"]
        self.access_token, self.refresh_token = data["access_token"], data["refresh_token"]
        self.user_id = data["user"]["id"]
        self.token_at = time.monotonic()
        return self._op("login", started=started, ok=True, status=200, request_ms=elapsed)

    async def _fresh_token(self) -> None:
        if time.monotonic() - self.token_at < TOKEN_RENEW_AFTER_SECONDS:
            return
        async with self._renew:
            if time.monotonic() - self.token_at < TOKEN_RENEW_AFTER_SECONDS:
                return
            res = await self.http.post("/auth/refresh", json={"refresh_token": self.refresh_token})
            if res.status_code == 200:
                data = res.json()["data"]
                self.access_token, self.refresh_token = data["access_token"], data["refresh_token"]
                self.token_at = time.monotonic()
            else:
                await self.login()

    async def recovery_key(self) -> RecoveryKey:
        res = await self.http.get("/recovery/public-key", headers=self._auth())
        res.raise_for_status()
        data = res.json()["data"]
        return RecoveryKey(data["key_id"], data["public_key_pem"])

    # --- file operations ------------------------------------------------------------------

    async def upload(
        self,
        plaintext: bytes,
        *,
        digest: str,
        filename: str,
        mime_type: str,
        algorithm: str,
        recovery: RecoveryKey,
        size_label: str = "",
        file_type: str = "",
    ) -> Op:
        await self._fresh_token()
        started = time.time()
        t0 = time.perf_counter()
        sealed = await asyncio.to_thread(
            envelope.seal,
            plaintext,
            file_id=uuid4(),
            filename=filename,
            mime_type=mime_type,
            algorithm=algorithm,
            owner_key_id=self.account.key_id,
            owner_public_key=self.public_key,
            recovery_key_id=recovery.key_id,
            recovery_public_key=recovery.public_key,
        )
        crypto_ms = (time.perf_counter() - t0) * 1000
        meta = {"bytes": len(plaintext), "size_label": size_label, "file_type": file_type}
        t1 = time.perf_counter()
        try:
            res = await self.http.post(
                "/files/upload",
                headers=self._auth(),
                data={"metadata": json.dumps(sealed.metadata)},
                files={
                    "file": (
                        f"{filename}.ciphertext",
                        sealed.ciphertext,
                        "application/octet-stream",
                    )
                },
            )
        except httpx.HTTPError as exc:
            return self._op(
                "upload",
                started=started,
                ok=False,
                error=type(exc).__name__,
                request_ms=(time.perf_counter() - t1) * 1000,
                crypto_ms=crypto_ms,
                **meta,
            )
        request_ms = (time.perf_counter() - t1) * 1000
        if res.status_code != 201:
            return self._op(
                "upload",
                started=started,
                ok=False,
                status=res.status_code,
                error=f"http_{res.status_code}",
                request_ms=request_ms,
                crypto_ms=crypto_ms,
                **meta,
            )
        self.files.append((str(sealed.file_id), digest))
        return self._op(
            "upload",
            started=started,
            ok=True,
            status=201,
            request_ms=request_ms,
            crypto_ms=crypto_ms,
            **meta,
        )

    async def download(
        self, file_id: str, digest: str, *, size_label: str = "", file_type: str = ""
    ) -> Op:
        """Fetch metadata and ciphertext, decrypt with this user's key, compare SHA-256."""
        await self._fresh_token()
        started = time.time()
        t0 = time.perf_counter()
        meta = {"size_label": size_label, "file_type": file_type}
        try:
            info = await self.http.get(f"/files/{file_id}", headers=self._auth())
            if info.status_code != 200:
                return self._op(
                    "download",
                    started=started,
                    ok=False,
                    status=info.status_code,
                    error=f"http_{info.status_code}",
                    request_ms=(time.perf_counter() - t0) * 1000,
                    **meta,
                )
            res = await self.http.post(f"/files/{file_id}/download", headers=self._auth())
        except httpx.HTTPError as exc:
            return self._op(
                "download",
                started=started,
                ok=False,
                error=type(exc).__name__,
                request_ms=(time.perf_counter() - t0) * 1000,
                **meta,
            )
        request_ms = (time.perf_counter() - t0) * 1000
        if res.status_code != 200:
            return self._op(
                "download",
                started=started,
                ok=False,
                status=res.status_code,
                error=f"http_{res.status_code}",
                request_ms=request_ms,
                **meta,
            )
        file = info.json()["data"]
        t1 = time.perf_counter()
        try:
            plaintext = await asyncio.to_thread(
                envelope.open_file, res.content, file=file, private_key=self.private_key
            )
        except InvalidTag:
            return self._op(
                "download",
                started=started,
                ok=False,
                status=200,
                error="auth_tag_failed",
                request_ms=request_ms,
                crypto_ms=(time.perf_counter() - t1) * 1000,
                verified=False,
                **meta,
            )
        crypto_ms = (time.perf_counter() - t1) * 1000
        verified = envelope.sha256(plaintext) == digest
        return self._op(
            "download",
            started=started,
            ok=verified,
            status=200,
            error=None if verified else "sha256_mismatch",
            request_ms=request_ms,
            crypto_ms=crypto_ms,
            bytes=len(plaintext),
            verified=verified,
            **meta,
        )

    async def list_files(self) -> Op:
        await self._fresh_token()
        started, t0 = time.time(), time.perf_counter()
        try:
            res = await self.http.get(
                "/files", params={"page": 1, "page_size": 25}, headers=self._auth()
            )
        except httpx.HTTPError as exc:
            return self._op("list", started=started, ok=False, error=type(exc).__name__)
        elapsed = (time.perf_counter() - t0) * 1000
        return self._op(
            "list",
            started=started,
            ok=res.status_code == 200,
            status=res.status_code,
            error=None if res.status_code == 200 else f"http_{res.status_code}",
            request_ms=elapsed,
        )

    async def share(self, file_id: str, recipient: VirtualUser) -> Op:
        """Rewrap one of this user's files to `recipient`, as the browser's share dialog does."""
        await self._fresh_token()
        started, t0 = time.time(), time.perf_counter()
        try:
            info = await self.http.get(f"/files/{file_id}", headers=self._auth())
            if info.status_code != 200:
                return self._op(
                    "share",
                    started=started,
                    ok=False,
                    status=info.status_code,
                    error=f"http_{info.status_code}",
                )
            dek = envelope.unwrap(
                self.private_key,
                envelope.unb64(info.json()["data"]["crypto_envelope"]["wrapped_file_key"]),
            )
            res = await self.http.post(
                f"/files/{file_id}/share",
                headers=self._auth(),
                json={
                    "target_user_id": recipient.user_id,
                    "target_key_id": recipient.account.key_id,
                    "wrapped_file_key": envelope.b64(envelope.wrap(recipient.public_key, dek)),
                    "can_download": True,
                    "can_share": False,
                },
            )
        except httpx.HTTPError as exc:
            return self._op("share", started=started, ok=False, error=type(exc).__name__)
        elapsed = (time.perf_counter() - t0) * 1000
        ok = res.status_code in (200, 201)
        return self._op(
            "share",
            started=started,
            ok=ok,
            status=res.status_code,
            error=None if ok else f"http_{res.status_code}",
            request_ms=elapsed,
        )

    async def delete_file(self, file_id: str) -> Op:
        """Delete one of this user's files, as the My Files delete button does."""
        await self._fresh_token()
        started, t0 = time.time(), time.perf_counter()
        try:
            res = await self.http.post(f"/files/{file_id}/delete", headers=self._auth())
        except httpx.HTTPError as exc:
            return self._op("delete", started=started, ok=False, error=type(exc).__name__)
        elapsed = (time.perf_counter() - t0) * 1000
        ok = res.status_code == 200
        return self._op(
            "delete",
            started=started,
            ok=ok,
            status=res.status_code,
            error=None if ok else f"http_{res.status_code}",
            request_ms=elapsed,
        )

    async def delete_account(self) -> int:
        """Close the account through the API; the server destroys every file it owns."""
        res = await self.http.post(
            "/auth/delete-account",
            headers=self._auth(),
            json={"password": self.account.password, "confirmation": "DELETE"},
        )
        return res.status_code
