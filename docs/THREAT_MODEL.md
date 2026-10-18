# Threat Model

English | [简体中文](THREAT_MODEL.zh-CN.md)

| | |
|---|---|
| Version | 1.6, 2026-10-09. Issue #60 complete as v1.0 (supply chain, CSP, uploads, tokens and recovery operations §11; findings register §12; review record §13); register statuses refreshed on 2026-10-01 and 2026-10-08; see §14 for every revision |
| Tracks | [Issue #60](https://github.com/jsonrar/fyp-secure-file-platform/issues/60) |
| Status | **Self-assessment.** Written by the crypto & security lead, who also implemented much of the cryptography it assesses. It is not an independent review and certifies nothing. |
| Reflects | `main` at `c3569c8` (2026-10-09), schema revision `0011_must_change_password`, staging at `https://secureview.tech`. Register statuses rechecked 2026-10-07 against `e4b3f13`, and F-08 on 2026-10-09 |

This document states what SecureView protects, from whom, where the trust boundaries lie, and
which threats each boundary does and does not stop. It consolidates controls that are
specified in detail elsewhere rather than restating them; each row links to the document or
code that is the source of truth. Where a control is claimed, the claim was checked against
the code or the live deployment, not assumed.

**Reading the status column.** *Mitigated* means a control exists and was verified.
*Partial* means a control exists but leaves a named gap. *Accepted* means the risk is known and
deliberately carried at FYP scope. *Open* means it is a finding to be resolved.

**Implemented is not deployed.** A control that exists in the repository but whose operation on
staging has not been verified is never marked *Mitigated*; the row says which half is missing.
The staging evidence tables in
[OBSERVABILITY § 8](OBSERVABILITY_AND_INCIDENT_RESPONSE.md#8-staging-evidence-record) and
[BACKUP_AND_RECOVERY](BACKUP_AND_RECOVERY.md#staging-installation-record-2026-09-24) are the
record this document checks against.

---

## 1. System in one paragraph

A Vue single-page app in the browser performs all file and account-key cryptography. It
encrypts each file under a fresh data encryption key (DEK), wraps that DEK to the owner's RSA
public key and to an offline recovery public key, and uploads only ciphertext. The account
private key is sealed in the browser under a key derived from an encryption passphrase that
never leaves the browser. A FastAPI backend behind nginx authenticates sessions, stores
ciphertext on local disk and envelopes in MySQL 8.4, enforces sharing and recovery policy, and
appends every security-sensitive change to a hash-chained audit log. Everything runs on one
VPS. See [ARCHITECTURE.md](ARCHITECTURE.md) and [SECURITY_FLOWS.md](SECURITY_FLOWS.md).

## 2. Security objectives

| # | Objective |
|---|---|
| O1 | Under the trusted client-code and API-boundary model, the backend, database and storage never hold the plaintext material needed to read file contents or unwrap a DEK — so compromising or stealing them yields no plaintext. This does **not** extend to an operator who replaces the client code (N1). |
| O2 | A file's content and the metadata bound into its AAD cannot be altered undetected. |
| O3 | Only the owner, current grantees, and an approved recovery can obtain a file's key. |
| O4 | A stolen server-side session alone cannot read files or seize the account's key custody. |
| O5 | Security-relevant actions are recorded in a log whose silent rewriting is detectable. |
| O6 | A forgotten *login password* is recoverable; a forgotten *encryption passphrase* is recoverable only by whoever holds the account's private key file. |

## 3. Explicit non-goals

These are out of scope by design. Stating them is part of the model: a reviewer should not
credit the system with protections it does not claim.

| # | Non-goal | Why |
|---|---|---|
| N1 | Protection from an **actively malicious server** that serves substituted code, keys, or ciphertext. | The browser runs JavaScript the server delivers. A server willing to ship hostile code can exfiltrate the passphrase. Zero-knowledge holds at the **API boundary**, not against the code supplier. See [SECURITY_FLOWS.md § Metadata Leakage](SECURITY_FLOWS.md#metadata-leakage-and-threat-limits). |
| N2 | Confidentiality of **file metadata**: filename, MIME type, size, timestamps, ownership, sharing graph. | Stored in cleartext columns so the server can list, search and enforce policy. Filename, MIME type and plaintext size are bound into AAD-3, so altering them is detected at decryption; timestamps, ownership and the sharing graph are cleartext, server-controlled, and not covered by any file tag. Decided in [§10.3](#103-metadata-and-traffic-leakage). |
| N3 | Anonymity and resistance to **traffic analysis**. | Access timing, IP addresses and ciphertext sizes are visible to the server and the network. |
| N4 | Protection of a **compromised endpoint**: malware, a malicious browser extension, or someone at the unlocked keyboard. | Whatever can read the page can read what the user decrypts. |
| N5 | **Retracting** plaintext or keys a recipient already obtained. | Revocation stops future server-mediated access; it cannot erase a download or a DEK already unwrapped. |
| N6 | Recovering a forgotten encryption passphrase **without** the private key file. | The server holds nothing that opens the AMK envelope. This is the price of O1. |
| N7 | High availability, geographic redundancy, and certification against any standard. | FYP scope, one VPS. |

## 4. Assets

| ID | Asset | Where it exists | Impact if disclosed | Impact if altered or lost |
|---|---|---|---|---|
| A1 | File plaintext | User's browser memory only, transiently | Total loss of confidentiality for that file | — |
| A2 | File DEK | Browser memory; stored only RSA-wrapped (`file_key_wrappings`) | Opens that one file | File unrecoverable |
| A3 | Encryption passphrase | User's head; browser memory during unlock | With the database, opens the account private key | O6 limits apply |
| A4 | Account master key (AMK) | Browser memory during unlock; stored only wrapped under the KEK | Opens the private-key bundle | Account locked out |
| A4a | Key-encryption key (KEK) | Derived from the passphrase with Argon2id each unlock; browser memory only; **never persisted** | Opens the stored wrapped AMK | Nothing to lose: re-derived from the passphrase |
| A5 | Account private key (RSA-3072) | Plaintext PEM exported once at registration; sealed bundle in DB; non-extractable `CryptoKey` while unlocked | Opens every file wrapped to the account | Files wrapped only to it are lost |
| A6 | Recovery private key | **Intended:** offline, per the *proposed* custody in [BACKUP_AND_RECOVERY.md § 7](BACKUP_AND_RECOVERY.md#7-recovery-key-custody). **Staging today:** an unencrypted PEM on a team member's workstation (T-I8) | Opens **every** file's recovery wrapping | Recovery impossible for files wrapped to it |
| A7 | Login password | User's head; Argon2id hash in DB | Account takeover of the server-side session | Resettable by email (O6) |
| A8 | Access and refresh tokens | Browser `localStorage`; SHA-256 hashes in DB | Session takeover until expiry or revocation | Re-login |
| A9 | Ciphertext objects | VPS disk, mode-0700 directory owned by the service user; encrypted backups | Nothing without A2 | Integrity failure; restore from backup |
| A10 | File metadata and sharing graph | MySQL cleartext columns | Privacy loss (N2) | Detected at decryption for AAD-bound fields; not for the rest |
| A11 | Audit log and chain head | MySQL. HMAC-authenticated external checkpoints are published hourly from staging; one was downloaded and verified on a separate machine (F-10, T-T6) | Reveals activity | Tampering must be detectable (O5) |
| A12 | Server secrets: `SECRET_KEY`, DB credentials, email API key, audit-checkpoint HMAC key | VPS protected environment and root-only files | Forged verification codes, DB access, mail abuse, forged checkpoints | Outage |
| A13 | Backup private key | Intended: offline, under the same proposed custody as A6. Its current location is not recorded in the staging installation record | Opens every backup set | Backups unreadable |
| A14 | Deployed code | GitHub `main`, pulled to the VPS by a read-only deploy key | See N1: whoever controls it controls A3 | — |

## 5. Actors and adversaries

| ID | Actor | Legitimate capability | Must not be able to |
|---|---|---|---|
| U1 | Anonymous internet user | Register, request a verification code, log in | Brute-force logins, reach any file, enumerate accounts by email (T-S2; usernames are public; a signed-in account can look one up to share with it, T-S2a) |
| U2 | Authenticated USER | Upload, download, share and revoke own files; request recovery for own key | Read others' files or metadata; escalate role |
| U3 | Share recipient | Decrypt files shared to them while the grant is live | Re-share without `can_share`; keep server-mediated access after revocation |
| U4 | RECOVERY_OFFICER | Approve or reject recovery requests; run offline rewrap | Approve their own request; obtain a file DEK online; read plaintext |
| U5 | ADMIN | Register recovery keys, verify the audit chain, manage roles | Read file contents or users' private keys |
| X1 | Network attacker | Observe and modify traffic between browser and nginx | Read or alter anything under TLS (HSTS, `includeSubDomains`) |
| X2 | Holder of a stolen session token | Act as the user against the API until revoked | Read files (needs A3 or A5); replace key envelopes (needs A5 — see T-E3) |
| X3 | Database or disk thief (dump, backup leak, disk image) | Read every row and object | Read files (O1); only offline passphrase guessing against A3 remains |
| X4 | Malicious or compromised server operator | Everything X3 can, plus modify stored data and **the code served to browsers** | Covered only up to N1 |
| X5 | Supply-chain attacker | Publish a malicious version of a dependency or push to `main` | See T-T5 and T-E5 |
| X6 | Insider on the team with repository write access | Merge to `main`, which auto-deploys | Bypass review (currently possible — T-E5) |
| X7 | Malicious recipient | Everything U3 can | Anything beyond N5 |
| X8 | **Data writer without code control:** a compromised backend process, a leaked runtime database credential, or an injection flaw | Read and **rewrite any database row** — public keys, recovery keys, bundles, grants. It **cannot** change the code browsers run: the release tree is owned by `mcs21-deploy`, world-readable only, and served by nginx, while the backend runs as `fypapp` | Read files (O1 still holds); see §10.2 for what rewriting public keys gains it |

## 6. Trust boundaries

```text
            TB1 (TLS)              TB2 (loopback)          TB3 (TLS, required)
[Browser] ────────────> [nginx] ──────────────> [FastAPI] ─────────────────> [MySQL 8.4]
   │  TB0: plaintext,               │                │ TB4 (fs, 0700)
   │  keys, passphrase stay here    │                └───────────────> [ciphertext on disk]
   │                                │                │ TB5 (HTTPS)
   │                                │                └───────────────> [email provider]
   │                         TB6: GitHub main ── read-only deploy key ──> [VPS release]
   │                         TB7: backups and audit checkpoints ──> [off-server storage]
   └── TB8: recovery and backup private keys — intended offline; see A6 for staging today
```

| ID | Boundary | What crosses it | Principal control |
|---|---|---|---|
| TB0 | Inside the browser vs. everything else | **Stays client-side:** file plaintext, the encryption passphrase, AMK, KEK, plaintext private keys and DEKs. **Crosses to the API:** ciphertext, wrapped keys, public keys and signatures, and also login passwords, verification codes, bearer and refresh tokens, usernames and emails, and cleartext metadata — filenames, MIME types, sizes | All secret-bearing *cryptography* is client-side; authentication secrets do cross, under TLS. [SECURITY_FLOWS.md](SECURITY_FLOWS.md) |
| TB1 | Browser ↔ nginx | Everything the API carries | TLS; HSTS one year with `includeSubDomains`; port 80 redirects with 308 |
| TB2 | nginx ↔ FastAPI | Proxied requests | Configured to bind `127.0.0.1:8000` with trusted proxy `forwarded-allow-ips=127.0.0.1`; the live bind check is still pending in OBSERVABILITY § 8 |
| TB3 | FastAPI ↔ MySQL | Envelopes, metadata, audit rows | `require_secure_transport=1`; least-privilege runtime account with no DDL |
| TB4 | FastAPI ↔ object storage | Ciphertext | Service user owns a mode-0700 root; SHA-256 recorded at upload and checked at download |
| TB5 | FastAPI ↔ email provider | Verification codes to user addresses | HTTPS API; codes stored only as HMAC digests |
| TB6 | GitHub ↔ VPS | Release code | Read-only deploy key; release gate with database verification and quarantine |
| TB7 | VPS ↔ off-server storage | Encrypted backups, HMAC checkpoints | Backup host holds only a public key (installed and running on staging). A 30-day bucket lock is part of the design, but the staging installation record does not verify it. HMAC checkpoints are uploaded hourly from staging, and one was verified off the host (F-10) |
| TB8 | Networked systems ↔ offline custody | Recovery and backup private keys | Procedural only, and not yet in effect on staging (A6). What *is* enforced in code: no endpoint accepts a recovery private key |

## 7. STRIDE analysis

Each threat has a stable ID; §12 collects every open, accepted or deferred one into the findings register.

### 7.1 Spoofing

| ID | Threat | Control | Status |
|---|---|---|---|
| T-S1 | Password guessing against login | Argon2id hashes; per-account and per-IP throttles in `auth_login_throttles` (10 failures per account, 500 per address); nginx `secureview_auth` at 60 credential checks per minute per IP; fail2ban after 60 rejected credentials in ten minutes (§11.6) | Mitigated |
| T-S2 | Account enumeration through registration, code sending or password reset | Code sending and password reset answer identically whether or not the account exists, and spend the allowance either way | Mitigated 2026-10-09: `POST /auth/register` now consumes the verification code before looking at the email, and a registered address answers the same `422 invalid_verification_code` as a wrong code. Only a taken username is reported (`409`, before the code), and usernames are public because sharing resolves them. → F-08 |
| T-S2a | A signed-in account looks another account up by email or username | Sharing needs to find the recipient, so `GET /keys/users/by-identifier/{identifier}/active` (and its deprecated `by-username` alias) resolves an exact username or email: no prefix or substring search, and no listing. It needs a signed-in session; nginx limits each address to 30 API requests a second, burst 60 (§11.6); and it returns only the user id and the active public key (key id, algorithm, size, PEM, fingerprint, creation time), never the email, the username or anything else about the account. A disabled or deleted account, or one without an active key, answers the same `404` as no account | Accepted 2026-10-09: intentional, because a sender knows a colleague's email or username, not their id. Any registered user can still learn whether an address has an account, one guess at a time. → F-21 |
| T-S3 | Session hijack by token theft | Tokens stored only as SHA-256; access 30 min, refresh 7 days, absolute 7 days; a replayed refresh token revokes the whole session family (`AUTH_REFRESH_REPLAY_DETECTED`) | Partial — see T-I4 for where tokens are kept |
| T-S4 | Substituted **recovery public key**, so every future upload is wrapped to an attacker | Browser recomputes the fingerprint from the PEM and displays it; the API's own fingerprint field is never trusted | Accepted at FYP scope — [§10.2](#102-public-key-identity-rollback-and-the-trust-anchor). The highest-impact of the three substitutions, and the first to fix if the project continues. |
| T-S5 | Substituted **recipient public key** during sharing | Recipient resolved by exact username or email; the browser wraps the DEK to whatever `public_key_pem` the API returns | **Mitigated against X8** (2026-10-04, PR #160) — [§10.2](#102-public-key-identity-rollback-and-the-trust-anchor). The share dialog recomputes the recipient's fingerprint from the PEM, refuses a key whose stated fingerprint disagrees, shows it for the sender to confirm and compare with the recipient's Settings, wraps to exactly the confirmed key, and pins it on the sender's device (trust on first use), warning when it later changes. Still open: a first share on a new device trusts the first key, the comparison is the sender's choice, and against X4 (N1) nothing in the browser helps. |
| T-S6 | Forged emailed verification code | 10-minute TTL, attempt limit, HMAC digest keyed by `SECRET_KEY`, purpose and address | Mitigated |
| T-S7 | Substituted **owner public key** during upload, so the owner's own wrapping goes to an attacker | The browser takes the owner key from `GET /keys/me` and wraps the DEK to it | Accepted at FYP scope — [§10.2](#102-public-key-identity-rollback-and-the-trust-anchor). Detected, late, when the owner first fails to open a new file. |
| T-S8 | Someone who saw the temporary password from an administrator's reset goes on using the account | The reset password is random, shown once to the administrator, ends every session of the account and emails the holder. Until the holder sets their own, `users.must_change_password` is enforced by the server (since 2026-10-09): `get_current_actor` answers `403 password_change_required` to every authenticated route except `GET /auth/me`, `POST /auth/change-password`, `POST /auth/logout` and `POST /auth/logout-all`. #212 had enforced it only in the frontend guard, which any other API client could ignore. An administrator cannot reset their own password or another administrator's | Partial: whoever holds the temporary password can still be the one who sets the new password, and the account is then theirs; the holder's only signal is the reset email and a password that no longer works |

### 7.2 Tampering

| ID | Threat | Control | Status |
|---|---|---|---|
| T-T1 | Altering ciphertext at rest or in transit | AEAD tag; the server also verifies SHA-256 before serving | Mitigated |
| T-T1a | Altering a stored object **and** the `files.encrypted_sha256` column so they agree | The upload's audit row records the ciphertext SHA-256 in the hash chain; every check and download compares against it too. A daily sweep (`scripts/integrity_sweep.py`) finds tampering with files nobody opens. `scripts/restore_file.py` puts the original back from an encrypted backup ([BACKUP_AND_RECOVERY.md §9](BACKUP_AND_RECOVERY.md)) | Mitigated for files uploaded since the digest was recorded; older files fall back to the column. A file newer than the last nightly backup cannot be restored. The sweep timer runs daily at 05:30 on staging (checked 2026-10-09). |
| T-T2 | Relabelling a file's name, MIME type, size or algorithm | All bound into AAD-3; any change fails authentication ([FILE_ENVELOPE.md](crypto/FILE_ENVELOPE.md)) | Mitigated |
| T-T3 | Replacing a user's key envelopes with garbage to lock them out | Rewrap, key addition and passphrase reset all require an RSA-PSS signature by the account private key, each under its own domain label | Mitigated |
| T-T4 | **Rolling back** a key bundle, protection profile or file to an earlier valid version | Optimistic revisions stop concurrent writers; files are immutable and AAD-3 binds `file_id`, so one file cannot be served as another | Accepted at FYP scope — [§10.2](#102-public-key-identity-rollback-and-the-trust-anchor). The dangerous case, re-activating a retired public key, is the substitution case again. |
| T-T5 | Malicious dependency version | Lockfiles; `@noble/ciphers` chosen for zero transitive dependencies | Partial — no provenance or audit gate. → F-12 |
| T-T6 | Rewriting the audit log consistently | Hash chain in the database; external HMAC-authenticated chain-head checkpoints implemented in `backend/scripts/audit_checkpoint.py`, with the HMAC key never given to the backend | Partial — the hash chain is live, and the external checkpoints have been published hourly from staging since 2026-09-25, when one was verified on a separate machine (F-10, Issue #59). A checkpoint only covers rows written before it was taken. |
| T-T7 | Tampering with an execution package during offline recovery | Server rechecks identities, lengths and the live grant before accepting the rewrap | Partial — the offline workstation is procedural (TB8) |

### 7.3 Repudiation

| ID | Threat | Control | Status |
|---|---|---|---|
| T-R1 | A user denies having shared, requested a download of, or reset | Every such action appends an audit event with actor, target, IP and user agent in the same transaction | Mitigated for what is recorded. A download is recorded as `FILE_DOWNLOAD_AUTHORIZED` when the server authorizes the request and has verified the ciphertext, **before** streaming it. That is evidence of an authorized request, not proof that the client received the whole stream or decrypted it. |
| T-R2 | An operator denies altering records | External HMAC checkpoints (T-T6), operating on staging since 2026-09-25 (F-10) | Partial — they cover the chain head, not who ran what on the host |
| T-R3 | A recovery officer denies approving or executing | Approval and execution are separate audited events; a requester cannot review their own request | Partial — one officer may both approve and execute ([SECURITY_FLOWS.md § Offline Recovery](SECURITY_FLOWS.md#offline-recovery-boundary)) |

### 7.4 Information disclosure

| ID | Threat | Control | Status |
|---|---|---|---|
| T-I1 | Database or disk theft exposes file contents | Nothing on the server opens a DEK (O1) | Mitigated |
| T-I2 | Database theft enables **offline passphrase guessing** | Argon2id at 64 MiB and 3 iterations; minimum 10 characters | Partial — measured in [§9](#9-argon2id-cost-and-the-passphrase-minimum): the KDF cost is adequate, but the length-only check admits passphrases that fall in minutes. |
| T-I3 | Metadata leakage: filenames, sizes, sharing graph | None beyond access control | Accepted — decided in [§10.3](#103-metadata-and-traffic-leakage), where the encrypted manifest was declined. → F-17 |
| T-I4 | **XSS steals tokens** from `localStorage` | CSP `script-src 'self' 'wasm-unsafe-eval'`, `object-src 'none'`, `frame-ancestors 'none'`. Vue escapes interpolation; the only two `v-html` sinks render bundled content — the logo SVG and the static knowledge-base articles, which `render-knowledge-content.ts` escapes before formatting — so no user- or server-supplied string reaches them today. | Partial — any future XSS reads both tokens. It still cannot extract the private key: it is held as a non-extractable `CryptoKey` and relocks after 15 idle minutes. It *can* use the key to decrypt while it is unlocked. |
| T-I5 | Secrets in logs | Documented exclusion list; `repr=False` on secret fields; [OBSERVABILITY § 7](OBSERVABILITY_AND_INCIDENT_RESPONSE.md#7-verification-that-sensitive-data-stays-out) | Partial — controls are in code; the live check that redaction markers are absent from staging outputs is still pending in OBSERVABILITY § 8 |
| T-I6 | **Public API documentation on staging** | `/docs`, `/redoc` and `/openapi.json` answer `200` on `https://secureview.tech`, and those locations use a relaxed CSP that loads script from `cdn.jsdelivr.net` | Open — **Medium**, raised from low in §11.2: the relaxed CSP loads a floating, unpinned third-party script on the origin that stores tokens. → F-03 |
| T-I7 | The plaintext PEM export is mishandled by the user | Shown once with a warning; read locally and never uploaded when used | Accepted — custody decided in [§10.1](#101-the-exported-private-key-and-the-limits-of-a-lost-passphrase) |
| T-I8 | Recovery private key exposure | Custody procedure in [BACKUP_AND_RECOVERY.md § 7](BACKUP_AND_RECOVERY.md#7-recovery-key-custody) | Open — the procedure is marked *proposed*, and the current staging recovery key is held as an unencrypted PEM on a team member's workstation, not offline. → F-02 |
| T-I9 | A share recipient keeps what they downloaded | — | Accepted (N5) |
| T-I10 | The **Encrypted preview** shows the first 128 bytes of a file's ciphertext, which could look like it helps an attacker | The preview is only shown to the owner and to people the file is shared with, and it shows what the server already stores: "Download encrypted file" gives the whole ciphertext anyway | Accepted, no change. AES-GCM and the other suites are designed to stay secure when an attacker sees all of the ciphertext, so seeing 128 bytes (8 rows) does not make breaking a file any easier. What protects the file is the key, which never leaves the browser unwrapped. Decided after the 2026-10-09 supervisor meeting |

### 7.5 Denial of service

| ID | Threat | Control | Status |
|---|---|---|---|
| T-D1 | Request flooding | nginx `secureview_api` at 30 requests per second per IP, burst 60 (sized for a venue network that arrives as one address, §11.6) | Partial — per-IP only |
| T-D2 | Upload abuse filling the disk | 500 MiB per upload; per-account 2 GiB storage and 5 GiB per 24 h; uploads refused below a free-disk floor; 50 uploads in flight per IP in nginx; `UPLOAD_BURST` agent rule; 85 % filesystem alert | Mitigated — one account can no longer fill the disk; many accounts still could, slowly, and registration is gated by email verification. → F-09 |
| T-D3 | Very large uploads exhaust the **browser** | — | Accepted — the in-memory design peaks near four times the file size; owned by the upload work, not this model → F-19 |
| T-D4 | Lock-out by envelope overwrite | See T-T3 | Mitigated |
| T-D5 | The platform loses its last active administrator | No route appoints an administrator. Closing your own account, and disabling an administrator, are refused with `409 last_admin` when no other administrator would stay active. Both lock the administrator rows in id order first, so two such requests cannot each count the other as the one who stays. An administrator still cannot disable themselves | Mitigated 2026-10-09 |

### 7.6 Elevation of privilege

| ID | Threat | Control | Status |
|---|---|---|---|
| T-E1 | A USER reaches ADMIN or RECOVERY_OFFICER routes | Admin and recovery routes depend on the role guards in `app/api/dependencies.py` (ADMIN, or ADMIN/RECOVERY_OFFICER) | Mitigated |
| T-E2 | A recipient re-shares without permission | `can_share` checked server-side | Mitigated |
| T-E3 | A stolen session seizes key custody (e.g. resets the passphrase) | Reset requires a signature by the private key, not a session | Mitigated |
| T-E4 | A requester self-approves recovery | Requester ≠ reviewer enforced by a database CHECK | Mitigated |
| T-E5 | Code reaches production without review | CI runs on every pull request and on every push to `main`; since 2026-10-01 the server deploys only commits CI has promoted | Mitigated — `main` still has **no branch protection** (unavailable on this plan), so a direct push bypasses PR review, but deployment now waits for every CI job to pass on that commit. `mcs21-deploy all main` bypasses the gate by design. → F-01 |
| T-E6 | Running application reaches the host | Unprivileged `fypapp` service user; loopback-only binding | Partial — no container or systemd sandboxing is claimed here |

## 8. Abuse cases

Worked end-to-end, each names the threats it chains.

1. **Stolen laptop session.** X2 opens the site with a live token. They can list files and
   metadata (T-I3) but cannot decrypt without the passphrase or key file, and cannot reset the
   passphrase without the key file (T-E3). *Residual:* metadata exposure until the session
   expires or is revoked.
2. **Leaked database dump.** X3 has every envelope. Files are safe (T-I1). The attacker runs an
   offline dictionary against each account's Argon2id envelope (T-I2). *Residual:* weak
   passphrases fall; strong ones do not. §9 quantifies both: a leaked-list passphrase falls in
   under two days on one laptop, four random words survive a million of them for about two years.
3. **Swapped recovery key.** X4 registers its own recovery public key. Every later upload
   wraps its DEK to X4 (T-S4). The upload page shows a different fingerprint, but only a user
   who compares it out of band notices. *Residual:* high impact, detection depends on the user.
4. **XSS in a future feature.** A script injection bypasses Vue escaping. It reads both tokens
   (T-I4) and, if the key is unlocked, decrypts whatever it asks for. It cannot export the
   private key. *Residual:* depends on the CSP holding.
5. **Unreviewed push.** A collaborator's machine is compromised and pushes to `main` (T-E5).
   Auto-deploy ships it; the code can capture passphrases (N1). *Residual:* the whole model
   rests on `main` being trustworthy.
6. **Revoked recipient.** X7 downloaded a file before revocation. They keep it (T-I9, N5).
   Revocation works as designed and cannot do more.

## 9. Argon2id cost and the passphrase minimum

Issue #60 criterion 2. The question is whether the enrolled KDF cost and the 10-character
passphrase minimum together make threat T-I2 — offline guessing after database theft —
acceptable, and what a user pays for it at unlock.

### 9.1 Method

- **Defender side.** `/benchmark/argon2` runs the production `deriveKek` — the same function,
  hash-wasm 4.12.0 build and parameters the unlock dialog uses — once untimed to warm up
  WebAssembly, then five timed runs per configuration with a fresh random salt each time. Run
  on a local production build (`vite preview`), which executes the same bundle as staging.
- **Attacker side.** `backend/scripts/benchmark_argon2_offline.py` runs argon2-cffi, the native
  C reference implementation, at the same parameters on one core and then on every core.
- **Same function.** The `argon2id_kek` vectors in
  [`test_vectors.json`](crypto/test_vectors.json) are generated by argon2-cffi and reproduced byte
  for byte by the browser's `deriveKek`, so the attacker figures apply to real envelopes rather
  than to a lookalike.
- **Raw data** is kept in [`benchmarks/argon2id-2026-09-30.json`](benchmarks/argon2id-2026-09-30.json).

### 9.2 What an unlock costs the user

Median of five runs, 2026-09-30.

| Cost | Chrome 153, macOS | Safari 18.6, macOS | iOS 26.6 (Quark, WebKit) |
|---|---|---|---|
| **64 MiB, t=3 (production)** | **100 ms** | **106 ms** | **151 ms** |
| 64 MiB, t=6 | 195 ms | 205 ms | 269 ms |
| 128 MiB, t=3 | 206 ms | 1 327 ms ⚠ | 268 ms |
| 256 MiB, t=3 | 426 ms | 433 ms | 555 ms |

The production cost is **0.10–0.15 s** on every client tested, and an unlock happens once for every
decrypted download and every share. The opened key lives only in page memory and is dropped as soon as that one operation
ends. The user-facing cost of the current setting is negligible.

Notes on the data, stated rather than smoothed:

- **Coverage is thin.** Two desktop engines on one Apple Silicon Mac and one iPhone. **No Android
  device, no Firefox, and no low-end or older hardware were measured**, and those are where
  Argon2id is slowest. The project has never declared which clients it supports, so "supported
  clients" is defined here as the tested set, and the gap is carried to the findings register.
- **Safari at 128 MiB is anomalous.** It took 1.3 s in all five runs, six times slower than the
  same browser at 256 MiB. It is not explained. It does not affect the production cost, but it
  must be reproduced before any change to 128 MiB.
- Every iOS browser is WebKit, so the Quark result approximates iOS Safari. The macOS user-agent
  strings say "Intel" because browsers freeze that string; the machine is Apple Silicon.

### 9.3 The parameters against published guidance

- **RFC 9106 §4, second recommended option:** Argon2id, t=3, p=4, m=64 MiB, 128-bit salt, 256-bit
  tag. SecureView matches it — 16-byte salt, 32-byte output — except for p=1. hash-wasm computes lanes one after another on a single thread, so four lanes
  would cost the defender the same wall time for the same memory and passes. p=1 is the honest
  setting for this implementation.
- **OWASP Password Storage Cheat Sheet minimum:** m=19 MiB, t=2, p=1. Exceeded.
- **The server's bounds** (`KeyProtectionProfileIn`) accept 64 MiB–1 GiB, 1–10 iterations and 1–16
  lanes, so raising the cost needs no backend change.

### 9.4 What guessing costs an attacker

One 10-core Apple Silicon laptop runs **52.8–58.3 guesses per second** across all cores, and 11
per second on one core. Ten cores buy only a 5.3× speedup because each guess occupies 64 MiB and
memory bandwidth, not core count, is the limit. The table uses **60 per second**, rounded in the
attacker's favour.

The multipliers are assumptions, not measurements. This document makes no claim about GPU or
ASIC throughput against Argon2id. A larger multiplier shortens every row proportionally.

Each account has its own salt, so every figure is **per account**.

| Passphrase | 1 laptop | 1 000 × | 1 000 000 × |
|---|---|---|---|
| In the first 10 000 of any guessing list (`aaaaaaaaaa`, `password12`, `qwertyuiop`) | 2.8 minutes | 0.2 s | instant |
| Anywhere in a 10-million-entry leaked-password list | 1.9 days | 2.8 minutes | 0.2 s |
| 10 random lowercase letters (26¹⁰) | 74 600 years | 75 years | 27 days |
| 4 random Diceware words (7776⁴, ≈51.7 bits) | 1.9 million years | 1 930 years | 1.9 years |
| 10 random printable ASCII characters (94¹⁰) | 2.8 × 10¹⁰ years | 2.8 × 10⁷ years | 28 400 years |

Times are to exhaust the whole space; the expected time to success is half.

### 9.5 Verdict

1. **The KDF cost is not the weak link.** At the current setting, any passphrase with about 50
   bits of real entropy — four random words — withstands a million laptops for years, and costs
   its owner a tenth of a second to unlock.
2. **The 10-character minimum is a usability floor, not a strength guarantee.** The check is
   length-only, plus "differs from the login password". `aaaaaaaaaa` and `password12` pass it,
   and fall in minutes on one laptop. Length is a poor proxy for entropy when people choose.
   *(Update 2026-10-08: R-1 is implemented, #205; both examples are now refused. See F-04.)*
3. **Only the browser can do better.** The passphrase never reaches the server, by design (O1),
   so the server can neither check it against a deny-list nor enforce anything about it. Any
   strength check must run client-side.

This leads to two recommendations, registered as F-04 and F-15 (§12):

- **R-1 (the one that matters): reject known-weak passphrases in the browser.** Apply the login
  password's deny-list, reject repeated and sequential patterns and the account's own
  identifiers, and steer users toward four or more random words. This closes the gap between
  rows 1–2 and rows 4–5 of the table far more than any cost increase could.
- **R-2 (optional): raise the enrolled cost.** There is measured headroom: 256 MiB, t=3 is at most
  0.56 s on every tested client and quadruples an attacker's cost per guess. Cost is stored per
  profile, so new enrolments would take the new value and existing accounts would upgrade at
  their next passphrase change or reset. **Do not change it until** a low-end Android device has
  been measured and the Safari 128 MiB anomaly reproduced.

## 10. Key custody, public-key identity and metadata

Issue #60 criteria 3, 4 and 5. Each asks for a **decision**, not only an analysis. The decisions
below are taken at FYP scope: none of these items appears in `TODO.md` or any Issue, and the
project deliberately does not build them. Each decision records what it accepts and, where it
matters, the cheapest effective control if the project continues.

### 10.1 The exported private key and the limits of a lost passphrase

**What the file is.** At registration the browser shows, once, the account private key as a
plaintext PKCS#8 `.pem` and offers it as a download. It carries no passphrase. Whoever holds it:

- can open every file key wrapped to the account, given the ciphertext and wrapped keys — which
  take a signed-in session or a database dump to obtain;
- together with a signed-in session, can set a new encryption passphrase (§ Passphrase reset in
  [SECURITY_FLOWS.md](SECURITY_FLOWS.md#passphrase-reset-with-the-private-key-file)).

It is therefore the account's master credential for everything cryptographic, and more powerful
than the passphrase, which only opens a stored copy of it.

**What losing things costs.**

| Lost | Outcome |
|---|---|
| Login password only | Reset by emailed code; files unaffected |
| Encryption passphrase, key file kept | Set a new passphrase in Settings with the key file (single-key accounts); files unaffected |
| Both passphrase and key file | **Files are unrecoverable.** Admin recovery does not help: it rewraps a DEK to the user's *registered* public key, whose private half is exactly what was lost, and it cannot register a replacement key |
| Key file stolen | The thief needs a session or a dump as well to reach ciphertext. Resetting the passphrase does not help — the key pair is unchanged — and there is no key-revocation flow in the browser |

**Decision.** Keep the plaintext `.pem` export. It is the only recovery factor independent of the
passphrase, and adding an encrypted export would mean a second secret the user must also keep,
which is what makes people lose both. Custody guidance stays in the product, not only here. The
registration page now states the limits correctly. Until this change it still told users the
passphrase "cannot be reset", which stopped being true when the key-file reset shipped.

*If the project continues:* an encrypted recovery kit — a random recovery code that derives a
second KEK wrapping the same AMK — would let a user print something safe to store. It needs a
second protection profile, which is a schema change.

### 10.2 Public-key identity, rollback and the trust anchor

Every wrap the browser performs uses a public key the server supplied: the owner's own key from
`GET /keys/me`, a recipient's from the identifier lookup, and the recovery key from
`GET /recovery/public-key`. The question is who can substitute them.

- **Against a malicious code supplier (X4), nothing here helps.** Code that can replace keys can
  also delete the check that would catch it. This is N1, and it stands.
- **Against a data writer without code control (X8), a check in the browser does help**, because
  X8 can rewrite the rows the browser reads but not the browser's code. The release tree is
  owned by `mcs21-deploy` and only readable by others, while the backend runs as `fypapp`.
  X8 is the adversary this section is about.

What X8 gains by substituting each key:

| Key | Gain for X8 | Noticed? | Cheapest effective control |
|---|---|---|---|
| Recovery (T-S4) | Every later upload's recovery wrapping — X8 can decrypt **every new file of every user** | Only if someone compares the fingerprint the upload page shows | A list of allowed recovery fingerprints **compiled into the frontend**, refusing to upload on mismatch. Rotation becomes a reviewed code change. |
| Recipient (T-S5) | Every file shared to that recipient from then on | Late — the real recipient cannot open the file | Show the recipient's fingerprint in the share dialog; pin it on the sender's device on first use and warn if it changes |
| Owner (T-S7) | The owner-wrapping of each new upload | Late — the owner cannot open the new file | Pin the owner's own fingerprint on the device at registration or first unlock — the registration page already shows it — and compare before each upload |

**Rollback (T-T4).** Files cannot be rolled back meaningfully: they are immutable, and AAD-3 binds
each ciphertext to its own `file_id`. Serving an older protection profile only helps someone who
knows the older passphrase, and they already hold a copy of that envelope. The one dangerous
rollback is re-activating a *retired public key*, for instance a recovery key rotated after
suspected compromise. That is the substitution case in the table above, with the same control.

**The trust anchor.** Only one thing the browser can trust is independent of the server's data:
the code it was built from, which comes from reviewed Git history. Any durable pinning has to
live there. Device-local trust-on-first-use is weaker — it binds nothing on a new device and
nothing after cleared storage. The build-time anchor, in turn, is only as strong as the path from
Git to production, which makes **T-E5 (no branch protection, deployment not gated on CI) a
prerequisite**, not a separate concern.

**Decision.** Accept T-S4, T-S7 and T-T4 at FYP scope. T-S5 has since been mitigated with the recipient control in the table above: the fingerprint shown, confirmed and pinned on first use, with a warning on change (PR #160). None is in `TODO.md` or any Issue, and
X8 is an adversary that has already compromised the backend or its database. If the project
continues, the recovery-key pin comes first: it has the largest blast radius, it is silent, and
it is the smallest change.

### 10.3 Metadata and traffic leakage

**Decision.** Keep the filename and MIME type in cleartext. The server-side filename search
(`File.original_filename LIKE …`) and the file list depend on them. Moving them into the
`encrypted_manifest` column the schema already reserves would require an unlock before any
filename could be shown, and would move search into the browser — a large change against a
privacy gain that N2 already declares out of scope. Their *integrity* is protected either way: all
three are bound into AAD-3.

*If the project continues:* the path is `envelope_version = 2`, carrying the filename and MIME type
in the encrypted manifest and exposing only padded or coarse values, as
[FILE_ENVELOPE.md](crypto/FILE_ENVELOPE.md) already notes.

What the server can therefore observe, recorded rather than implied:

| Observable | Source | Precision |
|---|---|---|
| Filename, MIME type | `files` columns | Exact |
| File size | `file_size_bytes`; every supported suite (AES-GCM, AES-GCM-SIV, (X)ChaCha20-Poly1305) produces ciphertext the same length as the plaintext | **Exact** — no padding |
| Upload, update and deletion times | `files` timestamps | Exact |
| Who owns what and who shares with whom, with which capabilities | `files`, `file_access_grants` | Exact |
| When each file was requested for download, and by whom | `FILE_DOWNLOAD_AUTHORIZED` audit rows | Exact, per request |
| Recovery activity | `recovery_requests`, audit rows | Exact |
| IP address and user agent per session and per audited action | `user_sessions`, `audit_logs` | Exact |
| Chosen encryption algorithm and KDF cost | `files`, `user_key_protection_profiles` | Exact |
| On the wire, to a network observer under TLS | — | Transfer sizes and timing; download size equals the file size |

## 11. Supply chain, CSP, upload abuse, tokens and recovery operations

Issue #60 criterion 6. Each subsection states what is in place, what was measured, and the
finding it produces in §12.

### 11.1 Dependencies and supply chain

| Area | In place | Gap |
|---|---|---|
| Frontend | `package-lock.json`; both CI and deployment install with `npm ci`, so every build uses the exact locked tree | `package.json` uses `^` ranges, but the lockfile pins what is installed |
| Backend | All 14 direct dependencies pinned with `==` in `requirements.txt` | Transitive dependencies are not pinned and there are no hashes, so a later install can resolve different indirect versions |
| Cryptographic libraries | `@noble/ciphers` chosen for zero transitive dependencies; `hash-wasm` and python-cryptography are the only other crypto code | — |
| Scripts on application pages | CSP `script-src 'self'`: the app loads no third-party script | `/docs` and `/redoc` do — see §11.2 |
| Automation | CI runs lint, type checks and tests on every PR and every push to `main` | No Dependabot or Renovate; no `npm audit` or `pip-audit` in CI; GitHub Actions pinned by major tag (`@v4`), not by commit |

**Point-in-time scan, 2026-09-30:** `npm audit` (production and development) and `pip-audit -r
backend/requirements.txt`, the latter run in an isolated virtual environment, both reported **no
known vulnerabilities**. That is a snapshot, not a policy: nothing re-runs it. → F-12.

### 11.2 Content Security Policy and its exceptions

The application's CSP is strict: `default-src 'self'`, `script-src 'self' 'wasm-unsafe-eval'`,
`connect-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`. Each relaxation is listed
with the reason it exists.

| Where | Relaxation | Why | Risk |
|---|---|---|---|
| App | `'wasm-unsafe-eval'` | hash-wasm compiles Argon2id as WebAssembly. Without it no account could unlock. Confirmed working on staging by `/benchmark/argon2` (§9) | Permits WebAssembly compilation only, not `eval` of JavaScript |
| App | `style-src 'unsafe-inline'` | Inline styles from Vue components and libraries | CSS injection only. Tokens are not in the DOM for selectors to read |
| App | `img-src data: blob:` | Images from `data:` and `blob:` URLs | Images carry no script |
| `/docs`, `/redoc` | `script-src 'unsafe-inline' https://cdn.jsdelivr.net` | FastAPI's Swagger UI and ReDoc pages | **The one place third-party code runs on the application's origin** → F-03 |

`/docs` loads `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js`. The version
floats across every future 5.x release, and there is **no Subresource Integrity** attribute
(checked on staging: zero `integrity=` attributes). It runs on `https://secureview.tech`, the same
origin whose `localStorage` holds every signed-in user's access and refresh tokens (T-I4). A
compromised release of that package, or of the CDN, could read the tokens of any signed-in user
who opens `/docs`. It could not decrypt files, which still need the passphrase or key file, but it
could take over sessions. This raises T-I6 from the low severity recorded in v0.1.

### 11.3 Upload abuse

Each upload is capped at 500 MiB, in both nginx and the backend, and `/api/` is rate-limited to 30
requests per second per IP with a burst of 60. Since 2026-10-04 the backend also refuses an upload
that would take an account over 2 GiB of stored ciphertext (`USER_STORAGE_QUOTA_BYTES`, 413
`storage_quota_exceeded`) or over 5 GiB uploaded in the last 24 hours, deleted files included so
that delete-and-reupload does not reset it (`USER_DAILY_UPLOAD_BYTES`, 429 `upload_daily_limit`),
and refuses every upload that would leave the storage filesystem below a floor
(`UPLOAD_MIN_FREE_DISK_BYTES`, 507 `server_storage_low`; 20 GiB on staging, which shares its disk
with other services). The checks use the declared size, which is then verified against the bytes
received, and run before anything is stored. nginx allows fifty uploads in flight per address, and
the security agent's `UPLOAD_BURST` rule reports 30+ uploads by one account in ten minutes. What
remains is many accounts filling the disk together, which needs that many verified email
addresses and is still caught by the floor and the 85 % alert → F-09. Separately, in-browser encryption holds about four times the file size in memory
at its peak — measured at exactly 4.00× — which is ~2 GB for a 500 MiB file, and phones are
likely to fail → F-19.

### 11.4 Token storage

Access tokens (30 minutes) and refresh tokens (7 days) are stored in `localStorage`, readable by
any script running on the origin. The alternative, `HttpOnly` cookies, keeps tokens away from
scripts, but it needs CSRF protection and changes to how the backend issues and reads sessions.
The existing controls are the strict application CSP, hashed tokens server-side, and refresh
rotation with family revocation on replay. The private key is unaffected: it is held as a
non-extractable `CryptoKey`, and `localStorage` never contains it. **Decision:** accept at FYP
scope, and remove the one weakening of the CSP (F-03) → F-07.

### 11.5 Offline recovery operations

The recovery workflow's code enforces maker ≠ checker, rechecks the live grant before executing,
and accepts no recovery private key on any endpoint. What the code cannot enforce is the custody
around it:

- The custody procedure in [BACKUP_AND_RECOVERY.md § 7](BACKUP_AND_RECOVERY.md#7-recovery-key-custody)
  is marked *proposed*. In practice, the staging recovery private key is an **unencrypted PEM on a
  team member's workstation**, which also keeps a plaintext copy → F-02.
- One RECOVERY_OFFICER may both approve and execute a request → F-13.
- An execution package already delivered cannot be recalled after revocation. This was already
  recorded in [SECURITY_FLOWS.md](SECURITY_FLOWS.md#offline-recovery-boundary) and is accepted.

### 11.6 Shared networks: every per-address limit is really per-room

Every limit keyed on the client address assumes one address is one person. On a campus or
venue Wi-Fi it is not: the whole room sits behind one NAT and reaches the server as a single IP.
With the original values a lecture hall using the site at the same time would have tripped the
limits by itself, and worse, fail2ban matched every 401 under `/api/v1/auth/`, including the
`/auth/me` call that every open tab makes once its thirty-minute access token has expired, so a
few idle tabs could ban the entire venue for an hour. On 2026-10-09, before the final
presentation, the per-address limits were resized for about a hundred people behind one address
while the per-account limits stayed as they were:

| Layer | Limit | Was | Now |
| --- | --- | --- | --- |
| nginx `secureview_api` | requests per second per address, burst | 10, 20 | 30, 60 |
| nginx `secureview_auth` | credential checks per minute per address, burst | 12, 8, on all of `/api/v1/auth/` | 60, 30, only on login, register, password reset, change password, delete account and code sending |
| nginx `secureview_upload_conn` | uploads in flight per address | 10 | 50 |
| fail2ban `secureview-auth` | rejected credentials in ten minutes, then ban | 20 then 1 h, any 401 or 429 under `/api/v1/auth/` | 60 then 15 min, only a 401 on the credential routes |
| backend `AUTH_LOGIN_IP_MAX_FAILURES` | failed sign-ins per address in 15 min | 50 | 500 |
| backend `AUTH_REAUTH_IP_MAX_FAILURES` | failed password re-checks per address | 20 | 200 |
| backend `AUTH_REGISTRATION_MAX_ATTEMPTS` | registrations per address per hour | 10 | 200 |
| backend `VERIFICATION_SEND_IP_MAX_PER_WINDOW` | codes sent per address per hour | 20 | 300 |
| backend `VERIFICATION_CHECK_IP_MAX_FAILURES` | wrong codes per address per hour | 50 | 500 |

What still protects an account is unchanged: ten failed sign-ins block the account for five
minutes, five failed re-checks block password change, five wrong codes burn a code, five codes
per email address per hour. What the per-address limits now stop is a script, not a crowd: sixty
wrong passwords in ten minutes is one every ten seconds, which a guessing tool reaches in its
first minute and a room of people mistyping does not. The residual risk is the one T-D1 already
records: a flood from many addresses is not stopped at this layer.

## 12. Findings register

Issue #60 criterion 7. Every open, accepted or deferred item from §7–§11, in one place.

**Severity** is impact × likelihood *in this deployment*:
- *High* — a realistic path to many users' file plaintext or keys, or to shipping arbitrary code.
- *Medium* — sessions or one user's data, given a plausible precondition.
- *Low* — limited impact, a demanding precondition, or a defence-in-depth gap.
- *Info* — a recorded fact, a coverage gap, or usability.

**Disposition:**
- *Recommended* — small, worth doing, not done in this review.
- *Accepted* — the risk is carried deliberately at FYP scope.
- *Deferred* — would be done if the project continues.
- *Resolved* — fixed during the review.

The owner column names one of the project's two defined roles, or *Unassigned* where neither fits.

| ID | Finding | Threats | Severity | Disposition | Owner | Evidence |
|---|---|---|---|---|---|---|
| F-01 | `main` has no branch protection, so a direct push bypasses review; until 2026-10-01 server-pull deployment also did not wait for CI | T-E5 | **High** | **Mitigated 2026-10-01** — deployment now waits for CI: the `promote` job moves a `deploy` branch only after every job passes on a commit, and `mcs21-auto-deploy` deploys that branch (#117, [AUTOMATIC_DEPLOYMENT.md](AUTOMATIC_DEPLOYMENT.md#the-ci-gate)). Still open: no review is required, because branch protection is unavailable (private repository on a free plan; rulesets API 403, branch protection 404), and `mcs21-deploy all main` bypasses CI by design. Closing it fully needs a paid plan or a public repository | Testing & Deployment Lead | `promote` created `deploy` on the merge commit (CI run 36807852633); the new script was installed on the VPS and reported the running release matches the latest CI-passed commit, 2026-10-01 |
| F-02 | Staging recovery private key held as an unencrypted PEM on a workstation, with a plaintext copy, not in the proposed offline custody | T-I8 | **High** | Recommended — move it into the proposed custody: passphrase-protected, offline, two holders | Crypto & Security Lead | §11.5; BACKUP_AND_RECOVERY § 7 marked *proposed* |
| F-03 | `/docs` runs a floating third-party script (`swagger-ui-dist@5`, no SRI) on the origin that stores tokens | T-I6, T-I4 | **Medium** | Recommended — set `APP_DOCS_ENABLED=false` on staging; configuration only. Still open on 2026-10-01 and rechecked on 2026-10-07 (`/docs` answers 200; `APP_DOCS_ENABLED=true`, `/docs` loads `swagger-ui-dist@5` from jsDelivr). Note the supervisor evaluation path uses `/docs`, so switch it off after the demo or pin the script with SRI | Testing & Deployment Lead | §11.2; `/docs` → 200, zero `integrity=` |
| F-04 | Passphrase check is length-only, so leaked-list passphrases pass and fall in under two days on one laptop | T-I2 | **Medium** | **Mitigated 2026-10-08** ([PR #205](https://github.com/jsonrar/fyp-secure-file-platform/pull/205)) — registration, the passphrase change and the key-file reset reject passphrases on the common list, repeated or sequential characters, and ones that are mostly the username or email, and suggest four random words (R-1). Still a browser check only: a modified client can skip it | Crypto & Security Lead | §9.4–9.5 |
| F-05 | Recovery public key can be substituted by a data writer; every later upload is then wrapped to it, silently | T-S4 | **Medium** | Accepted; first control if continued: compile allowed fingerprints into the frontend | Crypto & Security Lead | §10.2 |
| F-06 | Recipient and owner public keys can be substituted by a data writer | T-S5, T-S7 | Low | Recipient half mitigated 2026-10-04 (PR #160: confirm, show and pin the fingerprint); owner half (T-S7) accepted | Crypto & Security Lead | §10.2 |
| F-07 | Access and refresh tokens are readable by any script on the origin | T-I4, T-S3 | **Medium** | Accepted, conditional on F-03 being fixed | Unassigned | §11.4 |
| F-08 | Registration reveals whether a username or email exists, before checking the verification code | T-S2 | Low | **Mitigated 2026-10-09**: the code is consumed before the email is checked, and a registered email answers exactly like a wrong code. A taken username still answers `409` before the code, deliberately: usernames are public and the caller should not need a fresh code to pick another | Auth & Backend | `AuthService.register`; `tests/unit/test_auth_service.py` (taken email, duplicate-key race) |
| F-09 | No per-user storage quota; one account can fill the disk | T-D2 | Low | Mitigated 2026-10-04 — per-account storage and daily limits, free-disk floor, per-IP upload connections, `UPLOAD_BURST` rule | Testing & Deployment Lead | §11.3 |
| F-10 | External audit checkpoints are implemented but not operating on staging | T-T6, T-R2 | Low | **Resolved 2026-10-01** — checkpoints publish hourly and one was downloaded and HMAC-verified on a separate machine on 2026-09-25 (Issue #59) | Testing & Deployment Lead | Issue #59 closing comment; `mcs21-audit-checkpoint` journal, last run 2026-10-01 09:16 +08 |
| F-11 | Other staging verifications pending: loopback bind, 30-day bucket lock, log-redaction check | TB2, TB7, T-I5 | Low | **Resolved 2026-10-01** — loopback bind and log redaction were verified on staging on 2026-09-25 (Issue #59); the 30-day bucket lock is recorded under #56 (TODO.md) | Testing & Deployment Lead | Issue #59 closing comment; TODO.md #56 |
| F-12 | Backend transitive dependencies unpinned and unhashed; no automated vulnerability scanning; Actions pinned by tag | T-T5 | Low | **Partly resolved 2026-10-01** — `pip-audit` and `npm audit` now run in CI and the one high-severity axios advisory was fixed (#112). Still deferred: hash-locked backend dependencies and Actions pinned by commit SHA | Testing & Deployment Lead | §11.1; PR #112 |
| F-13 | One recovery officer may both approve and execute | T-R3 | Low | Accepted | Unassigned | SECURITY_FLOWS § Offline Recovery |
| F-14 | Key bundles, profiles and public keys can be rolled back to older valid versions | T-T4 | Low | Accepted | Crypto & Security Lead | §10.2 |
| F-15 | KDF cost could be quadrupled at under 0.6 s per unlock on the tested clients | T-I2 | Info | Deferred until a low-end Android device is measured (R-2) | Crypto & Security Lead | §9.5 |
| F-16 | Argon2id not measured on Android, Firefox or low-end hardware; Safari unexplainedly 6× slower at 128 MiB | — | Info | Deferred | Crypto & Security Lead | §9.2 |
| F-17 | Filenames, MIME types, exact sizes, timestamps and the sharing graph are visible to the server | T-I3 | Info | Accepted — decided in §10.3 | Crypto & Security Lead | §10.3 |
| F-18 | The exported private key is a plaintext `.pem` | T-I7 | Info | Accepted — decided in §10.1 | Crypto & Security Lead | §10.1 |
| F-19 | In-browser encryption peaks at ~4× file size, so large uploads can fail on phones | T-D3 | Low | **Mitigated 2026-10-01** — the upload page warns from 100 MiB, blocks files over the limit at selection, and turns an allocation failure into advice (#113). The ~4× peak itself stays accepted | Unassigned | §11.3; PR #113 |
| F-20 | Unknown routes render a blank page instead of a "not found" page | — | Info | **Resolved 2026-10-01** — a catch-all not-found page replaces the blank screen (#113); the server still answers such URLs with HTTP 200 | Unassigned | Observed on staging; PR #113 |
| F-21 | Any signed-in account can learn whether an email address or username has an account | T-S2a | Low | Accepted: sharing needs it. Exact match only, a session is required, nginx allows 30 API requests a second per address, and only the user id and public key are returned | Auth & Backend | `KeyRepository.get_active_public_key_by_identifier`; `deployment/server/nginx-secureview-limits.conf` |

**Resolved during the review:**
- The ten corrections from the peer review of v0.1 (#109), covered in §13.
- The registration page no longer claims the passphrase cannot be reset (#110).

**Status changes since v1.0 (2026-10-01):** F-10 and F-11 are resolved by the staging evidence in Issue #59, F-20 is resolved and F-19 mitigated by #113, and F-12 is partly resolved by #112. F-01 is mitigated by CI-gated deployment (#117, installed the same day), with the residual that branch protection is unavailable on this plan and no review is enforced. F-02, F-03 and F-04 are unchanged and still open.

**Status changes on 2026-10-08:** F-04 mitigated by #205 (browser-side rejection of common, patterned
and account-derived passphrases). F-02 and F-03 remain *Recommended*.

## 13. Review record

Issue #60's title asks for an *independent* security review. What actually happened is recorded
here, without upgrading it.

| Review | By | What it covered | Outcome |
|---|---|---|---|
| Self-assessment, v0.1–1.0 | The Crypto & Security Lead, who implemented much of the cryptography under review | This whole document | Findings in §12 |
| Peer review of v0.1 (#107) | A teammate who did not write the cryptography | Accuracy of every claim in §1–§8 against the code | 10 points raised, all confirmed against the implementation and corrected in v0.3 (#109). Applying its principle — *implemented is not deployed* — downgraded three further rows |

**No independent external review took place.** The peer review is independent of the author but
not of the project. Nothing in this document certifies SecureView against any standard, and it
should not be cited as though it did. An external review would start from §12, and from F-01 and
F-02 in particular.

## 14. Revision history

| Version | Change |
|---|---|
| 0.1 | Objectives, non-goals, assets, actors, trust boundaries, STRIDE analysis, abuse cases. |
| 0.2 | §9: Argon2id measured on three clients and against a native attacker; verdict on the 10-character minimum; recommendations R-1 and R-2. |
| 0.3 | Peer-review corrections: O1 scoped to trusted client code; TB0 lists everything that actually crosses; N2 and AAD scope; AMK and KEK separated; recipient fingerprint is **not** shown (T-S5); CI does run on pushes to `main` but deployment does not wait for it (T-E5); download audit proves authorization, not receipt (T-R1); recovery-key custody split into intended vs staging; external checkpoints, bucket lock, loopback bind and log redaction marked implemented-but-unverified; owner-key substitution added as T-S7. |
| 0.4 | §10: decisions on the exported private key and lost-passphrase limits, on public-key identity, rollback and the trust anchor (new adversary X8), and on cleartext metadata with a leakage inventory. T-S4, T-S5, T-S7, T-T4, T-I3 and T-I7 now point to their decisions. |
| 1.0 | §11: supply chain (point-in-time scans clean), CSP exceptions, upload abuse, token storage and recovery operations. T-I6 raised to Medium: `/docs` runs an unpinned third-party script on the token-bearing origin. §12: register of 20 findings with severity, disposition, owner and evidence. §13: review record, stating that no independent external review took place. |
| 1.1 | Register statuses refreshed against the live staging state on 2026-10-01: F-10, F-11, F-20 resolved; F-12 partly resolved and F-19 mitigated; F-01 records that branch protection needs a paid plan. No analysis changed. |
| 1.2 | F-01 and T-E5 updated: deployment is gated on CI (#117, installed 2026-10-01). No analysis changed. |
| 1.3 | 2026-10-09. §11.6 added with the per-address limits resized for a venue network behind one NAT (#210). F-04 recorded as mitigated by #205 (2026-10-08), which v1.2 had not picked up, and the version line above brought in line with this table. Sharing (T-S5): the client does not decrypt the file before a share; [FILE_ENVELOPE.md](crypto/FILE_ENVELOPE.md) §6 now says what it checks instead and why a wrong rewrap is a share that does not work rather than a disclosure. No other analysis changed. |
| 1.4 | 2026-10-09. T-I10 added: the Encrypted preview does not weaken a file, so it stays as it is. No other analysis changed. |
| 1.5 | 2026-10-09. T-S2 / F-08 recorded as mitigated by #212 (the table already said so, but no revision row did). Two fixes after #213: the access log shows a user rows about a file they own only when the row really is about a file (the file, its shares, checks and recovery), so a client-chosen file id that equals someone's user or key id no longer reveals that person's account rows; and sending a verification code answers the same for a registered and an unregistered email. Stale references fixed: TB7, T-T6 and T-R2 now say the external checkpoints run on staging (F-10); T-S1 and T-D1 point to §11.6; U1 matches T-S2; schema `0011_must_change_password`. No other analysis changed. |
| 1.6 | 2026-10-09. T-S8 added: the forced password change after an administrator's reset is now enforced by the server, which refuses every authenticated route except reading the account, changing the password and signing out until the holder sets their own (#212 enforced it only in the frontend). T-D5 added: the last active administrator can no longer close their account, and an administrator cannot be disabled when no other would stay active (`409 last_admin`). T-S2a and F-21 added: a signed-in account can look another up by exact email or username because sharing needs it; accepted, with its limits stated. No other analysis changed. |
