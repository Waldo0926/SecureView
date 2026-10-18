# 集成测试

[English](README.md) | [简体中文](README.zh-CN.md)

数据库、仓库和存储集成测试应放置于此，并且必须使用专用的、可随时销毁的 MySQL 8.4 数据库。绝不能让破坏性测试夹具指向常规开发数据库。请使用 `@pytest.mark.integration` 标记这些测试。

请将 `AUTH_TEST_DATABASE_URL` 指向一个已完成迁移、且库名带有独立 `_test` 段的数据库；未设置时这里的测试会全部跳过，而 CI 的 `mysql-gate` Job 遇到任何跳过都会失败。

- `test_auth_mysql.py`、`test_file_lifecycle_mysql.py`、`test_mysql_schema_parity.py`——同时覆盖服务、SQL 与存储层。
- `test_concurrency_mysql.py`——在各自独立连接上的真实线程，竞争会话上限、登录限流、refresh 重用、审计链、密钥重新包装、分享与恢复背后的行锁。
- `test_fault_injection_mysql.py`——真实故障：COMMIT 时连接被终止、对象存储拒绝写入或删除、格式错误的信封、伪造签名、过期的 revision。

并发与故障测试会写入永久数据行（原因见 `_concurrency_support.py`），请使用事后可以直接删除的数据库。
