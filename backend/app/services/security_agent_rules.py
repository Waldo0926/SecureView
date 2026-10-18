"""The rules of the SecureView security agent: what it looks at, what it decides, how it ranks.

The agent turns the evidence the platform already keeps -- the hash-chained audit log, the
integrity-check history, file status and recovery requests -- into a short, ranked list of
things an administrator should do something about. It exists to answer one question: *of
everything that happened, which is worth my attention now, how urgent is it, and what do I do?*

What it is, deliberately:

* **Deterministic.** Every finding is produced by a named rule with a stated threshold, from
  counts and timestamps. The same evidence gives the same report, a rule can be unit-tested
  against fabricated events, and an administrator can read exactly why something was flagged. No
  model is asked to judge anything, so nothing is guessed and nothing leaves the server.
* **Read-only.** It never writes, never changes a file or an account, and cannot execute a
  recovery. It recommends; a person acts.
* **Metadata only.** Its inputs are event types, times, counts, account names, source addresses
  and file identifiers. It never sees file contents, keys, passphrases or ciphertext.

This module is pure: it takes an `AgentInputs` snapshot and returns findings, so the rules are
tested without a database. `SecurityAgentService` gathers the snapshot.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.core.time import site_stamp


class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


_PRIORITY_ORDER = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}

# --- thresholds, in one place so the report can state them and a change is reviewed ----------
LOGIN_FAILURE_SPAN = timedelta(minutes=15)
LOGIN_FAILURES_MEDIUM = 10
LOGIN_FAILURES_HIGH = 30
SIGN_IN_AFTER_FAILURES = 5  # failures in LOGIN_FAILURE_SPAN before a success, per account or source
DOWNLOAD_SPAN = timedelta(minutes=10)
DOWNLOADS_MEDIUM = 20
DOWNLOADS_HIGH = 60
SHARE_SPAN = timedelta(hours=1)
SHARES_LOW = 10
UPLOAD_SPAN = timedelta(minutes=10)
UPLOADS_MEDIUM = 30
UPLOADS_HIGH = 100
PASSWORD_FAILURE_SPAN = timedelta(minutes=15)
PASSWORD_FAILURES_MEDIUM = 5
SWEEP_STALE_AFTER = timedelta(hours=36)
RECOVERY_PENDING_AFTER = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Event:
    """One audit event reduced to what the rules need."""

    at: datetime
    actor: str | None = None  # account name, when the event had one
    source: str | None = None  # source address, when the event had one
    admin: bool = False  # the account is an administrator
    # False once the account has been closed by its owner or disabled by an administrator. The
    # events still count (a burst is a burst), but "disable the account" is no advice for one
    # that is already gone, and the deleted-… tombstone name alone does not explain itself.
    active: bool = True


@dataclass(frozen=True, slots=True)
class DamagedFile:
    file_id: str
    filename: str
    owner: str
    status: str
    last_result: str | None
    uploaded_at: datetime
    last_valid_at: datetime | None  # newest VALID check before the damage was first seen
    first_failure_at: datetime | None  # when the current run of failing checks began


@dataclass(frozen=True, slots=True)
class AgentInputs:
    now: datetime
    window: timedelta
    login_failures: Sequence[Event] = ()
    login_successes: Sequence[Event] = ()
    refresh_replays: Sequence[Event] = ()
    downloads: Sequence[Event] = ()
    shares: Sequence[Event] = ()
    uploads: Sequence[Event] = ()
    password_failures: Sequence[Event] = ()
    recoveries_executed: Sequence[Event] = ()
    recoveries_pending_old: int = 0
    damaged: Sequence[DamagedFile] = ()
    chain_valid: bool | None = None  # None: not checked
    chain_first_invalid_position: int | None = None
    chain_checked_entries: int = 0
    last_sweep_at: datetime | None = None
    checkable_files: int = 0
    never_checked_files: int = 0
    # Sign-in throttle buckets blocked right now. The throttle keeps only hashes of the address
    # and the account name, so these are counts and nothing more.
    throttled_addresses: int = 0
    throttled_accounts: int = 0
    throttle_policy: str = ""


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    priority: Priority
    title: str
    summary: str
    evidence: tuple[str, ...]
    recommended_action: str
    file_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuleInfo:
    rule_id: str
    name: str
    watches: str
    threshold: str


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    info: RuleInfo
    findings: int


def max_in_span(times: Sequence[datetime], span: timedelta) -> tuple[int, datetime | None]:
    """The most events that fall inside any window of length `span`, and when that peak began."""
    ordered = sorted(times)
    best, best_start, left = 0, None, 0
    for right, moment in enumerate(ordered):
        while moment - ordered[left] > span:
            left += 1
        if right - left + 1 > best:
            best, best_start = right - left + 1, ordered[left]
    return best, best_start


def _stamp(value: datetime) -> str:
    return site_stamp(value)


def _plural(count: int, noun: str) -> str:
    if count == 1:
        return f"{count} {noun}"
    return f"{count} {noun}{'es' if noun.endswith(('s', 'sh', 'ch', 'x')) else 's'}"


def _group(
    events: Sequence[Event], key: Callable[[Event], str | None]
) -> dict[str, list[datetime]]:
    grouped: dict[str, list[datetime]] = defaultdict(list)
    for event in events:
        label = key(event)
        if label:
            grouped[label].append(event.at)
    return grouped


# --- the rules --------------------------------------------------------------------------------


def backup_window_advice(file: DamagedFile) -> str:
    """Which backup sets can hold the original, from when the file was last known good.

    A backup set is named by the UTC time it was taken, while every time here is Kuala Lumpur
    time (MYT, UTC+8), so the advice says so. The object was intact when it was last
    checked VALID, so sets taken up to then certainly hold the original; sets taken up to when
    the damage was first seen probably do; later sets may already hold the damaged bytes, and
    `restore_file.py` refuses any set whose copy does not match the recorded SHA-256.
    """
    uploaded = _stamp(file.uploaded_at)
    if file.last_valid_at is None:
        start = (
            "This file has no passing check on record, so it cannot be said when it was last "
            f"intact. Try the earliest backup set taken after the upload ({uploaded}) first."
        )
    else:
        start = (
            f"Backup sets taken between the upload ({uploaded}) and {_stamp(file.last_valid_at)} "
            "certainly hold the original."
        )
    if file.first_failure_at is not None:
        end = (
            f" Sets taken up to {_stamp(file.first_failure_at)}, when the damage was first seen, "
            "probably do. A later set may already hold the damaged bytes."
        )
    else:
        end = " A set taken after the damage began may already hold the damaged bytes."
    return (
        start
        + end
        + " Backup set names are in UTC, 8 hours behind MYT."
        + " restore_file.py checks the SHA-256 and refuses a set that does not match. "
        "If the file was uploaded after the newest nightly backup, no set holds it yet."
    )


def rule_integrity(inputs: AgentInputs) -> list[Finding]:
    findings: list[Finding] = []
    for file in inputs.damaged:
        if file.last_result == "MISSING":
            priority, what = Priority.HIGH, "its encrypted object is missing from storage"
            cause = (
                "A missing object is usually a storage problem (an unmounted volume) or a "
                "deletion; it proves nothing about the contents."
            )
        elif file.last_result == "ERROR":
            priority, what = Priority.MEDIUM, "its encrypted object could not be read"
            cause = "An unreadable object is a storage problem, not evidence of tampering."
        else:
            priority = Priority.CRITICAL
            what = "its stored bytes no longer match the recorded SHA-256"
            cause = (
                "Modified ciphertext is evidence about the bytes themselves; treat it as tampering."
            )
        evidence = [
            f"File {file.filename} (owner {file.owner}), status {file.status}",
            f"Latest check: {file.last_result or 'marked corrupted earlier'}",
        ]
        if file.first_failure_at is not None:
            evidence.append(f"Damage first seen {_stamp(file.first_failure_at)}")
        if file.last_valid_at is not None:
            evidence.append(f"Last intact check {_stamp(file.last_valid_at)}")
        findings.append(
            Finding(
                rule_id="INTEGRITY_DAMAGE",
                priority=priority,
                title=f"{file.filename}: {what}",
                summary=cause,
                evidence=tuple(evidence),
                recommended_action=(
                    "Restore the original with scripts/restore_file.py "
                    f"--file-id {file.file_id} (run without --apply first; the Integrity tab "
                    "shows the exact command). By default it reads the server's nightly backup; "
                    "an encrypted off-site set is the fallback. " + backup_window_advice(file)
                ),
                file_id=file.file_id,
            )
        )
    return findings


def rule_audit_chain(inputs: AgentInputs) -> list[Finding]:
    if inputs.chain_valid is not False:
        return []
    return [
        Finding(
            rule_id="AUDIT_CHAIN_BROKEN",
            priority=Priority.CRITICAL,
            title="The audit log's hash chain does not verify",
            summary=(
                "Every audit entry is chained to the one before it, so a row that was changed, "
                "removed or inserted breaks the chain from that point on."
            ),
            evidence=(
                f"First entry that fails: position {inputs.chain_first_invalid_position}",
                f"Entries verified before it: {inputs.chain_checked_entries}",
            ),
            recommended_action=(
                "Treat this as a possible database compromise. Stop deploying, keep the database "
                "as it is, compare the chain head with the latest external checkpoint "
                "(scripts/audit_checkpoint.py verify) and follow the incident runbook "
                "(docs/OBSERVABILITY_AND_INCIDENT_RESPONSE.md)."
            ),
        )
    ]


def rule_detection_running(inputs: AgentInputs) -> list[Finding]:
    if inputs.checkable_files == 0:
        return []
    stale = inputs.last_sweep_at is None or inputs.now - inputs.last_sweep_at > SWEEP_STALE_AFTER
    if not stale:
        return []
    last = "never" if inputs.last_sweep_at is None else _stamp(inputs.last_sweep_at)
    return [
        Finding(
            rule_id="SCAN_NOT_RUNNING",
            priority=Priority.MEDIUM,
            title="The daily integrity scan has not run recently",
            summary=(
                "Tampering with a file nobody opens is only found by the scan, so without it "
                "this report cannot say the stored files are intact."
            ),
            evidence=(
                f"Last scan recorded: {last}",
                f"{_plural(inputs.never_checked_files, 'file')} never checked, "
                f"{inputs.checkable_files} checkable",
            ),
            recommended_action=(
                "Run “Scan now” on the Integrity tab, then check that the timer is active on the "
                "server: systemctl status mcs21-integrity-sweep.timer."
            ),
        )
    ]


def _burst_findings(
    *,
    rule_id: str,
    events: Sequence[Event],
    key: Callable[[Event], str | None],
    span: timedelta,
    medium: int | None,
    high: int | None,
    low: int | None = None,
    title: Callable[[str, int], str],
    summary: str,
    action: Callable[[str], str],
    describe_subject: str,
    extra_evidence: Callable[[str], list[str]] | None = None,
    inactive_action: Callable[[str], str] | None = None,
) -> list[Finding]:
    """One finding per subject whose busiest `span` reaches a threshold.

    `inactive_action` replaces `action` when the subject is an account that is no longer active:
    telling the administrator to disable an account that its owner already closed, or that an
    administrator already disabled, would send them looking for a button that is not there.
    """
    findings: list[Finding] = []
    minutes = int(span.total_seconds() // 60)
    # Only account-keyed rules pass `inactive_action`; for a rule keyed by address the flag
    # would describe whichever account was tried, which is not the finding's subject.
    inactive = {key(e) for e in events if not e.active and key(e)} if inactive_action else set()
    for subject, times in sorted(_group(events, key).items()):
        peak, began = max_in_span(times, span)
        if high is not None and peak >= high:
            priority = Priority.HIGH
        elif medium is not None and peak >= medium:
            priority = Priority.MEDIUM
        elif low is not None and peak >= low:
            priority = Priority.LOW
        else:
            continue
        window_text = f"{_plural(peak, 'event')} within {minutes} minutes"
        if began is not None:
            window_text += f", starting {_stamp(began)}"
        closed = subject in inactive
        findings.append(
            Finding(
                rule_id=rule_id,
                priority=priority,
                title=title(subject, peak),
                summary=summary,
                evidence=(
                    f"{describe_subject}: {subject}",
                    window_text,
                    f"{_plural(len(times), 'event')} in the whole analysis window",
                    *(extra_evidence(subject) if extra_evidence else ()),
                    *((INACTIVE_ACCOUNT_NOTE,) if closed else ()),
                ),
                recommended_action=(
                    inactive_action(subject) if closed and inactive_action else action(subject)
                ),
            )
        )
    return findings


# The flag is the account's status now, not at the time of the events: a disabled account can be
# guessed at after it was disabled, so the note does not say when.
INACTIVE_ACCOUNT_NOTE = (
    "This account is not active now: it has been closed by its owner or disabled by an "
    "administrator"
)


def _inactive_burst_action(subject: str) -> str:
    """For the download, share and upload bursts: the account did reach things."""
    return (
        f"{subject} is already closed or disabled, so there is nothing to switch off. Check the "
        "Activity Log page for what it reached and whether any share it made still needs "
        "revoking. If the burst was your own test run, no action is needed."
    )


def _inactive_guessing_action(subject: str) -> str:
    """For guessing at an account's password: nothing was reached while it stays inactive."""
    return (
        f"{subject} is not active, so the guessing cannot get in while it stays that way. If it "
        "is a disabled account you mean to enable again, have its owner reset the password "
        "first. The Audit chain tab shows whether any attempt on it succeeded."
    )


