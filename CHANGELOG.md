# SecureView Public Changelog

This is a **curated public changelog** for the SecureView portfolio repository. The private team repository keeps the full engineering record. This file lists the main milestones and leaves out assessment-only source, test accounts and operational secrets.

## 2026-10-07 to 2026-10-17

### Passphrase and account hardening

- Users can change their encryption passphrase in Settings.
- Passphrase strength check rejects common, patterned and account-derived passphrases.
- The passphrase is asked again on every download and share. "Access Records" is renamed "Activity Log".
- Registration no longer reveals whether an email exists, and account deletion is throttled.
- An admin login-password reset now forces a new password, enforced by the server. The last admin account is protected.

### Cryptography, audit and operations

- AES-192-GCM works in every browser, all six suites are shared end to end, and the cipher test vectors are also checked on the server.
- Audit log can be filtered by event type, result, date and keyword, and loads page by page.
- Security Agent reports one address signing into many accounts as a single finding.
- Clearer messages for recovery requests and refused downloads. The Integrity tab gives a restore command that works from the nightly backup.
- Per-address limits are sized for a venue network behind one NAT.
- Deploys keep the newest 10 pre-deploy backups, and each MySQL deadlock retry is logged.
- All times on the site are shown in Kuala Lumpur time (MYT).

### Evidence and media

- 2026-10-09: load test re-run through the public URL: 18,256 operations, 7,444 verified downloads, 0 integrity failures, no HTTP 500 at 100 users.
- 2026-10-12: OWASP ZAP re-scan, still 0 FAIL.
- 2026-10-13: CI run with 718 backend unit, 786 MySQL-suite, 899 frontend, 977 frontend live and 57 browser tests passing.
- New home-page copy, and the Help videos re-made at 1080p.
- All test results collected into one test report folder.

## 2026-10-06

### Account administration and portfolio sync

- Added administrator account details: email/verification state, role, status, account dates and aggregate usage counts.
- Added administrator login-password reset with a one-time temporary password, session revocation and audit logging. Encryption passphrases and file keys remain outside administrator access.
- Added a Settings flow for users to change their own login password.
- Synced the public portfolio README with the current feature set, testing numbers, October performance study and latest UI.
- Replaced the old portfolio screenshot section with the October walkthrough and Help videos.
- Added a public documentation index, media guide, security overview, and testing/performance summary.

## 2026-10-05

### UI redesign completed

- Completed the current "Sealed" visual system across the public site and authenticated workspace.
- Added the persistent signed-in sidebar, redesigned upload Seal Receipt and a responsive My Files details panel.
- Reworked the public home page with proof/evidence sections, comparison questions and a compact project footer.
- Added site-wide heading/intro text auditing across multiple widths and both languages.
- Re-recorded the six-step walkthrough in English and Simplified Chinese.
- Re-recorded the public Help videos: How it works, Encrypt and upload, and Share and open.
- Fixed stale lazy-loaded page recovery after a deployment and several translation/layout regressions discovered while re-recording.

## 2026-10-04

### Capacity bottleneck fixed and security scans recorded

- Diagnosed the 100-user upload failure as an interaction between the API database pool and worker thread pool rather than CPU saturation.
- After the fix, measured upload failures at 100 users fell from up to 78% to 0%, throughput increased from 0.33 to 56 operations/second, and the staging re-run completed 102/102 uploads.
- Recorded an OWASP ZAP baseline scan with 0 FAIL. After the static security-header findings were fixed in Nginx, the result was 0 FAIL, 5 WARN and 62 PASS.
- Recorded clean production-dependency results for pip-audit and npm audit.
- Added encrypted off-server backup/restore evidence and isolated tamper testing.

## 2026-10-03

### Measured capacity campaign

- Completed 22,264 measured operations.
- Verified 5,094 downloaded files against the originals with 0 integrity failures.
- Confirmed byte-exact round trips for common file types through 500 MB.
- Ran long mixed-load tests and measured up to 50 concurrent users without server errors.
- Used the load tool to expose concurrency-only MySQL deadlocks and added regression tests after fixing them.

## Late September to early October 2026

### Security, cryptography and product hardening

- Expanded per-file encryption to six AEAD choices with AES-256-GCM-SIV and XChaCha20-Poly1305.
- Added visible encryption evidence, ciphertext preview and encrypted-file download.
- Added the browser Help Assistant and account-aware help answers.
- Added English / Simplified Chinese UI support.
- Added upload-abuse limits, risky-file warnings and recipient key-fingerprint confirmation.
- Added integrity sweeps, recovery evidence and Security Agent improvements.
- Added MySQL release gates, live end-to-end testing, Playwright golden-path coverage, fault injection and tamper drills.

## Earlier MVP milestones

- Browser-side encryption/decryption with no plaintext file upload.
- RSA-OAEP file-key wrapping and recipient re-wrapping.
- Secure registration/login, session refresh and account-key unlock.
- File upload/download, sharing, revocation and access history.
- Hash-chained audit logging and role-based administration.
- Public Education, Help, Contact and project-information pages.

---

For current screenshots and videos, see [docs/MEDIA.md](docs/MEDIA.md). For the measured evidence behind the testing claims, see [docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md).
