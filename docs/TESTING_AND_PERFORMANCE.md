# SecureView Testing and Performance

This document is a short summary. The full results, raw load-test output, server metrics and scan reports are in [test report](test%20report/README.md), [performance](performance/) and [security](security/).

## Latest CI results

From the CI run on 13 October 2026:

| Job | Result | Coverage |
|---|---|---|
| Backend unit tests | 718 passed | 81.8% |
| Full backend suite on MySQL 8.4 | 786 passed, 0 skipped | 86.6% |
| Frontend tests | 899 passed | 77.4% statements |
| Frontend live suites (real backend) | 977 passed, 0 skipped | 79.7% statements |
| Playwright browser tests | 57 | |

## Test layers

### Backend

- Contract, authorisation, repository, migration and transaction-boundary tests.

### Frontend

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

## Capacity study: 3 and 4 October 2026

The custom load tool performs encryption/decryption using the same cryptographic envelope model as the browser.

### Aggregate results

- 22,264 operations.
- 5,094 downloaded files decrypted and compared against the originals.
- 0 integrity failures.
- Common file types from 1 MB to 500 MB round-tripped byte-exact.
- A 108-minute mixed-load run with 5 active users recorded 19,372 operations.
- Up to 50 concurrent users completed the measured run without server error.

### 100-user bottleneck and fix

At 100 concurrent users, 65% to 78% of uploads failed with HTTP 500 while CPU averaged about 3%. The result showed that CPU was not the bottleneck.

The failure was traced to an interaction between database connections and worker threads during uploads. After the fix:

- failed uploads: up to 78% to 0%;
- throughput: 0.33 to 56 operations/second;
- staging re-run: 102/102 uploads completed successfully.

## Re-run through the public URL: 9 October 2026

The load test was run again against the public site instead of staging:

- 18,256 operations.
- 7,444 downloads verified with 0 integrity failures.
- No HTTP 500 at 100 concurrent users.
- Some uploads got HTTP 429 from Nginx because the whole test came from one address and hit the per-address limit. That limit was later sized for a venue network behind one NAT.

## Security scanning

### OWASP ZAP

The first baseline scan reported 0 FAIL and flagged missing security headers on static responses. After those headers were added in Nginx, the result was:

- 0 FAIL
- 5 WARN
- 62 PASS

A re-scan on 12 October 2026 gave the same result.

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