def _accounts_tried(events: Sequence[Event], source: str) -> list[str]:
    """Which accounts one address tried, so the source finding also names its targets."""
    named = sorted({e.actor for e in events if e.source == source and e.actor})
    unknown = sum(1 for e in events if e.source == source and not e.actor)
    lines: list[str] = []
    if named:
        shown = ", ".join(named[:5]) + (f" and {len(named) - 5} more" if len(named) > 5 else "")
        lines.append(f"Accounts tried: {shown}")
    if unknown:
        lines.append(f"{_plural(unknown, 'attempt')} at names with no account")
    return lines


def rule_login_guessing_by_source(inputs: AgentInputs) -> list[Finding]:
    return _burst_findings(
        rule_id="LOGIN_GUESSING_SOURCE",
        events=inputs.login_failures,
        key=lambda e: e.source,
        span=LOGIN_FAILURE_SPAN,
        medium=LOGIN_FAILURES_MEDIUM,
        high=LOGIN_FAILURES_HIGH,
        title=lambda s, n: f"{n} failed sign-ins from {s}",
        summary=(
            "Many failed sign-ins from one address in a short time is what password guessing "
            "looks like."
        ),
        action=lambda s: (
            f"Check whether {s} is expected (a colleague, a test run). If not, block it at the "
            "firewall or with fail2ban; the sign-in throttle already slows it but does not stop it."
        ),
        describe_subject="Source address",
        extra_evidence=lambda s: _accounts_tried(inputs.login_failures, s),
    )


