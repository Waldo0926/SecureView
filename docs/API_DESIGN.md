# API Design

English | [简体中文](API_DESIGN.zh-CN.md)

## Current Status and Method Policy

The backend exposes implemented authentication, account-key custody, encrypted-file,
sharing, audit, recovery, and administration routes under:

```text
/api/v1
```

These routes use real authorization, persistence, transactions, storage where applicable,
and audit events.

Application HTTP methods are restricted to `GET` and `POST`. `GET` is read-only. Creation,
updates, deletion, revocation, verification commands, and all other state changes use
`POST`, normally with an explicit action path. Application routes, clients, examples,
OpenAPI, and CORS must not define `PUT`, `PATCH`, or `DELETE` business operations.

Unversioned operational endpoints are:

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health/live` | Process liveness; does not check dependencies |
| GET | `/health/ready` | Database connectivity and exact application schema-revision marker |

## Response, Authentication, and Error Contract

JSON application responses use a common envelope whose `data` member has a route-specific
DTO. A failure example is:

```json
{
  "success": false,
  "status": "fail",
  "message": "Request validation failed",
  "data": {
    "error_code": "request_validation_failed",
    "details": []
  },
  "description": null,
  "code": 422
}
```

`error_code` is stable for clients and `message` is safe for users. Validation errors expose
field locations without echoing rejected values. Internal exceptions, database details,
filesystem paths, credentials, passphrases, plaintext private keys, and plaintext DEKs are
never returned.

Protected routes use `Authorization: Bearer <opaque-access-token>` and return
`WWW-Authenticate: Bearer` on authentication failure. Secret-bearing responses use
`Cache-Control: no-store, no-cache` and `Pragma: no-cache`. Sequential database IDs do not
cross the API boundary; public resources use UUIDs.

## Auth API

| Method | Endpoint | Auth | Success | Description |
|---|---|---|---:|---|
| POST | `/auth/verification-codes/send` | Public | 200 | Email a one-time code for registration or password reset |
| POST | `/auth/register` | Public | 201 | Create USER account and persist client-created encrypted key material |
| POST | `/auth/password-reset` | Public | 200 | Set a new login password after an emailed code |
| POST | `/auth/login` | Public | 200 | Verify login password and issue access/refresh pair |
| POST | `/auth/refresh` | Refresh token in JSON | 200 | Consume and rotate the one-time refresh credential |
| GET | `/auth/me` | Bearer | 200 | Return the current account |
| POST | `/auth/logout` | Bearer | 200 | Revoke the current session family |
| POST | `/auth/logout-all` | Bearer | 200 | Revoke all active session families for the account |
| POST | `/auth/change-password` | Bearer | 200 | Change login password and revoke every session |
| POST | `/auth/delete-account` | Bearer + login password | 200 | Close the account and delete the files it owns; not reversible |
| GET | `/auth/sessions` | Bearer | 200 | List at most the 100 newest server-side sessions |
| POST | `/auth/sessions/{session_id}/revoke` | Bearer | 200 | Revoke an account-owned session by public UUID |
| POST | `/auth/avatar/upload` | Bearer | 200 | Upload a validated PNG/JPEG avatar (stored outside the encrypted-object root) |
| GET | `/auth/avatar` | Bearer | 200 | Return the caller's avatar image |
| POST | `/auth/avatar/delete` | Bearer | 200 | Remove the avatar; initials remain the fallback |

`POST /auth/verification-codes/send` takes `email` and a `purpose` of `REGISTRATION` or
`PASSWORD_RESET`. It always answers `200` with `code_sent`, `expires_in_seconds`, and
`resend_available_in_seconds`, whether or not the address has an account, so the endpoint
cannot be used to enumerate registered users. A code is emailed only when the address is
actually eligible for the requested purpose. Sends are rate limited per address and per IP,
and a resend inside the cooldown returns `429` with `Retry-After`.

Registration requires `username`, `email`, `password`, `verification_code`, and
`key_material`. `key_material` contains a client-generated RSA-OAEP-SHA256 public key, a
KEK-wrapped AMK profile using Argon2id plus AES-256-GCM, and an AMK/HKDF-derived AES-256-GCM
encrypted PKCS8-DER private-key bundle.

Those algorithm names, the format and AAD versions, and the derived key length are fixed by
the API rather than declared by the caller, and sending one is rejected as an unexpected
field. What the request carries is the material a caller alone can produce: the public key,
the salts, the KDF cost parameters, the sealed envelopes with their nonces and tags, and the
bundle's `ciphertext_sha256`. Stored rows and every `*Out` response still record which
algorithm sealed each envelope, so a second one can be introduced later. A registration that
omits the code fails validation with `422`.

The checks run in a fixed order so that the response reveals only what is public. A taken
username answers `409 account_identifier_unavailable` first, before the code is consumed:
usernames are public (sharing resolves them), and reporting it early means the caller can pick
another name without requesting a new code. The code is consumed next, and an incorrect or
expired one fails with `error_code` `invalid_verification_code`. Only then is the email checked,
and an address that already has an account answers that same `422 invalid_verification_code`,
so a registered email cannot be told apart from a wrong code. (The send endpoint never delivers
a code to a registered address, so that branch normally only closes a race.) Consuming the
code proves control of the address, so the created account is stored with `email_verified`
already true. The successful response returns `user`, `key_id`, and
`public_key_fingerprint`; it does not return a private key.

`POST /auth/password-reset` takes `username`, `email`, `verification_code`, and
`new_password`. The code is consumed before the username/email pair is judged, so a mismatched
pair costs an attempt instead of revealing that the code itself was valid; every failure
returns the same `invalid_verification_code` response. A successful reset writes a new
Argon2id password hash, revokes every session family, and returns `revoked_sessions`. It does
not touch the account's key-protection profile or encrypted private-key bundle:
`key_envelopes_unchanged` is always `true`, because the encryption passphrase is
independent of the login password and the reset therefore never costs the account access to
its encrypted files.

The login password and encryption passphrase are independent. The API never accepts the
encryption passphrase. Login and password-change inputs are Unicode NFC-normalized; new
passwords must contain 8 to 128 characters from at least two character classes and pass local
common/account-derived checks
before Argon2id hashing.

Successful login data contains `user`, `access_token`, `refresh_token`, `token_type`,
`access_expires_at`, `refresh_expires_at`, and `session_id`. Access and refresh values are
independent opaque credentials; the server stores only their hashes. Refresh replay revokes
the complete session family.

`user` (in login and in `GET /auth/me`) carries `must_change_password`. It is `true` from an
administrator's `POST /admin/users/{user_id}/reset-password` until the holder sets a password
of their own through `POST /auth/change-password` or `POST /auth/password-reset`. While it is
set, the server refuses every authenticated route with `403 password_change_required` except
`GET /auth/me`, `POST /auth/change-password`, `POST /auth/logout` and `POST /auth/logout-all`
(`POST /auth/refresh` takes no bearer token, and the tokens it issues are held to the same
list). Delete-account is refused too. The frontend sends the holder to Settings from the flag,
and from any `password_change_required` answer, until the password is changed.

`POST /auth/delete-account` takes `password` on top of the bearer token, because it is the one
irreversible action in the API. The password check shares the change-password
re-authentication throttle: a wrong password counts against the `REAUTH_ACCOUNT` and
`REAUTH_IP` buckets, is audited as `ACCOUNT_DELETION_PASSWORD_FAILED`, and answers `422
invalid_current_password`; while a bucket is blocked the endpoint answers `429
auth_rate_limited` with `Retry-After` before any password is compared. The last active
administrator cannot close their account: the call answers `409 last_admin` until another
administrator account is active.

Email verification and forgotten-login-password reset are implemented on top of the emailed
one-time code above. MFA and external identity-provider login remain unimplemented.

Emailed codes are a recovery channel for the login password only. They can never restore a
forgotten encryption passphrase: the server holds no material that can open the AMK envelope,
so that loss stays unrecoverable by design.

## Account-Key API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/keys/me` | Bearer | Return caller's public key, KEK-wrapped AMK profile, and encrypted private-key bundle |
| GET | `/keys/me/{key_id}` | Bearer | Return an owned current or historical encrypted key bundle |
| POST | `/keys/me/rewrap/signing-payload` | Bearer | Build the canonical digest covering a complete proposed protection rewrap |
| POST | `/keys/me/rewrap` | Bearer + current-key signature | Replace the wrapped-AMK/KDF profile using optimistic revision and proof of current private-key possession |
| POST | `/keys/me/reset-protection/signing-payload` | Bearer | Build the canonical digest covering a new AMK envelope and a re-sealed private-key bundle |
| POST | `/keys/me/reset-protection` | Bearer + current-key signature | Reset a forgotten passphrase: replace both envelopes under a new AMK, proven by the private key file |
| POST | `/keys/add/signing-payload` | Bearer | Build the canonical digest that the current client key must authorize |
| POST | `/keys/add` | Bearer | Add a successor public/encrypted-private key using RSA-PSS-SHA256 current-key authorization |
| GET | `/keys/users/{user_id}/active` | Bearer | Return only a user's active public encryption key for sharing |
| GET | `/keys/users/by-identifier/{identifier}/active` | Bearer | The same key, addressed by exact username or email, so a sender can resolve a known recipient without browsing a directory |
| GET | `/keys/users/by-username/{username}/active` | Bearer | Deprecated compatibility alias for username-only clients |

