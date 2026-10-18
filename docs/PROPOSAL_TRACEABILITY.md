# Proposal-to-Delivery Traceability

English | [简体中文](PROPOSAL_TRACEABILITY.zh-CN.md)

Originally audited on **2026-09-05** against the FIT3161 MCS21 Project Proposal Report, GitHub
`main`, all pull requests and commits, current repository tests, and the public staging
deployment. Repository and board records were rechecked on **2026-09-07**; that record-only
update did not re-verify the public deployment. Rechecked again on **2026-10-01** against `main`
at `70fcb6d`: the statuses below were refreshed from the Issues, the CI runs, the staging host and
the live site, and the public deployment was verified to be running that same SHA. The statuses
were rechecked on **2026-10-07** against `main` at `e4b3f13` (also the SHA deployed on staging
that day).

This is an evidence map, not a claim that every completed implementation has received final
academic or independent-security approval.

The live source of truth is the
[SecureView Development Board](https://github.com/users/Waldo0926/projects/1). Its five team views
separate active backlog, proposal WBS, milestones, acceptance criteria, and PR evidence. The PR
evidence view contains all 56 merged pull requests plus open PR #49 (the board was last synchronized
on 2026-09-07 and has not been re-synced since); closed, unmerged PRs #2,
#3, and #17 are intentionally excluded because they did not deliver code. Historical
direct-to-`main` CT work remains attributed by the exact commit table below and the archived
crypto-track record rather than a personal board view or fabricated PR history.

## Status rules

| Status | Evidence rule | Completion value |
| --- | --- | ---: |
| Backlog | Required by the proposal, but no implementation/test artefact was found | 0% |
| Ready | Defined and prioritised, but implementation has not started | 10% |
| In progress | Partial implementation or evidence exists; acceptance is not complete | 50% |
| In review | Implementation exists, but an explicit review/sign-off artefact is missing | 90% |
| Done | Repository/deployment evidence satisfies the stated work package | 100% |

