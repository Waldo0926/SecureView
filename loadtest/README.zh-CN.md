# SecureView 压力测试

[English](README.md) | 简体中文

一个行为与浏览器一致的客户端：每次上传都用真实的文件信封加密，每次下载都解密并校验 SHA-256，同时为每个
操作计时。

- 测试计划、已知限制、发现和完整流程：[`docs/PERFORMANCE_TESTING.zh-CN.md`](../docs/PERFORMANCE_TESTING.zh-CN.md)。
- 针对一次性环境的本地演练：`bash loadtest/run_local.sh`（需要指向 `_test` 数据库的 `DB_*`）。
- 测试：`.venv/bin/python -m pytest tests`。
- 经公网地址压测 staging：`LOAD_ACCOUNTS=loadtest-accounts.json bash loadtest/run_staging.sh`
  （加 `LOAD_LARGE_FILES=1` 才跑 1 到 500 MiB 的大文件矩阵）。
- 结果：[`docs/performance/REPORT-2026-10-09.zh-CN.md`](../docs/performance/REPORT-2026-10-09.zh-CN.md)（修复后，公网地址，2026-10-09），
  修复前的对照 [`docs/performance/REPORT-2026-10-03.md`](../docs/performance/REPORT-2026-10-03.md)（staging，2026-10-03/04），
  以及 100 用户问题的修复和 staging 重测
  [`docs/performance/pool-fix-2026-10-04/`](../docs/performance/pool-fix-2026-10-04/README.zh-CN.md)。

| 文件 | 作用 |
| --- | --- |
| `secureview_load/envelope.py` | 浏览器的文件信封（AAD-3、AES-128/192/256-GCM 与 ChaCha20-Poly1305、RSA-OAEP），以 `docs/crypto/test_vectors.json` 为准。这里未实现 AES-256-GCM-SIV 和 XChaCha20-Poly1305；压测使用 AES-256-GCM |
| `secureview_load/client.py` | 通过公开 API 操作的一个虚拟用户 |
| `secureview_load/runner.py` | 场景：`smoke`、`steps`、`parallel`、`mixed`、`sizes`、`logins`。`sizes` 按文件类型各用一个账号，每个文件验证完就删除，所以账号配额可以一直开着 |
| `secureview_load/report.py` | Markdown 报告和图表，与服务器采样数据对齐 |
| `run_staging.sh` | 对公网地址（默认 `https://secureview.tech/api/v1`）跑完各场景，限流开着；大文件矩阵只有设置 `LOAD_LARGE_FILES=1` 时才跑 |
| `server_sampler.py` | 用系统 Python 在服务器上运行：CPU、内存、磁盘、网络、进程和连接数 |
| `../backend/scripts/seed_load_users.py` | 在服务器上创建测试账户 |

未告知团队前，不要把它指向共享服务器；除非加上 `--confirm-remote`，它会拒绝非本地主机。`cleanup` 会删除所有测试账号和它们的文件；nginx 返回 429 时它会等一下再重试，不会留下账号。

第二天早上 06:00 会收到安全 Agent 的告警邮件，这是正常的：按规则的定义，从一个地址跑压测就是一轮上传、下载和登录突增，
检查本来就该在这种情况下失败。对照你的报告核对地址和时间，然后等 24 小时窗口滑过去就行。见
[SECURITY_AGENT.zh-CN.md](../docs/SECURITY_AGENT.zh-CN.md#主动告警每日)。
