# Testing summary

English | [简体中文](TESTING_SUMMARY.zh-CN.md)

One page with every number about how SecureView is tested, so the report, the slides and the
README can quote the same figures. Numbers are from the CI run on `main` at `1b1bcce` (PR #240,
2026-10-13) and the load test of 2026-10-09. Where a number changes, change it here first.

## Automated tests (every pull request and every push to `main`)

CI runs on three self-hosted runners on the staging VPS (deployment/ci-runner).
A pull request cannot deploy, and `main` only deploys after all of these pass
([AUTOMATIC_DEPLOYMENT.md](AUTOMATIC_DEPLOYMENT.md#the-ci-gate)).

| Job | What it runs | Result on `1b1bcce` | Coverage |
| --- | --- | --- | --- |
| `backend` | Backend unit and API tests, no database; ruff lint and format | 718 passed | 81.84 % (gate 78 %) |
| `mysql-gate` | The full backend suite against a real MySQL 8.4 over TLS, the runtime grant checks, the MySQL release gate (fresh install, migrations, read-only verification) and the encrypted backup and restore drill | 786 passed, 0 skipped; release gate and restore drill passed | 86.64 % (gate 82 %) |
| `frontend` | Vue type check, vitest unit tests, production build, `npm audit` | 899 passed, 78 skipped | 77.36 % statements |
| `e2e-live` | Every frontend suite against a disposable API and MySQL, including the 78 above; then Playwright in Chromium through the built pages | 977 passed, 0 skipped; 57 browser tests passed | 79.72 % statements |
| `tamper-drill` | An isolated attacker container changes stored ciphertext and the database; the app must report MODIFIED or MISSING and refuse the download | Passed | |

"0 skipped" is enforced, not hoped for: `check_no_skips.py` fails the job if any test in those
JUnit reports was skipped, so a missing database or environment variable cannot turn into a green run.

Some checks are worth naming because they back a specific claim:

| Claim | Test that backs it |
| --- | --- |
| The server only ever holds ciphertext | Upload tests and the evidence recorded in [ENCRYPTION_EVIDENCE.md](ENCRYPTION_EVIDENCE.md) |
| Browser and server agree on the cryptography | `docs/crypto/test_vectors.json` is checked by the frontend and by `backend/tests/unit/test_crypto_vectors.py` with python-cryptography, for all six suites |
| Every suite works for sharing | The live stack shares, decrypts and revokes a file under each of the six suites |
| A changed file is caught | Integrity check tests, the tamper drill, and the browser test that downloads a tampered file |
| Revoked access is really gone | Read, download and integrity check all answer the same 404 after revocation |
| A file is never uploaded twice | The golden path browser test counts `POST /files/upload` and clicks the finished status |
| A temporary password cannot be used for anything else | `test_password_change_required.py` walks every authenticated route in the OpenAPI spec |
| Only GET and POST | Route and client tests, and CORS allows only those two |

## Load test (2026-10-09, after the fixes)

Run through the public URL with nginx and its limits on, from one home connection. Full report:
[performance/REPORT-2026-10-09.md](performance/REPORT-2026-10-09.md).

| Measure | Result |
| --- | --- |
| Operations | 18,256 |
| Downloads decrypted and SHA-256-compared | 7,444, all matching, 0 integrity failures |
| Server errors (5xx) | 0 |
| 1 to 50 concurrent users | Every request succeeded; upload p95 134 ms at 1 user, 3.3 s at 50 |
| 100 concurrent users | 0 server errors (before the fix, 2026-10-03: 65 to 78 % of uploads were HTTP 500); some uploads were answered 429 because one address may have 50 uploads in flight |
| File types and sizes | pdf, png, jpg, mp4, zip, exe at 1 to 500 MiB: 36/36 files, 72/72 downloads byte-exact |
| Server load | CPU average 4.5 %, peak 42 %; API memory flat at 199 MiB |
| Limit | The VPS's 100 Mbit/s port (a single 500 MiB transfer ran at 87 to 98 Mbit/s) |

The before-fix baseline stays in [performance/REPORT-2026-10-03.md](performance/REPORT-2026-10-03.md).

## Checked on the live staging site

After each merge the deploy is checked to have reached the exact commit, `/health/ready` to answer
ready, and the changed user flow to work. The latest results are in the "Verified" table at the top
of [TODO.md](BACKLOG.md). Staging also runs a daily integrity sweep, hourly audit-chain checkpoints
and a nightly encrypted backup with an off-server copy.

## Size of what is tested

| Thing | Count |
| --- | --- |
| API routes under `/api/v1` | 64 (23 GET, 41 POST), plus 4 health and docs routes |
| Database tables | 17, plus `alembic_version`; schema revision `0011_must_change_password` |
| Audit event types | 42 |
| Encryption suites offered for files | 6 (AES-256-GCM default, AES-256-GCM-SIV, XChaCha20-Poly1305, ChaCha20-Poly1305, AES-192-GCM, AES-128-GCM) |

## What is not covered

- **No formal usability study.** The supervisor, the team, the teaching team and other students
  used the live site, but no SUS score or completion rate was measured.
- **Browser tests run in Chromium only.** Firefox and Safari are not part of CI.
- **The 15, 30 and 60 minute soaks were not repeated** after the fixes; the 2026-10-03 soak showed
  flat memory and connections over 58 minutes.
- **The load test came from one address.** It shows the per-address limits working; it does not
  show how many different users from different networks the site can serve at once.
- **MySQL-only tests do not run on a laptop by default.** They run in `mysql-gate`; locally they need
  a MySQL 8.4 and the variables in [E2E_TESTING.md](E2E_TESTING.md).

## Running the tests yourself

| What | Command |
| --- | --- |
| Backend unit and API | `cd backend && .venv/bin/python -m pytest tests/unit tests/api` |
| Frontend unit | `cd frontend && npx vitest run` |
| Everything against a real API and MySQL, plus the browser | `E2E_BROWSER=1 DB_HOST=… bash backend/tests/e2e/run_live_stack.sh` ([E2E_TESTING.md](E2E_TESTING.md)) |
| Load test against staging | `LOAD_ACCOUNTS=… bash loadtest/run_staging.sh` ([PERFORMANCE_TESTING.md](PERFORMANCE_TESTING.md)) |
