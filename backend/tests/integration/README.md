# Integration tests

[English](README.md) | [简体中文](README.zh-CN.md)

Database, repository, and storage integration tests belong here and must use a dedicated
disposable MySQL 8.4 database. Never point destructive fixtures at the normal development
database. Mark these tests with `@pytest.mark.integration`.

Set `AUTH_TEST_DATABASE_URL` to an already-migrated database whose name has a distinct `_test`
segment; without it every test here skips, and CI's `mysql-gate` job fails on any skip.

- `test_auth_mysql.py`, `test_file_lifecycle_mysql.py`, `test_mysql_schema_parity.py` — the
  service, SQL and storage layers together.
- `test_concurrency_mysql.py` — real threads on separate connections racing the row locks
  behind session limits, login throttling, refresh reuse, the audit chain, key rewraps,
  sharing and recovery.
- `test_fault_injection_mysql.py` — real failures: a connection killed at COMMIT, an object
  store that refuses a write or unlink, malformed envelopes, forged signatures, stale
  revisions.

The concurrency and fault suites write permanent rows (see `_concurrency_support.py` for why),
so use a database you can drop afterwards.