Protection rewrap is a two-call proof-of-possession workflow. After unlocking the AMK and the
newest current private key locally, the client prepares `authorizing_key_id`,
`expected_revision`, and the complete proposed protection profile. It submits those unsigned
fields to `POST /keys/me/rewrap/signing-payload`, receives a canonical Base64-encoded 32-byte
SHA-256 digest, and signs it locally with RSA-PSS-SHA256. It then sends the exact same fields,
`authorization_algorithm`, and signature to `POST /keys/me/rewrap`.

The digest binds the actor UUID, newest current key UUID, protection-profile UUID, expected
revision, every KDF parameter, and the complete new wrapped-AMK AEAD envelope. The service
locks and rechecks the profile revision/current key and verifies the signature before updating
the profile and audit chain atomically. A bearer session or expected revision alone is
insufficient. Neither endpoint accepts either passphrase, and the encrypted private-key
bundle is not replaced. Stale revisions, stale authorizing keys, modified proposed fields,
and invalid signatures fail closed.

Passphrase reset follows the same two-call shape for the case rewrap cannot cover: the
passphrase is forgotten, so the old AMK is unreachable, but the private key file from
registration is not. The client generates a new AMK, seals both the AMK envelope and the
private-key bundle afresh, and sends `authorizing_key_id`, `expected_profile_revision`,
`expected_bundle_revision`, `protection`, and `private_key_bundle` to
`POST /keys/me/reset-protection/signing-payload`. It signs the returned digest with the key
file and submits the same fields plus the signature to `POST /keys/me/reset-protection`. The
digest carries its own domain label (`FYP-KEY-PROTECTION-RESET`) and covers every field of
both envelopes. Both rows are updated in one transaction; the key pair, key id, profile id and
bundle id are unchanged. An account holding more than one key answers `409
key_protection_reset_unavailable`, because one AMK seals every bundle and one key file cannot
re-seal the others. The audit action is `KEY_PROTECTION_RESET_WITH_PRIVATE_KEY`.

