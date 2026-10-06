# SecureView Testing and Performance

This document summarises the evidence used by the public portfolio. Raw logs, environment-specific server metrics and private test-account material remain in the assessment repository.

## Test layers

### Backend

- 503 backend unit tests on the current main branch.
- 633 tests in the full backend/MySQL suite.
- Approximately 85% branch coverage in the full MySQL-backed run.
- Contract, authorisation, repository, migration and transaction-boundary tests.

### Frontend

- 810 frontend tests on the current main branch.
- Type checking and production build verification.
- English / Simplified Chinese translation checks.
- Layout and text audits across desktop, tablet and phone widths.

### Live end-to-end

The live stack exercises real HTTP, browser-compatible cryptography and MySQL 8.4 across:

- verification-code registration;
- login and refresh-token rotation;
- account-key unlock;
- all six file ciphers;
- upload/download and byte comparison;
- sharing and revocation;
- audit visibility;
- role/permission denial;
- account deletion.

The release test policy treats a skipped required test as a failure rather than a pass.

### Real browser

Playwright covers the golden path in Chromium and checks responsive layouts at phone widths. The browser flow uses the same built application that users interact with.

### Concurrency and fault injection

Dedicated tests target:

- session-limit races;
- audit-chain ordering;
- key rewraps;
- duplicate sharing;
- recovery races;
- database disconnection around commit;
- object-storage write failures;
- malformed envelopes and forged signatures.

The concurrency suite found real MySQL deadlocks that were reproduced, fixed and retained as regression tests.

## Capacity study — 3–4 October 2026

The custom load tool performs encryption/decryption using the same cryptographic envelope model as the browser.

### Aggregate results

- 22,264 operations.
- 5,094 downloaded files decrypted and compared against the originals.
- 0 integrity failures.
- Common file types from 1 MB to 500 MB round-tripped byte-exact.
- A 108-minute mixed-load run with 5 active users recorded 19,372 operations.
- Up to 50 concurrent users completed the measured run without server error.

### 100-user bottleneck and fix

At 100 concurrent users, 65–80% of uploads could fail while CPU averaged about 3%. The result showed that CPU was not the bottleneck.

The failure was traced to an interaction between database connections and worker threads during uploads. After the fix:

- failed uploads: about 80% → 0%;
- throughput: 0.33 → 56 operations/second;
- staging re-run: 102/102 uploads completed successfully.

This is useful evidence because the load test did more than produce a headline number: it found an architectural bottleneck and verified the repair.

## Security scanning

### OWASP ZAP

Recorded baseline result:

- 0 FAIL
- 8 WARN
- 59 PASS

The scan identified missing security headers on static responses; those headers were then added in Nginx.

### Dependency audits

At the recorded scan:

- pip-audit: no production-runtime dependency findings;
- npm audit: no production dependency findings.

### Tamper tests

The project deliberately modifies stored ciphertext and confirms:

- the corrupted download is refused;
- replacing the stored SHA-256 value is still insufficient because authenticated-encryption verification fails;
- audit/integrity evidence records the event.

## Backup and restore

Encrypted off-server backups are accompanied by a clean-host restore drill. A backup is therefore treated as unverified until the restore procedure can recreate a working data set.

## Interpretation

The numbers in this document describe the measured staging environment and test conditions, not a universal production capacity guarantee. They are included to show repeatable evidence, discovered failure modes and verified remediation.