def rule_login_guessing_by_account(inputs: AgentInputs) -> list[Finding]:
    """Guessing at one account from **several** addresses.

    Guessing from a single address is already reported, with the accounts it tried, by the
    source rule. Reporting the same ten failures a second time under the account only doubled
    the count for one incident. What only this rule can see is an account tried from many
    places, which the per-address view splits into pieces too small to notice.
    """
    sources: dict[str, set[str]] = defaultdict(set)
    for event in inputs.login_failures:
        if event.actor and event.source:
            sources[event.actor].add(event.source)
    distributed = [e for e in inputs.login_failures if e.actor and len(sources[e.actor]) >= 2]
    return _burst_findings(
        rule_id="LOGIN_GUESSING_ACCOUNT",
        events=distributed,
        key=lambda e: e.actor,
        span=LOGIN_FAILURE_SPAN,
        medium=LOGIN_FAILURES_MEDIUM,
        high=None,
        title=lambda s, n: f"{n} failed sign-ins against account {s} from several addresses",
        summary=(
            "One account is being tried from more than one address, which spreads the attempts "
            "so that no single address looks busy."
        ),
        action=lambda s: (
            f"Ask the owner of {s} whether it was them. If not, disable the account on the Users "
            "tab (this also ends its sessions) and have them reset the password before enabling it."
        ),
        describe_subject="Account",
        inactive_action=_inactive_guessing_action,
        extra_evidence=lambda s: [f"From {_plural(len(sources[s]), 'address')}"],
    )