Private-bundle, wrapped-AMK, nonce, tag, salt, and ciphertext fields use canonical Base64.
KDF algorithms, AEAD suites, key sizes, and envelope versions are closed enums/bounds in the
request schema; unknown fields are rejected.

Adding a successor key is a separate two-call client workflow. The client first submits the unsigned
addition fields, including current key/profile UUIDs and expected profile revision, to obtain
a deterministic 32-byte authorization payload. It signs that payload locally with the
current private key using RSA-PSS-SHA256, then submits the same fields plus signature to
`POST /keys/add`. The server verifies the signature with the newest current client public
key and atomically stores the successor public key and its client-encrypted private bundle.
Previous keys and their file wrappings are retained, so historical bundles remain retrievable.
The configured account key size (`USER_RSA_KEY_SIZE`, 3072 by default) must match registration
and successor-key inputs.

## File API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/files/upload` | Bearer | Store client-encrypted ciphertext and its versioned crypto envelope |
| GET | `/files` | Bearer | Page through files with an active grant and active user wrapping |
| GET | `/files/{file_id}` | Bearer | Get authorized metadata and caller-specific wrapped DEK |
| POST | `/files/{file_id}/download` | Bearer | Verify and stream stored ciphertext; never decrypt server-side |
| POST | `/files/{file_id}/delete` | Bearer owner | Soft-delete file, revoke access/wrappings, and remove object |
| POST | `/files/{file_id}/integrity-check` | Bearer | Recompute and record ciphertext-storage integrity |
| POST | `/files/{file_id}/ciphertext-preview` | Bearer, download capability | A fixed 128-byte sample of the stored ciphertext as hex, with the exact sizes and recorded SHA-256. Not verified (no full hash) and never decrypted; audited as `FILE_CIPHERTEXT_PREVIEWED`, which is not a download |
| GET | `/files/folders` | Bearer | List the caller's folders |
| POST | `/files/folders` | Bearer | Create a folder |
| POST | `/files/folders/{folder_id}/rename` | Bearer owner | Rename a folder |
| POST | `/files/folders/{folder_id}/delete` | Bearer owner | Delete a folder; its files move to "No folder", none is deleted |
| POST | `/files/{file_id}/move` | Bearer + file access | Place a file in one of the caller's folders (an owner's placement is on the file, a recipient's on their own grant) |

