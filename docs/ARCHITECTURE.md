# Backend Architecture

English | [简体中文](ARCHITECTURE.zh-CN.md)

## Decision and Current Shape

The backend is a **modular monolith**: one deployable FastAPI application, one MySQL
database, and a local encrypted-object storage adapter with strict internal boundaries.
This fits the FYP scope while preserving explicit database, storage, cryptographic, and
identity seams. Microservices would add distributed transactions without improving the key-
custody boundary.

Authentication, client-wrapped account keys, encrypted files and folders, sharing, audit
queries, recovery, integrity checking, and administration (including counts-only statistics
and the security-agent report) are implemented vertical slices. The public API contains real
handlers for all of these modules.

## Dependency Direction

```text
HTTP router / dependency
          |
          v
application service (use-case transaction owner)
          |
          +----> repository / SQLAlchemy session
          +----> encrypted-object storage port
          +----> validation/crypto capability
          +----> domain policy and audit append
```

Rules:

1. Routers validate HTTP input, resolve an authenticated actor, call an application service,
   and map results to response DTOs. They contain no SQL, filesystem, or private-key logic.
2. Services coordinate use cases through constructor-injected dependencies; they do not
   create database sessions or infrastructure adapters internally.
3. A command owns one database transaction. Repositories may query, add, and `flush`, but do
   not `commit`. Authentication throttle evidence is the deliberate precondition exception:
   it commits separately so a rejected login/registration cannot roll back its own evidence.
4. ORM models are persistence models and never become public responses. Pydantic schemas are
   strict transport contracts and do not contain SQLAlchemy behavior.
5. Configuration and composition happen at `core/config.py` and `main.py`; modules do not
   depend on the process working directory.
6. Application HTTP operations use only `GET` and `POST`. Every state-changing action uses
   `POST` and an explicit command path where useful.

## Package Responsibilities