@dataclass(slots=True)
class _Takeover:
    success: Event
    on_account: int
    from_source: int
    failures: set[int]
    first_failure: datetime
    source_set: set[str]
    last_success: datetime
    later_successes: int = field(default=0)  # same account again, no new failures between
    repeat_successes: int = field(default=0)  # same account again while the failures went on
    # Other accounts that signed in from the same address on the same run of failures: one
    # address stuffing many accounts is one incident with many victims, not many incidents.
    other_accounts: list[Event] = field(default_factory=list)

    @property
    def admin(self) -> bool:
        return self.success.admin or any(e.admin for e in self.other_accounts)

    @property
    def inactive(self) -> bool:
        return not self.success.active or any(not e.active for e in self.other_accounts)


def _extend(
    incident: _Takeover,
    success: Event,
    matched: set[int],
    failures: Sequence[Event],
    from_source: set[int],
) -> None:
    """Fold one more success, and the failures it saw, into an open incident."""
    incident.failures |= matched
    incident.first_failure = min(incident.first_failure, failures[min(matched)].at)
    incident.from_source = sum(
        1 for i in incident.failures if failures[i].source == incident.success.source
    )
    incident.source_set |= {failures[i].source for i in matched if failures[i].source}
    incident.last_success = success.at


def rule_sign_in_after_guessing(inputs: AgentInputs) -> list[Finding]:
    """A sign-in that succeeded right after a run of failures: guessing that may have worked.

    For each success, the failures in the `LOGIN_FAILURE_SPAN` before it are counted two ways:
    against the same account, and from the same source address. Either reaching
    `SIGN_IN_AFTER_FAILURES` fires. The account count catches guessing spread over several
    addresses; the address count catches credential stuffing, where one address tries many
    accounts and the one it got into may have had no failure of its own.

    A successful sign-in clears the account's throttle bucket, but not the audit log, so the
    failures are still here to count.

    One incident is reported once. A later success to the same account whose failures were all
    counted already (the intruder signing in a second time, say) is added to that finding instead
    of raising another. So is a success to a *different* account from the same address on the
    same failures: one address that tries many names and then gets into thirty accounts is one
    incident with thirty victims, and thirty findings that all quote the same 68 failures only
    bury the rest of the report (the 2026-10-09 load test did exactly this). The accounts are
    listed in the one finding so each owner can still be asked. The guessing itself may still be
    reported by LOGIN_GUESSING_SOURCE or LOGIN_GUESSING_ACCOUNT: that the guessing happened and
    that it worked are different facts.
    """
    failures = sorted(inputs.login_failures, key=lambda e: e.at)
    times = [e.at for e in failures]
    incidents: list[_Takeover] = []
    latest: dict[str, _Takeover] = {}
    for success in sorted(inputs.login_successes, key=lambda e: e.at):
        lo = bisect_left(times, success.at - LOGIN_FAILURE_SPAN)
        hi = bisect_right(times, success.at)
        on_account = {
            i for i in range(lo, hi) if success.actor and failures[i].actor == success.actor
        }
        from_source = {
            i for i in range(lo, hi) if success.source and failures[i].source == success.source
        }
        if max(len(on_account), len(from_source)) < SIGN_IN_AFTER_FAILURES:
            continue
        matched = on_account | from_source
        key = success.actor or ""
        previous = latest.get(key)
        if previous is not None and matched <= previous.failures:
            previous.later_successes += 1
            continue
        if previous is not None and matched & previous.failures:
            # The same account again while the guessing at it went on: the same incident.
            _extend(previous, success, matched, failures, from_source)
            previous.repeat_successes += 1
            continue
        same_run = next(
            (
                i
                for i in incidents
                if success.source
                and i.success.source == success.source
                and len(on_account) < SIGN_IN_AFTER_FAILURES
                and len(from_source) >= SIGN_IN_AFTER_FAILURES
                and from_source & i.failures
            ),
            None,
        )
        if same_run is not None:
            # A sign-in explained only by the address's run of failures (not by failures on its
            # own account), from the same address as an open incident, on the same run, perhaps
            # still growing while the sign-ins happen: extend that incident rather than open
            # another. An account that was guessed at directly keeps its own finding, with its
            # own "N against this account" count, even from that address.
            _extend(same_run, success, matched, failures, from_source)
            if any(success.actor == e.actor for e in same_run.other_accounts):
                same_run.repeat_successes += 1
            else:
                same_run.other_accounts.append(success)
            latest[key] = same_run
            continue
        incident = _Takeover(
            success=success,
            on_account=len(on_account),
            from_source=len(from_source),
            failures=matched,
            first_failure=min(failures[i].at for i in matched),
            source_set={failures[i].source for i in matched if failures[i].source},
            last_success=success.at,
        )
        latest[key] = incident
        incidents.append(incident)

    findings: list[Finding] = []
    for incident in incidents:
        success = incident.success
        account = success.actor or "an unknown account"
        others = incident.other_accounts
        evidence = [
            f"Account: {account}" + (" (administrator)" if success.admin else ""),
            f"{_plural(len(incident.failures), 'failed sign-in')} between "
            f"{_stamp(incident.first_failure)} and "
            f"{'the last of these sign-ins' if others else 'the success'}: "
            f"{incident.on_account} against this account, {incident.from_source} from the "
            "address that then signed in",
            f"Failures came from {_plural(len(incident.source_set), 'address')}",
            (
                f"Sign-ins between {_stamp(success.at)} and {_stamp(incident.last_success)} from "
                f"{success.source}"
                if others
                else f"Successful sign-in at {_stamp(success.at)} from "
                f"{success.source or 'an unrecorded address'}"
            ),
        ]
        if others:
            names = [e.actor or "an unknown account" for e in others]
            shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
            admins = sum(1 for e in others if e.admin)
            evidence.append(
                f"{_plural(len(others), 'other account')} signed in from the same address on the "
                f"same run of failures: {shown}"
                + (f" ({_plural(admins, 'administrator')} among them)" if admins else "")
            )
        which = "these accounts" if others else "this account"
        if incident.later_successes:
            evidence.append(
                f"{_plural(incident.later_successes, 'more sign-in')} to {which} after that, "
                "with no new failures"
            )
        if incident.repeat_successes:
            evidence.append(
                f"{_plural(incident.repeat_successes, 'more sign-in')} to {which} while the "
                "failures went on"
            )
        if incident.inactive:
            evidence.append(
                "At least one of these accounts is not active now: closed by its owner or "
                "disabled by an administrator"
            )
        if others:
            title = (
                f"{account} and {_plural(len(others), 'other account')} signed in from "
                f"{success.source} right after a run of failed sign-ins"
            )
            whom = f"the owners of {account} and the other accounts listed"
            disable = "disable each account that was not its owner on the Users tab"
        else:
            title = f"{account} signed in right after a run of failed sign-ins"
            whom = f"the owner of {account}"
            disable = "disable the account on the Users tab"
        findings.append(
            Finding(
                rule_id="SIGN_IN_AFTER_GUESSING",
                priority=Priority.CRITICAL if incident.admin else Priority.HIGH,
                title=title,
                summary=(
                    "A sign-in succeeded straight after repeated failures. If the failures were "
                    "someone guessing, the guess worked: this is what an account takeover looks "
                    "like."
                ),
                evidence=tuple(evidence),
                recommended_action=(
                    f"Confirm with {whom} that it was them. If it was not, {disable} (this ends "
                    "its sessions), have them reset the password, and review the account's "
                    f"Activity Log from {_stamp(success.at)} onwards."
                    + (
                        " An account that is already closed cannot be disabled; its Activity "
                        "Log still shows what it reached."
                        if incident.inactive
                        else ""
                    )
                ),
            )
        )
    return findings


