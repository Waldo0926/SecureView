from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.dialects import mysql

from app.models.file import File
from app.models.file_folder import FileFolder
from app.repositories.file_repository import FileRepository


def _compiled_access_sql() -> str:
    statement = FileRepository._active_access_statement(user_id=7)
    return str(
        statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_authorized_access_admits_a_corrupted_file() -> None:
    """A damaged file must stay reachable to the people who hold a grant on it.

    Filtering CORRUPTED out of this statement removed the owner's only route to see the
    damage, re-check it, or delete it -- the row survived, but nothing could name it.
    """
    sql = _compiled_access_sql()

    assert "files.status IN ('ACTIVE', 'CORRUPTED')" in sql


def test_authorized_access_still_excludes_a_deleted_file() -> None:
    sql = _compiled_access_sql()

    assert "'DELETED'" not in sql


def test_authorized_access_still_requires_a_live_grant_and_wrapping() -> None:
    sql = _compiled_access_sql()

    assert "file_access_grants.status = 'ACTIVE'" in sql
    assert "file_key_wrappings.status = 'ACTIVE'" in sql
    assert "user_keys.status = 'ACTIVE'" in sql


def _search_pattern(term: str) -> str:
    """The LIKE pattern the repository will bind, which is where the escaping lives.

    Asserted at the parameter rather than in rendered SQL: the MySQL dialect doubles `%`
    when it inlines a literal, so a string assertion over the compiled statement tests the
    renderer as much as the escaping.
    """
    return FileRepository._filename_contains(term).right.value


def _search_escape(term: str) -> str:
    return FileRepository._filename_contains(term).modifiers["escape"]


def test_search_matches_a_substring_of_the_filename() -> None:
    assert _search_pattern("thesis") == "%thesis%"


def test_search_takes_like_wildcards_literally() -> None:
    """`%` and `_` are ordinary characters in a filename, and a user means them literally.

    Unescaped, a search for `_` matches every single character and a search for `%`
    matches every file the caller can see -- so the box would answer confidently with
    results the user never asked for.
    """
    assert _search_pattern("100%-complete") == "%100\\%-complete%"
    assert _search_pattern("a_b") == "%a\\_b%"
    assert _search_escape("a_b") == "\\"


def test_search_escapes_the_escape_character_itself() -> None:
    """Otherwise a trailing backslash escapes the closing wildcard and changes the pattern."""
    assert _search_pattern("a\\b") == "%a\\\\b%"


def test_search_does_not_relax_the_access_predicates() -> None:
    """A filter must narrow the result set, never widen it."""
    statement = FileRepository._active_access_statement(user_id=7).where(
        FileRepository._filename_contains("anything")
    )
    sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "files.status IN ('ACTIVE', 'CORRUPTED')" in sql
    assert "file_access_grants.status = 'ACTIVE'" in sql
    assert "file_key_wrappings.status = 'ACTIVE'" in sql
    assert "user_keys.status = 'ACTIVE'" in sql


def test_folder_filter_is_owner_scoped() -> None:
    folder_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    predicate = File.folder.has(
        and_(FileFolder.folder_uuid == str(folder_id), FileFolder.owner_id == 7)
    )
    sql = str(predicate.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "file_folders.folder_uuid = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'" in sql
    assert "file_folders.owner_id = 7" in sql
