from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import IntegrityVerificationError, StorageUnavailableError
from app.repositories.file_repository import FileAccessRecord
from app.services.file_storage_service import StorageObjectError, StorageObjectMissingError
from app.services.integrity_service import IntegrityService

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
FILE_ID = UUID("11111111-1111-4111-8111-111111111111")


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeRepository:
    def __init__(self, *, anchor: str | None = None, candidates=()) -> None:
        self.checks = []
        self.anchor = anchor
        self.candidates = list(candidates)

    def add_integrity_check(self, check) -> None:
        self.checks.append(check)

    def upload_anchor_sha256(self, file_uuid: str) -> str | None:
        return self.anchor

    def list_scan_candidates(self, *, limit: int):
        return self.candidates[:limit]

    def count_scan_candidates(self) -> int:
        return len(self.candidates)


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    def append(self, **event) -> None:
        self.events.append(event)


class FailingStorage:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    def open_verified(self, object_key: str):
        raise self.failure

    def hash_object(self, object_key: str) -> tuple[str, int]:
        raise self.failure


def _actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("22222222-2222-4222-8222-222222222222"),
        session_id=8,
        session_public_id=UUID("33333333-3333-4333-8333-333333333333"),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


def _record() -> FileAccessRecord:
    return FileAccessRecord(
        file=SimpleNamespace(
            id=91,
            file_uuid=str(FILE_ID),
            storage_object_key="opaque/object.ciphertext",
            encrypted_sha256="d" * 64,
            encrypted_size_bytes=5,
            status="ACTIVE",
            updated_at=NOW.replace(tzinfo=None),
            revision=1,
        ),
        grant=SimpleNamespace(),
        wrapping=SimpleNamespace(),
        user_key=SimpleNamespace(),
    )


@pytest.mark.parametrize(
    ("storage_failure", "public_error"),
    [
        (StorageObjectError("host path must stay private"), StorageUnavailableError),
        (StorageObjectMissingError("missing"), IntegrityVerificationError),
    ],
)
def test_download_integrity_failure_uses_stable_public_error(
    storage_failure: Exception,
    public_error: type[Exception],
) -> None:
    db = FakeDb()
    repository = FakeRepository()
    audit = FakeAudit()
    service = IntegrityService(
        db=db,
        settings=SimpleNamespace(),
        storage=FailingStorage(storage_failure),
        audit_service=audit,
        repository=repository,
        access_control=SimpleNamespace(),
        clock=lambda: NOW,
    )

    with pytest.raises(public_error):
        service.open_verified_for_download(
            record=_record(),
            actor=_actor(),
            context=RequestContext(),
        )

    assert db.commits == 1
    assert db.rollbacks == 0
    assert len(repository.checks) == 1
    assert audit.events[0]["action"] == "FILE_DOWNLOAD_INTEGRITY_FAILED"


class StubStorage:
    """Answers with a fixed digest and size, as a healthy or a damaged object would."""

    def __init__(self, *, sha256: str, size_bytes: int) -> None:
        self.sha256 = sha256
        self.size_bytes = size_bytes

    def hash_object(self, object_key: str) -> tuple[str, int]:
        return self.sha256, self.size_bytes

    def open_verified(self, object_key: str):
        return SimpleNamespace(
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            stream=SimpleNamespace(close=lambda: None),
        )


def _service(storage, record, *, repository=None) -> IntegrityService:
    return IntegrityService(
        db=FakeDb(),
        settings=SimpleNamespace(),
        storage=storage,
        audit_service=FakeAudit(),
        repository=repository or FakeRepository(),
        access_control=SimpleNamespace(require=lambda **_: record),
        clock=lambda: NOW,
    )


def test_missing_object_does_not_mark_the_file_corrupted() -> None:
    """A momentary storage outage says nothing about bytes nobody could read.

    Marking the file here is what let an unmounted volume permanently strand an intact
    file: the status never moved back, and every read route filtered CORRUPTED away.
    """
    record = _record()
    service = _service(FailingStorage(StorageObjectMissingError("missing")), record)

    result = service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext())

    assert result.status == "MISSING"
    assert record.file.status == "ACTIVE"
    assert record.file.revision == 1