def rule_sign_in_throttle_active(inputs: AgentInputs) -> list[Finding]:
    """Sign-in throttle blocks in force now, which the audit log cannot show.

    Attempts the throttle refuses with 429 are deliberately not audited (an attacker could
    otherwise flood the hash-chained log), so while a block lasts the rules above cannot see
    whether the guessing goes on. This is a rule of its own rather than extra evidence on the
    guessing findings because the throttle keys are hashed: a count cannot be tied to any one
    address or account, and printing it under one would claim a link nobody can check.
    """
    addresses, accounts = inputs.throttled_addresses, inputs.throttled_accounts
    if not addresses and not accounts:
        return []
    evidence = [
        f"Blocked right now: {_plural(addresses, 'address')}, {_plural(accounts, 'account')}",
        "Attempts refused while blocked are not in the audit log, so they are not counted "
        "anywhere in this report",
    ]
    if inputs.throttle_policy:
        evidence.append(f"Throttle policy: {inputs.throttle_policy}")
    return [
        Finding(
            rule_id="SIGN_IN_THROTTLE_ACTIVE",
            priority=Priority.MEDIUM if addresses else Priority.LOW,
            title=(
                f"The sign-in throttle is blocking {_plural(addresses, 'address')} and "
                f"{_plural(accounts, 'account')}"
            ),
            summary=(
                "Someone failed to sign in often enough to be blocked. An address block takes "
                "many failures, so it is rarely a user who forgot a password."
            ),
            evidence=tuple(evidence),
            recommended_action=(
                "Look at the failed sign-in findings in this report, or the Audit chain tab, for "
                "the guessing that caused it. A block ends by itself; an address that keeps "
                "getting blocked should be blocked at the firewall or with fail2ban."
            ),
        )
    ]


