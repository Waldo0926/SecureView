# Security Agent

[English](SECURITY_AGENT.md) | [简体中文](SECURITY_AGENT.zh-CN.md)

The supervisor's guidance for the AI Agent item was that an agent must **solve a specific automation
problem, not just add a chat box**: define its input data, its rules or model, its output format
and its boundaries, and demonstrate Critical / High / Medium / Low classification with a
Recommended Action. This is that definition and what was built (Admin → **Security agent**).
v2 ([#137](https://github.com/jsonrar/fyp-secure-file-platform/issues/137)) added a daily run that
mails the team when anything is Critical or High, a rule for guessing that succeeded, and
visibility of sign-in throttle blocks.

## The problem it automates

The platform already records a lot: a hash-chained audit log, integrity checks, file status,
recovery requests. No administrator will read thousands of rows to notice that one account has been
guessed at, that a session token was reused, or that a stored file changed. The agent reads that
evidence for them and answers one question: **of everything that happened, what is worth my
attention now, how urgent is it, and what should I do?**

## What it is, and is not

| It is | It is not |
|---|---|
| **Rule-based and deterministic.** Every finding comes from a named rule with a stated threshold. The same evidence gives the same report, each rule is unit-tested against fabricated events, and an administrator can read exactly why something was flagged. | A language model judging logs. No model is asked anything, so nothing is guessed and no log leaves the server. |
| **Read-only.** It never writes, never changes a file or an account, and cannot execute a recovery. A test fails if its modules gain a database write path or an audit-append. | Allowed to "fix" things. It recommends; an administrator acts. |
| **Metadata only.** It reads event type, time, count, account name, source address and file identifier. | Able to see file contents, keys, passphrases or ciphertext. The queries select named columns only, and a test pins that. |
| **Honest about its limits.** Every report says how much it read, and a clean report says it is not proof that nothing happened. | A claim that everything is safe. It sees only what the platform recorded. |

## Input data

| Source | What is read |
|---|---|
| `audit_logs` (window: last 24 h or 7 days; at most 5,000 newest events per type, and the report says when a type hit that cap) | `AUTH_LOGIN_FAILED`, `AUTH_LOGIN_SUCCEEDED`, `AUTH_REFRESH_REPLAY_DETECTED`, `FILE_DOWNLOAD_AUTHORIZED`, `FILE_SHARED`, `AUTH_PASSWORD_CHANGE_FAILED`, `RECOVERY_REQUEST_EXECUTED`: action, time, account name and role, source address |
| the audit hash chain | Recomputed in full (`AuditQueryService.verify_chain`; the daily run uses `verify_chain_for_trusted_job`, the same check with no signed-in actor, which no HTTP route can reach): valid or not, and the first entry that fails |
| `auth_login_throttles` | How many address and account buckets are blocked right now (`blocked_until` in the future), per scope. Counts only: the keys are hashes and are never read |
| `integrity_checks` and `files` | Files that are `CORRUPTED` or whose newest check was `MODIFIED`, `MISSING` or `ERROR`, with each file's check history |
| `recovery_requests` | How many are still pending after 24 hours |
| integrity-scan coverage | When the last scan was recorded, how many files were never checked |

## Rules

| Rule | Watches | Raises |
|---|---|---|
| `INTEGRITY_DAMAGE` | Damaged stored files | **MODIFIED = Critical**, MISSING = High, ERROR = Medium |
| `AUDIT_CHAIN_BROKEN` | The audit hash chain | Any entry that does not verify = **Critical** |
| `SCAN_NOT_RUNNING` | When the last integrity scan ran | None in 36 h (or ever) while files exist = Medium |
| `LOGIN_GUESSING_SOURCE` | Failed sign-ins per source address, naming the accounts it tried | 10+ in 15 min = Medium, 30+ = High |
| `LOGIN_GUESSING_ACCOUNT` | Failed sign-ins against one account from **two or more** addresses | 10+ in 15 min = Medium |
| `SIGN_IN_AFTER_GUESSING` | A successful sign-in, against the failures in the 15 minutes before it on the **same account** or from the **same address** | 5+ either way = **High**, **Critical** if the account is an administrator |
| `SIGN_IN_THROTTLE_ACTIVE` | Sign-in throttle blocks in force now (counts only) | Any address blocked = Medium, accounts only = Low |
| `SESSION_TOKEN_REUSE` | A used refresh token presented again | Any = High |
| `DOWNLOAD_BURST` | Downloads per account | 20+ in 10 min = Medium, 60+ = High |
| `SHARE_BURST` | Shares per account | 10+ in an hour = Low |
| `UPLOAD_BURST` | Uploads per account | 30+ in 10 min = Medium, 100+ = High |
| `PASSWORD_CHANGE_GUESSING` | Failed password changes per account | 5+ in 15 min = Medium |
| `RECOVERY_EXECUTED` | Executed recoveries, requests waiting over a day | Executed = Medium, waiting = Low |

One address guessing at one account is one incident and is reported once, by the source rule,
with the account named in its evidence; the account rule is for guessing spread across addresses,
which the per-address view splits into pieces too small to notice.

`SIGN_IN_AFTER_GUESSING` is the most valuable detection: guessing that **worked** is a likely
account takeover. Counting failures by address as well as by account catches credential stuffing,
where one address tries many accounts and the one it gets into may have had no failure of its own.
A successful sign-in clears the account's throttle bucket, but the failures stay in the audit log, so
the rule still sees them. It does not double-report: the guessing itself may still appear as
`LOGIN_GUESSING_SOURCE` (that it happened and that it worked are two facts), but a second sign-in to the
same account on the same failures is added to the first finding, not raised again. Neither is a
sign-in to a *different* account from the same address on the same run of failures: one address that
tries many names and then gets into thirty accounts is one incident with thirty victims, so it is one
finding that lists the accounts (the first five and a count), with the whole run of failures and the
first and last sign-in time. It is Critical if any of those accounts is an administrator. The
2026-10-09 load test's cleanup showed why: 68 failures at already-deleted names and then 32 sign-ins
from one address gave 32 findings quoting the same failures, and the five real bursts were hard to see
under them. The price of the address count is that, behind a shared address (a campus NAT, the CI
runner), someone else's sign-in just after a guessing run is flagged too; the evidence says which count
fired, so an administrator can tell.

An account that is not active now (closed by its owner, or disabled by an administrator) is said so
in the evidence of a burst, guessing or takeover finding keyed on that account, and the advice changes
with it: a download, share or upload burst points at the Activity Log page, since there is no account
left to disable; guessing at its password gets "have the owner reset the password before enabling it
again", since nothing was reached while it stays inactive. The flag is the account's status now, not at
the time of the events, so the note does not claim an order. Findings keyed on an address never carry
it. Before this the finding named the `deleted-<hex>` tombstone and told the administrator to disable
it. The repository reads `users.status` for this; still no metadata, user agents or file contents.

### What the sign-in throttle hides

The throttle bounds what the audit log can show. Its policy (`backend/app/core/config.py`): an
**account** is blocked for **5 minutes** after **10** failures in 15 minutes; an **address** for
**15 minutes** after **500** (an address is a whole venue behind one NAT, see THREAT_MODEL §11.6). Attempts it refuses with 429 are **not audited**, on purpose: auditing
every 429 would let an attacker flood the hash-chained log, and every append takes the chain-head
lock. So while a block lasts, the rules above cannot see whether the guessing goes on.
`SIGN_IN_THROTTLE_ACTIVE` reads the throttle table instead and reports how many blocks are in force.
It is a rule of its own rather than extra evidence on the guessing findings because the throttle
keys are hashed: a count cannot be tied to one address or account, and printing it under one finding
would claim a link nobody can check. Being a snapshot of *now*, it mostly matters when an
administrator opens the tab during an attack; the daily run at 06:00 will rarely catch a block.

Bursts are measured with a sliding window: 40 failures spread over a day are not a burst; 10 in
five minutes are. The thresholds are constants at the top of
`backend/app/services/security_agent_rules.py`; changing one is a reviewed code change, and the
report states them.

Priority means: **Critical** act now, **High** act today, **Medium** look into it this week,
**Low** when convenient.

## Output format

`GET /api/v1/admin/agent/report?window_hours=24|168` (administrators only) returns, and the page shows:

```
generated_at, window_hours
counts:      critical / high / medium / low
findings[]:  rule_id, priority, title, summary,
             evidence[]            (why it was flagged: counts, accounts, addresses, times),
             recommended_action    (what to do),
             file_id?              (for file findings)
rules[]:     every rule, what it watches, its threshold, how many findings it raised this time
inputs:      audit events read, audit-chain entries verified, files checkable / never checked, last scan
boundaries[] what the agent will not do
```

## Proactive alerts (daily)

The tab only analyses when someone opens it, so the same analysis also runs every day:

- `backend/scripts/security_agent_check.py` builds the report for the last **24 hours** through
  `SecurityAgentService.report_for_scheduled_check` (no HTTP actor; the admin route's check is
  unchanged). It prints **only** counts per priority, the rule ids that fired and any capped event
  types, never a username, address, file name or finding title. It exits **3** when
  `critical + high > 0` (findings, not a crash) and 0 otherwise.
- `deployment/server/mcs21-security-agent.service` runs it as `fypapp` with
  `ProtectSystem=strict`, no write path, and the object store made inaccessible; `.timer` fires daily
  at **06:00 Asia/Kuala_Lumpur**, after the 05:30 integrity sweep, so a file the sweep has just found
  damaged is in the same morning's run (`Persistent=true` catches up after downtime).
- Exit 3 fails the unit, and `OnFailure=mcs21-alert@%n.service` sends the existing failure-alert mail.
  The mail still carries **no journal content**, only the unit's state and a fixed sentence: the
  security agent has Critical or High findings; open Admin → Security agent. The details stay behind
  the administrator login.
- **An unresolved Critical finding mails every day until it is fixed.** A damaged file that has not
  been restored, for example, fails the check each morning. That is intended: it is a reminder, not
  noise. Medium and Low findings never mail.
- **A load test trips it, and should.** `loadtest/` signs in dozens of throwaway accounts from one
  address and moves hundreds of files in minutes, which is exactly what the burst and guessing rules
  look for. The morning after the 2026-10-09 run (2026-10-10 06:00) the check exited 3 with 43 High
  findings: `UPLOAD_BURST` and `DOWNLOAD_BURST` for the five busiest test accounts, `LOGIN_GUESSING_SOURCE`
  for 68 sign-in attempts at accounts the first cleanup had already deleted, and `SIGN_IN_AFTER_GUESSING`
  for each of the 32 accounts that then signed in from that address (one finding since the merge
  described above). Every event carried the `secureview-loadtest/1.0` user agent and came from the
  tester's two home addresses, and the accounts had been deleted by the test's own cleanup. Nothing was
  changed on the server; the 24-hour window moves past the run by the next morning, so the check clears
  by itself. After a load test, expect that mail, and check the addresses and times against the test
  report before dismissing it.
- The units are on `mcs21-deploy`'s closed `ops_units` list, so a healthy release installs them like
  the integrity sweep ([AUTOMATIC_DEPLOYMENT.md](AUTOMATIC_DEPLOYMENT.md#ops-units-a-release-installs-by-itself)).
  That needs the current `mcs21-deploy` installed on the server by someone with root; see the
  operations note in #137.

## Recovery guidance for damaged files

For a damaged file the recommended action names the exact command (`scripts/restore_file.py --file-id
… `, always the dry run) and **which backup sets can hold the original**, worked out from the
file's own check history: sets taken between the upload and the last passing check *certainly* hold
it; sets up to when the damage was first seen *probably* do; a later set may already hold the damaged
bytes. `restore_file.py` checks the SHA-256 and refuses a set that does not match. This ties the agent
to the recovery flow in [BACKUP_AND_RECOVERY.md §9](BACKUP_AND_RECOVERY.md#9-finding-and-restoring-one-damaged-file)
without the agent being able to run it.

## Demonstration (with real events, nothing fabricated)

The audit log is append-only and hash-chained, so there is no way to inject fake events, and none is
wanted. To show each class:

1. **Medium, password guessing:** send ten wrong passwords for one account from one address. The
   sign-in throttle answers 429 after ten, and all ten are in the audit log, so the report shows one
   `LOGIN_GUESSING_SOURCE` naming the account, and `SIGN_IN_THROTTLE_ACTIVE` (Low) while the block lasts.
2. **High, guessing that worked:** five wrong passwords for an account, then the right one:
   `SIGN_IN_AFTER_GUESSING`. Do it for an administrator account and it is **Critical**.
3. **Critical, tampered file:** in the tamper lab (`security-lab/run.sh`) or a disposable stack,
   flip a byte of a stored object and press **Scan now** on the Integrity tab, then open **Security agent**:
   `INTEGRITY_DAMAGE` with the backup window and the restore command.
4. **High, missing object:** move an object out of storage and scan: `INTEGRITY_DAMAGE` as High,
   described as a storage problem, not tampering.
5. **Medium, detection not running:** on a deployment whose timer has not run in 36 hours.

## Tests

- `tests/unit/test_security_agent_rules.py`: each rule's thresholds, grading, attribution to the
  right source and account, ordering, determinism, the backup-window text, and that only the dry
  run is ever suggested; for v2, the five-failure threshold, administrator escalation, failures
  outside the span or after the success, no double counting, and the throttle grades.
- `tests/unit/test_security_agent_check.py`: the daily check's exit codes, and that its output holds
  no username, address or file name even when every finding is full of them.
- `tests/unit/test_ops_units.py`: the new unit passes `ops_unit_acceptable`, the allowlist is exactly
  the two units, and the timer runs at 06:00 after the sweep.
- `tests/unit/test_security_agent_service.py`: the window, which events are requested, how a check
  history becomes "last intact" and "damage first seen", admin-only access, the SQL selects named
  columns only (the throttle query never selects the hashed keys), the modules and the daily script
  have no write path, and no HTTP route reaches the trusted-job entry points.
- `frontend/src/e2e/live-stack.integration.test.ts` (CI `e2e-live`): ten real failed sign-ins against the running API become one ranked `LOGIN_GUESSING_SOURCE` finding with evidence and an action; five wrong passwords and then the right one for a fresh account become `SIGN_IN_AFTER_GUESSING`; an ordinary user is refused.
- `tests/integration/test_security_agent_mysql.py`: on real MySQL, a really tampered file is reported
  as Critical with its backup window, real failures followed by a real success are reported as
  `SIGN_IN_AFTER_GUESSING` (High, Critical for an administrator), and every query runs.
- `frontend/src/utils/agent-report.test.ts`: how findings are presented.

## Limits, and what comes next

- It sees only what is recorded. An attack that left no audit event is invisible to it.
- Source addresses behind a proxy are as good as the proxy headers the API trusts.
- It cannot see sign-in attempts the throttle refused (see above), only how many blocks are in force.
- There is no stored history of reports and no way to acknowledge a finding: that needs a schema
  change and a write path, so it is a separate decision. Until then an unresolved Critical finding
  mails daily.
- **A language-model layer is deliberately not part of the agent.** Its only plausible job would be rewording
  a finding for a non-technical reader, and that would send audit metadata (account names, addresses)
  to a third party. If it is ever added it should be optional, off by default, fed only the already
  redacted finding text, and never allowed to change a priority or take an action.