def test_unreadable_object_does_not_mark_the_file_corrupted() -> None:
    record = _record()
    service = _service(FailingStorage(StorageObjectError("errno")), record)

    result = service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext())

    assert result.status == "ERROR"
    assert record.file.status == "ACTIVE"


def test_modified_ciphertext_still_marks_the_file_corrupted() -> None:
    record = _record()
    service = _service(StubStorage(sha256="e" * 64, size_bytes=5), record)

    result = service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext())

    assert result.status == "MODIFIED"
    assert record.file.status == "CORRUPTED"
    assert record.file.revision == 2
    assert record.file.updated_at == NOW.replace(tzinfo=None)


def test_a_passing_recheck_restores_a_corrupted_file() -> None:
    """Status describes the ciphertext now, not the worst ever observed about it."""
    record = _record()
    record.file.status = "CORRUPTED"
    service = _service(StubStorage(sha256="d" * 64, size_bytes=5), record)

    result = service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext())

    assert result.status == "VALID"
    assert record.file.status == "ACTIVE"
    assert record.file.revision == 2


def test_a_passing_download_verification_restores_a_corrupted_file() -> None:
    record = _record()
    record.file.status = "CORRUPTED"
    service = _service(StubStorage(sha256="d" * 64, size_bytes=5), record)

    service.open_verified_for_download(
        record=record,
        actor=_actor(),
        context=RequestContext(),
    )

    assert record.file.status == "ACTIVE"


def test_a_valid_check_on_a_healthy_file_does_not_bump_the_revision() -> None:
    record = _record()
    service = _service(StubStorage(sha256="d" * 64, size_bytes=5), record)

    service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext())

    assert record.file.status == "ACTIVE"
    assert record.file.revision == 1


def test_a_deleted_file_is_never_resurrected_by_a_verification() -> None:
    record = _record()
    record.file.status = "DELETED"
    service = _service(StubStorage(sha256="d" * 64, size_bytes=5), record)

    service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext())

    assert record.file.status == "DELETED"


def test_a_digest_edited_together_with_the_object_is_caught_by_the_audit_anchor() -> None:
    """Rewriting the object *and* files.encrypted_sha256 leaves them agreeing with each other.

    The upload's audit row recorded the original digest in the hash chain, and a database
    edit cannot move that quietly, so the disagreement is the finding.
    """
    record = _record()
    record.file.encrypted_sha256 = "f" * 64  # the attacker's rewritten column
    storage = StubStorage(sha256="f" * 64, size_bytes=5)  # ... and the matching rewritten object
    service = _service(storage, record, repository=FakeRepository(anchor="d" * 64))

    result = service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext())

    assert result.status == "MODIFIED"
    assert record.file.status == "CORRUPTED"
    assert service.repository.checks[0].message.endswith("at upload")


def test_the_audit_anchor_also_stops_a_download() -> None:
    record = _record()
    record.file.encrypted_sha256 = "f" * 64
    service = _service(
        StubStorage(sha256="f" * 64, size_bytes=5),
        record,
        repository=FakeRepository(anchor="d" * 64),
    )

    with pytest.raises(IntegrityVerificationError):
        service.open_verified_for_download(record=record, actor=_actor(), context=RequestContext())

    assert record.file.status == "CORRUPTED"


def test_a_matching_anchor_changes_nothing() -> None:
    record = _record()
    service = _service(
        StubStorage(sha256="d" * 64, size_bytes=5),
        record,
        repository=FakeRepository(anchor="d" * 64),
    )

    assert (
        service.check(actor=_actor(), file_id=FILE_ID, context=RequestContext()).status == "VALID"
    )


