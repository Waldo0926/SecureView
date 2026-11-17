# SecureView

**English** · [中文](README.zh-CN.md)

> A secure file encryption and sharing platform built by a four-person **FIT3161/FIT3162 MCS21** Final Year Project team at Monash University Malaysia.

[![Live Site](https://img.shields.io/badge/Live_Site-secureview.tech-2563eb?style=for-the-badge&logo=googlechrome&logoColor=white)](https://secureview.tech)
[![API Docs](https://img.shields.io/badge/API-Swagger_UI-85ea2d?style=for-the-badge&logo=swagger&logoColor=black)](https://secureview.tech/docs)
[![Status](https://img.shields.io/badge/Status-In_Production-16a34a?style=for-the-badge)](#features)
[![Uptime](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FWaldo0926%2Fuptime%2FHEAD%2Fapi%2Fsecureview%2Fuptime.json&style=for-the-badge)](https://waldo0926.github.io/uptime/history/secureview)
[![Source](https://img.shields.io/badge/Source-View_Only-475569?style=for-the-badge)](#about-this-copy)
[![License](https://img.shields.io/badge/License-All_Rights_Reserved-dc2626?style=for-the-badge)](LICENSE)

![Vue 3](https://img.shields.io/badge/Vue_3-TypeScript-42b883?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?logo=fastapi&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.4-4479a1?logo=mysql&logoColor=white)
[![Tests](https://github.com/Waldo0926/SecureView/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Waldo0926/SecureView/actions/workflows/tests.yml)

**Synced with the team repository on 30 October 2026 (team commit `051cc8e`).**

## Overview

SecureView encrypts files **in the browser before upload**. The server only stores ciphertext and wrapped key material, and authorised users can share, revoke, download and audit access to encrypted files.

The server stores public keys, encrypted private-key bundles, ciphertext and wrapped file keys. A user's encryption passphrase, plaintext private key, plaintext file key and plaintext file never go into an API request or a database row.

SecureView runs in production at **[https://secureview.tech](https://secureview.tech)** (type the full https:// address). This repository has the project's source code, tests and documentation, copied from the team repository with test accounts and server details removed, plus this summary of the product and my contributions. The code is here to read. It is not open source (see [LICENSE](LICENSE)).

### At a glance

| | |
|---|---|
| **What** | Web app for storing and sharing files that are encrypted in the browser |
| **Team** | Four students, Final Year Project (FIT3161/FIT3162, team MCS21) |
| **My part** | Authored 187 of the team's 212 merged PRs: testing and CI, security features, deployment and operations |
| **Stack** | Vue 3 + TypeScript, FastAPI, MySQL 8.4, Nginx, Docker, GitHub Actions |
| **Tests** | 718 backend unit tests, 786-test MySQL suite at 86.6% coverage, 899 frontend tests, 977 live frontend tests, 57 browser tests |
| **Load test** | 22,264 operations with 0 integrity failures; fixed a 100-user bug that took upload failures from up to 78% to 0% |

## My Contributions

As of **30 October 2026**, I authored **187 of the project's 212 merged pull requests** (**195 authored PRs** in total) and opened **29 issues**. Every PR merged after 6 October is mine, apart from four Dependabot updates.

### Testing and quality engineering

- Built the load/capacity tool and ran the staging capacity study.
- Diagnosed and fixed the 100-user database-pool failure and two MySQL concurrency deadlocks, with regression coverage.
- Built CI quality gates, the MySQL 8.4 release gate, live end-to-end testing, concurrency/fault-injection coverage and Playwright browser tests.
- Built the isolated and live ciphertext tamper tests.
- Added responsive browser checks, layout audits and the later site-wide text audit.
- Ran OWASP ZAP, pip-audit and npm audit and fixed the security-header findings.

### Security and product features

- Added AES-256-GCM-SIV and XChaCha20-Poly1305 to the original AES-GCM/ChaCha set.
- Built the Security Agent and its later evidence/de-duplication improvements.
- Built the integrity/recovery pipeline, daily checks and single-file restore view.
- Implemented upload-abuse limits, risky-file warnings and recipient key-fingerprint confirmation.
- Added encryption-passphrase change and a passphrase strength check, made AES-192-GCM work in every browser and added server-side checks of the cipher test vectors.
- Hardened accounts: registration no longer reveals whether an email exists, account deletion is throttled, an admin reset forces a new password on the server, and the last admin account is protected.
- Added audit-log filters (event type, result, date, keyword) with paging, and made every download and share ask for the passphrase again.
- Built the Help Assistant, bilingual interface, admin console, account details/login-password reset, file details, encrypted preview and visible encryption-step evidence.
- Implemented earlier core browser flows including download/decryption, recipient re-wrapping, private-key-file unlock, idle relock, session renewal and account deletion.

### Deployment, operations and documentation

- Built and maintained guarded automatic deployment of exact CI-passed commits. After each deploy it checks that the live backend reports the new commit, and rolls back if not.
- Deployed and hardened Nginx/HTTPS, security headers, rate limiting and fail2ban.
- Added encrypted off-server backups, clean-host restore verification, reconciliation, monitoring and redacted operational evidence.
- Maintained bilingual architecture, security, threat-model, testing, performance and release documentation, plus final-presentation evidence.

## Features

- **Six client-side AEAD choices per file:** AES-128-GCM, AES-192-GCM, AES-256-GCM, AES-256-GCM-SIV, ChaCha20-Poly1305 and XChaCha20-Poly1305. AES-256-GCM is the default.
- **RSA-OAEP key wrapping:** the browser re-wraps the file's data-encryption key to each authorised recipient's public key.
- **Controlled sharing and revocation:** share by exact username or email, confirm the recipient's key fingerprint, and revoke future server-mediated access.
- **File details and encryption evidence:** exact plaintext/ciphertext sizes, ciphertext SHA-256, access list, activity history, encrypted download, ciphertext preview and measured encryption steps.
- **Integrity protection:** SHA-256 check before download, authenticated-encryption tag checks, daily integrity sweeps and an admin Integrity view.
- **Tamper-evident audit history:** security-sensitive events are hash chained and administrators can verify the chain. The log can be filtered by event type, result, date and keyword.
- **Role-based administration:** USER, ADMIN and RECOVERY_OFFICER roles, with governed recovery workflows.
- **Security Agent:** a read-only, rule-based admin view that ranks security findings with evidence and recommended actions.
- **Passphrase safety:** users can change their encryption passphrase, weak or account-derived passphrases are rejected, and the passphrase is asked again on every download and share.
- **Account administration:** admins can view account metadata and reset a user's **login password** to a one-time temporary password. Users then set their own login password in Settings. The encryption passphrase stays on the client and admins never see it.
- **Help Assistant:** a local browser assistant for how-to and product questions. It answers from curated project content, uses no language model and does not send the question anywhere.
- **English / Simplified Chinese UI:** language switching across the public site and the signed-in workspace.
- **Redesigned interface:** the "Sealed" design with a signed-in sidebar, centred page headers, a Seal Receipt on upload, a responsive My Files details panel, mobile layouts and refreshed public pages.

## Walkthrough

Captured after the October 2026 UI redesign, using made-up sample data.

| 1. Choose a file | 2. Encrypt in the browser |
|---|---|
| ![Choose a file](https://secureview.tech/walkthrough/01-select.webp) | ![Encrypt in the browser](https://secureview.tech/walkthrough/02-encrypt.webp) |

| 3. Manage the encrypted file | 4. Share to a checked recipient |
|---|---|
| ![Manage the encrypted file](https://secureview.tech/walkthrough/03-file.webp) | ![Share to a checked recipient](https://secureview.tech/walkthrough/04-recipient.webp) |

| 5. Recipient unlocks locally | 6. Verify and download |
|---|---|
| ![Recipient unlocks locally](https://secureview.tech/walkthrough/05-unlock.webp) | ![Verify and download](https://secureview.tech/walkthrough/06-download.webp) |

### Videos

The public Help page uses three 1080p clips recorded on the current interface:

- **[How SecureView works](https://secureview.tech/videos/how-it-works.mp4)**: product flow and trust boundary.
- **[Encrypt and upload](https://secureview.tech/videos/encrypt-upload.mp4)**: local encryption, sealing and upload.
- **[Share and open](https://secureview.tech/videos/share-open.mp4)**: recipient check, sharing and local unlock.

See **[docs/MEDIA.md](docs/MEDIA.md)** for video posters and the Chinese walkthrough.

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

The Vue frontend handles file encryption and account keys. The FastAPI backend authenticates and authorises users, validates requests, runs business transactions, appends audit records and stores encrypted objects and metadata. It never decrypts user files.

| Area | Technologies |
|---|---|
| Frontend | Vue 3, TypeScript, Vite, WebCrypto |
| Backend | FastAPI, Python, Pydantic, SQLAlchemy, Alembic |
| Database | MySQL 8.4 |
| Cryptography | AES-GCM, AES-GCM-SIV, (X)ChaCha20-Poly1305, RSA-OAEP, Argon2id, SHA-256 |
| Testing | pytest, Vitest, Playwright, custom load testing, OWASP ZAP, pip-audit, npm audit |
| Infrastructure | Linux, Nginx, Docker, systemd, GitHub Actions self-hosted runners |

## Security Design

- Each file gets a fresh browser-generated data-encryption key.
- Authenticated encryption protects both confidentiality and integrity of file content.
- RSA-OAEP with SHA-256 wraps the file key separately for the owner and each authorised recipient.
- Login passwords are hashed with Argon2id on the server.
- The separate encryption passphrase is used in the browser to derive key-encryption material and is never sent to the server.
- A saved private-key file can recover access if the encryption passphrase is forgotten.
- Audit records are hash chained, so later changes to the history can be detected.
- Upload quotas, free-space guards and rate limits reduce storage abuse.
- The server only has ciphertext, so it cannot scan shared files for malware. Recipients get a warning for executable or macro-capable files.

SecureView is a **university team project** running in production. Its security has **not been independently audited**. The public security summary and known limitations are in **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)**.

## Testing and Verification

### Automated suites

Results from the CI run on 13 October 2026:

- **718 backend unit tests** pass (81.8% coverage).
- The full backend suite against real MySQL 8.4 has **786 tests**, 0 skipped, at **86.6% coverage**.
- **899 frontend tests** pass, and the frontend live suites against a real backend run **977 tests** with 0 skipped.
- **57 Playwright browser tests**.
- Live end-to-end tests cover verification-code registration, session refresh and replay rejection, account unlock, all six ciphers, upload/download, sharing/revocation, audit visibility, role denial and account deletion.
- Playwright drives the real browser through registration, upload, unlock, download, byte-for-byte comparison, sharing, revocation and logout.
- Concurrency tests target session limits, audit chaining, key rewraps, duplicate shares and recovery races.
- Fault-injection tests cover failed database commits, storage failures, malformed envelopes and forged signatures.
- Cryptographic vectors are checked against OpenSSL, libsodium and RFC 8452 references.

### Capacity and performance

The staging capacity study on 3 and 4 October 2026 recorded:

- **22,264 operations**.
- **5,094 verified downloads** with **0 integrity failures**.
- Common file types from 1 MB to **500 MB** round-tripped byte-exact.
- No server errors up to **50 concurrent users** in the measured run.
- A 100-user run exposed a database-pool/thread-pool interaction: 65% to 78% of uploads failed with HTTP 500 while CPU averaged only 3%.
- After the fix, the 100-user failure rate dropped to **0%**, throughput went from **0.33 to 56 operations/second**, and the staging re-run completed **102/102 uploads**.

A second run through the public URL on 9 October 2026 recorded **18,256 operations** and **7,444 verified downloads** with **0 integrity failures**, and no HTTP 500 at 100 users. Some uploads in that run got HTTP 429 because the whole test came from one address and hit the per-address limit.

### Security checks

- OWASP ZAP baseline scan: **0 FAIL**. After the missing static security headers were added in Nginx, the result is **0 FAIL, 5 WARN, 62 PASS**, and a re-scan on 12 October 2026 gave the same result.
- pip-audit and npm audit: no findings in production dependencies at the recorded scan.
- Tamper drills modify stored ciphertext and check that download is refused. Changing the recorded SHA-256 as well is still rejected by authenticated encryption.
- Encrypted off-server backups are checked with a clean-host restore drill.

More detail: **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)**.

## Repository Layout

| Folder | What it contains |
|---|---|
| [frontend/](frontend/) | Vue 3 + TypeScript app, browser crypto, unit tests and Playwright browser tests |
| [backend/](backend/) | FastAPI app, Alembic migrations, ops scripts and pytest suites |
| [database/](database/) | MySQL provisioning, schema and verification SQL |
| [deployment/server/](deployment/server/) | Nginx config, systemd units, deploy, backup and alert scripts |
| [loadtest/](loadtest/) | The load test tool used for the capacity studies |
| [security-lab/](security-lab/) | Isolated ciphertext tamper drill |
| [.github/workflows/](.github/workflows/) | The tests that run in this repository on every push: backend unit tests, frontend tests, MySQL release gate |
| [ci/](ci/) | The team's full GitHub Actions workflow, kept for reference |
| [docs/](docs/README.md) | Design, security, testing and operations documents, test reports and scan results |
| [changelog/](changelog/CHANGELOG.md) | Full engineering changelog |

How the team ran it locally is in **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)**.

## Documentation

- **[docs/README.md](docs/README.md)**: index of every document.
- **[CHANGELOG.md](CHANGELOG.md)**: short public milestone list.
- **[docs/MEDIA.md](docs/MEDIA.md)**: English and Chinese screenshots and videos.
- **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)**: public security model and limitations.
- **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)**: test strategy and measured performance.

## About This Copy

This is a copy of the four-person team repository. It was first published as one commit and is synced from the team repository from time to time. The commit history and pull requests stay in the team repository, so git blame here does not show who wrote each file. My share of the work is listed in [My Contributions](#my-contributions).

Removed before publishing: test account passwords, the CI runner host setup, the server's public IP, the backup bucket name, the internal Docker gateway address and the server's sshd rules.

The backend unit tests, the frontend tests and the MySQL 8.4 release gate run in this repository too, on GitHub-hosted runners (`.github/workflows/tests.yml`), so the badge at the top reflects this copy of the code. The live end-to-end job and the tamper drill need the removed test accounts and are not run here.

The code is shared so reviewers can read it. It is not open source: copying, modifying, deploying or reusing it needs written permission. See [LICENSE](LICENSE).

---

**Project:** SecureView · **Institution:** Monash University Malaysia · **Units:** FIT3161 / FIT3162 · **Team:** MCS21 · **Team size:** Four students

**My other live project:** [Monash Hub](https://github.com/Waldo0926/monash-hub) at [monashhub.secureview.tech](https://monashhub.secureview.tech), a solo project that runs on a subdomain and is not part of the SecureView team's work.