def rule_refresh_replay(inputs: AgentInputs) -> list[Finding]:
    findings: list[Finding] = []
    by_actor = _group(inputs.refresh_replays, lambda e: e.actor or "unknown account")
    for actor, times in sorted(by_actor.items()):
        known = actor != "unknown account"
        findings.append(
            Finding(
                rule_id="SESSION_TOKEN_REUSE",
                priority=Priority.HIGH,
                title=f"A used session token was presented again for {actor}",
                summary=(
                    "Session tokens are single-use. Seeing one a second time means a copy of it "
                    "exists somewhere it should not, which is how a stolen session looks."
                ),
                evidence=(
                    f"Account: {actor}",
                    f"{_plural(len(times), 'replay')}, latest {_stamp(max(times))}",
                ),
                recommended_action=(
                    f"The server already revoked that session family. Ask {actor} to sign in again "
                    "and change their password; if it recurs, disable the account on the Users tab."
                    if known
                    else "Check the Audit chain tab for the matching events and the source address."
                ),
            )
        )
    return findings


def rule_download_burst(inputs: AgentInputs) -> list[Finding]:
    return _burst_findings(
        rule_id="DOWNLOAD_BURST",
        events=inputs.downloads,
        key=lambda e: e.actor,
        span=DOWNLOAD_SPAN,
        medium=DOWNLOADS_MEDIUM,
        high=DOWNLOADS_HIGH,
        title=lambda s, n: f"{s} downloaded {n} files in minutes",
        summary=(
            "An unusually fast run of downloads can be someone copying everything an account can "
            "reach. It can also be a legitimate bulk download."
        ),
        action=lambda s: (
            f"Ask {s} whether this was them. The Activity Log page lists exactly what was "
            "downloaded. If it was not them, disable the account on the Users tab."
        ),
        describe_subject="Account",
        inactive_action=_inactive_burst_action,
    )


