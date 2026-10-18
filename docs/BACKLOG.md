# SecureView Prioritized Backlog
[English](BACKLOG.md) | [简体中文](BACKLOG.zh-CN.md)

Originally synchronized from GitHub `main`, the shared changelog, repository tests, and
the live staging deployment on 2026-09-03. Rechecked against GitHub `main` at `cab44b1`
on 2026-09-07 after the 500 MiB upload-limit change merged; live deployment was not
re-verified in that backlog-only synchronization. Rechecked again on 2026-10-01 against `main`
at `70fcb6d`: the CI run on that commit passed, and staging was running the same SHA with its
timers healthy. Rechecked on 2026-10-07 against `main` at `e4b3f13` (see the tables below). GitHub Issues are the executable backlog,
and the [SecureView Development Board](https://github.com/users/Waldo0926/projects/1) is the
shared Kanban view; this file is the prioritized summary and must link to them rather than
becoming a second, drifting list.

The shipped MVP capabilities below remain checked. GitHub Issues are authoritative; unchecked
items below still need product, operations, security-review, or deployment evidence. Partial
work is not marked complete.

The proposal audit is recorded in
[`docs/PROPOSAL_TRACEABILITY.md`](PROPOSAL_TRACEABILITY.md): 23 of 24 WBS packages are
Done and one is In review (security testing, waiting for an independent external review). Non-expert
usability is Done on informal real use; the formal study was not run and #115 was closed as not planned. Every product acceptance criterion is Done; the last one, the dismissible progress pipeline (AC7),
closed with [PR #200](https://github.com/jsonrar/fyp-secure-file-platform/pull/200). Milestone M3 is Done based on
the supervisor-reviewed and signed MVP/UI checkpoint; the supervisor's 70–80% whole-project
assessment describes that historical checkpoint rather than an exact current completion value.

## Shipped MVP baseline

Shipped on 2026-10-08: the seal receipt's close button, closing AC7 ([PR #200](https://github.com/jsonrar/fyp-secure-file-platform/pull/200)); passphrase change with the
current passphrase ([PR #201](https://github.com/jsonrar/fyp-secure-file-platform/pull/201)); deadlock-retry logging ([PR #202](https://github.com/jsonrar/fyp-secure-file-platform/pull/202)); Vue 3.5.43 for two npm advisories
([PR #203](https://github.com/jsonrar/fyp-secure-file-platform/pull/203)); pre-deploy backup pruning, installed on the VPS the same day (175 old sets removed, 73 GB freed) ([PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204));
and browser-side rejection of weak passphrases, threat model F-04 ([PR #205](https://github.com/jsonrar/fyp-secure-file-platform/pull/205)).

The homepage picture guide (seven annotated screenshots, English and Chinese) and the Help videos
were re-shot after the "Sealed" redesign and are live on staging (#192); the guide and the two Help
walkthroughs were re-shot again on 2026-10-10 for the upload page after #215. The scrolling Core
Features lane was retired from the home page in that redesign (#177).

- [x] Email-code registration and login-password reset, login plus server-revoking logout,
  backend session-revocation endpoints, refresh rotation,
  session invalidation, account deletion, throttling, Argon2id password hashing, and RBAC.
- [x] Browser-held account-key enrolment, passphrase/private-key-file unlock, idle relock, and
  historical key-bundle retrieval without sending plaintext private keys to the server.
- [x] Browser-side AES-128/192/256-GCM, AES-256-GCM-SIV, ChaCha20-Poly1305 and XChaCha20-Poly1305 file encryption, RSA-OAEP-SHA256
  DEK wrapping, authenticated download/decryption, integrity failures, and encrypted storage.
- [x] Filename search, pagination, owner/shared separation, sharing by recipient-key rewrap,
  recipient list, revocation, notifications, per-file history, and ownership-correct audit
  visibility.
- [x] Conditional recovery and admin APIs, tamper-evident audit chaining, MySQL least-privilege
  production SQL, HTTPS, nginx rate limits, fail2ban, guarded automatic deployment, and
  reconciliation implementation.
- [x] Public staging and evaluation endpoints:
  [application](https://secureview.tech), [Swagger UI](https://secureview.tech/docs), and
  [OpenAPI JSON](https://secureview.tech/openapi.json).
- [x] Public product pages and signed-in account chrome: landing `/`, Education
  (`/education`: algorithms, playground, knowledge), Help (`/help`: How to Use walkthroughs),
  Contact us (`/team`: a feedback form, the supervisor profile and Development Team cards), header active-tab theme colour, and the avatar menu with
  `/profile` and `/settings`. Evidence and rationale live in
  [`changelog/CHANGELOG.md`](../changelog/CHANGELOG.md) under `[Unreleased]`.

- [x] Explainers for newcomers (2026-10-02): an animated, step-through explainer at `/how-it-works` and on the
  home page, three captioned videos on Help recorded from the real product, a comparison with ordinary cloud
  storage, and a four-step quick start. See the changelog entry for what each shows. The comparison table
  now has a labelled, numbered question column, and the footer has no empty track ([PR #194](https://github.com/jsonrar/fyp-secure-file-platform/pull/194)).
  Headings and intros site-wide: one line where they fit, breaks only between sentences, no two-sentence
  headings, checked by `text-audit.mjs` ([PR #195](https://github.com/jsonrar/fyp-secure-file-platform/pull/195)).
- [x] Access Records filters (2026-10-09): event type, result, date range and keyword on `GET /audit-logs`, inside the same visibility rule, and pages of 100 with Load more instead of fetching 1,000 events up front ([PR #213](https://github.com/jsonrar/fyp-secure-file-platform/pull/213)).
- [x] Every upload suite in every browser (2026-10-09): AES-192-GCM falls back to `@noble/ciphers` where WebCrypto lacks it, all six suites are shared end to end in the live suite, and the backend checks `docs/crypto/test_vectors.json` itself ([PR #211](https://github.com/jsonrar/fyp-secure-file-platform/pull/211)).
- [x] Account fixes (2026-10-09): registration answers a registered email the same as a wrong code, account deletion is throttled and writes an audit row, an administrator's password reset makes the holder pick a new password at the next sign-in (`must_change_password`, schema `0011`), and dead crypto code and `app/utils` are removed ([PR #212](https://github.com/jsonrar/fyp-secure-file-platform/pull/212)).
- [x] Upload fixes from supervisor feedback (2026-10-09): a file is never uploaded twice, the finished state is a green status instead of a button, the algorithm dropdown shows a grade for each choice (for example Max · Recommended) with an explanation box, and the explainer steps take about 3 s ([PR #215](https://github.com/jsonrar/fyp-secure-file-platform/pull/215)).

The reason and evidence for shipped behavior belong in
[`changelog/CHANGELOG.md`](../changelog/CHANGELOG.md), not in duplicated historical TODO text.

## Verified on 2026-10-17 (`main` at `a96fed9`, tests last ran on `1b1bcce`)

| Gate | Result | Interpretation |
| --- | --- | --- |
| GitHub Actions on `1b1bcce` (PR #240, 2026-10-13) | All test jobs and `promote` green | The last push to `main` that ran the test jobs; `a96fed9` (#241) was documentation only, so its test jobs and `promote` were skipped by design |
| Backend (`mysql-gate`) | 786 passed, 0 skipped; coverage 86.64 % | Also runs the MySQL release gate and the backup/restore drill, both passing |
| Backend (`backend` job, no MySQL) | 718 passed, 68 deselected; coverage 81.84 % | Unit and API tests without MySQL |
| Frontend (`frontend` job) | 899 passed, 78 skipped; statements 77.36 % | The skips are live-backend suites, run in `e2e-live` |
| Frontend live suites (`e2e-live`) | 977 passed, 0 skipped; statements 79.72 % | Every suite against a disposable API and MySQL |
| Browser specs (`e2e-live`) | 57 passed | Playwright |
| Tamper drill | Passed | Isolated attacker container (#90) |
| Live staging | Running `1b1bcce`, schema `0011_must_change_password` | `/opt/mcs21/current` points at that release; `/health/ready` answers ready (checked 2026-10-17) |

## Verified on 2026-10-10 (`main` at `2ffc36c`)

| Gate | Result | Interpretation |
| --- | --- | --- |
| GitHub Actions on `2ffc36c` (PR #222) | All test jobs and `promote` green | Backend, frontend, `mysql-gate`, `e2e-live` and `tamper-drill` |
| Backend (`mysql-gate`) | 759 passed, 0 skipped; coverage 86.52 % | Also runs the MySQL release gate and the backup/restore drill, both passing |
| Backend (`backend` job, no MySQL) | 691 passed, 68 deselected; coverage 81.67 % | Unit and API tests without MySQL |
| Frontend (`frontend` job) | 886 passed, 78 skipped; statements 74.97 % | The skips are live-backend suites, run in `e2e-live` |
| Frontend live suites (`e2e-live`) | 964 passed, 0 skipped; statements 79.12 % | Every suite against a disposable API and MySQL |
| Browser specs (`e2e-live`) | 57 passed | Playwright |
| Tamper drill | Passed | Isolated attacker container (#90) |
| Live staging | Running `2ffc36c`, schema `0011_must_change_password` | `/opt/mcs21/current` points at that release; `/health/ready` answers ready |
| Security agent daily check | 2026-10-10 06:00: exit 3, 43 High findings | All from the 2026-10-09 load test (load-test user agent, the tester's addresses, accounts deleted by the test's cleanup); nothing to do on the server. See [SECURITY_AGENT.md](SECURITY_AGENT.md#proactive-alerts-daily) |

## Verified on 2026-10-09 (`main` at `0bb6238`)

| Gate | Result | Interpretation |
| --- | --- | --- |
| GitHub Actions on `0bb6238` (PR #217) | All test jobs green | Backend, frontend, `mysql-gate`, `e2e-live` and `tamper-drill` |
| Backend (`mysql-gate`) | 759 passed, 0 skipped; coverage 86.52 % | Also runs the MySQL release gate and the backup/restore drill, both passing |
| Backend (`backend` job, no MySQL) | 691 passed; coverage 81.67 % | Unit and API tests without MySQL |
| Frontend (`frontend` job) | 881 passed, 78 skipped; statements 74.89 % | The skips are live-backend suites, run in `e2e-live` |
| Frontend live suites (`e2e-live`) | 959 passed, 0 skipped; statements 79.05 % | Every suite against a disposable API and MySQL |
| Browser specs (`e2e-live`) | 57 passed | Playwright |
| Tamper drill | Passed | Isolated attacker container (#90) |
| Live staging | Running `0bb6238`, schema `0011_must_change_password` | `/health/ready` answers ready; the 0011 SQL was applied by hand before `c3569c8` was deployed, as DEPLOYMENT.md requires |
| Schema head | `0011_must_change_password` | Adds the admin-reset flag (#212) |

## Verified on 2026-10-07 (`main` at `e4b3f13`)

| Gate | Result | Interpretation |
| --- | --- | --- |
| GitHub Actions on `e4b3f13` | All five test jobs and `promote` green | Runs on the self-hosted VPS runners; `promote` moved `deploy`, so staging deployed it |
| Backend (`mysql-gate`) | 632 passed, 0 skipped; branch coverage 85.27 % (floor 82 %) | The whole suite against MySQL 8.4, including concurrency and fault injection |
| Backend (`backend` job, no MySQL) | 568 passed, 64 deselected; coverage 80.35 % (floor 78 %) | The deselected tests are the MySQL ones above |
| Frontend (`frontend` job) | 810 passed, 56 skipped | The skips are live-backend suites |
| Frontend live suites (`e2e-live`) | 866 passed, 0 skipped | Every suite against a disposable API and MySQL |
| Browser specs (`e2e-live`) | 57 passed | Golden path, tamper view, phone widths, Help assistant, language switch, not-found |
| Schema head | `0010_shared_file_folders` | 17 application tables plus `alembic_version` |
| Live staging | Running `e4b3f13` | `/opt/mcs21/current` points at that release; all nine `mcs21-*` timers active |

## Verified on 2026-10-01 (`main` at `70fcb6d`)

| Gate | Result | Interpretation |
| --- | --- | --- |
| Backend Pytest | 400 passed, 49 skipped, 1 warning | The skips are MySQL integration tests; the `mysql-gate` CI job runs them and fails on any skip |
| Frontend Vitest | 284 passed, 51 skipped | The skips are live-backend suites; the `e2e-live` CI job runs them un-skipped |
| Typecheck, production build, Ruff | Pass | `vue-tsc --noEmit`, Vite build, `ruff format --check` and `ruff check` |
| GitHub Actions | All five jobs green on `main` | `backend`, `frontend`, `mysql-gate`, `e2e-live`, `tamper-drill` |
| Dependency audit | `pip-audit` clean; `npm audit` had one high axios advisory | Fixed and gated in CI by [#112](https://github.com/jsonrar/fyp-secure-file-platform/pull/112) |
| Schema head | `0008_avatars` | Includes folders (`0007`) and avatars (`0008`) |
| Live staging | Running `70fcb6d`, the same SHA | `/`, `/docs`, `/openapi.json` return 200; OpenAPI lists the folder and avatar routes |
| Staging operations | Backup, off-site backup, reconcile, audit checkpoint and observer timers all ran successfully | Restore verification last ran 2026-09-27 (weekly) and passed on the 2026-09-26 backup; reconcile ran daily 2026-09-25 to 2026-10-01 with 0 eligible rows and 0 orphans |

## Historical baseline on 2026-09-03 (kept for comparison)

| Gate | Result | Interpretation |
| --- | --- | --- |
| Backend Pytest | 317 passed, 21 skipped, 1 warning | Unit/API pass; real MySQL coverage did not run |
| Frontend Vitest | 233 passed, 18 skipped | Offline suite passes; integration coverage is skipped |
| Frontend typecheck | Pass | `vue-tsc --noEmit` is operational |
| Frontend production build | Pass | Vite production bundle builds |
| Ruff format/check | **Fail** | Four files need formatting; three import blocks fail |
| GitHub Actions | **Absent** | No required CI gate currently protects `main` |
| Schema baseline | `0007_file_folders` | 18 production SQL tables |
| Live staging | `a085ae4` (PR #51, before this documentation sync) | `/`, health, docs, schema, and ReDoc return 200 |

A test run with skipped integration tests is evidence about the offline subset only; it is
not a release pass.

## P0 — release and data-protection blockers

- [x] [#52 Establish required CI quality gates and fix the current Ruff baseline](https://github.com/jsonrar/fyp-secure-file-platform/issues/52)
  — `.github/workflows/ci.yml` runs backend (Ruff + non-MySQL pytest with a coverage floor) and frontend (test with coverage/typecheck/build)
  on every PR and push to `main`; the Ruff baseline is fixed, not suppressed. Branch protection is **not
  available** on the current plan: the repository is private on GitHub's free tier, and the protection and
  rulesets APIs refuse it (checked 2026-10-01; threat-model F-01). It needs a paid plan or a public
  repository, so the checks are required by convention and review only. What replaced it is
  [#117](https://github.com/jsonrar/fyp-secure-file-platform/pull/117): staging deploys only a `deploy` branch
  that CI moves forward after every job has passed on a commit ([docs](AUTOMATIC_DEPLOYMENT.md#the-ci-gate)).
  Verified 2026-10-01: the `promote` job created `deploy` on the merge commit, the new script was installed on
  the VPS, and it reported the running release already matches the latest CI-passed commit. It does not require
  a review, and `mcs21-deploy all main` still bypasses CI by design. Since [#171](https://github.com/jsonrar/fyp-secure-file-platform/pull/171) a docs-only push to `main` is
  judged against `deploy`, so it can no longer cancel a code commit's run and leave that code unpromoted.
- [x] [#53 Run the full MySQL 8.4 and schema-parity release gate in CI](https://github.com/jsonrar/fyp-secure-file-platform/issues/53)
  — the `mysql-gate` job provisions MySQL 8.4 with verified TLS, exercises every migration through
  the head (`0011_must_change_password` today), runs `alembic current`/`check`, runs the whole backend suite (coverage
  floor 82%) and fails on any skipped test, and checks runtime-vs-admin grants and live schema
  parity. The two gaps once deferred here are closed: the migration-lock race now runs 8 randomized
  iterations that must each show one applier and one waiter, and restores are compared by per-table
  `CHECKSUM TABLE` plus a schema fingerprint, proven by a one-row mutation. Still not a long-running
  chaos test.
- [x] [#56 Automate encrypted off-server backups and prove clean-host restore](https://github.com/jsonrar/fyp-secure-file-platform/issues/56)
  — live on staging since 2026-09-24: nightly encrypted sets to Cloudflare R2 (35-day lifecycle,
  30-day bucket lock), a least-privilege backup account, and failure emails. A real set was
  restored on a separate machine with the offline key in 6.97 s and matched the live database
  and files exactly ([docs/BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md) §5). Follow-ups:
  time the 4 h whole-service RTO on a fresh VPS. Pruning `mcs21-deploy`'s pre-deploy dumps is done ([PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204)).
- [x] [#61 Keep README, TODO, Issues, changelog, PRs, and deployments synchronized](https://github.com/jsonrar/fyp-secure-file-platform/issues/61)
  — this synchronization PR installs the shared records and evidence checklist; future changes
  use the same rule.

## P1 — complete implemented backend capabilities and operations

- [x] [#54 Complete browser passphrase change and successor-key rotation](https://github.com/jsonrar/fyp-secure-file-platform/issues/54)
  — closed with only part of its criteria met; see the P3 entry below and the scope record on the Issue.
- [x] [#55 Complete admin, recovery-officer, and audit-verification workflows](https://github.com/jsonrar/fyp-secure-file-platform/issues/55)
  — `/admin` is role-aware: ADMIN gets an Overview of counts (users, files, storage, shares, integrity and
  audit health, with anything needing attention flagged first), users, files, audit-chain verify, recovery-key
  registration, and recovery review; RECOVERY_OFFICER reviews and executes (offline rewrap
  paste-back); ordinary users open requests from My Files and track/cancel them here. Since 2026-10-02 it
  is reached from an "Admin" header link, its sections are grouped in one URL-addressable row, and the
  Users/Files lists hide deleted records by default (status filter, search, confirm-before-disable).
- [x] [#89 Revoke the server session when a user logs out](https://github.com/jsonrar/fyp-secure-file-platform/issues/89)
  — intentional Log out calls `POST /auth/logout` before clearing the browser; expiry and
  account deletion still clear locally only.
- [x] [#57 Validate and enable the staging reconciliation timer safely](https://github.com/jsonrar/fyp-secure-file-platform/issues/57)
  — repository side done: directory grace, volume guard (exit 3), both-sides boundary report,
  MySQL idempotency and no-audit/key/recovery-statement tests, a 05:00 timer after the same-host
  backup, email alerts, and [docs/RECONCILIATION_RUNBOOK.md](RECONCILIATION_RUNBOOK.md).
  Installed on staging 2026-09-24; report-only review recorded (43 eligible, 0 orphans) and the
  timer enabled. First scheduled run 2026-09-25 05:00 and seven consecutive daily runs to
  2026-10-01 all succeeded (journal: 0 eligible, 0 orphaned objects each time). Those repeat runs
  show it is harmless on an empty set; an idempotent re-run after a real deletion has not been
  observed because nothing has been eligible since.
- [x] [#58 Expand browser E2E, concurrency, fault-injection, and coverage gates](https://github.com/jsonrar/fyp-secure-file-platform/issues/58)
  — the `e2e-live` CI job runs every frontend live-backend suite un-skipped against a
  disposable API and MySQL (registration through account deletion, all six file algorithms,
  role denial), then a Chromium smoke test that clicks the built pages through register,
  verify, sign in, unlock, upload, download, share, revoke and log out; `mysql-gate` runs
  multi-connection concurrency and real fault-injection suites; coverage floors and sanitized
  JUnit/coverage artifacts are in place ([docs/E2E_TESTING.md](E2E_TESTING.md)).
- [x] [#59 Add redacted observability, incident runbooks, and external audit checkpoints](https://github.com/jsonrar/fyp-secure-file-platform/issues/59)
  — repository implementation is ready: redacted structured events, loopback metrics and threshold alerts, trusted-proxy enforcement, HMAC external audit checkpoints, sparse alert email, and paired incident runbooks. Staging evidence recorded 2026-09-25 (closing comment on the Issue and §8 of
  [the runbook](OBSERVABILITY_AND_INCIDENT_RESPONSE.md)): loopback bind, metrics not exposed by nginx, an
  external checkpoint downloaded and HMAC-verified on a separate machine, and a test alert with no journal
  contents. The checkpoint timer was still publishing hourly on 2026-10-01.

- [x] [#140 Measure server capacity and performance on staging (meeting items 4–6)](https://github.com/jsonrar/fyp-secure-file-platform/issues/140)
  — run on 2026-10-03/04, evidence merged in [PR #155](https://github.com/jsonrar/fyp-secure-file-platform/pull/155):
  22,264 operations, 5,094 SHA-256-verified downloads with 0 integrity failures, every type to 500 MiB
  byte-exact, no server error up to 50 concurrent users, the 15-connection DB pool is the first limit at 100.
  [Report](performance/REPORT-2026-10-03.md); conclusions in
  [docs/PERFORMANCE_TESTING.md](PERFORMANCE_TESTING.md). Transfer figures are bounded by the
  generator's home link; read the report's test conditions first.
  Re-run after the fixes on 2026-10-09 through the public URL (release `ac5e2b0`, HTTPS and nginx,
  limits on): 18,256 operations, 7,444 verified downloads with 0 integrity failures, 0 server 5xx;
  every request OK up to 50 users and 0 server errors at 100, where the only refusals were 429s from
  the per-address upload limit. [Report](performance/REPORT-2026-10-09.md). The 2026-10-03/04
  report stays as the before-fix baseline.
- [x] [#139 Two MySQL deadlocks under concurrent use return HTTP 500](https://github.com/jsonrar/fyp-secure-file-platform/issues/139)
  — fixed in [PR #154](https://github.com/jsonrar/fyp-secure-file-platform/pull/154) by retrying MySQL
  1213/1205; the regression test reproduced the deadlock ~7/10 times before the fix and never after.
  The #140 run saw no 1213 or 1205 in 28,540 requests.

- [x] ~~[#115 Run the non-expert usability study (WBS 5.4, NFR2)](https://github.com/jsonrar/fyp-secure-file-platform/issues/115)~~
  — **closed as not planned on 2026-10-04.** The team chose not to run the formal study. Instead the
  supervisor, the four team members, the FIT3162 Teaching Team and other students have used staging
  with their own accounts. That is informal real use: there is no SUS score, no per-task completion
  rate. The study kit (`docs/usability/` and the scoring script) was deleted on 2026-10-05; it is in the
  git history (PR #114) if a formal study is ever wanted.

- [x] A stalled pip download no longer hangs a deploy: per-attempt time limit, three attempts, and the
  build directory is removed on failure ([PR #196](https://github.com/jsonrar/fyp-secure-file-platform/pull/196)). `/usr/local/sbin/mcs21-deploy` is installed by hand.
- [x] Admin account details and login-password reset (temporary password shown once, sessions revoked,
  holder emailed), and a Settings card to change the login password ([PR #197](https://github.com/jsonrar/fyp-secure-file-platform/pull/197)).

## P2 — formal security assurance

- [x] [#90 Add an isolated VPS adversarial tamper drill with integrity evidence](https://github.com/jsonrar/fyp-secure-file-platform/issues/90)
  — a resource-limited attacker container sees only disposable lab volumes and a MySQL 8.4
  `_test` database. It proves `MODIFIED`/`CORRUPTED`, refused download, `MISSING`, recovery to
  `VALID`/`ACTIVE`, and the SHA-256 versus AEAD trust boundary; CI retains a sanitized report
  ([runbook](../security-lab/README.md)).

- [x] [#60 Complete the formal threat model and independent security review](https://github.com/jsonrar/fyp-secure-file-platform/issues/60)
  — complete in [THREAT_MODEL.md](THREAT_MODEL.md) v1.0: objectives and non-goals, STRIDE,
  measured Argon2id cost, key-custody, key-identity and metadata decisions, a review of supply chain,
  CSP, uploads, tokens and recovery operations, and a register of 20 findings with severity and
  disposition. It is a self-assessment with one peer review, not an independent external review,
  and certifies nothing. Register refreshed on 2026-10-01 (v1.1): F-10, F-11 and F-20 resolved, F-12
  partly and F-19 mitigated; F-01 mitigated the same day by CI-gated deploys (#117, below). Two
  *Recommended* findings remain unimplemented: F-02 recovery-key custody and F-03 disabling `/docs` on
  staging. F-04 weak-passphrase rejection was mitigated on 2026-10-08 ([PR #205](https://github.com/jsonrar/fyp-secure-file-platform/pull/205)).
  The current version is v1.5 (2026-10-09), which also records F-08 as mitigated by #212.

## P3 — planned product UX

Triaged into executable Issues on 2026-09-07 and placed in the shared backlog. These items are
not treated as closed by nearby UI polish; partial branch implementations are noted below.
Each Issue carries its acceptance criteria under [#61](https://github.com/jsonrar/fyp-secure-file-platform/issues/61).

- [x] [#72 Add secondary confirmation for destructive and high-risk actions](https://github.com/jsonrar/fyp-secure-file-platform/issues/72)
  — file deletion and share revocation use a dedicated consequence dialog; account deletion
  keeps the password + typed-`DELETE` dialog and is available from Profile as well as Settings.
- [x] [#71 Add authenticated ciphertext preview and encrypted-blob download](https://github.com/jsonrar/fyp-secure-file-platform/issues/71)
  — owners and authorized recipients can save the stored ciphertext without a passphrase (#78,
  refined in #79), and since 2026-10-01 each file has an **Encrypted preview**: exact sizes, the
  recorded SHA-256 and a hex dump of the first 128 bytes of ciphertext, with a check that the
  stored bytes do not begin like an unencrypted file of that type. The Issue had been closed
  without it; this completes the preview criterion. Still not done from the original wording: a
  mobile-layout test for these actions. Why the two sizes match, and how to show it, is in
  [docs/ENCRYPTION_EVIDENCE.md](ENCRYPTION_EVIDENCE.md).
- [x] [#73 Add file shelves and move-to-shelf organization in My Files](https://github.com/jsonrar/fyp-secure-file-platform/issues/73) — merged in #103 and deployed (staging's OpenAPI lists the folder routes, 2026-10-01). The Issue was closed 2026-09-29 without a written walkthrough of the affected flow.
  — create owner-scoped shelves and move owned files between them or root without changing
  encryption, sharing, file identity, or audit semantics.
- [x] [#54 Complete browser passphrase change, key-file reset, and successor-key rotation](https://github.com/jsonrar/fyp-secure-file-platform/issues/54)
  — **the key-file reset only** (#80): Settings verifies the saved private-key file against the
  account public key, re-seals it under a new AMK and passphrase, and proves possession with an
  RSA-PSS signature; plaintext private keys never leave the browser. Changing the passphrase while
  the current one is known followed on 2026-10-08 ([PR #201](https://github.com/jsonrar/fyp-secure-file-platform/pull/201)): the current passphrase opens the
  key in the browser and the same reseal-and-sign path runs, with a live test and a browser step.
  **Not implemented**, and not tracked as open work: successor-key rotation in the browser, the normative account-envelope specification, and browser E2E for the
  reset (searched `frontend/src` and `docs` on 2026-10-01). The Issue was closed with these
  unmet; the project owner chose to record that rather than reopen it. See the scope record on
  the Issue.
- [x] [#146 Help assistant: floating bot for how-to, how-it-works and comparison questions (no LLM in v1)](https://github.com/jsonrar/fyp-secure-file-platform/issues/146)
  — approved 2026-10-02 to come before #74. Client-side retrieval over curated intents and the
  existing Help/Education content; no network call, cited comparisons. Deployed, verified and closed
  on 2026-10-02. See [docs/HELP_ASSISTANT.md](HELP_ASSISTANT.md).
- [x] [#148 Help assistant v2: answer questions about the signed-in visitor's own account](https://github.com/jsonrar/fyp-secure-file-platform/issues/148)
  — seven read-only checks (who has access, a file's history, what I shared, what is shared with
  me, files marked Modified, recent activity, an overview) using the existing My Files and Access
  Records requests. No LLM; nothing is changed from the panel. Deployed, verified and closed on 2026-10-02.
- [x] [#74 Add persistent English and Simplified Chinese language switching](https://github.com/jsonrar/fyp-secure-file-platform/issues/74)
  — English / 简体中文 switcher in the header, the phone menu and Settings, remembered per device
  and restored before the first paint. Shared chrome uses keyed vue-i18n messages; the rest of the
  interface is shown in Chinese from a dictionary drafted at build time by Zhipu `glm-4-flash` and
  checked against the security glossary by script and test. **The Chinese is machine-drafted and
  has not had a full human review**, and the Help assistant still matches only English questions.
  See [docs/I18N.md](I18N.md).
- [x] [#75 Add validated user avatar upload and display](https://github.com/jsonrar/fyp-secure-file-platform/issues/75)
  — optional profile/header image with content validation, safe serving, cleanup, rate limits,
  and initials fallback. Merged (#101, #106) and deployed (the avatar routes are in staging's OpenAPI,
  2026-10-01); the short upload/display/delete walkthrough was not recorded on the Issue before it closed
  on 2026-09-29.
- [x] [#76 Fix mobile and narrow-viewport usability across product flows](https://github.com/jsonrar/fyp-secure-file-platform/issues/76)
  — repair narrow-screen layout and interaction regressions across public, account, and file
  flows, with repeatable mobile browser evidence. **Closed 2026-10-02.** An
  automated audit of 23 screens at 360 and 320 px found horizontal scrolling on four pages
  (education; registration, forgot-password and upload at 320 px), a My Files table that
  pushed its actions off a phone screen, 9–20 px footer links and dozens of other undersized
  targets; those are fixed (My Files is a card list below 768 px, every flagged target is at
  least 40 px, dialogs wrap long file names and fit the screen) and covered by three Chromium specs
  ([docs/E2E_TESTING.md](E2E_TESTING.md#phone-widths)). On 2026-10-02 the phone specs also passed
  in WebKit (Safari's engine) as an iPhone 13 and in Chromium as a Pixel 7. **Not done:** no run on a
  physical phone, and the notifications and settings flows were audited for layout only.

## Final presentation and FYP Award (12-minute talk)

Prioritised in [docs/presentation/REFLECTION.md](presentation/REFLECTION.md), where each item
has its problem, fix and effort. What to say, with evidence, is in
[docs/presentation/TALKING_POINTS.md](presentation/TALKING_POINTS.md).

Must do:

- [x] Demo script for a 4-minute live demo — [docs/presentation/DEMO_SCRIPT.md](presentation/DEMO_SCRIPT.md)
- [x] Demo accounts `demo-alice` / `demo-bob` created on staging (2026-10-04)
- [x] Record the backup video — [docs/presentation/media/demo-backup.mp4](presentation/media/demo-backup.mp4)
- [x] Re-record the Help videos `frontend/public/videos/encrypt-upload.mp4` and `share-open.mp4` and re-shoot the homepage
  picture guide for the upload page after [PR #215](https://github.com/jsonrar/fyp-secure-file-platform/pull/215) (2026-10-10)
- [ ] Re-record the backup video [docs/presentation/media/demo-backup.mp4](presentation/media/demo-backup.mp4): it still shows
  the upload page from before PR #215, and it has no Access history (AC5) or Security agent (AC8) step
- [x] On staging, upload `quarterly-results.txt` as `demo-alice` and share it with `demo-bob` (verified 2026-10-08: shared and active; needed for the live tamper step)
- [x] File-row actions: Download (decrypt), Share and Delete visible with labels, the rest under "More";
  fix the Help assistant button covering the row at ~800 px ([PR #159](https://github.com/jsonrar/fyp-secure-file-platform/pull/159))
- [x] Re-capture the homepage picture guide: its screenshots still showed the old six-icon row
  (refreshed 2026-10-04; step 5 now shows the recipient confirmation with the key fingerprint)
- [x] Live tamper demonstration: change one byte of stored ciphertext, the recipient's download fails —
  `backend/scripts/demo_tamper.py` and [docs/presentation/TAMPER_DEMO.md](presentation/TAMPER_DEMO.md)
- [ ] Slides: architecture diagram, encryption flow, requirements-status table, limitations (last)
- [x] UI redesign ("Sealed" style: warm paper, near-black ink, mint accent, Geist fonts), all features kept. Step 1 global
  style: done ([PR #176](https://github.com/jsonrar/fyp-secure-file-platform/pull/176)). Step 2 public pages: done ([PR #177](https://github.com/jsonrar/fyp-secure-file-platform/pull/177); dark hero, replace the Core Features card wall, keep Under the hood and the
  six-step guide). Step 3 app pages: sidebar, file detail panel, upload seal receipt, workspace and access records restyled (PRs #178, #180 and #182). Step 3 follow-up from the 10-05 audit: P1 centred headers, one content width, two-column Settings and Profile, sidebar on every signed-in page done ([#183](https://github.com/jsonrar/fyp-secure-file-platform/issues/183)); P2 (near-white dark primary, no pill labels, split sign-in layout) done ([#184](https://github.com/jsonrar/fyp-secure-file-platform/issues/184)); P3 (Access Records without failed requests, step-dot targets, 768px overflow) done in code ([#185](https://github.com/jsonrar/fyp-secure-file-platform/issues/185); the staging check of the SHA-256 is with the project lead). My Files details entry (whole row, file name and a Details button) and a non-modal side panel: done ([PR #193](https://github.com/jsonrar/fyp-secure-file-platform/pull/193)). Step 4 re-shot picture guide (English and Chinese), Help videos and the demo backup video: done ([#186](https://github.com/jsonrar/fyp-secure-file-platform/issues/186)); the slides are the project lead's own
- [x] State NFR2 (usability) honestly — TALKING_POINTS §10 (informal real use, no formal study)

Strongly recommended (Award):

- [x] Fix the DB-pool bottleneck, with a before/after measurement at 100 users (locally:
  80 % failed → 0 %, [PR #163](https://github.com/jsonrar/fyp-secure-file-platform/pull/163))
- [x] Re-run the #140 `steps` on staging after PR #163 deploys: 100 users went from 78 % failed uploads to 0 of 102 ([evidence](performance/pool-fix-2026-10-04/staging-rerun/REPORT.md))
- [x] Re-run the load matrix (all but the long soaks) after all fixes through the public URL (2026-10-09, release `ac5e2b0`): 100 users went from 65 to 78 % HTTP 500 uploads to 0 server errors, 7,444 verified downloads with 0 integrity failures, 36/36 files (six types, 1 to 500 MiB) byte-exact ([report](performance/REPORT-2026-10-09.md))
- [x] ~~#115 usability study with SUS~~ — not planned (#115 closed 2026-10-04); informal real use instead
- [x] Confirm the recipient before sharing, with their key fingerprint (key verification) —
  [PR #160](https://github.com/jsonrar/fyp-secure-file-platform/pull/160); threat model T-S5 now mitigated against a data writer
- [x] Upload abuse limits and the shared-program warning (threat model F-09) —
  [PR #157](https://github.com/jsonrar/fyp-secure-file-platform/pull/157); deployed with the nginx and env changes its PR lists

Optional:

- [x] Two-step registration and signing in straight after registering ([PR #161](https://github.com/jsonrar/fyp-secure-file-platform/pull/161))
- [x] First-login checklist (upload → share → recipient downloads) ([PR #162](https://github.com/jsonrar/fyp-secure-file-platform/pull/162))
- [x] OWASP ZAP baseline scan of staging plus `pip-audit` / `npm audit` report —
  [docs/security/scans-2026-10-04/](security/scans-2026-10-04/README.md); headers fixed in the tracked nginx file
- [x] Install the updated `nginx-secureview.conf` on the VPS and re-run the ZAP baseline (done 2026-10-04: 8 WARN → 5, 0 FAIL; [after-nginx](security/scans-2026-10-04/after-nginx/zap-baseline.md))

Done for the presentation:

- [x] Upload page shows the real encryption steps, measured times and a before/after byte sample
  ([PR #156](https://github.com/jsonrar/fyp-secure-file-platform/pull/156))

## Definition of done for each Issue

- The implementation and tests satisfy the Issue acceptance criteria.
- A reviewed PR links the Issue and updates the bilingual changelog.
- README/TODO and other design documents are updated when their statements changed; otherwise
  the PR says why they are `N/A`.
- All contributors use the shared changelog; do not create or extend personal or track-specific
  change logs.
- Secret and generated-artifact review passes before merge.
- For runtime changes, automatic deployment reaches the exact merged SHA and health plus the
  affected user-visible flow are verified. Merge alone is not deployment completion.
- The Issue closes only when the evidence above is linked.

## Explicitly deferred beyond the current FYP

- Google Drive-style collaborative editing, encrypted full-text search, and large-scale object
  storage optimization.
- Guaranteed support for files above 1 GB.
- DRM-like prevention of copies already made by recipients.
- Production KMS/HSM implementation and independent certification. Their design and custody
  requirements remain in scope for the security review.
