# SecureView

**English** · [中文](README.zh-CN.md)

> A secure file encryption and sharing platform developed by the four-person **FIT3161/FIT3162 MCS21** Final Year Project team at Monash University Malaysia.

[![Live Site](https://img.shields.io/badge/Live_Site-secureview.tech-2563eb?style=for-the-badge&logo=googlechrome&logoColor=white)](https://secureview.tech)
[![API Docs](https://img.shields.io/badge/API-Swagger_UI-85ea2d?style=for-the-badge&logo=swagger&logoColor=black)](https://secureview.tech/docs)
[![Status](https://img.shields.io/badge/Status-Active_FYP-16a34a?style=for-the-badge)](#current-product-state)
[![Source](https://img.shields.io/badge/Source-Private_During_Assessment-475569?style=for-the-badge)](#source-code-availability)
[![License](https://img.shields.io/badge/License-All_Rights_Reserved-dc2626?style=for-the-badge)](LICENSE)

**Public portfolio snapshot synced: 6 October 2026.**

## Overview

SecureView encrypts files **inside the browser before upload**, stores only ciphertext and wrapped key material on the server, and lets authorised users share, revoke, download and audit access to encrypted files.

The server stores public keys, encrypted private-key bundles, ciphertext and wrapped file keys. A user's encryption passphrase, plaintext private key, plaintext file key and plaintext file do not belong in an API request or database row.

The end-to-end browser MVP is live at **[https://secureview.tech](https://secureview.tech)**. This public repository is a curated portfolio mirror: it documents the current product, architecture, testing evidence, screenshots, demo media and my contributions without publishing the private assessment source repository, credentials, test accounts or operational secrets.

## Current Product State

The current build is beyond the original MVP and includes the following:

- **Six client-side AEAD choices per file:** AES-128-GCM, AES-192-GCM, AES-256-GCM, AES-256-GCM-SIV, ChaCha20-Poly1305 and XChaCha20-Poly1305. AES-256-GCM remains the default.
- **RSA-OAEP key wrapping:** the file data-encryption key is re-wrapped in the browser to each authorised recipient's public key.
- **Controlled sharing and revocation:** share by exact username or email, confirm the recipient key fingerprint, and revoke future server-mediated access.
- **File details and encryption evidence:** exact plaintext/ciphertext sizes, ciphertext SHA-256, access list, activity history, encrypted download, ciphertext preview and measured encryption steps.
- **Integrity protection:** SHA-256 verification before download, authenticated-encryption tag checks, daily integrity sweeps and an admin Integrity view.
- **Tamper-evident audit history:** security-sensitive events are hash chained and can be verified by administrators.
- **Role-based administration:** USER, ADMIN and RECOVERY_OFFICER roles, with governed recovery workflows.
- **Security Agent:** a read-only rule-based admin view that ranks security findings with evidence and recommended actions.
- **Account administration:** admins can inspect account metadata and reset a user's **login password** to a one-time temporary password; users can then choose their own login password in Settings. The encryption passphrase remains client-side and is never shown to administrators.
- **Help Assistant:** a local browser assistant for how-to and product questions. It uses curated project content, not a language model, and does not send the question to a remote service.
- **English / Simplified Chinese UI:** language switching across the public site and authenticated workspace.
- **Redesigned interface:** the current "Sealed" visual system includes a signed-in sidebar, centred page headers, a Seal Receipt on upload, a responsive My Files details panel, responsive mobile layouts and refreshed public pages.

## Latest Walkthrough

The old screenshots previously stored in this portfolio repository were removed because they showed an earlier interface. The six images below are the **current walkthrough captured after the October UI redesign**, using fabricated demo data.

| 1. Choose a file | 2. Encrypt in the browser |
|---|---|
| ![Choose a file](https://secureview.tech/walkthrough/01-select.webp) | ![Encrypt in the browser](https://secureview.tech/walkthrough/02-encrypt.webp) |

| 3. Manage the encrypted file | 4. Share to a checked recipient |
|---|---|
| ![Manage the encrypted file](https://secureview.tech/walkthrough/03-file.webp) | ![Share to a checked recipient](https://secureview.tech/walkthrough/04-recipient.webp) |

| 5. Recipient unlocks locally | 6. Verify and download |
|---|---|
| ![Recipient unlocks locally](https://secureview.tech/walkthrough/05-unlock.webp) | ![Verify and download](https://secureview.tech/walkthrough/06-download.webp) |

### Demo videos

The public Help page also uses three freshly re-recorded clips from the redesigned interface:

- **[How SecureView works](https://secureview.tech/videos/how-it-works.mp4)** — product flow and trust boundary.
- **[Encrypt and upload](https://secureview.tech/videos/encrypt-upload.mp4)** — local encryption, sealing and upload.
- **[Share and open](https://secureview.tech/videos/share-open.mp4)** — recipient verification, sharing and local unlock.

See **[docs/DEMO.md](docs/DEMO.md)** for posters, Chinese walkthrough images and the media manifest.

## Architecture

~~~mermaid
flowchart LR
U[User Browser<br/>WebCrypto + AEAD] -->|HTTPS| N[Nginx]
N --> F[Vue 3 + TypeScript SPA]
N -->|/api/v1| A[FastAPI]
A --> D[(MySQL 8.4)]
A --> S[(Encrypted Object Storage)]
A --> L[Audit Chain, RBAC, Integrity and Security Agent]
classDef client fill:#dbeafe,stroke:#2563eb,color:#0f172a
classDef server fill:#ede9fe,stroke:#7c3aed,color:#0f172a
classDef data fill:#dcfce7,stroke:#16a34a,color:#0f172a
class U,F client
class N,A,L server
class D,S data
~~~

The Vue frontend owns file-content cryptography and account-key handling. The FastAPI backend authenticates and authorises actors, validates requests, runs business transactions, appends audit records and stores encrypted objects and metadata. It does not decrypt user files.

| Area | Technologies |
|---|---|
| Frontend | Vue 3, TypeScript, Vite, WebCrypto |
| Backend | FastAPI, Python, Pydantic, SQLAlchemy, Alembic |
| Database | MySQL 8.4 |
| Cryptography | AES-GCM, AES-GCM-SIV, (X)ChaCha20-Poly1305, RSA-OAEP, Argon2id, SHA-256 |
| Testing | pytest, Vitest, Playwright, custom load testing, OWASP ZAP, pip-audit, npm audit |
| Infrastructure | Linux, Nginx, Docker, systemd, GitHub Actions self-hosted runners |

## Security Design

- Each file receives a fresh browser-generated data-encryption key.
- Authenticated encryption protects both confidentiality and integrity of file content.
- RSA-OAEP with SHA-256 wraps the file key separately for the owner and each authorised recipient.
- Login passwords are one-way hashed with Argon2id on the server.
- The separate encryption passphrase is used in the browser to derive key-encryption material and is never sent to the server.
- A saved private-key file can recover access if the encryption passphrase is forgotten.
- Audit records are hash chained, making later history modification detectable.
- Upload quotas, free-space guards and rate limits reduce storage-abuse risk.
- Because the server stores ciphertext, it cannot inspect shared files for malware; risky executable or macro-capable files therefore trigger recipient warnings.

SecureView is an **academic prototype**, not a claim of independently audited production security. The public security summary and residual-risk notes are in **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)**.

## Testing and Verification

### Automated suites

- **503 backend unit tests** and **810 frontend tests** pass on the current main branch.
- The full backend suite against real MySQL 8.4 contains **633 tests** and runs at about **85% branch coverage**.
- Live end-to-end tests cover verification-code registration, session refresh and replay rejection, account unlock, all six ciphers, upload/download, sharing/revocation, audit visibility, role denial and account deletion.
- Playwright drives the real browser flow through registration, upload, unlock, download, byte-for-byte comparison, sharing, revocation and logout.
- Concurrency tests target session limits, audit chaining, key rewraps, duplicate shares and recovery races.
- Fault-injection tests exercise failed database commits, storage failures, malformed envelopes and forged signatures.
- Cryptographic vectors are checked against OpenSSL, libsodium and RFC 8452 references.

### Capacity and performance

The staging capacity study on 3–4 October 2026 recorded:

- **22,264 operations**.
- **5,094 verified downloads** with **0 integrity failures**.
- Common file types from 1 MB through **500 MB** round-tripped byte-exact.
- No server error up to **50 concurrent users** in the measured run.
- A 100-user run exposed a database-pool/thread-pool interaction: failed uploads reached about 80% while CPU averaged only 3%.
- After the fix, the 100-user failure rate dropped from **80% to 0%**, throughput improved from **0.33 to 56 operations/second**, and the staging re-run completed **102/102 uploads** successfully.

### Security checks

- OWASP ZAP baseline scan: **0 FAIL, 8 WARN, 59 PASS**, with the reported missing static security headers subsequently fixed in Nginx.
- pip-audit and npm audit: no findings in production dependencies at the recorded scan.
- Tamper drills modify stored ciphertext and verify that download is refused; changing the recorded SHA-256 as well is still rejected by authenticated encryption.
- Encrypted off-server backups are validated by a clean-host restore drill.

More detail: **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)**.

## My Contributions

As of **6 October 2026**, I authored **137 of the project's 158 merged pull requests** (**145 authored PRs** in total) and opened **29 issues**.

### Testing and quality engineering

- Built the load/capacity tool and ran the staging capacity study.
- Diagnosed and fixed the 100-user database-pool failure and two MySQL concurrency deadlocks, with regression coverage.
- Built CI quality gates, the MySQL 8.4 release gate, live end-to-end testing, concurrency/fault-injection coverage and Playwright browser tests.
- Built the isolated tamper drill and live tamper demonstration.
- Added responsive browser checks, layout audits and the later site-wide text audit.
- Ran OWASP ZAP, pip-audit and npm audit and fixed the security-header findings.

### Security and product features

- Added AES-256-GCM-SIV and XChaCha20-Poly1305 to the original AES-GCM/ChaCha set.
- Built the Security Agent and its later evidence/de-duplication improvements.
- Built the integrity/recovery pipeline, daily checks and single-file restore view.
- Implemented upload-abuse limits, risky-file warnings and recipient key-fingerprint confirmation.
- Built the Help Assistant, bilingual interface, admin console, account details/login-password reset, file details, encrypted preview and visible encryption-step evidence.
- Implemented earlier core browser flows including download/decryption, recipient re-wrapping, private-key-file unlock, idle relock, session renewal and account deletion.

### Deployment, operations and documentation

- Built and maintained guarded automatic deployment of exact CI-passed commits.
- Deployed and hardened Nginx/HTTPS, security headers, rate limiting and fail2ban.
- Added encrypted off-server backups, clean-host restore verification, reconciliation, monitoring and redacted operational evidence.
- Maintained bilingual architecture, security, threat-model, testing, performance and release documentation, plus final-presentation evidence.

## Public Documentation

- **[CHANGELOG.md](CHANGELOG.md)** — curated public milestone history.
- **[docs/README.md](docs/README.md)** — documentation and evidence index.
- **[docs/DEMO.md](docs/DEMO.md)** — current screenshots, Chinese screenshots and videos.
- **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)** — public security model and limitations.
- **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)** — test strategy and measured performance.

## Live Site

Visit **[https://secureview.tech](https://secureview.tech)** and include the https:// prefix.

## Source Code Availability

The main implementation repository remains private while the university team project is under active assessment. This portfolio repository intentionally excludes private source code, credentials, test-account secrets, private-key material and internal deployment details.

More implementation material may be published later when academic and team requirements allow.

---

**Project:** SecureView · **Institution:** Monash University Malaysia · **Units:** FIT3161 / FIT3162 · **Team:** MCS21 · **Team size:** Four students