def _stored_file(
    file_id: int, *, sha: str = "d" * 64, status: str = "ACTIVE", key: str | None = None
):
    return SimpleNamespace(
        id=file_id,
        file_uuid=f"00000000-0000-4000-8000-{file_id:012d}",
        storage_object_key=key or f"opaque/{file_id}.ciphertext",
        encrypted_sha256=sha,
        encrypted_size_bytes=5,
        status=status,
        updated_at=NOW.replace(tzinfo=None),
        revision=1,
    )


class PerObjectStorage:
    """Answers per object key, as a store holding one good object and one damaged one would."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers

    def hash_object(self, object_key: str):
        answer = self.answers[object_key]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _sweep(files, answers, **kwargs):
    repository = FakeRepository(candidates=files)
    service = IntegrityService(
        db=FakeDb(),
        settings=SimpleNamespace(),
        storage=PerObjectStorage(answers),
        audit_service=FakeAudit(),
        repository=repository,
        access_control=SimpleNamespace(),
        clock=lambda: NOW,
    )
    summary = service.sweep(actor_user_id=None, context=RequestContext(), limit=50, **kwargs)
    return service, repository, summary


def test_a_sweep_checks_every_stored_object_without_a_requesting_user() -> None:
    good, bad, gone = _stored_file(1), _stored_file(2), _stored_file(3)
    _, repository, summary = _sweep(
        [good, bad, gone],
        {
            good.storage_object_key: ("d" * 64, 5),
            bad.storage_object_key: ("e" * 64, 5),
            gone.storage_object_key: StorageObjectMissingError("missing"),
        },
    )

    assert (summary.scanned, summary.valid, summary.modified, summary.missing) == (3, 1, 1, 1)
    assert summary.damaged == 2
    assert summary.damaged_file_ids == [bad.file_uuid, gone.file_uuid]
    assert [check.result for check in repository.checks] == ["VALID", "MODIFIED", "MISSING"]
    assert all(check.checked_by is None for check in repository.checks)
    assert bad.status == "CORRUPTED"
    assert gone.status == "ACTIVE"  # an unreadable object says nothing about its bytes


def test_a_sweep_audits_findings_and_one_summary_but_not_every_healthy_file() -> None:
    good, bad = _stored_file(1), _stored_file(2)
    service, _, _ = _sweep(
        [good, bad],
        {good.storage_object_key: ("d" * 64, 5), bad.storage_object_key: ("e" * 64, 5)},
    )

    actions = [(event["action"], event["result"]) for event in service.audit.events]
    assert actions == [
        ("FILE_INTEGRITY_CHECKED", "FAIL"),
        ("INTEGRITY_SWEEP_COMPLETED", "FAIL"),
    ]
    assert service.audit.events[-1]["metadata"]["scanned"] == 2


def test_a_clean_sweep_records_a_successful_summary() -> None:
    good = _stored_file(1)
    service, _, summary = _sweep([good], {good.storage_object_key: ("d" * 64, 5)})

    assert summary.damaged == 0
    assert service.audit.events[-1]["action"] == "INTEGRITY_SWEEP_COMPLETED"
    assert service.audit.events[-1]["result"] == "SUCCESS"


def test_a_sweep_that_runs_out_of_budget_stops_and_says_so() -> None:
    files = [_stored_file(n) for n in range(1, 5)]
    answers = {f.storage_object_key: ("d" * 64, 5) for f in files}
    ticks = iter([0.0, 0.0, 1.0, 9.0, 9.0, 9.0, 9.0, 9.0])

    _, repository, summary = _sweep(
        files, answers, budget_seconds=5.0, monotonic=lambda: next(ticks)
    )

    assert summary.stopped_early is True
    assert summary.scanned == 2
    assert summary.candidates == 4
    assert len(repository.checks) == 2


def test_a_sweep_heals_a_file_whose_object_was_restored() -> None:
    restored = _stored_file(1, status="CORRUPTED")
    _, _, summary = _sweep([restored], {restored.storage_object_key: ("d" * 64, 5)})

    assert summary.valid == 1
    assert restored.status == "ACTIVE"
