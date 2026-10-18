"""The optional filters on `GET /audit-logs`: validated at the edge, narrowing only.

Three things have to hold. An unknown action or a malformed window is refused with a 422
before any query runs. Every filter compiles to a WHERE clause on top of the visibility rule,
never instead of it, so a non-admin who filters still sees only their own rows. And the
keyword search takes LIKE wildcards literally, the same way the file search does.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, Table, create_engine, insert
from sqlalchemy.orm import Session

from app.api.dependencies import get_audit_query_service, get_current_actor
from app.api.v1.routers.audit_router import router
from app.domain.auth import ActorContext
from app.domain.enums import SystemRole, UserStatus
from app.models.audit_log import AuditLog
from app.models.file import File
from app.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit_schema import AUDIT_ACTIONS, AuditLogQuery
from app.services.audit_query_service import AuditQueryService

BACKEND_ROOT = Path(__file__).resolve().parents[2]
NOON = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _actor(role: SystemRole = SystemRole.USER) -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("44444444-4444-4444-8444-444444444444"),
        session_id=8,
        session_public_id=UUID("55555555-5555-4555-8555-555555555555"),
        role=role,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


# --- the schema -----------------------------------------------------------------------------


def test_the_whitelist_names_every_action_the_code_writes() -> None:
    # Any `"SOME_ACTION"` literal on a line that mentions `action`, in the application and
    # the operator scripts. A new audit action that is not added to the whitelist cannot be
    # filtered for, which the person adding it would not notice until the dropdown is missing
    # an entry; this makes it a failing test instead.
    written: set[str] = set()
    for folder in ("app", "scripts"):
        for path in (BACKEND_ROOT / folder).rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "action" in line:
                    written.update(re.findall(r'"([A-Z]+(?:_[A-Z]+)+)"', line))
    assert written <= AUDIT_ACTIONS, sorted(written - AUDIT_ACTIONS)


def test_an_unknown_action_is_refused() -> None:
    with pytest.raises(ValidationError):
        AuditLogQuery(action="FILE_SHARED_WITH_EVERYONE")
    assert AuditLogQuery(action="FILE_SHARED").action == "FILE_SHARED"


def test_a_result_other_than_success_or_fail_is_refused() -> None:
    with pytest.raises(ValidationError):
        AuditLogQuery(result="MAYBE")


def test_the_window_is_normalised_to_utc_and_must_be_ordered() -> None:
    # A bare timestamp is UTC; one with an offset is converted, so 10:00 in Melbourne (+10)
    # is the same instant as 00:00 UTC and compares equally against the UTC column.
    melbourne = timezone(timedelta(hours=10))
    query = AuditLogQuery.model_validate(
        {"from": "2026-10-01T00:00:00", "to": datetime(2026, 10, 2, 10, 0, tzinfo=melbourne)}
    )
    assert query.from_time == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert query.to_time == datetime(2026, 10, 2, 0, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        AuditLogQuery.model_validate({"from": "2026-10-03T00:00:00Z", "to": "2026-10-02T00:00:00Z"})


def test_the_keyword_is_trimmed_and_capped_at_100_characters() -> None:
    assert AuditLogQuery(q="  report  ").q == "report"
    assert AuditLogQuery(q="   ").q is None
    assert AuditLogQuery(q="x" * 100).q == "x" * 100
    with pytest.raises(ValidationError):
        AuditLogQuery(q="x" * 101)


def test_an_empty_query_is_the_plain_page() -> None:
    assert AuditLogQuery().is_empty
    assert AuditLogQuery(limit=10, offset=20).is_empty
    assert not AuditLogQuery(result="FAIL").is_empty


# --- the repository -------------------------------------------------------------------------


class _CapturingDb:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return []


def _sql(statement) -> str:
    # The default dialect renders `%` once; MySQL's pyformat rendering doubles it, which only
    # makes the LIKE patterns harder to read in an assertion.
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def _where(statement) -> str:
    sql = _sql(statement)
    assert "WHERE " in sql
    return sql.split("WHERE ", maxsplit=1)[1]


def _list(db: _CapturingDb, *, admin: bool = False, **filters) -> str:
    AuditRepository(db).list_logs(  # type: ignore[arg-type]
        actor_user_id=7, admin=admin, limit=51, offset=0, resource_id=None, **filters
    )
    return _sql(db.statements[-1])


def test_each_filter_becomes_its_own_where_clause() -> None:
    db = _CapturingDb()
    sql = _list(
        db,
        action="FILE_SHARED",
        result="FAIL",
        created_from=datetime(2026, 10, 1, 0, 0),
        created_to=datetime(2026, 10, 2, 0, 0),
    )
    where = sql.split("WHERE ", maxsplit=1)[1]
    assert "audit_logs.action = 'FILE_SHARED'" in where
    assert "audit_logs.result = 'FAIL'" in where
    assert "audit_logs.created_at >= '2026-10-01 00:00:00'" in where
    assert "audit_logs.created_at <= '2026-10-02 00:00:00'" in where


def test_filters_are_added_to_the_visibility_rule_not_in_place_of_it() -> None:
    # The whole point: a non-admin who filters still sees a subset of their own page.
    db = _CapturingDb()
    _list(db, action="FILE_DOWNLOAD_AUTHORIZED", result="SUCCESS", keyword="report")
    where = _where(db.statements[-1])
    assert "audit_logs.actor_user_id = 7" in where
    assert "audit_logs.target_user_id = 7" in where
    assert "files.owner_id = 7" in where
    assert "audit_logs.action = 'FILE_DOWNLOAD_AUTHORIZED'" in where


def test_an_admin_with_filters_is_narrowed_by_the_filters_only() -> None:
    db = _CapturingDb()
    _list(db, admin=True, result="FAIL")
    where = _where(db.statements[-1])
    assert "audit_logs.result = 'FAIL'" in where
    assert "owner_id" not in where
    assert "actor_user_id = 7" not in where


def test_the_keyword_searches_the_description_and_the_resolved_file_name() -> None:
    db = _CapturingDb()
    sql = _list(db, keyword="report")
    # The name comes from `files` through an outer join on the resource id, so a row about
    # no file (a sign-in) still matches on its description.
    assert "LEFT OUTER JOIN files AS files_1 ON files_1.file_uuid = audit_logs.resource_id" in sql
    where = sql.split("WHERE ", maxsplit=1)[1]
    assert "audit_logs.description LIKE '%report%'" in where
    assert "files_1.original_filename LIKE '%report%'" in where


def test_the_keyword_takes_like_wildcards_literally() -> None:
    # `report_v2` must not match `reportXv2`, and `100%` must not match everything.
    db = _CapturingDb()
    where = _list(db, keyword="100%_v2\\").split("WHERE ", maxsplit=1)[1]
    assert "LIKE '%100\\%\\_v2\\\\%' ESCAPE '\\'" in where


def test_without_a_keyword_the_files_table_is_not_joined() -> None:
    db = _CapturingDb()
    sql = _list(db, action="AUTH_LOGIN_FAILED")
    assert "LEFT OUTER JOIN files" not in sql


# --- the visibility rule on a real database --------------------------------------------------


def _visibility_db() -> Session:
    """SQLite copies of the three tables the query reads, with no constraints or defaults.

    The real tables use MySQL-only defaults and checks, so they are copied column by column.
    That is enough to run the real statement and see which rows it returns.
    """
    metadata = MetaData()
    for model in (User, File, AuditLog):
        table = model.__table__
        Table(
            table.name,
            metadata,
            *[Column(c.name, c.type, primary_key=c.primary_key) for c in table.columns],
        )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    return Session(engine)


def test_an_owned_file_id_equal_to_someone_elses_account_id_does_not_reveal_their_rows() -> None:
    # The upload's file id is chosen by the client, so user 7 can upload a file whose id is
    # user 9's public id (or one of their key ids). Rows about user 9's account carry that same
    # id as their resource id, and must stay out of user 7's page.
    colliding = "99999999-9999-4999-8999-999999999999"
    db = _visibility_db()
    db.execute(insert(File.__table__), [{"id": 1, "file_uuid": colliding, "owner_id": 7}])
    rows = [
        ("AUTH_LOGIN_SUCCEEDED", "USER"),
        ("ADMIN_PASSWORD_RESET", "USER"),
        ("USER_KEY_ADDED", "AUTH"),
        ("RECOVERY_KEY_ROTATED", "RECOVERY"),
        ("FILE_DOWNLOAD_AUTHORIZED", "FILE"),
        ("FILE_SHARED", "SHARE"),
        ("RECOVERY_REQUEST_APPROVED", "RECOVERY"),
    ]
    db.execute(
        insert(AuditLog.__table__),
        [
            {
                "id": index,
                "actor_user_id": 9,
                "action": action,
                "resource_type": resource_type,
                "resource_id": colliding,
                "result": "SUCCESS",
                "created_at": datetime(2026, 10, 1, 12, index),
            }
            for index, (action, resource_type) in enumerate(rows, start=1)
        ],
    )

    visible = AuditRepository(db).list_logs(actor_user_id=7, admin=False, limit=50, offset=0)

    # The owner still sees what was done to their file by someone else.
    assert {log.action for log, _actor, _target in visible} == {
        "FILE_DOWNLOAD_AUTHORIZED",
        "FILE_SHARED",
        "RECOVERY_REQUEST_APPROVED",
    }
    # An administrator is not narrowed by ownership at all.
    assert len(AuditRepository(db).list_logs(actor_user_id=7, admin=True, limit=50, offset=0)) == 7


# --- the service ----------------------------------------------------------------------------


class _ForwardingRepository:
    def __init__(self) -> None:
        self.calls = []

    def list_logs(self, **values):
        self.calls.append(values)
        return []


def test_the_service_hands_the_repository_naive_utc_bounds() -> None:
    repository = _ForwardingRepository()
    service = AuditQueryService(db=object(), repository=repository)  # type: ignore[arg-type]
    melbourne = timezone(timedelta(hours=10))
    query = AuditLogQuery.model_validate(
        {
            "action": "FILE_SHARED",
            "result": "SUCCESS",
            "from": datetime(2026, 10, 1, 10, 0, tzinfo=melbourne),
            "to": "2026-10-02T00:00:00Z",
            "q": "report",
        }
    )

    service.list_logs(actor=_actor(), limit=50, offset=0, filters=query)

    call = repository.calls[-1]
    assert call["created_from"] == datetime(2026, 10, 1, 0, 0)
    assert call["created_from"].tzinfo is None
    assert call["created_to"] == datetime(2026, 10, 2, 0, 0)
    assert call["action"] == "FILE_SHARED"
    assert call["result"] == "SUCCESS"
    assert call["keyword"] == "report"
    assert call["limit"] == 51


def test_no_filters_means_the_repository_gets_none_for_each() -> None:
    repository = _ForwardingRepository()
    service = AuditQueryService(db=object(), repository=repository)  # type: ignore[arg-type]

    service.list_logs(actor=_actor(), limit=50, offset=0)

    call = repository.calls[-1]
    assert {call[key] for key in ("action", "result", "created_from", "created_to", "keyword")} == {
        None
    }


# --- the route ------------------------------------------------------------------------------


class _RecordingService:
    def __init__(self) -> None:
        self.calls = []

    def list_logs(self, **values):
        self.calls.append(values)
        return []

    def file_labels(self, rows):
        return {}

    @staticmethod
    def safe_metadata(metadata):
        return {}


def _client(service: _RecordingService, role: SystemRole = SystemRole.USER) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/audit-logs")
    app.dependency_overrides[get_current_actor] = lambda: _actor(role)
    app.dependency_overrides[get_audit_query_service] = lambda: service
    return TestClient(app)


@pytest.mark.parametrize(
    "query",
    [
        "action=FILE_SHARED_WITH_EVERYONE",
        "action=file_shared",
        "result=MAYBE",
        "from=2026-10-03T00:00:00Z&to=2026-10-02T00:00:00Z",
        "from=yesterday",
        "q=" + "x" * 101,
        "limit=101",
        "limit=0",
    ],
)
def test_a_bad_filter_is_a_422_before_any_query_runs(query: str) -> None:
    service = _RecordingService()

    response = _client(service).get(f"/audit-logs?{query}")

    assert response.status_code == 422
    assert service.calls == []


def test_the_route_forwards_the_filters_and_echoes_the_page() -> None:
    service = _RecordingService()

    response = _client(service).get(
        "/audit-logs?action=FILE_SHARED&result=FAIL&from=2026-10-01T00:00:00Z"
        "&to=2026-10-02T00:00:00Z&q=report&limit=10&offset=20"
    )

    assert response.status_code == 200
    call = service.calls[-1]
    assert call["limit"] == 10 and call["offset"] == 20
    filters = call["filters"]
    assert filters.action == "FILE_SHARED"
    assert filters.result == "FAIL"
    assert filters.from_time == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert filters.to_time == datetime(2026, 10, 2, 0, 0, tzinfo=UTC)
    assert filters.q == "report"
    data = response.json()["data"]
    assert data["limit"] == 10 and data["offset"] == 20 and data["has_more"] is False


def test_the_plain_page_still_works_with_its_old_defaults() -> None:
    service = _RecordingService()

    response = _client(service).get("/audit-logs")

    assert response.status_code == 200
    call = service.calls[-1]
    assert call["limit"] == 50 and call["offset"] == 0
    assert call["filters"].is_empty
