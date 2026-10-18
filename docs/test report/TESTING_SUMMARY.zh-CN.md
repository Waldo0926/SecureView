# 测试总结

[English](TESTING_SUMMARY.md) | 简体中文

把 SecureView 所有和测试有关的数字放在一页里，报告、幻灯片和 README 引用同一组数字。数字来自 `main` 在 `1b1bcce`（PR #240，2026-10-13）上的 CI，以及 2026-10-09 的压测。数字有变化时，先改这里。

## 自动化测试（每个 pull request 和每次推送到 `main`）

CI 跑在 staging VPS 上的三台自托管 runner 上（deployment/ci-runner）。pull request 不会部署；`main` 只有在下面全部通过后才会部署（[AUTOMATIC_DEPLOYMENT.zh-CN.md](../AUTOMATIC_DEPLOYMENT.zh-CN.md)）。

| Job | 跑什么 | `1b1bcce` 上的结果 | 覆盖率 |
| --- | --- | --- | --- |
| `backend` | 不需要数据库的后端单元测试和 API 测试；ruff 检查和格式 | 718 通过 | 81.84%（门槛 78%） |
| `mysql-gate` | 在真实 MySQL 8.4（TLS）上跑完整后端测试，检查运行时权限，跑 MySQL 发布门禁（全新安装、迁移、只读核验）和加密备份恢复演练 | 786 通过，0 跳过；发布门禁和恢复演练通过 | 86.64%（门槛 82%） |
| `frontend` | Vue 类型检查、vitest 单元测试、生产构建、`npm audit` | 899 通过，78 跳过 | 语句 77.36% |
| `e2e-live` | 所有前端测试套件连一次性的 API 和 MySQL 跑，包括上面跳过的 78 个；然后用 Playwright 在 Chromium 里操作构建好的页面 | 977 通过，0 跳过；57 个浏览器测试通过 | 语句 79.72% |
| `tamper-drill` | 隔离的攻击容器修改存储的密文和数据库，程序必须报告 MODIFIED 或 MISSING 并拒绝下载 | 通过 | |

"0 跳过"是强制的：只要这些 JUnit 报告里有任何测试被跳过，`check_no_skips.py` 就会让 Job 失败，所以缺数据库或缺环境变量不会变成一次假的通过。

下面这些测试值得单独说，因为它们支撑具体的说法：

| 说法 | 支撑它的测试 |
| --- | --- |
| 服务器上只有密文 | 上传测试，以及 [ENCRYPTION_EVIDENCE.zh-CN.md](../ENCRYPTION_EVIDENCE.zh-CN.md) 里记录的证据 |
| 浏览器和服务器的加密算法一致 | `docs/crypto/test_vectors.json` 同时被前端和 `backend/tests/unit/test_crypto_vectors.py`（python-cryptography）校验，六种套件都有 |
| 每种套件都能分享 | 真实后端测试在六种套件下各自分享、解密、撤销一个文件 |
| 文件被改会被发现 | 完整性检查测试、篡改演练，以及下载被篡改文件的浏览器测试 |
| 撤销后真的拿不到 | 撤销后读取、下载和完整性检查都返回同样的 404 |
| 文件不会被上传两次 | golden path 浏览器测试统计 `POST /files/upload` 次数，并点击完成状态 |
| 临时密码不能拿来做别的 | `test_password_change_required.py` 按 OpenAPI 把所有需要登录的接口都过一遍 |
| 只用 GET 和 POST | 路由和客户端测试，CORS 也只允许这两种 |

## 压测（2026-10-09，修复后）

从家里的一个地址经公网 URL 发出，nginx 和它的限流都开着。完整报告：[performance/REPORT-2026-10-09.zh-CN.md](../performance/REPORT-2026-10-09.zh-CN.md)。

| 指标 | 结果 |
| --- | --- |
| 操作次数 | 18,256 |
| 解密后和 SHA-256 比对的下载 | 7,444 次，全部一致，0 次完整性失败 |
| 服务器错误（5xx） | 0 |
| 1 到 50 个并发用户 | 所有请求都成功；上传 p95 在 1 人时 134 ms，50 人时 3.3 s |
| 100 个并发用户 | 0 个服务器错误（修复前，2026-10-03：65% 到 78% 的上传是 HTTP 500）；部分上传得到 429，因为一个地址最多同时 50 个上传 |
| 文件类型和大小 | pdf、png、jpg、mp4、zip、exe，1 到 500 MiB：36/36 个文件，72/72 次下载逐字节一致 |
| 服务器负载 | CPU 平均 4.5%，峰值 42%；API 内存一直是 199 MiB |
| 上限 | VPS 的 100 Mbit/s 网口（单个 500 MiB 传输就达到 87 到 98 Mbit/s） |

修复前的对照保留在 [performance/REPORT-2026-10-03.zh-CN.md](../performance/REPORT-2026-10-03.zh-CN.md)。

## 在线上 staging 上核对的内容

每次合并后，都会确认部署到了准确的提交、`/health/ready` 返回 ready、改动的用户流程能用。最新结果在 [TODO.zh-CN.md](../BACKLOG.zh-CN.md) 顶部的"已核验"表里。staging 上还每天跑完整性巡检，每小时做审计链检查点，每晚做加密备份并复制到服务器以外。

## 被测试的规模

| 项目 | 数量 |
| --- | --- |
| `/api/v1` 下的 API 路由 | 64 个（23 个 GET，41 个 POST），另有 4 个健康检查和文档路由 |
| 数据库表 | 17 张，另加 `alembic_version`；schema 版本 `0011_must_change_password` |
| 审计事件类型 | 42 种 |
| 文件可选的加密套件 | 6 种（默认 AES-256-GCM，另有 AES-256-GCM-SIV、XChaCha20-Poly1305、ChaCha20-Poly1305、AES-192-GCM、AES-128-GCM） |

## 没有覆盖到的

- **没有正式的可用性研究。** 导师、组员、教学团队和其他同学都用过线上网站，但没有测 SUS 分数或完成率。
- **浏览器测试只跑 Chromium。** Firefox 和 Safari 不在 CI 里。
- **15、30、60 分钟的长时间压测修复后没有重跑；** 2026-10-03 的 58 分钟长测里内存和连接数都很平稳。
- **压测只从一个地址发出。** 它证明了按地址的限流在起作用，但不能说明来自不同网络的不同用户同时访问时网站能撑多少人。
- **只在 MySQL 上跑的测试默认不在笔记本上跑。** 它们在 `mysql-gate` 里跑；本地要跑需要 MySQL 8.4 和 [E2E_TESTING.zh-CN.md](E2E_TESTING.zh-CN.md) 里的环境变量。

## 自己跑测试

| 内容 | 命令 |
| --- | --- |
| 后端单元和 API 测试 | `cd backend && .venv/bin/python -m pytest tests/unit tests/api` |
| 前端单元测试 | `cd frontend && npx vitest run` |
| 全部套件连真实 API 和 MySQL，再加浏览器测试 | `E2E_BROWSER=1 DB_HOST=… bash backend/tests/e2e/run_live_stack.sh`（[E2E_TESTING.zh-CN.md](E2E_TESTING.zh-CN.md)） |
| 对 staging 压测 | `LOAD_ACCOUNTS=… bash loadtest/run_staging.sh`（[PERFORMANCE_TESTING.zh-CN.md](PERFORMANCE_TESTING.zh-CN.md)） |