Commits are evidence for work packages; they are not treated as independent tasks. GitHub
Issues and PRs share one number sequence. On 2026-10-01 the repository had **95 PRs**: 87 merged,
two open and six closed without merge (#2, #3, #17, #95, #97, #100). The rechecked `70fcb6d`
`main` baseline contains 241 commits. On 2026-10-07 there were **168 PRs** (158 merged, 10 closed
without merge, none open) and `main` at `e4b3f13` contains 317 commits.

## Proposal WBS audit

| WBS | Work package | Status | Primary evidence or remaining gap |
| --- | --- | --- | --- |
| 1.1 | Functional and non-functional requirements | Done | Proposal Sections 3–4; `docs/PROJECT_SCOPE.md`; PR #62 |
| 1.2 | Scope definition and supervisor review | Done | Supervisor reviewed the MVP demonstration, signed the submitted proposal material, accepted the checkpoint, and assessed the whole project as approximately 70–80% complete at that time |
| 1.3 | Goals and core vision | Done | README goal and deployed product |
| 2.1 | Competitive analysis | Done | Proposal background study and selected differentiators |
| 2.2 | Privacy and OWASP threat modelling | Done | [THREAT_MODEL.md](THREAT_MODEL.md) v1.0: STRIDE threat model, measured Argon2id cost, key-custody and metadata decisions, and a 20-item findings register (Issue #60). A self-assessment with one peer review — no independent external review took place |
| 2.3 | Target users and stakeholders | Done | Proposal stakeholders and implemented user/RBAC roles |
| 3.1 | UI/UX and Figma prototypes | Done | Implemented/deployed user journeys and PR #46 |
| 3.2 | REST API and FastAPI module design | Done | `docs/API_DESIGN.md` and public OpenAPI/Swagger contract |
| 3.3 | MySQL schema and migration design | Done | Alembic head `0011_must_change_password`, production SQL, PRs #1, #24, #103, #106 and #145 |
| 3.4 | AES/RSA hybrid workflow design | Done | `docs/SECURITY_FLOWS.md` and authenticated envelope implementation |
| 3.5 | Educational-page design | Done | `/education`, algorithm explorer, playground and knowledge search |
| 4.1 | Vue frontend | Done | Vue 3/TypeScript application, tests, typecheck and build |
| 4.2 | FastAPI backend modules | Done | Auth, keys, files and folders, sharing, audit, admin (statistics, account details, integrity, security agent) and recovery APIs |
| 4.3 | MySQL and Alembic implementation | Done | MySQL 8.4 staging, migrations and least-privilege production SQL |
| 4.4 | AES-GCM encryption | Done | Browser AES-128/192/256-GCM (CT-1.7) and AES-256-GCM-SIV (#145), alongside ChaCha20-Poly1305 and XChaCha20-Poly1305 |
| 4.5 | RSA-OAEP key wrapping | Done | Owner/recovery/recipient DEK wrapping; PR #34 |
| 4.6 | SHA-256 and tamper detection | Done | Authenticated envelope, download verification and integrity UX |
| 4.7 | Argon2id and protected private keys | Done | Password hashing and browser-protected account-key bundles |
| 4.8 | RBAC and session management | Done | Server enforcement, refresh rotation, logout revocation (#89), and role-aware admin/recovery UI (#55) |
| 4.9 | Audit logging | Done | Hash-chained events, per-file history and corrected visibility rules |
| 5.1 | Functional and end-to-end testing | Done | `e2e-live` runs every live-backend suite un-skipped and a Chromium golden-path test; `mysql-gate` runs the whole suite against MySQL 8.4 with concurrency and fault-injection and fails on any skip; a tamper drill runs in CI (Issues #53, #58, #90, #93); further Chromium specs cover the tamper view, phone widths, the Help assistant and the language switch; staging was load-tested on 2026-10-03/04 (#140) and the 100-user failure fixed and re-run (#163, #172); after the fixes the load test was re-run through the public URL on 2026-10-09 with 0 server errors at 100 users and 0 integrity failures in 7,444 verified downloads ([report](performance/REPORT-2026-10-09.md)). Still not a long-running chaos test |
| 5.2 | Cryptographic correctness testing | Done | Primitive, envelope, tamper, upload/download and live integration tests |
| 5.3 | OWASP and security testing | In review | Hardening/regression tests, the isolated tamper drill, the OWASP ZAP baseline scan (2026-10-04, repeated 2026-10-12, 0 FAIL both times) and the [THREAT_MODEL.md](THREAT_MODEL.md) self-assessment with one peer review exist (Issue #60). What is still missing for Done is an **independent external review**: nobody outside the team has reviewed the threat model or tested the deployment. Also open: F-01 is mitigated by CI-gated deployment (#117) and two *Recommended* findings (F-02, F-03) are open; F-04 was mitigated by #205 |
| 5.4 | Non-expert usability testing | Done | Evidence is informal real use, not a formal study: the supervisor, the four team members, the FIT3162 Teaching Team and other students used staging with their own accounts, and what they ran into was fixed in the open (for example #209: error styles, integrity check progress, the key relocking while someone was still working, Chinese wording). The formal study was **not run** (Issue #115 closed as not planned on 2026-10-04), so there is no SUS score and no per-task completion rate, and NFR2 is never described as formally verified. The study kit was deleted on 2026-10-05 (it is in the git history, PR #114) |

**WBS summary:** 23 Done, 1 In review, 0 In progress, 0 Backlog (5.4 moved to Done on 2026-10-09 on
the informal-use evidence above). The simple board completion average is 99.6% (23 × 100 + 90,
over 24); this is a tracking indicator, not an assessment
mark or effort-weighted earned value. The 2026-09-07 summary of 20 Done, 3 In progress and
1 Backlog (89.6%) disagreed with its own table, which already showed 21 Done.

## Milestone audit

| Milestone | Status | Evidence or exit condition |
| --- | --- | --- |
| M1 Scope finalised | Done | Assessed proposal and maintained scope artefacts |
| M2 REST API contract | Done | Documented and live OpenAPI contract |
| M3 Figma prototypes reviewed | Done | Supervisor reviewed the MVP/UI demonstration, signed the submitted material, accepted the checkpoint, and assessed the whole project as approximately 70–80% complete at that time; the interfaces are now also implemented and deployed |
| M4 Core cryptographic modules | Done | AES, RSA, SHA/integrity, Argon2id and ChaCha20 implementations/tests |
| M5 Feature freeze | Done | Browser MVP complete; remaining work explicitly classified as hardening/assurance |
| M6 Full system integration | Done | Public HTTPS stack and live two-account MVP test |
| M7 Final demo readiness | Done | The P0 CI, MySQL and backup blockers are closed with evidence; demo script, scripted tamper demo, pre-shared demo file and backup video exist (#167, #164, #173); the last acceptance criterion (AC7) closed with #200. Usability has informal real use only; the formal study (#115) was closed as not planned |

**Milestone summary:** all 7 Done. The supervisor's 70–80% assessment is evidence
for the completed historical checkpoint, not a claim that the current repository has an exact
70–80% completion value.

## Chen Tai cryptography contribution traceability

The nine CT work packages were delivered directly to `main` before the team adopted reviewed
pull requests. They are already ancestors of current `main`; they must not be cherry-picked or
merged again. The shared table below attributes every package to **Chen Tai** through its exact
commit; `changelog/work-packages/crypto-track.md` remains a read-only historical archive. New CT
and other contributor work belongs in the team changelog, README, and TODO rather than a separate
personal tracking view.

| Package | Verified scope | Commit |
| --- | --- | --- |
| CT-1.0 | Prepared the cryptography development environment and documentation; no application or cryptography implementation changed | [`9593e753`](https://github.com/jsonrar/fyp-secure-file-platform/commit/9593e753ecadfcc37f3afb56c5f1f92bf3aaea29) |
| CT-1.1 | Audited the existing cryptography baseline and recorded limitations; no new primitive was implemented | [`99e2f972`](https://github.com/jsonrar/fyp-secure-file-platform/commit/99e2f972862c55d5f39d066152bb491cac8164bc) |
| CT-1.2 | Implemented browser cryptographic primitives | [`415202e6`](https://github.com/jsonrar/fyp-secure-file-platform/commit/415202e661b8c8da30b40458424a8361d6febdb5) |
| CT-1.3 | Defined and validated the encrypted-file envelope | [`9f89ea56`](https://github.com/jsonrar/fyp-secure-file-platform/commit/9f89ea56867ec086f1d2a721942a10c4868a128d) |
| CT-1.4 | Completed encrypted browser upload | [`8e174c6e`](https://github.com/jsonrar/fyp-secure-file-platform/commit/8e174c6e10ff601e06b8f60243ec8b64e8369380) |
| CT-1.5 | Provisioned recovery-key wrapping | [`f3c36a20`](https://github.com/jsonrar/fyp-secure-file-platform/commit/f3c36a20aa88fd8395b224a9b495d745dc1be62e) |
| CT-1.6 | Connected the encrypted-file list | [`aa4e8589`](https://github.com/jsonrar/fyp-secure-file-platform/commit/aa4e858965c61af06e2390bff2a8d55092abfd84) |
| CT-1.7 | Added selectable AES key lengths | [`e04f5fcd`](https://github.com/jsonrar/fyp-secure-file-platform/commit/e04f5fcdd170e1dad2c62b91139af93a02da97fe) |
| CT-1.8 | Added ChaCha20-Poly1305 | [`6c8821a5`](https://github.com/jsonrar/fyp-secure-file-platform/commit/6c8821a5dd00edc58b8c6dce7ef7a5bad749b4a9) |

Current-code regression evidence is stronger than the historical commit messages alone: the
targeted frontend primitive, envelope, upload, download and sharing suite passes **147 tests**,
and the targeted backend migration/model/production-SQL suite passes **10 tests**. This does not
replace the remaining required CI, browser E2E, MySQL or independent-security evidence.

## Product acceptance audit

| Criterion | Status | Evidence or remaining gap |
| --- | --- | --- |
| AC1 Registration and protected RSA private key | Done | Browser key generation and protected private-key bundle |
| AC2 Algorithm choice and ciphertext-only upload | Done | Six selectable authenticated ciphers and client-side encryption; the upload shows the real encryption steps and a plaintext-vs-ciphertext byte comparison (#156) |
| AC3 Recipient decrypts with own passphrase | Done | Recipient-key rewrap and live two-account proof; the sender confirms the recipient's key fingerprint before sharing (#160) |
| AC4 Tamper detection before successful decrypt | Done | Authenticated decryption/integrity refusal and UI error |
| AC4a Recovery after tampering (teacher's integrity-and-recovery ask) | Done | Daily sweep (installed automatically from a healthy release, #134; runs 05:30 on staging), admin Integrity tab, `restore_file.py`, drill step in `mysql-gate` (BACKUP_AND_RECOVERY §9); live tamper demonstration (#164) |
| AC8 AI agent that solves a defined automation problem (supervisor's guidance) | Done (v2, rule-based) | Admin → Security agent: inputs, thirteen rules, Critical/High/Medium/Low output with recommended actions, stated boundaries; v2 (#137) runs it daily and mails the team on Critical/High findings, detects a sign-in that succeeded after guessing, and reports active sign-in throttle blocks — [SECURITY_AGENT.md](SECURITY_AGENT.md) |
| AC5 Timestamped actor/access audit | Done | Upload/download/share/revoke events and per-file history |
| AC6 Interactive crypto education | Done | AES/RSA/SHA/Argon2id content and playgrounds |
| AC7 Dismissible four-stage progress pipeline | Done | Four measured stages (#156): read the file → encrypt and self-check → wrap the file key → upload the ciphertext, then complete; the receipt closes with its close button once nothing is running (#200), checked in the golden-path browser test |

## Immediate evidence priorities

1. Security sign-off (WBS 5.3): an independent external review is the one thing missing.
   Non-expert usability (WBS 5.4) is Done on informal real use; describe NFR2 that way, never as
   formally verified (the formal study, Issue #115, was closed as not planned).
2. Decide the two open *Recommended* security findings (F-02, F-03): move the recovery key into
   proposed custody, and switch off `/docs` after the demo. (F-01, CI-gated deployment, was done on
   2026-10-01; F-04, rejecting known-weak passphrases, on 2026-10-08 in #205.)
3. Time the 4-hour whole-service recovery on a fresh VPS (follow-up from Issue #56).

Done since the 2026-10-01 recheck: the staging capacity and performance test (#140, PR #155), the
two concurrency deadlocks (#139, PR #154), and the 100-user database-pool failure with its staging
re-run (PR #163, #172), the after-fix load test through the public URL on 2026-10-09
([report](performance/REPORT-2026-10-09.md)), and the AC7 close button (#200).

These records should be updated in the same PR that changes their evidence. A runtime change is
not Done until the merged SHA is deployed and the affected live path is verified.