def rule_share_burst(inputs: AgentInputs) -> list[Finding]:
    return _burst_findings(
        rule_id="SHARE_BURST",
        events=inputs.shares,
        key=lambda e: e.actor,
        span=SHARE_SPAN,
        medium=None,
        high=None,
        low=SHARES_LOW,
        title=lambda s, n: f"{s} shared files {n} times in an hour",
        summary="A burst of sharing widens who can read the account's files.",
        action=lambda s: (
            f"Check {s}'s shares on the Activity Log page and revoke any that are not intended."
        ),
        describe_subject="Account",
        inactive_action=_inactive_burst_action,
    )


def rule_upload_burst(inputs: AgentInputs) -> list[Finding]:
    return _burst_findings(
        rule_id="UPLOAD_BURST",
        events=inputs.uploads,
        key=lambda e: e.actor,
        span=UPLOAD_SPAN,
        medium=UPLOADS_MEDIUM,
        high=UPLOADS_HIGH,
        title=lambda s, n: f"{s} uploaded {n} files in minutes",
        summary=(
            "An unusually fast run of uploads can be someone trying to fill the server's disk or "
            "load it. The per-account storage and daily limits cap how much gets stored; this "
            "shows who is pushing against them. It can also be a legitimate bulk upload."
        ),
        action=lambda s: (
            f"Ask {s} whether this was them. If it was not, or it continues, disable the account "
            "on the Users tab."
        ),
        describe_subject="Account",
        inactive_action=_inactive_burst_action,
    )


def rule_password_change_failures(inputs: AgentInputs) -> list[Finding]:
    return _burst_findings(
        rule_id="PASSWORD_CHANGE_GUESSING",
        events=inputs.password_failures,
        key=lambda e: e.actor,
        span=PASSWORD_FAILURE_SPAN,
        medium=PASSWORD_FAILURES_MEDIUM,
        high=None,
        title=lambda s, n: f"{n} failed password checks on {s}",
        summary=(
            "Changing a password or closing the account needs the current one. Repeated "
            "failures from a signed-in session suggest someone is guessing it from a session "
            "they should not have."
        ),
        action=lambda s: (
            f"Contact {s} to check their session. If it was not them, disable the account on the "
            "Users tab, which ends its sessions."
        ),
        describe_subject="Account",
        inactive_action=_inactive_guessing_action,
    )


def rule_recovery(inputs: AgentInputs) -> list[Finding]:
    findings: list[Finding] = []
    for event in sorted(inputs.recoveries_executed, key=lambda e: e.at):
        who = event.actor or "an administrator"
        findings.append(
            Finding(
                rule_id="RECOVERY_EXECUTED",
                priority=Priority.MEDIUM,
                title="A file recovery was executed",
                summary=(
                    "Recovery re-wraps a file's key for a new holder using the offline recovery "
                    "key. It is meant to be rare and to follow a request."
                ),
                evidence=(f"Executed by {who} at {_stamp(event.at)}",),
                recommended_action=(
                    "Confirm the file's owner asked for it, using the request on the Recovery "
                    "requests tab and the audit entries around that time."
                ),
            )
        )
    if inputs.recoveries_pending_old:
        count = inputs.recoveries_pending_old
        findings.append(
            Finding(
                rule_id="RECOVERY_EXECUTED",
                priority=Priority.LOW,
                title=f"{_plural(count, 'recovery request')} waiting over a day",
                summary="Someone asked to regain access to a file and nobody has answered.",
                evidence=(f"{_plural(count, 'request')} pending for more than 24 hours",),
                recommended_action=(
                    "Review the queue on the Recovery requests tab and approve or reject each one."
                ),
            )
        )
    return findings


