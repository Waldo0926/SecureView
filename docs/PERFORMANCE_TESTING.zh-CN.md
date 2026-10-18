# 性能与容量测试

[English](PERFORMANCE_TESTING.md) | [简体中文](PERFORMANCE_TESTING.zh-CN.md)

2026-10-01 的会议上，导师要的是数字，而不是“支持多人同时使用”：服务器能承受多少用户、多少文件、多大的文件，
以及在哪里开始出问题（会议行动项第 4、5、6 项）。本文是测试计划、测试工具、开测前就已知的上限，以及本地预演发现的问题。

**状态（2026-10-04）：** 完整测试矩阵已于 2026-10-03 至 04 夜间在 staging 上跑完。报告、图表、原始汇总、服务器采样
CSV 和运行日志都在 [`performance/`](performance/REPORT-2026-10-03.md)，结论填在本页末尾。引用任何数字之前请先读报告里的
“Test conditions”：所有传输类数字受限于压测端的家庭网络，而不是服务器。由
[#140](https://github.com/jsonrar/fyp-secure-file-platform/issues/140) 跟踪。修复之后，2026-10-09 经公网地址重跑了测试矩阵
（[报告](performance/REPORT-2026-10-09.zh-CN.md)），结论见本页末尾。

## 测的是什么，服务器实际做了什么

SecureView 在浏览器里加密。服务器从不加密或解密文件：上传时它校验信封、边写盘边计算哈希，并在一个事务里写入元数据、
授权、密钥包装和一条哈希链审计记录；下载时边传输边复核存储的 SHA-256，并追加一条审计记录。所以报告里的“加密耗时”是
**客户端**的耗时（由压测工具测量，它做的工作和浏览器完全一样），服务器的开销是 I/O、哈希、数据库事务和审计链。

压测工具（`loadtest/`）的行为和浏览器完全一致：每次上传都用同样的 AAD 绑定信封加密（与浏览器加密库自己的已知答案向量
`docs/crypto/test_vectors.json` 对齐），**每次下载都会解密并用 SHA-256 与原文件比对**。所以每一次操作都同时证明了数据完整，而不只是速度。

## 开测前已知的上限

这些来自代码和服务器配置，决定了任何测试能测出的上限：

| 上限 | 数值 | 对测试的影响 |
| --- | --- | --- |
| 服务器 | 8 vCPU、16 GB 内存、387 GB 磁盘（剩余 237 GB） | 硬件天花板 |
| API 进程 | 只有一个 uvicorn 进程，没有 `--workers` | 所有 Python 工作共享一个解释器；同步接口在它的线程池里运行 |
| 数据库连接池 | SQLAlchemy 默认：5 个连接 + 10 个溢出 | API 同时最多 15 个数据库事务 |
| nginx，按来源 IP | API 每秒 10 个请求（突发 20）；登录每分钟 12 次（突发 8） | 从一台机器经 `https://secureview.tech` 压测，测到的是这个限制而不是服务器 |
| 密码哈希 | `AUTH_PASSWORD_HASH_CONCURRENCY=2`：同时最多两个 Argon2id（64 MiB）验证；第三个**立即返回 429**，不排队 | 超过 2 个的同时登录会失败，需要客户端重试 |
| 上传大小 | 明文 500 MiB（`MAX_UPLOAD_SIZE_BYTES`），nginx 请求体 501 MB，代理超时 300 秒 | 最大文件；网速慢时接近上限可能超时 |
| 访问令牌 | 30 分钟 | 长时间测试时工具会自动续期 |

表中 nginx 一行是做这些测试时的设置。PR #210（2026-10-09）已把它调高到 API 每秒 30 个请求（突发 60）、每分钟 60 次凭证校验（突发 30）、每个 IP 同时 50 个上传。

## 本地预演发现的问题

最初几次本地运行就发现了两个并发 bug。两者都是 MySQL 死锁（错误 1213），用户看到的是 **HTTP 500**；都在后端代码里，
所以记录在这里和 [#139](https://github.com/jsonrar/fyp-secure-file-platform/issues/139)，没有在压测这项工作里顺手改：

1. **两个用户同时登录可能死锁。** `_enforce_session_limit` 执行
   `SELECT … FROM user_sessions WHERE user_id=? AND status='ACTIVE' FOR UPDATE`。在 MySQL 默认的 REPEATABLE READ 下，
   对一个还没有活动会话的用户，这条语句锁住的是 `idx_user_sessions_user_status` 里的*间隙*；两个这样的用户（比如最新注册的两个账户）
   锁住同一个间隙，各自的 `INSERT INTO user_sessions` 都在等对方，于是其中一个被回滚。在两用户运行的第二次登录上复现。
2. **下载和分享可能在审计链头上死锁。** InnoDB 的死锁报告显示：一个分享事务持有 `audit_chain_heads`（id 1），在写审计记录时
   要等一个 `users` 行的共享锁（外键检查）；一个下载事务持有该 `users` 行的排他锁，在等 `audit_chain_heads`。
   6 用户混合负载下，约 1,330 次操作中失败了 4 次（0.3%）。

这类故障只在并发下出现，这正是做压测的意义。MySQL 对 1213 的建议是应用重试事务；更彻底的修法（让任何路径都不会在持有用户行时
再去等链头，或对这些事务使用 READ COMMITTED）由后端负责人选择。staging 正式测试会测出在真实并发下它们出现的频率。

## 压力从哪里来

由于 nginx 按 IP 限流，选择压测目标很关键：

| 目标 | 方法 | 测到的是 | 注意 |
| --- | --- | --- | --- |
| **经 SSH 隧道直连应用**（测容量推荐） | `ssh -N -L 18000:127.0.0.1:8000 <server>`，然后 `--base-url http://127.0.0.1:18000/api/v1` | 应用和数据库本身，不经过 nginx 和 TLS | 大文件吞吐受压测机自己的上行带宽限制，报告里要写明 |
| 入口（公网地址） | `--base-url https://secureview.tech/api/v1` | 包含 nginx 和 TLS 的真实路径 | 从一台机器主要测到每秒 10 个请求的限制；适合*展示*限流，不适合测容量 |
| 在另一台服务器上压测（如 j1900） | 从那台机器开同样的隧道 | 与直连相同，带宽取决于那台机器 | 需要在那台机器上装 loadtest 环境 |

PR #210 之后入口限制是每秒 30 个请求（突发 60），所以经公网地址的单台压测机能比上表压得更高。
2026-10-09 修复后的那次压测用 `loadtest/run_staging.sh` 走公网地址，限流全程开着，不需要隧道，也不用改 sshd。

在 VPS 本机上跑压测工具虽然没有网络瓶颈，但会抢占被测服务器的 CPU，所以不推荐。

**隧道需要 sshd 例外。** 服务器的 sshd 设置了 `AllowTcpForwarding no`，唯一的例外（`Match User jason,junyan,charter`）只放行
`127.0.0.1:3306`，所以上面的隧道能在本地开出端口，但每个请求都会被重置。2026-10-03 那次测试临时在 `/etc/ssh/sshd_config`
末尾加了一个只针对 root 的块（先备份，`sshd -t` 检查，`systemctl reload ssh` 生效），测完用备份还原：

```text
Match User root
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:8000
```

长时间测试时给隧道加上 `-o ServerAliveInterval=15`。

## 测试矩阵

对应会议纪要里的矩阵。时长只是建议；错误率超过约 5% 或 p95 涨到三倍以上时，就不要再继续加压。

| 维度 | 命令（接在通用参数之后） | 记录 |
| --- | --- | --- |
| 并发用户 | `steps --users 1,5,10,20,50,100 --duration 60 --size 1MiB` | 每档的 p50/p95/p99、每秒操作数、错误 |
| 文件大小与类型 | `sizes --sizes 1MiB,10MiB,50MiB,100MiB,200MiB,500MiB --types pdf,png,jpg,mp4,zip,exe` | 每个文件：上传、下载、分享、接收方下载、客户端加解密耗时、SHA-256 是否一致 |
| 单用户并行任务 | `parallel --users 5 --tasks 1,2,5,10 --duration 60` | 一个用户会不会拖慢其他人 |
| 混合负载 | `mixed --users <稳定值> --duration 300`（70% 上传、20% 下载、10% 分享/列表） | 最接近真实使用 |
| 持续压力 | `mixed --users <接近上限> --duration 1800 --window 60`（15/30/60 分钟） | p95、内存、连接数随时间的变化 |
| 超载与恢复 | `steps --users <稳定值>,<稳定值×1.5>,<稳定值×2>,<稳定值> --duration 60` | 超载时的错误类型，以及最后一档能否恢复 |
| 同时登录 | `logins --users 1,2,4,8,16 --rounds 3` | Argon2id 并发上限和登录死锁率，不重试 |

整个测试期间在服务器上运行 `server_sampler.py`；报告会把它记录的 CPU、iowait、内存、磁盘、网络、API 与 MySQL 进程的 CPU/内存，
以及数据库连接数，按每一档的时间段对齐。

## 运行步骤

**前提：** 服务器上没有别的负载；已通知团队；在 04:15 备份之前结束（否则备份会把测试文件也复制进去），也要在 05:30 完整性扫描之前结束。

**上传限额：** 自 2026-10-04 起，每个账户最多存储 2 GiB、24 小时内最多上传 5 GiB，nginx 限制每个地址同时最多 50 个上传。
光是 `sizes` 场景就会从一个账户上传约 5 GiB，soak 更多，所以做容量测试时要在 `/etc/fyp-secure-file-platform/backend.env`
里设置 `USER_STORAGE_QUOTA_BYTES=0` 和 `USER_DAILY_UPLOAD_BYTES=0`，重启 `fyp-backend`，测完再改回来。SSH 隧道绕过了 nginx，
所以连接数限制不影响测试。`UPLOAD_MIN_FREE_DISK_BYTES` 保持不变：它能防止压测把与其他服务共用的磁盘写满。自 2026-10-09 起，`sizes` 场景
按文件类型各用一个账号，每个文件验证完就删除，所以不会超出配额，那次压测配额也是开着的。

1. 在服务器上创建测试账号（文件权限 0600，只含测试账号）：

   ```bash
   cd /opt/mcs21/current/backend && set -a && . /etc/fyp-secure-file-platform/backend.env && set +a
   sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA \
     env PYTHONPATH=$PWD .venv/bin/python scripts/seed_load_users.py \
     --count 100 --out /tmp/loadtest-accounts.json
   ```

   `sudo` 会重置环境变量，不加 `--preserve-env` 的话，脚本会退回使用别处的数据库配置，报
   `Access denied for user 'fyp_user'`。

   把文件复制到压测机（`scp <server>:/tmp/loadtest-accounts.json .`），然后从服务器上删掉。
2. 在服务器上启动采样：
   `python3 /opt/mcs21/current/loadtest/server_sampler.py --interval 2 --out /root/loadtest-metrics.csv`
3. 在压测机上开隧道并运行各场景：

   ```bash
   cd loadtest && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
   ssh -N -L 18000:127.0.0.1:8000 <server> &
   .venv/bin/python -m secureview_load --base-url http://127.0.0.1:18000/api/v1 \
     --accounts loadtest-accounts.json --confirm-remote --out results steps --users 1,5,10,20,50,100
   ```

   目标不是本机时，没有 `--confirm-remote` 工具会拒绝运行。

   如果要走公网地址，`LOAD_ACCOUNTS=loadtest-accounts.json bash loadtest/run_staging.sh` 会按顺序跑完各场景，默认目标是
   `https://secureview.tech/api/v1`。大文件矩阵（每个方向约 5 GiB）只有设置 `LOAD_LARGE_FILES=1` 时才会跑。
4. 停止采样（Ctrl-C），把 CSV 复制回来，生成报告：
   `.venv/bin/python -m secureview_load.report results --server-metrics loadtest-metrics.csv --out results/REPORT.md`
5. 通过 API 删除测试账号及其全部文件：
   `.venv/bin/python -m secureview_load --base-url … --accounts loadtest-accounts.json --confirm-remote cleanup`

**存储：** 每次上传 1 MiB 时，一档 100 用户的测试就可能写入好几 GiB。清理会删掉它们；前后各看一次 `df -h`。

## 本地预演

`loadtest/run_local.sh` 用小规模参数对一次性的本地 API 和 MySQL（数据库名必须包含 `_test`）跑完所有场景，生成报告，并删除测试账号。
它的数字描述的是笔记本而不是服务器；它的作用是让正式测试不出意外。

```bash
DB_HOST=127.0.0.1 DB_PORT=3310 DB_USER=root DB_PASSWORD=... DB_NAME=fyp_loadtest_test bash loadtest/run_local.sh
```

工具自身的测试：`cd loadtest && .venv/bin/python -m pytest tests`。

## 结论

### 2026-10-09 重跑（修复后，公网地址）

版本 `ac5e2b0`，从家里宽带的笔记本经 `https://secureview.tech`（HTTPS 和 nginx，限流开着）压测。完整数字和测试条件见
[2026-10-09 报告](performance/REPORT-2026-10-09.zh-CN.md)。

- **完整性和错误：** 共 18,256 次操作；7,444 次下载解密后做了 SHA-256 校验，完整性失败 0 次；服务器 5xx 为 0（后端日志
  共 25,637 个请求，没有一个 500）。
- **容量：** 50 个并发用户以内所有请求都成功（上传 p95：1 人 134 ms，50 人 3.3 s；下载 p95：1 人 76 ms，50 人 9.5 s）。
  100 个用户时服务器没有出错。两次 100 用户步骤里被拒绝的 644 次上传，都是 nginx"每个地址最多 50 个上传同时进行"返回的
  429，因为所有负载都来自同一个地址。修复前同一步有 65% 到 78% 的上传返回 HTTP 500。
- **大文件：** pdf、png、jpg、mp4、zip、exe，1 到 500 MiB：36 个文件全部完成上传、分享和接收方下载，72 次下载全部逐字节
  一致。500 MiB 在这条网络上上传约 48 秒，下载约 43 秒。
- **瓶颈：** 从 10 个用户开始，吞吐停在每个方向约 8 到 9 MiB/s（约 70 Mbit/s），而服务器 CPU 平均 4.5%（峰值 42%），
  API 内存一直是 199 MiB。瓶颈是网络，不是程序。
- **限流和重试：** 共 713 个 429（644 个是同时上传数限制，1 个是 API 请求速率，68 个是登录并发上限和凭证校验限制），都是限制
  按设计起作用；1 个 413 来自每个账号 2 GiB 的配额（同一个文件随后用空账号重新上传成功）。MySQL 报了 8 次死锁，每次都被
  #139 的重试重试一次就成功，这是 #202 的日志才看得到的。
- **没有重跑：** 15、30、60 分钟的长时间压测。
- **第二天早上：** 安全 Agent 的每日检查（2026-10-10 06:00）失败，43 条 High 发现全部来自这次压测：五个最忙账号的上传和下载突增、
  清理步骤对已删除账号的 68 次登录失败，以及紧接着登进来的 32 个账号。这是 Agent 在真实流量上正常工作；
  如何确认、规则现在怎么说，见 [SECURITY_AGENT.zh-CN.md](SECURITY_AGENT.zh-CN.md#主动告警每日)。

### 修复前的对照（staging 实测，2026-10-03/04）

来自会议纪要，按 [staging 报告](performance/REPORT-2026-10-03.md) 填写：

- **容量：** 在当前服务器（8 vCPU、16 GB）上，5 个并发用户的上传/下载/分享混合负载累计运行 108 分钟（19,372 次操作），
  服务器端零错误；1 MiB 文件在测试链路上的上传 p95 为 2.1–4.9 秒、下载 p95 为 1.7–2.3 秒。50 个并发用户以内服务器没有返回
  任何错误（10–50 用户时看到的失败来自压测端的 SSH 隧道，详见报告）。100 个并发用户时 65–78% 的上传返回 HTTP 500。
  每用户 1/2/5/10 个并行任务均未引起服务器错误。
- **瓶颈：** 超过 50 个用户后，瓶颈是单个 API 进程的数据库连接池（5 + 10 个连接，最多等待 30 秒）：100 个用户时请求因等不到
  连接而超时，而服务器 CPU 平均只有 3%，内存平稳。**已于 2026-10-04 修复（PR #163）：** 原因是上传在等待线程池时一直占着连接，
  而线程池的线程又都在等连接；现在上传的数据库操作放在线程池里执行，暂存文件期间不持有连接。本地 100 用户那一档从 80% 上传
  失败变为零失败、每秒 56 次操作（[详情](performance/pool-fix-2026-10-04/README.zh-CN.md)）；当晚在 staging 上重测：100 用户时 102 次上传全部成功，完整性校验 0 次失败（[结果](performance/pool-fix-2026-10-04/README.zh-CN.md#staging-重跑2026-10-04-晚)）。再往上
  扩展，需要增加 uvicorn worker、扩大连接池，并用本工具重新测量。在这之下，所有传输数字都受网络限制：VPS 网口约 100 Mbit/s，测试链路约上行
  24 Mbit/s、下行 13 Mbit/s。
- **大文件：** 所有类型（pdf、png、jpg、mp4、zip、exe）在 500 MiB 以内都能逐字节一致地往返（144/144 次操作，每次下载都做了
  SHA-256 校验）；500 MiB 在约上行 24 Mbit/s、下行 13 Mbit/s 的链路上，上传 p50 为 146 秒、下载 p50 为 295 秒。整晚共校验
  5,094 次下载，完整性失败 0 次。
- **登录：** 服务器按设计同一时间只验证两个密码；4、8、16 个同时登录中分别有 50%、75%、71% 被立即以 HTTP 429 拒绝并需要
  重试，没有任何一次返回 500 或死锁。
- **恢复与监控：** 100 用户过载之后，紧接着的 5 用户阶段零错误，无需重启或人工干预；每次故意制造的过载都让 `mcs21-observe`
  发出且只发出一封告警邮件，并在下一次检查时自动解除。
