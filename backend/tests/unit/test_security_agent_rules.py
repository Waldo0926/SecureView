"""The security agent's rules, against fabricated evidence: thresholds, ranking, and advice."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.time import site_stamp
from app.services.security_agent_rules import (
    RULES,
    AgentInputs,
    DamagedFile,
    Event,
    Priority,
    backup_window_advice,
    evaluate,
    max_in_span,
)

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _events(count: int, *, every: timedelta, actor="mallory", source="203.0.113.7", start=None):
    start = start or NOW - timedelta(hours=1)
    return [Event(at=start + i * every, actor=actor, source=source) for i in range(count)]


def _inputs(**kwargs) -> AgentInputs:
    return AgentInputs(now=NOW, window=timedelta(hours=24), **kwargs)


def _titles(findings):
    return [finding.title for finding in findings]


def _damaged(**over) -> DamagedFile:
    values = {
        "file_id": "11111111-1111-4111-8111-111111111111",
        "filename": "report.pdf",
        "owner": "alice",
        "status": "CORRUPTED",
        "last_result": "MODIFIED",
        "uploaded_at": NOW - timedelta(days=5),
        "last_valid_at": NOW - timedelta(days=2),
        "first_failure_at": NOW - timedelta(hours=3),
    }
    values.update(over)
    return DamagedFile(**values)


def test_a_quiet_system_produces_no_findings_and_says_which_rules_ran() -> None:
    findings, outcomes = evaluate(
        _inputs(chain_valid=True, last_sweep_at=NOW - timedelta(hours=5), checkable_files=4)
    )

    assert findings == []
    assert [outcome.info.rule_id for outcome in outcomes] == [info.rule_id for info, _ in RULES]
    assert all(outcome.findings == 0 for outcome in outcomes)


def test_the_sliding_window_finds_the_densest_stretch_not_the_total() -> None:
    spread = [NOW + timedelta(minutes=10 * i) for i in range(12)]  # 12 events, never 3 in 15 min
    burst = [NOW + timedelta(seconds=5 * i) for i in range(8)]

    assert max_in_span(spread, timedelta(minutes=15))[0] == 2
    peak, began = max_in_span(spread + burst, timedelta(minutes=15))
    assert peak >= 8 and began is not None
    assert max_in_span([], timedelta(minutes=1)) == (0, None)


def test_login_guessing_is_graded_by_how_fast_and_how_many() -> None:
    quiet = _events(9, every=timedelta(minutes=1))
    assert evaluate(_inputs(login_failures=quiet))[0] == []

    medium = _events(12, every=timedelta(minutes=1))
    findings, _ = evaluate(_inputs(login_failures=medium))
    assert [(f.rule_id, f.priority) for f in findings] == [
        ("LOGIN_GUESSING_SOURCE", Priority.MEDIUM)
    ]

    high = _events(35, every=timedelta(seconds=20))
    findings, _ = evaluate(_inputs(login_failures=high))
    assert [(f.rule_id, f.priority) for f in findings] == [("LOGIN_GUESSING_SOURCE", Priority.HIGH)]


def test_one_address_guessing_one_account_is_one_finding_that_names_the_account() -> None:
    findings, _ = evaluate(
        _inputs(login_failures=_events(12, every=timedelta(minutes=1), actor="alice"))
    )

    (finding,) = findings
    assert "Accounts tried: alice" in finding.evidence


def test_the_source_finding_counts_attempts_at_names_that_do_not_exist() -> None:
    events = _events(6, every=timedelta(minutes=1), actor=None) + _events(
        6, every=timedelta(minutes=1), actor="bob"
    )

    (finding,) = evaluate(_inputs(login_failures=events))[0]

    assert "Accounts tried: bob" in finding.evidence
    assert "6 attempts at names with no account" in finding.evidence


def test_an_account_tried_from_many_addresses_is_caught_even_when_no_address_is_busy() -> None:
    spread = [
        Event(
            at=NOW - timedelta(minutes=10) + timedelta(seconds=30 * i),
            actor="alice",
            source=f"198.51.100.{i}",
        )
        for i in range(12)
    ]

    findings, _ = evaluate(_inputs(login_failures=spread))

    assert [f.rule_id for f in findings] == ["LOGIN_GUESSING_ACCOUNT"]
    assert "From 12 addresses" in findings[0].evidence


def test_slow_guessing_that_never_bunches_up_is_not_flagged() -> None:
    slow = _events(40, every=timedelta(minutes=5))  # 40 failures a day, 3 per 15 minutes

    assert evaluate(_inputs(login_failures=slow))[0] == []


def test_guessing_is_attributed_to_the_right_source_and_account() -> None:
    a = _events(12, every=timedelta(minutes=1), actor="alice", source="198.51.100.1")
    b = _events(3, every=timedelta(minutes=1), actor="bob", source="198.51.100.2")

    findings, _ = evaluate(_inputs(login_failures=a + b))

    text = " ".join(" ".join(f.evidence) for f in findings)
    assert "198.51.100.1" in text and "198.51.100.2" not in text
    assert "alice" in text and "bob" not in text


def test_a_modified_file_is_critical_and_names_the_backup_window() -> None:
    findings, outcomes = evaluate(_inputs(damaged=[_damaged()]))

    (finding,) = findings
    assert finding.priority is Priority.CRITICAL and finding.rule_id == "INTEGRITY_DAMAGE"
    assert finding.file_id == "11111111-1111-4111-8111-111111111111"
    assert (
        "scripts/restore_file.py --file-id 11111111-1111-4111-8111-111111111111"
        in finding.recommended_action
    )
    assert "certainly hold the original" in finding.recommended_action
    assert "2026-09-30 20:00 MYT" in finding.recommended_action  # last intact check
    assert "2026-10-02 17:00 MYT" in finding.recommended_action  # damage first seen
    assert next(o for o in outcomes if o.info.rule_id == "INTEGRITY_DAMAGE").findings == 1


def test_missing_and_unreadable_objects_rank_below_modified_ones_and_are_not_called_tampering() -> (
    None
):
    findings, _ = evaluate(
        _inputs(
            damaged=[
                _damaged(file_id="a" * 8 + "-1111-4111-8111-111111111111", last_result="ERROR"),
                _damaged(file_id="b" * 8 + "-1111-4111-8111-111111111111", last_result="MISSING"),
                _damaged(),
            ]
        )
    )

    assert [f.priority for f in findings] == [Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM]
    assert "not evidence of tampering" in findings[2].summary
    assert "proves nothing about the contents" in findings[1].summary


def test_advice_without_a_known_good_check_says_so_and_still_gives_a_starting_point() -> None:
    advice = backup_window_advice(_damaged(last_valid_at=None, first_failure_at=None))

    assert "no passing check on record" in advice
    assert "earliest backup set taken after the upload" in advice
    assert "no set holds it yet" in advice


def test_a_broken_chain_is_critical_and_says_not_to_deploy() -> None:
    findings, _ = evaluate(
        _inputs(chain_valid=False, chain_first_invalid_position=41, chain_checked_entries=40)
    )

    (finding,) = findings
    assert finding.priority is Priority.CRITICAL and finding.rule_id == "AUDIT_CHAIN_BROKEN"
    assert "position 41" in " ".join(finding.evidence)
    assert "Stop deploying" in finding.recommended_action


def test_an_unchecked_chain_is_not_reported_as_broken() -> None:
    assert evaluate(_inputs(chain_valid=None))[0] == []
    assert evaluate(_inputs(chain_valid=True))[0] == []


def test_a_stale_or_missing_scan_is_flagged_only_when_there_is_something_to_scan() -> None:
    assert evaluate(_inputs(last_sweep_at=None, checkable_files=0))[0] == []

    never, _ = evaluate(_inputs(last_sweep_at=None, checkable_files=3, never_checked_files=3))
    assert [f.rule_id for f in never] == ["SCAN_NOT_RUNNING"] and never[
        0
    ].priority is Priority.MEDIUM
    assert "never" in " ".join(never[0].evidence)

    old, _ = evaluate(_inputs(last_sweep_at=NOW - timedelta(hours=40), checkable_files=3))
    assert [f.rule_id for f in old] == ["SCAN_NOT_RUNNING"]
    recent, _ = evaluate(_inputs(last_sweep_at=NOW - timedelta(hours=35), checkable_files=3))
    assert recent == []


def test_a_replayed_session_token_is_high_and_grouped_per_account() -> None:
    replays = [Event(at=NOW - timedelta(minutes=m), actor="alice") for m in (5, 3)] + [
        Event(at=NOW - timedelta(minutes=1), actor=None)
    ]

    findings, _ = evaluate(_inputs(refresh_replays=replays))

    assert [f.priority for f in findings] == [Priority.HIGH, Priority.HIGH]
    assert any("2 replays" in " ".join(f.evidence) for f in findings)
    assert any("Check the Audit chain tab" in f.recommended_action for f in findings)


def test_bulk_downloading_is_medium_then_high() -> None:
    medium = _events(25, every=timedelta(seconds=10), actor="carol")
    high = _events(70, every=timedelta(seconds=5), actor="dave")

    findings, _ = evaluate(_inputs(downloads=medium + high))

    by_actor = {f.title.split()[0]: f.priority for f in findings}
    assert by_actor == {"carol": Priority.MEDIUM, "dave": Priority.HIGH}


def test_sharing_bursts_and_password_guessing_have_their_own_grades() -> None:
    shares = _events(11, every=timedelta(minutes=2), actor="erin")
    password = _events(5, every=timedelta(minutes=1), actor="frank")

    findings, _ = evaluate(_inputs(shares=shares, password_failures=password))

    by_rule = {f.rule_id: f.priority for f in findings}
    assert by_rule == {"SHARE_BURST": Priority.LOW, "PASSWORD_CHANGE_GUESSING": Priority.MEDIUM}


def test_upload_bursts_are_graded_and_a_normal_pace_is_quiet() -> None:
    normal = _events(29, every=timedelta(seconds=20), actor="grace")  # 29 in 10 min: under
    medium = _events(30, every=timedelta(seconds=20), actor="heidi")
    high = _events(100, every=timedelta(seconds=5), actor="ivan")

    findings, _ = evaluate(_inputs(uploads=normal + medium + high))

    by_actor = {f.title.split()[0]: (f.rule_id, f.priority) for f in findings}
    assert by_actor == {
        "heidi": ("UPLOAD_BURST", Priority.MEDIUM),
        "ivan": ("UPLOAD_BURST", Priority.HIGH),
    }


def test_recovery_activity_is_reported_and_old_requests_are_a_low_notice() -> None:
    findings, _ = evaluate(
        _inputs(
            recoveries_executed=[Event(at=NOW - timedelta(hours=2), actor="admin")],
            recoveries_pending_old=2,
        )
    )

    assert [f.priority for f in findings] == [Priority.MEDIUM, Priority.LOW]
    assert "2 recovery requests waiting" in findings[1].title


def test_the_report_is_ordered_most_urgent_first() -> None:
    findings, _ = evaluate(
        _inputs(
            login_failures=_events(12, every=timedelta(minutes=1)),
            damaged=[_damaged()],
            refresh_replays=[Event(at=NOW, actor="alice")],
            shares=_events(11, every=timedelta(minutes=2), actor="erin"),
        )
    )

    priorities = [f.priority for f in findings]
    assert priorities == sorted(
        priorities,
        key=lambda p: [Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM, Priority.LOW].index(p),
    )
    assert priorities[0] is Priority.CRITICAL and priorities[-1] is Priority.LOW


def test_the_same_evidence_always_gives_the_same_report() -> None:
    inputs = _inputs(login_failures=_events(12, every=timedelta(minutes=1)), damaged=[_damaged()])

    assert evaluate(inputs)[0] == evaluate(inputs)[0]


def test_the_agent_only_ever_suggests_the_dry_run_of_a_restore() -> None:
    findings, _ = evaluate(_inputs(damaged=[_damaged()]))

    for finding in findings:
        # "run without --apply first" is the instruction; a command that applies is never given.
        text = finding.recommended_action.replace("without --apply", "")
        assert "--apply" not in text


# --- v2: a sign-in that worked after guessing, and throttle blocks ---------------------------


def _success(at=None, *, actor="victim", source="203.0.113.7", admin=False) -> Event:
    return Event(at=at or NOW - timedelta(minutes=30), actor=actor, source=source, admin=admin)


def _takeovers(findings):
    return [f for f in findings if f.rule_id == "SIGN_IN_AFTER_GUESSING"]


def test_a_sign_in_after_five_failures_on_the_account_is_high_and_four_is_nothing() -> None:
    success = _success()
    start = success.at - timedelta(minutes=5)

    four = _events(
        4, every=timedelta(seconds=30), actor="victim", source="198.51.100.1", start=start
    )
    assert _takeovers(evaluate(_inputs(login_failures=four, login_successes=[success]))[0]) == []

    five = _events(
        5, every=timedelta(seconds=30), actor="victim", source="198.51.100.1", start=start
    )
    (finding,) = _takeovers(evaluate(_inputs(login_failures=five, login_successes=[success]))[0])
    assert finding.priority == Priority.HIGH
    assert finding.title == "victim signed in right after a run of failed sign-ins"
    text = " ".join(finding.evidence)
    assert "5 failed sign-ins" in text and "5 against this account, 0 from the address" in text
    assert "Failures came from 1 address" in text
    assert "from 203.0.113.7" in text  # where the success came from
    assert "disable the account on the Users tab" in finding.recommended_action
    assert "Activity Log" in finding.recommended_action


def test_five_failures_from_the_same_address_at_other_accounts_also_fire() -> None:
    # Credential stuffing: one address tries several accounts, then gets into one of them,
    # which itself had no failed attempt.
    success = _success(actor="carol", source="203.0.113.50")
    tried = [
        Event(
            at=success.at - timedelta(minutes=4, seconds=i * 20), actor=name, source="203.0.113.50"
        )
        for i, name in enumerate(["a1", "a2", "a3", "a4", None])
    ]

    (finding,) = _takeovers(evaluate(_inputs(login_failures=tried, login_successes=[success]))[0])
    assert "0 against this account, 5 from the address that then signed in" in " ".join(
        finding.evidence
    )


def test_an_administrator_signing_in_after_guessing_is_critical() -> None:
    success = _success(actor="root-admin", admin=True)
    failures = _events(
        6, every=timedelta(seconds=10), actor="root-admin", start=success.at - timedelta(minutes=2)
    )

    (finding,) = _takeovers(
        evaluate(_inputs(login_failures=failures, login_successes=[success]))[0]
    )
    assert finding.priority == Priority.CRITICAL
    assert "Account: root-admin (administrator)" in finding.evidence


def test_failures_older_than_the_span_or_after_the_success_do_not_count() -> None:
    success = _success()
    old = _events(
        10, every=timedelta(seconds=5), actor="victim", start=success.at - timedelta(minutes=40)
    )
    after = _events(
        10, every=timedelta(seconds=5), actor="victim", start=success.at + timedelta(seconds=5)
    )

    assert (
        _takeovers(evaluate(_inputs(login_failures=old + after, login_successes=[success]))[0])
        == []
    )


def test_failures_elsewhere_are_not_attributed_to_an_unrelated_sign_in() -> None:
    success = _success(actor="bystander", source="192.0.2.200")
    guessing = _events(
        9,
        every=timedelta(seconds=10),
        actor="victim",
        source="203.0.113.7",
        start=success.at - timedelta(minutes=3),
    )

    assert (
        _takeovers(evaluate(_inputs(login_failures=guessing, login_successes=[success]))[0]) == []
    )


def test_signing_in_again_on_the_same_failures_is_one_incident_not_two() -> None:
    first = _success()
    again = _success(first.at + timedelta(minutes=2))
    failures = _events(
        7, every=timedelta(seconds=10), actor="victim", start=first.at - timedelta(minutes=3)
    )

    findings, outcomes = evaluate(_inputs(login_failures=failures, login_successes=[first, again]))
    (finding,) = _takeovers(findings)
    assert "1 more sign-in to this account after that, with no new failures" in finding.evidence
    assert next(o for o in outcomes if o.info.rule_id == "SIGN_IN_AFTER_GUESSING").findings == 1


def test_a_second_run_of_guessing_that_works_again_is_a_second_incident() -> None:
    first = _success()
    later = _success(first.at + timedelta(hours=2))
    failures = _events(
        5, every=timedelta(seconds=10), actor="victim", start=first.at - timedelta(minutes=2)
    )
    failures += _events(
        5, every=timedelta(seconds=10), actor="victim", start=later.at - timedelta(minutes=2)
    )

    assert (
        len(
            _takeovers(
                evaluate(_inputs(login_failures=failures, login_successes=[first, later]))[0]
            )
        )
        == 2
    )


def test_the_takeover_is_added_to_the_guessing_finding_not_a_third_finding_for_it() -> None:
    success = _success()
    failures = _events(
        12, every=timedelta(seconds=10), actor="victim", start=success.at - timedelta(minutes=3)
    )

    findings, _ = evaluate(_inputs(login_failures=failures, login_successes=[success]))
    # That guessing happened (source rule) and that it worked (takeover rule): two facts, two
    # findings. The account rule stays quiet because it was one address.
    assert sorted(f.rule_id for f in findings) == [
        "LOGIN_GUESSING_SOURCE",
        "SIGN_IN_AFTER_GUESSING",
    ]


def test_a_success_with_no_failures_before_it_is_nothing() -> None:
    assert (
        evaluate(_inputs(login_successes=[_success(), _success(actor="x", source=None)]))[0] == []
    )


def test_throttle_blocks_are_counted_and_graded_by_scope() -> None:
    assert evaluate(_inputs())[0] == []

    (accounts_only,) = evaluate(_inputs(throttled_accounts=2, throttle_policy="policy text"))[0]
    assert accounts_only.rule_id == "SIGN_IN_THROTTLE_ACTIVE"
    assert accounts_only.priority == Priority.LOW
    assert "Blocked right now: 0 addresses, 2 accounts" in accounts_only.evidence
    assert "Throttle policy: policy text" in accounts_only.evidence

    (with_address,) = evaluate(_inputs(throttled_addresses=1, throttled_accounts=3))[0]
    assert with_address.priority == Priority.MEDIUM
    assert with_address.title == "The sign-in throttle is blocking 1 address and 3 accounts"
    assert "not in the audit log" in " ".join(with_address.evidence)


def test_one_address_getting_into_many_accounts_on_one_run_of_failures_is_one_finding() -> None:
    # Credential stuffing, or a load test: one address fails 68 times at names that do not
    # exist, then signs in to thirty accounts. Thirty findings quoting the same failures would
    # bury the report; one finding that lists the accounts is what the administrator needs.
    source = "203.0.113.50"
    start = NOW - timedelta(minutes=40)
    tried = [Event(at=start + timedelta(seconds=i), actor=None, source=source) for i in range(68)]
    accounts = [f"load-{i:02d}" for i in range(30)]
    successes = [
        Event(at=start + timedelta(minutes=2, seconds=i), actor=name, source=source)
        for i, name in enumerate(accounts)
    ]
    # The first account signs in once more later, still with no new failures.
    successes.append(Event(at=start + timedelta(minutes=5), actor=accounts[0], source=source))

    findings, outcomes = evaluate(_inputs(login_failures=tried, login_successes=successes))
    (finding,) = _takeovers(findings)
    assert next(o for o in outcomes if o.info.rule_id == "SIGN_IN_AFTER_GUESSING").findings == 1
    assert finding.priority == Priority.HIGH
    assert finding.title == (
        "load-00 and 29 other accounts signed in from 203.0.113.50 right after a run of failed "
        "sign-ins"
    )
    text = " ".join(finding.evidence)
    assert "29 other accounts signed in from the same address on the same run of failures" in text
    assert "load-01, load-02, load-03, load-04, load-05 and 24 more" in text
    assert "1 more sign-in to these accounts after that" in text
    assert "the owners of load-00 and the other accounts listed" in finding.recommended_action
    assert "disable each account that was not its owner" in finding.recommended_action


def test_an_administrator_among_the_stuffed_accounts_makes_the_one_finding_critical() -> None:
    source = "203.0.113.50"
    start = NOW - timedelta(minutes=40)
    tried = [Event(at=start + timedelta(seconds=i), actor=None, source=source) for i in range(6)]
    user = _success(start + timedelta(minutes=1), actor="carol", source=source)
    admin = _success(start + timedelta(minutes=2), actor="root-admin", source=source, admin=True)

    (finding,) = _takeovers(
        evaluate(_inputs(login_failures=tried, login_successes=[user, admin]))[0]
    )
    assert finding.priority == Priority.CRITICAL
    assert "1 other account signed in" in " ".join(finding.evidence)
    assert "(1 administrator among them)" in " ".join(finding.evidence)


def test_sign_ins_from_different_addresses_are_not_folded_together() -> None:
    # Two addresses each guessing and getting in are two incidents, even in the same minutes.
    start = NOW - timedelta(minutes=40)
    first = [
        Event(at=start + timedelta(seconds=i), actor=None, source="198.51.100.1") for i in range(6)
    ]
    second = [
        Event(at=start + timedelta(seconds=i), actor=None, source="198.51.100.2") for i in range(6)
    ]
    a = _success(start + timedelta(minutes=1), actor="alice", source="198.51.100.1")
    b = _success(start + timedelta(minutes=1), actor="bob", source="198.51.100.2")

    assert (
        len(_takeovers(evaluate(_inputs(login_failures=first + second, login_successes=[a, b]))[0]))
        == 2
    )


def test_a_closed_account_in_a_burst_is_said_so_and_not_sent_to_the_users_tab() -> None:
    start = NOW - timedelta(minutes=30)
    gone = [
        Event(
            at=start + timedelta(seconds=i), actor="deleted-abc", source="203.0.113.9", active=False
        )
        for i in range(70)
    ]
    here = [
        Event(at=start + timedelta(seconds=i), actor="dave", source="203.0.113.9")
        for i in range(70)
    ]

    findings, _ = evaluate(_inputs(downloads=gone + here))
    by_title = {f.title.split(" ")[0]: f for f in findings if f.rule_id == "DOWNLOAD_BURST"}
    assert set(by_title) == {"deleted-abc", "dave"}
    closed, open_ = by_title["deleted-abc"], by_title["dave"]
    assert closed.priority == open_.priority == Priority.HIGH
    assert "This account is not active now" in closed.evidence[-1]
    assert "nothing to switch off" in closed.recommended_action
    assert "not active now" not in " ".join(open_.evidence)
    assert "disable the account on the Users tab" in open_.recommended_action


def test_a_takeover_of_an_account_closed_since_says_it_cannot_be_disabled() -> None:
    success = Event(
        at=NOW - timedelta(minutes=30), actor="deleted-abc", source="203.0.113.7", active=False
    )
    failures = _events(
        6, every=timedelta(seconds=10), actor="deleted-abc", start=success.at - timedelta(minutes=2)
    )

    (finding,) = _takeovers(
        evaluate(_inputs(login_failures=failures, login_successes=[success]))[0]
    )
    assert "not active now" in " ".join(finding.evidence)
    assert "already closed cannot be disabled" in finding.recommended_action


def test_a_run_of_failures_that_keeps_growing_while_accounts_sign_in_is_still_one_incident() -> (
    None
):
    # The real 2026-10-09 pattern: the failures and the successes were interleaved over two
    # minutes, so a sign-in at 12:18 saw 68 failures and one at 12:17 only 59. Those are not
    # separate incidents; the same address, the same run.
    source = "203.0.113.50"
    start = NOW - timedelta(minutes=40)
    tried = [
        Event(at=start + timedelta(seconds=2 * i), actor=None, source=source) for i in range(68)
    ]
    successes = [
        Event(at=start + timedelta(seconds=30 + 3 * i), actor=f"load-{i:02d}", source=source)
        for i in range(30)
    ]

    (finding,) = _takeovers(evaluate(_inputs(login_failures=tried, login_successes=successes))[0])
    text = " ".join(finding.evidence)
    # Failures after the last sign-in are not counted: 59 of the 68 fall before it.
    assert "59 failed sign-ins between" in text and "the last of these sign-ins" in text
    assert "59 from the address that then signed in" in text
    assert "29 other accounts signed in from the same address" in text
    assert f"Sign-ins between {site_stamp(start + timedelta(seconds=30))}" in text


def test_the_inactive_note_never_lands_on_an_address_finding() -> None:
    # LOGIN_GUESSING_SOURCE is keyed by address; the tried account's status is not its subject.
    tried = _events(12, every=timedelta(seconds=10), actor="bob", source="203.0.113.5")
    tried = [Event(at=e.at, actor=e.actor, source=e.source, active=False) for e in tried]

    findings, _ = evaluate(_inputs(login_failures=tried))
    (source,) = [f for f in findings if f.rule_id == "LOGIN_GUESSING_SOURCE"]
    assert "not active" not in " ".join(source.evidence)
    assert "fail2ban" in source.recommended_action


def test_guessing_at_a_disabled_account_advises_a_reset_before_enabling_it() -> None:
    start = NOW - timedelta(minutes=30)
    tried = [
        Event(at=start + timedelta(seconds=10 * i), actor="carol", source=s, active=False)
        for i, s in enumerate(["198.51.100.1", "198.51.100.2"] * 6)
    ]

    findings, _ = evaluate(_inputs(login_failures=tried))
    (account,) = [f for f in findings if f.rule_id == "LOGIN_GUESSING_ACCOUNT"]
    assert "This account is not active now" in account.evidence[-1]
    assert "reset the password first" in account.recommended_action
    assert "Activity Log" not in account.recommended_action
    assert "disable the account" not in account.recommended_action


def test_a_repeat_sign_in_while_the_guessing_goes_on_is_not_called_no_new_failures() -> None:
    source = "203.0.113.7"
    first = _success(NOW - timedelta(minutes=30), actor="victim", source=source)
    failures = _events(
        6,
        every=timedelta(seconds=10),
        actor="victim",
        source=source,
        start=first.at - timedelta(minutes=2),
    )
    failures += _events(
        3,
        every=timedelta(seconds=10),
        actor="victim",
        source=source,
        start=first.at + timedelta(minutes=1),
    )
    again = _success(first.at + timedelta(minutes=2), actor="victim", source=source)

    (finding,) = _takeovers(
        evaluate(_inputs(login_failures=failures, login_successes=[first, again]))[0]
    )
    text = " ".join(finding.evidence)
    assert "9 failed sign-ins" in text and "9 from the address" in text
    assert "1 more sign-in to this account while the failures went on" in text
    assert "no new failures" not in text


def test_merged_counts_add_up_when_the_run_spans_two_windows() -> None:
    # The union of failures and the per-address count are computed from the same set, so the
    # sentence "N failed sign-ins: M from the address" cannot show N > M for a one-address run.
    source = "203.0.113.50"
    start = NOW - timedelta(hours=1)
    early = [Event(at=start + timedelta(seconds=i), actor=None, source=source) for i in range(20)]
    late = [
        Event(at=start + timedelta(minutes=14, seconds=i), actor=None, source=source)
        for i in range(20)
    ]
    a = _success(start + timedelta(seconds=30), actor="a", source=source)
    # b's 15-minute window still holds the early failures, so the two sign-ins are one run.
    b = _success(start + timedelta(minutes=14, seconds=30), actor="b", source=source)

    (finding,) = _takeovers(
        evaluate(_inputs(login_failures=early + late, login_successes=[a, b]))[0]
    )
    text = " ".join(finding.evidence)
    assert "40 failed sign-ins" in text and "40 from the address that then signed in" in text


def test_an_account_guessed_elsewhere_is_not_folded_into_an_address_incident() -> None:
    # A is stuffed from S1 and signs in from S1. B is guessed from S2 and S3 and then signs in
    # from S1 (a shared office address) with fewer than five S1 failures: B's own finding, not
    # a victim of the S1 run.
    start = NOW - timedelta(hours=1)
    # Five S1 failures spread over 14 minutes: all five are in A's window, only three in B's.
    s1 = [
        Event(at=start + timedelta(minutes=m), actor=None, source="198.51.100.1")
        for m in (0, 4, 8, 12, 14)
    ]
    b_elsewhere = [
        Event(at=start + timedelta(minutes=18, seconds=10 * i), actor="b", source=s)
        for i, s in enumerate(["198.51.100.2", "198.51.100.3"] * 3)
    ]
    a = _success(start + timedelta(minutes=14, seconds=30), actor="a", source="198.51.100.1")
    b = _success(start + timedelta(minutes=20), actor="b", source="198.51.100.1")

    takeovers = _takeovers(
        evaluate(_inputs(login_failures=s1 + b_elsewhere, login_successes=[a, b]))[0]
    )
    assert len(takeovers) == 2
    assert not any("other account" in f.title for f in takeovers)


def test_an_account_guessed_directly_keeps_its_own_finding_even_from_the_stuffing_address() -> None:
    # The live suite runs everything from 127.0.0.1: earlier tests leave ten failures and an
    # administrator sign-in behind, then a throwaway account gets five wrong passwords and signs
    # in. That account was guessed at itself, so it is its own finding, not a line under the
    # administrator's.
    source = "127.0.0.1"
    start = NOW - timedelta(minutes=20)
    earlier = [
        Event(at=start + timedelta(seconds=i), actor="mallory", source=source) for i in range(10)
    ]
    admin = _success(start + timedelta(minutes=1), actor="root-admin", source=source, admin=True)
    own = [
        Event(at=start + timedelta(minutes=2, seconds=i), actor="takeover-1", source=source)
        for i in range(5)
    ]
    target = _success(start + timedelta(minutes=3), actor="takeover-1", source=source)

    findings = _takeovers(
        evaluate(_inputs(login_failures=earlier + own, login_successes=[admin, target]))[0]
    )
    assert len(findings) == 2
    (mine,) = [f for f in findings if f.title.startswith("takeover-1 ")]
    assert mine.priority == Priority.HIGH
    assert "5 against this account" in " ".join(mine.evidence)
    assert "disable the account on the Users tab" in mine.recommended_action


def test_times_in_findings_are_kuala_lumpur_time() -> None:
    # Stored and compared in UTC; written for a person in MYT, naive values read as UTC.
    assert site_stamp(datetime(2026, 10, 12, 18, 19, tzinfo=UTC)) == "2026-10-13 02:19 MYT"
    assert site_stamp(datetime(2026, 10, 12, 18, 19)) == "2026-10-13 02:19 MYT"