RULES: tuple[tuple[RuleInfo, Callable[[AgentInputs], list[Finding]]], ...] = (
    (
        RuleInfo(
            "INTEGRITY_DAMAGE",
            "Damaged stored files",
            "Files whose newest integrity check is MODIFIED, MISSING or ERROR, or whose status "
            "is CORRUPTED",
            "Any file. MODIFIED is critical, MISSING high, ERROR medium",
        ),
        rule_integrity,
    ),
    (
        RuleInfo(
            "AUDIT_CHAIN_BROKEN",
            "Audit log tampering",
            "Recomputes the whole audit hash chain",
            "Any entry that does not verify is critical",
        ),
        rule_audit_chain,
    ),
    (
        RuleInfo(
            "SCAN_NOT_RUNNING",
            "Detection is running",
            "When the last integrity scan was recorded",
            "No scan in 36 hours (or ever) while files exist is medium",
        ),
        rule_detection_running,
    ),
    (
        RuleInfo(
            "LOGIN_GUESSING_SOURCE",
            "Password guessing from one address",
            "Failed sign-ins, grouped by source address",
            f"{LOGIN_FAILURES_MEDIUM}+ in 15 minutes is medium, {LOGIN_FAILURES_HIGH}+ high",
        ),
        rule_login_guessing_by_source,
    ),
    (
        RuleInfo(
            "LOGIN_GUESSING_ACCOUNT",
            "Password guessing against one account",
            "Failed sign-ins against one account from two or more addresses",
            f"{LOGIN_FAILURES_MEDIUM}+ in 15 minutes is medium",
        ),
        rule_login_guessing_by_account,
    ),
    (
        RuleInfo(
            "SIGN_IN_AFTER_GUESSING",
            "Guessing that worked",
            "Successful sign-ins, against the failures in the 15 minutes before them on the same "
            "account or from the same address",
            f"{SIGN_IN_AFTER_FAILURES}+ failures before a success is high, critical for an "
            "administrator",
        ),
        rule_sign_in_after_guessing,
    ),
    (
        RuleInfo(
            "SIGN_IN_THROTTLE_ACTIVE",
            "Sign-in blocks in force",
            "Sign-in throttle buckets blocked right now (counts only; the keys are hashed)",
            "Any blocked address is medium, blocked accounts only low",
        ),
        rule_sign_in_throttle_active,
    ),
    (
        RuleInfo(
            "SESSION_TOKEN_REUSE",
            "Stolen session",
            "Refresh tokens presented after they were already used",
            "Any replay is high",
        ),
        rule_refresh_replay,
    ),
    (
        RuleInfo(
            "DOWNLOAD_BURST",
            "Bulk downloading",
            "Authorised downloads, grouped by account",
            f"{DOWNLOADS_MEDIUM}+ in 10 minutes is medium, {DOWNLOADS_HIGH}+ high",
        ),
        rule_download_burst,
    ),
    (
        RuleInfo(
            "SHARE_BURST",
            "Burst of sharing",
            "File shares, grouped by account",
            f"{SHARES_LOW}+ in an hour is low",
        ),
        rule_share_burst,
    ),
    (
        RuleInfo(
            "UPLOAD_BURST",
            "Burst of uploads",
            "File uploads, grouped by account",
            f"{UPLOADS_MEDIUM}+ in 10 minutes is medium, {UPLOADS_HIGH}+ high",
        ),
        rule_upload_burst,
    ),
    (
        RuleInfo(
            "PASSWORD_CHANGE_GUESSING",
            "Guessing the current password",
            "Failed password changes and account-closing checks, grouped by account",
            f"{PASSWORD_FAILURES_MEDIUM}+ in 15 minutes is medium",
        ),
        rule_password_change_failures,
    ),
    (
        RuleInfo(
            "RECOVERY_EXECUTED",
            "Recovery activity",
            "Executed recoveries, and requests pending over 24 hours",
            "An executed recovery is medium, a request waiting over a day is low",
        ),
        rule_recovery,
    ),
)


def evaluate(inputs: AgentInputs) -> tuple[list[Finding], list[RuleOutcome]]:
    """Run every rule. Returns the findings, most urgent first, and how many each rule raised."""
    findings: list[Finding] = []
    outcomes: list[RuleOutcome] = []
    for info, rule in RULES:
        raised = rule(inputs)
        findings.extend(raised)
        outcomes.append(RuleOutcome(info, len(raised)))
    findings.sort(key=lambda f: (_PRIORITY_ORDER[f.priority], f.rule_id, f.title))
    return findings, outcomes