```text
backend/app/
|-- api/                 FastAPI routers, dependencies, error/response mapping
|   `-- v1/              Auth, keys, files and folders, sharing, audit, recovery, admin
|-- core/                Configuration, database/session factory, security primitives
|-- domain/              Trusted contexts, enums, domain inputs/results/errors
|-- models/              SQLAlchemy persistence models
|-- repositories/        Persistence operations without independent commits
|-- schemas/             Strict Pydantic transport DTOs
|-- services/            Use-case coordinators and capability services
`-- main.py              Application factory and composition root

backend/migrations/      Alembic authoring history for development/CI
database/mysql/          Reviewed administrator SQL for production delivery
backend/tests/
|-- unit/                Policy, validation, crypto, storage, and service tests
|-- api/                 HTTP contract/dependency-override tests
|-- integration/         MySQL, migration, repository, and storage tests
`-- e2e/                 Live API server and runner for the frontend live-backend suites
```

The request-scoped SQLAlchemy `Session` is the unit of work. Each service is responsible for
commit/rollback and appends its security event through the same session.

## Identity and Authorization Boundary

The session model uses independent high-entropy opaque credentials, not JWTs:

- Only an access-token SHA-256 hash is stored on the session row. A single dependency resolves
  it to an `ActorContext` containing trusted internal/public identity and session fields.
- Refresh tokens have separate hashes and monotonically increasing generations. A successful
  refresh consumes one generation and rotates both credentials. Replay revokes the entire
  session family; an absolute expiry prevents immortal sessions.
- Logout, logout-all, password change, administrative disable, and session limits revoke the
  appropriate server-side session families.

Login passwords use Unicode NFC normalization, an 8-to-128-character policy that requires at
least two character classes, local common and account-derived checks, and `pwdlib`'s recommended Argon2id hasher. Valid legacy bcrypt hashes
are upgraded on login. Unknown users still trigger dummy verification. MySQL-backed HMAC
account/IP buckets coordinate throttling across workers, while each worker separately bounds
concurrent memory-hard operations.

Every non-public endpoint requires a trusted actor. Role checks occur at the API/service edge;
resource checks use internal actor IDs inside the use case. File access always requires both:

1. an ACTIVE logical grant with the requested capability; and
2. an ACTIVE user-key wrapping for that user and file, tied to an ACTIVE user public key.

Missing and unauthorized files use the same public not-found behavior. ADMIN-only operations
are explicit. Recovery review is limited to ADMIN and RECOVERY_OFFICER, and a requester cannot
review their own request.

## Client-Side Account-Key Custody

The encryption passphrase never crosses the API boundary and is independent of the login
password. A trusted client generates its RSA key pair and AMK before registration:

```text
passphrase --Argon2id + random salt--> 256-bit KEK
KEK --AES-256-GCM--> wrapped 256-bit AMK
AMK --HKDF-SHA256--> private-key encryption key
private-key encryption key --AES-256-GCM--> encrypted PKCS8-DER RSA private key
```

Registration atomically stores the account, public RSA key/fingerprint, public KDF/AEAD
parameters, wrapped AMK, encrypted private-key bundle, and audit event. The backend validates
RSA type/size and envelope structure but never generates, receives, decrypts, or persists a
plaintext private key.

`GET /keys/me` returns the encrypted bundle to its owner. A passphrase change does not
re-encrypt the RSA private-key bundle, but replacing the KDF/wrapped-AMK profile requires more
than the bearer session and optimistic revision. The client first requests a canonical digest
for the complete proposal from `POST /keys/me/rewrap/signing-payload`, signs it locally with
the newest current private key using RSA-PSS-SHA256, and submits that signature to
`POST /keys/me/rewrap`. Sharing clients obtain a recipient's active public key through a
public-key-only endpoint.

The rewrap digest is domain-separated and length-prefixes variable data. It covers actor,
authorizing-key and profile UUIDs, expected revision, KDF suite/version/salt/cost parameters,
derived-key length, wrapping suite, wrapped AMK, nonce, tag, and AAD version. The service
locks the account profile and newest current client key before building/verifying the digest.
Revision/key changes and signature failure therefore reject the command; a successful update
and audit append share one transaction. The signing-payload endpoint returns only the 32-byte
digest and algorithm identifier, never plaintext key material.

Successor-key addition is likewise authorized by possession of the newest current private key, not by
the bearer session alone. The server constructs a length-prefixed canonical SHA-256 digest
covering actor, current key, profile/revision, new public key/fingerprint, and encrypted-bundle
fields; the client signs it with RSA-PSS-SHA256. The service verifies the signature before
storing the new public key and bundle. Existing keys remain available to decrypt historical
file wrappings, and an owner-scoped endpoint returns a requested historical encrypted bundle.
The newest active key is advertised for new sharing.

There is one account-level protection-profile row. All client-wrapped private-key bundles are
expected to remain under keys derived from that AMK; the server cannot cryptographically
prove this because it never learns the AMK. The successor-key flow is therefore rotation of
an RSA key under the existing AMK, not a safe new-AMK reset/versioning mechanism.

A **forgotten passphrase** is handled by a separate flow that does create a new AMK. At
registration the browser offers the account private key once as a plaintext PKCS#8 `.pem`
file. With that file and a signed-in session, the client builds a new AMK under a KEK from the
new passphrase, re-encrypts the same private key under it, signs a canonical digest of both
replacement envelopes with RSA-PSS-SHA256 (from
`POST /keys/me/reset-protection/signing-payload`), and submits them to
`POST /keys/me/reset-protection`. The key pair and every file wrapping are unchanged, so no
file is re-encrypted. A session alone cannot reset the passphrase; losing both the passphrase
and the key file makes the account's files unrecoverable (see
[SECURITY_FLOWS.md](SECURITY_FLOWS.md#passphrase-reset-with-the-private-key-file)). Changing a
passphrase the user still knows uses the same endpoint: the browser opens the key with the current
passphrase instead of reading the key file (#201). The browser-side `/keys/me/rewrap` path described
above remains in the API but is not what the Settings page calls.

This is a key-custody boundary, not proof against a malicious server. Stored KDF material
supports offline passphrase guessing after database theft, and clients need fingerprint/
revision pinning or an external trust anchor to detect malicious key substitution or rollback.

## Encrypted-Object and Transaction Boundary

Files are encrypted by the client before upload. Each file uses an independent random DEK and
one of six authenticated suites chosen per upload (AES-128/192/256-GCM, AES-256-GCM-SIV,
ChaCha20-Poly1305, XChaCha20-Poly1305; AES-256-GCM is the default), its nonce and detached
tag, a versioned envelope/AAD contract, an owner-public-key RSA-OAEP-SHA256
wrapping, and a recovery-public-key wrapping. The API accepts ciphertext plus those envelopes;
it never accepts file plaintext, a private key, or a plaintext DEK.

MySQL cannot atomically commit a local storage object. Upload therefore uses staging and
compensation:

1. validate public metadata, algorithm versions, key ownership, recovery key, and RSA
   ciphertext lengths;
2. stream bounded ciphertext to a random staging object while computing SHA-256;
3. build file metadata, owner grant, owner/recovery wrappings, and audit entry in one DB unit
   of work;
4. publish the staged object to an opaque final object key, then commit;
5. before COMMIT is attempted, failures roll back and best-effort delete staged/published
   objects; after COMMIT is sent, a connection failure has an ambiguous outcome, so the
   published object is preserved and reconciliation determines whether it is referenced or
   orphaned.

Database rows store opaque object keys, never host filesystem paths. The storage adapter
resolves and containment-checks those keys inside its configured root.

Uploads are also bounded per account: 2 GiB stored and 5 GiB uploaded per rolling 24 hours by
default (`USER_STORAGE_QUOTA_BYTES`, `USER_DAILY_UPLOAD_BYTES`), and all uploads are refused
when free disk would fall below a floor. Upload request handling keeps blocking database work
off the event loop, so slow bodies cannot exhaust the connection pool (#163).

Download does not decrypt. It requires grant plus wrapping, verifies the ciphertext hash, and
streams ciphertext. A separate metadata response gives the authorized client its nonce, tag,
wrapped DEK, algorithm versions, and optional encrypted manifest. Decryption and GCM
authentication happen on the client. The backend therefore verifies storage integrity but
cannot validate client-produced GCM semantics without learning the DEK.

Soft deletion durably marks the file and revokes grants/wrappings before idempotent storage
cleanup. Integrity checks recompute object hashes and append their result: every download is
verified, and a daily sweep (`mcs21-integrity-sweep.timer`) checks every stored object against
the digest anchored in the upload's audit event, so rewriting the database digest alone does
not hide a changed object. Damaged files appear on the administrator's Integrity tab and can be
restored from backup one file at a time (`backend/scripts/restore_file.py`).

## Sharing Boundary

The sender locally unlocks its account private key, unwraps the file DEK, retrieves the
recipient public key, and creates a new RSA-OAEP-SHA256 DEK wrapping. The service receives only
the target UUIDs, capabilities, and RSA ciphertext. It validates target/key association and
atomically creates or reactivates the logical grant, cryptographic wrapping, and audit event.
Requested capabilities are attenuated against the acting grant: a delegated sharer cannot
grant `can_download` or `can_share` unless it also holds that capability. The canonical owner
grant is immutable. Updating or reactivating an existing non-owner grant additionally requires
either `can_manage` on the acting grant or identity as that grant's current `granted_by`.

Revocation changes grant and active wrappings in the same transaction and cannot revoke the
canonical owner. It controls future server-mediated access; it cannot erase data that was
already copied.

## Recovery Boundary

An ADMIN registers recovery **public** keys. New registration rotates which key is active for
future uploads; existing recovery wrappings are not rewritten, so matching historical private
keys must remain securely available offline.

A request targets one of the requester's active user public keys and expires after a bounded
interval (24 hours by default). Creation requires a live `ACTIVE`, `can_download` grant and an
active user wrapping backed by an active user key, including when the requester is the owner.
An ADMIN or RECOVERY_OFFICER who is not the requester approves or rejects it. Each execution-
package read rechecks that same live entitlement before returning the recovery-wrapped DEK,
recovery public-key identity, and target user public key. An isolated offline/HSM process uses
the recovery private key to unwrap and immediately rewrap the DEK.

Execution follows the per-file lock order `File -> Grant/UserKey/Wrapping -> Request -> Audit`
and rechecks the live entitlement before any wrapping mutation. The API receives only the new
RSA ciphertext, creates or updates the target-key wrapping, and marks the request executed. It
does not create, reactivate, or elevate the logical grant, so a revoke or permission reduction
after approval cannot be undone by recovery. A package cached before revocation cannot be
clawed back; subsequent package reads and execution still fail closed.

No normal or recovery endpoint accepts a recovery private key. The application does not
decrypt during recovery. This workflow recovers a file wrapping; it does not reset an
encryption passphrase, decrypt the account private-key bundle, or create a replacement user
key. The current maker-checker rule separates requester from reviewer, but does not require
separate officers for approval and execution.

## Metadata and Threat Boundary

The server deliberately retains operational metadata: account identifiers, public keys and
fingerprints, KDF/envelope parameters, plaintext filename and MIME type, declared plaintext
and ciphertext sizes, timestamps, ownership/sharing graph, session IP/user-agent fields,
recovery state, and audit actions. Ciphertext size and traffic timing also leak information.
The optional encrypted manifest is opaque, but the present filename/MIME columns are not.

Accordingly, “zero knowledge” in this project means that the ordinary API does not learn
plaintext key material or file contents when a conforming client performs cryptography. It
does not mean anonymous metadata, defense against traffic analysis, or defense against an
actively malicious server able to substitute database objects and public keys.

## Audit Integrity

Security-sensitive mutations append to the hash chain in the same transaction. A singleton
`audit_chain_heads` row is locked with `SELECT ... FOR UPDATE`; it records the final log ID,
hash, and schema revision so concurrent transactions cannot fork the chain. Canonical
persisted `DATETIME(6)` values and `{}` metadata permit deterministic recomputation.

Audit reads are actor/file scoped and return allowlisted metadata; ADMIN may verify the full
chain and head. Restrictive identity foreign keys preserve hashed history, so account removal
is status-based. A database-local plain hash chain cannot prevent an administrator from
rewriting and recomputing all history, so staging also publishes an HMAC-authenticated
checkpoint of the chain head to external S3-compatible storage
(`backend/scripts/audit_checkpoint.py`, `mcs21-audit-checkpoint.timer`); the application
process never holds that HMAC key.

Transactions that MySQL aborts with a deadlock (1213) or lock-wait timeout (1205) are retried
from the start, up to three attempts (`app/core/db_retry.py`, #139).

## Schema and Delivery Rules

- ORM metadata and ordered Alembic revisions through `0011_must_change_password` are the
  development/CI schema-authoring authority.
- `database/mysql/02-schema.sql` is the reviewed production empty-database artifact derived
  from that authority; parity tests compare tables, columns, indexes, and constraints.
- The application never calls `create_all()` and never runs DDL at startup. `/health/ready`
  verifies connectivity and exact expected revision but does not migrate.
- Production installation remains
  `01-provision.sql -> 02-schema.sql -> 03-verify.sql -> fyp_user`; the runtime identity has no
  migration privileges.
- A non-empty deployment requires a separately reviewed, versioned DBA upgrade with writer
  drain, serialization, verified backup, and release-specific verification.
- MySQL-specific integration tests use MySQL 8.4 rather than SQLite substitutes.

## Definition of Done for a Use Case

A use case is complete only with:

- strict request/response schemas and no plaintext secret/internal fields;
- authentication, role, and resource policy;
- a named transaction owner and rollback/compensation behavior;
- stable errors and same-transaction audit events;
- bounded storage and pagination behavior where applicable; and
- unit/API/integration coverage for success, denial, conflict, and relevant retry paths.