Upload is `multipart/form-data` with:

- `file`: the ciphertext under the suite named in `metadata.encryption_algorithm`
  (`AES-128-GCM`, `AES-192-GCM`, `AES-256-GCM` (default), `AES-256-GCM-SIV`,
  `ChaCha20-Poly1305` or `XChaCha20-Poly1305`). The 16-byte tag is supplied separately, so the
  ciphertext byte count must equal declared plaintext size. The nonce is 12 bytes, or 24 for
  XChaCha20-Poly1305.
- `metadata`: a JSON string containing file UUID, plaintext filename/size/MIME type,
  envelope/AAD versions, Base64 nonce/tag, owner key UUID and RSA-OAEP-SHA256-wrapped DEK,
  recovery key UUID and recovery-wrapped DEK, plus an optional Base64 encrypted manifest.

An active recovery key and matching recovery wrapping are currently required. The server
never accepts plaintext file data or a private key. `GET /files/{file_id}` provides the
authorized client's decryption envelope; download streams `application/octet-stream`
ciphertext with no-store headers.

Uploads are refused with a clear error when they would exceed the account's storage quota
(2 GiB) or rolling 24-hour upload allowance (5 GiB), or leave less free disk than the floor.

File-list pagination uses `page` and `page_size` (`1..100`). Unauthorized and nonexistent
file resources are intentionally indistinguishable.

## Sharing API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/files/{file_id}/share` | Bearer + SHARE | Create/reactivate an authorized, capability-attenuated target grant and client-prepared DEK wrapping |
| GET | `/files/{file_id}/shared-users` | Bearer + SHARE | List active grantees and their capabilities |
| POST | `/files/{file_id}/revoke` | Bearer + REVOKE | Revoke a non-owner user's grant and active wrappings |

The share request contains `target_user_id`, `target_key_id`, the target-public-key-wrapped
DEK, `can_download`, and `can_share`. The client performs unwrap/rewrap locally. The server
validates the target/key association and RSA ciphertext size, but never receives a private
key or plaintext DEK. Delegated capabilities are attenuated: neither requested capability may
be `true` unless the acting grant has the corresponding capability. The canonical owner grant
is immutable. An existing non-owner grant may be updated or reactivated only by an actor with
`can_manage`, or by the actor currently recorded as its `granted_by`; another delegated sharer
cannot overwrite it. Revocation cannot erase data already copied by the recipient.

## Audit API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/audit-logs` | Bearer | Return a scoped, redacted log page; ADMIN sees the administrative scope. Optional filters `action`, `result`, `from`, `to`, `q` narrow the caller's own scope |
| GET | `/audit-logs/file/{file_id}` | Bearer + file access | Return scoped logs for one file |
| POST | `/audit-logs/verify-chain` | ADMIN | Recompute the complete chain and verify its singleton head |

List endpoints use `limit` (`1..100`) and `offset`; returned metadata is allowlisted.
Verification is a read-only security command but intentionally uses `POST` under the
repository's application-method policy.

`GET /audit-logs` also accepts, all optional: `action` (one event type, exactly as the API
writes it, for example `FILE_SHARED`; any other value is a 422), `result` (`SUCCESS` or
`FAIL`), `from` and `to` (ISO 8601 instants in UTC, an inclusive window on `created_at`,
and `from` must not be later than `to`) and `q` (a keyword of at most 100 characters,
matched case-insensitively against the description and the name of the file the row is
about; `%` and `_` are literal). Filters only narrow: the visibility rule (your own actions,
actions on you, everything done to a file you own) is applied first and the filters on top,
so a filtered page is always a subset of the unfiltered one for the same caller. The response
keeps `limit`, `offset` and `has_more`; `offset + logs.length` asks for the next page.

## Recovery API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/recovery/public-key` | Bearer | Return the active recovery public key used by new uploads |
| POST | `/recovery/public-key/register` | ADMIN | Register/rotate an offline-custody recovery public key |
| POST | `/recovery/public-key/{key_id}/revoke` | ADMIN | Revoke a recovery public key for new use |
| POST | `/recovery/request` | Bearer | Create a time-bounded request while a live downloadable grant and user wrapping still exist |
| POST | `/recovery/{request_id}/approve` | ADMIN or RECOVERY_OFFICER | Approve a non-self request |
| POST | `/recovery/{request_id}/reject` | ADMIN or RECOVERY_OFFICER | Reject a non-self request with reason |
| POST | `/recovery/{request_id}/cancel` | Request owner | Cancel own pending or approved request |
| GET | `/recovery/{request_id}/execution-package` | ADMIN or RECOVERY_OFFICER | Return public data for isolated offline unwrap/rewrap |
| POST | `/recovery/{request_id}/execute` | ADMIN or RECOVERY_OFFICER | Store the offline-produced target-key-wrapped DEK |
| GET | `/recovery/requests` | Bearer | Page own requests; reviewer roles can page all requests |

No recovery endpoint accepts a private key or passphrase. The execution package includes
the recovery-wrapped DEK and public-key identities. An offline/HSM process unwraps the DEK
and returns only the requester-public-key-wrapped DEK. Request creation, every execution-package
read, and execution require the requester to still have an `ACTIVE`, `can_download` grant plus
an `ACTIVE` user wrapping backed by an active user key; owners are subject to the same rule.
Execution locks and rechecks that entitlement before changing any wrapping, validates UUIDs and
RSA ciphertext shape, and conditionally moves the request to `EXECUTED`. It never creates,
reactivates, elevates, or otherwise repairs a revoked or reduced grant. A package obtained and
cached before revocation cannot be clawed back, although later package reads and server-side
execution fail closed. Recovery does not reset the encryption passphrase or decrypt the
account's private-key bundle.

## Admin API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/admin/users` | ADMIN | Page user records; optional `status` = `ACTIVE`, `DISABLED`, `DELETED`, or `CURRENT` (everything not deleted) |
| GET | `/admin/files` | ADMIN | Page file metadata records; optional `status` = `ACTIVE`, `CORRUPTED`, `DELETED`, or `CURRENT` |
| GET | `/admin/stats` | ADMIN | Counts-only platform summary: users by status, files by status and algorithm, bytes stored, active shares, 24-hour integrity checks and failures, pending recovery requests, audit totals and the five newest failed events (action, time, actor only) |
| POST | `/admin/users/{user_id}/disable` | ADMIN | Soft-disable an account and revoke active sessions. Not for the caller's own account (`409`), and `409 last_admin` when it would leave no active administrator |
| POST | `/admin/users/{user_id}/enable` | ADMIN | Re-enable a disabled account |
| GET | `/admin/users/{user_id}` | ADMIN | One account: email and whether it is verified, role, status, created, last sign-in, password changed, and counts only (files, stored bytes, shares sent and received, sessions open). Never a password, hash or key |
| POST | `/admin/users/{user_id}/reset-password` | ADMIN | Set a new random login password, returned once (`no-store`); only its hash is stored. Signs the account out everywhere, marks it `must_change_password` until the holder sets their own, audits `ADMIN_PASSWORD_RESET` without the password and emails the holder. Not for the caller's own account or another administrator. The encryption passphrase and files are untouched |
| GET | `/admin/integrity` | ADMIN | Integrity tab: latest sweep result and damaged files |
| POST | `/admin/integrity/scan` | ADMIN | Run an integrity sweep now |
| GET | `/admin/agent/report` | ADMIN | The security agent's ranked findings (read-only, metadata only, rule-based) |

Admin list endpoints use `limit` (`1..100`) and `offset`. Status changes are conditional and
audited; hard deletion is not used for identities referenced by the audit chain.

## Contract Rules

- Routers declare strict request and response models; ORM objects never cross the boundary.
- Public resources use UUIDs; auto-increment database IDs remain internal.
- Collection endpoints have stable ordering and bounded pagination.
- Retriable state changes use UUID uniqueness, optimistic revisions, conditional transitions,
  or idempotent terminal-state handling as appropriate.
- Authentication and resource failures avoid revealing whether an inaccessible account,
  file, session, or key exists.
- Ciphertext and wrapped keys are intentionally transported. Plaintext private keys, AMKs,
  KEKs, DEKs, passphrases, token hashes, storage object keys, and filesystem paths are not.
