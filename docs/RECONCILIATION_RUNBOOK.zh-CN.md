# 对账清理运行手册

[English](RECONCILIATION_RUNBOOK.md) | [简体中文](RECONCILIATION_RUNBOOK.zh-CN.md)

本文说明 staging 对账清理任务如何安装、审查、启用、手动运行、停用、回滚与监控（issue #57）。任务本体是
`backend/scripts/reconcile.py`，它删除再也不会被读取的数据库行与存储条目。正因为它会删除数据，只有在
运维人员于真实主机上阅读过一次 report-only 运行结果、并记录到 [§11](#11-安装记录) 之后，才会启用。

| 组件 | 作用 |
|---|---|
| `backend/scripts/reconcile.py` | 默认只报告；加 `--apply` 才删除。每个类别都从截止线两侧计数。异常数量会被拒绝 |
| `deployment/server/mcs21-reconcile.{service,timer}` | 每天 05:00（Asia/Kuala_Lumpur）以 `fypapp` 运行，且只在同机备份刚完成之后 |
| `deployment/server/mcs21-alert` + `mcs21-alert@.service` | 任一运维 unit 失败时发邮件通知到人 |
| `deployment/server/mcs21-backup.service.d/alert.conf`、`mcs21-backup-verify.service.d/alert.conf` | 为两个仅存在于服务器上的备份 unit 加上告警的 drop-in |
| `deployment/server/mcs21-backup`、`mcs21-backup-verify` | 同机每日备份与每周恢复校验脚本，现已纳入版本管理 |

以上文件都不由 `mcs21-deploy` 安装，需按 §4 手动复制。

## 1. 它删除什么

行截止线为 30 天（`--retain-days`），存储宽限期为 60 分钟（`--storage-grace-minutes`）。

| 类别 | 删除条件 | 为什么已经无用 |
|---|---|---|
| `session_refresh_tokens` | 在截止线之前过期、已被使用或已被吊销，或属于本次一并删除的会话 | 一次性使用；已用或过期的令牌不会再被接受 |
| `user_sessions` | `absolute_expires_at` 或 `revoked_at` 早于截止线 | 过期在请求时按时间戳判定，已失效的会话本来就不可用 |
| `auth_login_throttles` | 计数窗口开始于截止线之前，**且**任何封禁都已在截止线之前结束 | 仍在封禁某人的桶永远不会被删除；删除它等于解除锁定 |
| `email_verification_codes` | `expires_at` 早于截止线 | 只存了带密钥的摘要，过期验证码本来就会被拒绝 |
| 孤立密文对象 | `ENCRYPTED_FILE_DIR` 下没有任何非 `DELETED` 的 `files` 行引用、且超过宽限期的 `*.ciphertext` | 请求在发布与提交之间中断，或删除时 unlink 失败所遗留 |
| 过期暂存上传 | `TEMP_FILE_DIR` 中超过宽限期的 `*.staging` | 从未完成的上传 |
| 空的按文件目录 | 超过宽限期的空 `ENCRYPTED_FILE_DIR/<file_id>/` | 对象删除后遗留的目录 |

在 staging 上，`ENCRYPTED_FILE_DIR=/var/lib/fyp-secure-file-platform/encrypted`，
`TEMP_FILE_DIR=/var/lib/fyp-secure-file-platform/tmp`，两者均为 `0700 fypapp`。

空目录与对象享有同样的宽限期。`app/services/file_storage_service.py` 中的 `publish` 先创建
`<file_id>/`，再把对象硬链接进去；客户端还可能用同一个 `file_id` 重试上传。若在这两步之间删掉新目录，
正在进行的上传就会失败。删除目录中最后一个对象会刷新该目录的 mtime，因此某次运行清空的目录会由下一次
运行回收。

## 2. 它永远不碰什么，以及证据

| 永不触碰 | 证据 |
|---|---|
| `audit_logs`、`audit_chain_heads` | 运行时授权（`database/mysql/02-schema.sql`）对 `audit_logs` 只有 `SELECT, INSERT`，对 `audit_chain_heads` 只有 `SELECT, UPDATE (last_log_id, current_hash, updated_at)`。以 `fyp_user` 连接时，即使有 bug，任务也**不可能**删除审计证据 |
| `users`、`user_keys`、`user_key_protection_profiles`、`encrypted_private_key_bundles`、`recovery_keys`（密钥保管） | 脚本从不引用这些表。指向被清理表的唯一外键是 `session_refresh_tokens.session_id → user_sessions ON DELETE CASCADE`；没有任何级联从被清理的表传到审计、密钥或恢复相关的表 |
| `recovery_requests` | 从不引用；过期的请求是问责证据 |
| `files`、`file_folders`、`file_access_grants`、`file_key_wrappings`、`integrity_checks`（在用授权） | `files` 只被读取，用来判断哪些对象在用，从不写入。被在用行引用的对象无论多旧都保留 |
| 本应失效的访问 | 访问令牌只能通过连接 `user_sessions.access_token_hash` 认证（`app/repositories/auth_repository.py` 中的 `get_access_principal`）。会话行被删除意味着令牌被拒绝，因此删除只会减少访问，永远不会让访问复活 |

测试强制保证这些。`backend/tests/unit/test_reconcile.py` 编译任务发出的每条语句；
`backend/tests/integration/test_reconcile_mysql.py` 在一次 report 运行和一次 apply 运行期间捕获 MySQL
收到的每条语句。任何语句引用上表中的表，或写操作的目标不是那四张被清理的表，两者都会失败。MySQL 测试还
检查 `audit_logs` 行数、哈希链头与 `users` 行数不变，以及一个 90 天前、仍有在用行的对象被保留。

## 3. 调度中内置的保护

- **先有回滚点。** `mcs21-backup.timer` 在 04:15 运行（最多随机延迟 20 分钟），
  `mcs21-reconcile.timer` 在 05:00 运行。删除任何东西之前，服务会先等待
  `/run/lock/mcs21-backup.lock`，并且除非存在一个不超过 3 小时的完整 `/var/backups/mcs21-daily` 备份集，
  否则**拒绝启动**。05:00 时有资格被删除的东西（超过 60 分钟）都创建于 04:00 之前，因此都在当天早上的
  备份里。停机后两者一起补跑时，`After=mcs21-backup.service` 保证这个顺序不变。
- **数量保护。** 带 `--apply` 时，若一次运行将删除的条目总数超过 `--max-deletions`（1000），或密文对象
  超过 `--max-object-deletions`（10），则**什么都不删**，打印原因并以状态码 **3** 退出；unit 随之失败，
  告警触发。取值理由：staging 对象存储总共只有约二十几个对象（约 738 MB），孤立对象只来自崩溃的请求，
  一天超过十个就说明目录或数据库配错了——正是任务否则会清空存储的情况。数据行的增长大约是每次登录一个
  会话，外加每半小时活跃一个刷新令牌；少数测试者加上 E2E 套件每天产生几十到几百行，每日运行大约删除一天
  的量，一千相当于好几天的量。report-only 运行超限时只打印 `WARNING`。
- **幂等。** 删除条件只取决于时间戳和在用状态。紧接着再运行一次什么也找不到（由
  `test_apply_removes_only_what_crossed_and_a_second_run_finds_nothing` 证明）。
- **顺序。** 四类数据行在同一个事务中删除；存储只在该事务提交之后才被触碰，因此中途崩溃要么删除了全部
  行，要么一行都没删。

## 4. 安装（一次性，在 PR 合并并部署之后）

在 staging 主机上执行。`R` 是已部署的 release，因此这些文件就是合并、审阅过的版本。

```bash
R=/opt/mcs21/current
cat "$R/.mcs21-release"          # 必须是 #57 PR 的合并提交

# 纳入版本管理的副本与当前运行的版本只有审阅过的差异：头部注释，以及 backup-verify 的修复。
sudo diff -u /usr/local/sbin/mcs21-backup "$R/deployment/server/mcs21-backup"
sudo diff -u /usr/local/sbin/mcs21-backup-verify "$R/deployment/server/mcs21-backup-verify"

sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-backup"        /usr/local/sbin/mcs21-backup
sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-backup-verify" /usr/local/sbin/mcs21-backup-verify
sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-alert"         /usr/local/sbin/mcs21-alert

sudo install -o root -g root -m 0644 "$R/deployment/server/mcs21-alert@.service" \
  "$R/deployment/server/mcs21-reconcile.service" "$R/deployment/server/mcs21-reconcile.timer" \
  /etc/systemd/system/
sudo install -D -o root -g root -m 0644 "$R/deployment/server/mcs21-backup.service.d/alert.conf" \
  /etc/systemd/system/mcs21-backup.service.d/alert.conf
sudo install -D -o root -g root -m 0644 "$R/deployment/server/mcs21-backup-verify.service.d/alert.conf" \
  /etc/systemd/system/mcs21-backup-verify.service.d/alert.conf
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/mcs21-reconcile.service \
  /etc/systemd/system/mcs21-reconcile.timer
```

`mcs21-offsite-backup.service`（issue #56）已自带 `OnFailure=`，一经安装即会告警。

然后配置并测试告警（§9），并确认修复后的恢复校验能通过。它自 2026-08-16 起每周都失败，因为它期望的
Schema 是 `0002`：

```bash
sudo systemctl start mcs21-backup-verify.service      # 需要几分钟
sudo journalctl -u mcs21-backup-verify.service -n 5 --no-pager
# 期望："MCS21 backup restore verification passed: mcs21-db-<stamp>.sql.gz"
```

## 5. report-only 运行（演练）

它不删除任何东西。它以 `fypapp` 身份、带应用的环境运行，与 unit 完全一致。输出只有数量和截止时间，
不含令牌哈希、邮箱或文件名，因此可以保留并贴到 issue 中。

```bash
sudo install -d -o root -g root -m 0750 /var/log/mcs21-reconcile
sudo systemd-run --pipe --wait --quiet --uid=fypapp --gid=fypapp \
  --working-directory=/opt/mcs21/current/backend \
  --property=EnvironmentFile=/etc/fyp-secure-file-platform/backend.env \
  /opt/mcs21/current/backend/.venv/bin/python scripts/reconcile.py \
  | sudo tee "/var/log/mcs21-reconcile/report-only-$(date +%Y%m%d).txt"
```

各列含义：

- `eligible`：现在就会被删除的数量。
- `crossed last 7d`：其中在最近七天内越过截止线的数量（刚过边界）。
- `crosses next 7d`：今天保留，但将在未来七天内越过截止线的数量（刚在边界内）。对存储类别（`*`），
  这一列统计仍处于 60 分钟宽限期内、未被引用的条目。

## 6. 审查每条边界的两侧

在启用 timer 之前完成，并把结果记录到 §11。

1. **数据行。** 对每个数据行类别，`crossed last 7d` 与 `crosses next 7d` 应处于同一数量级：大约五周前
   一周的正常登录量。两者严重不对称通常意味着时钟或时区有问题，检查 `timedatectl`。
   `lapsed throttle buckets` 绝不能包含仍在封禁某人的桶：谓词排除了它，MySQL 测试也证明了这一点。
2. **独立交叉核对数据行**（只读，在容器内以 MySQL root 执行，只返回数量；时间均为不带时区的 UTC）：

   ```bash
   sudo docker exec mcs21-mysql sh -c 'MYSQL_PWD=$(cat /run/secrets/mysql-root-password) mysql -uroot --protocol=socket fyp_secure_file_platform -e "
     SET @c = UTC_TIMESTAMP() - INTERVAL 30 DAY, @w = 7;
     SELECT what, SUM(t < @c) eligible,
            SUM(t >= @c - INTERVAL @w DAY AND t < @c) crossed_7d,
            SUM(t >= @c AND t < @c + INTERVAL @w DAY) crosses_7d
     FROM (
       SELECT \"sessions\" what, LEAST(absolute_expires_at, COALESCE(revoked_at, absolute_expires_at)) t FROM user_sessions
       UNION ALL SELECT \"codes\", expires_at FROM email_verification_codes
     ) lapsed GROUP BY what;"'
   ```

   sessions 与 codes 两行应与脚本的 `expired sessions`、`expired verification codes` 完全一致（两次运行
   之间恰好越过边界的行除外）。脚本的刷新令牌数量会比简单查询多，因为它还包括了随会话一起删除的令牌。
3. **对象。** 如果 `orphaned ciphertext objects` 不为零，先列出孤立对象并逐个核对，再决定是否启用。
   对象键是随机 UUID 而不是文件名，但这些清单仍只保存在 root 下，不要贴进 issue：

   ```bash
   sudo -i
   cd /var/lib/fyp-secure-file-platform/encrypted
   find . -name '*.ciphertext' | sed 's#^\./##' | sort > /root/objects.txt
   docker exec mcs21-mysql sh -c 'MYSQL_PWD=$(cat /run/secrets/mysql-root-password) mysql -uroot --protocol=socket -N fyp_secure_file_platform -e "SELECT storage_object_key FROM files WHERE status <> \"DELETED\" ORDER BY 1"' | sort > /root/live.txt
   comm -23 /root/objects.txt /root/live.txt      # 未被引用：报告中的 eligible + 宽限期内的对象
   comm -13 /root/objects.txt /root/live.txt      # 有在用行却没有对象：必须调查，不能忽略
   ```

   对每个孤立对象，`SELECT file_uuid, status FROM files WHERE file_uuid = '<file_id>'` 应当没有返回行，
   或返回一行 `DELETED`。出现其他结果则停止上线。
4. **数量。** 如果报告以 `WARNING: ... exceed --max-deletions` 结尾，那是第一次运行的积压。按 §7 手动
   清理一次，不要调高 unit 的上限。

## 7. 启用、手动运行、停用

```bash
# 启用（仅在 §6 已记录之后）
sudo systemctl enable --now mcs21-reconcile.timer
systemctl list-timers mcs21-backup.timer mcs21-reconcile.timer

# 现在带全部保护运行 unit（先做一次新备份；unit 要求备份不超过 3 小时）
sudo systemctl start mcs21-backup.service
sudo systemctl start mcs21-reconcile.service
sudo journalctl -u mcs21-reconcile.service -n 40 --no-pager

# 阅读报告后一次性清理积压：先做新备份，再显式指定上限
sudo systemctl start mcs21-backup.service
sudo systemd-run --pipe --wait --quiet --uid=fypapp --gid=fypapp \
  --working-directory=/opt/mcs21/current/backend \
  --property=EnvironmentFile=/etc/fyp-secure-file-platform/backend.env \
  /opt/mcs21/current/backend/.venv/bin/python scripts/reconcile.py --apply --max-deletions <审阅过的总数>

# 幂等检查：紧接着运行 §5 的 report-only 命令，eligible 应全部为 0

# 停用
sudo systemctl disable --now mcs21-reconcile.timer
sudo systemctl stop mcs21-reconcile.service     # 仅当有运行正在进行时
```

不要为了清理孤立对象而调高 `--max-object-deletions`。超过十个孤立对象是事故（§10），不是积压。

## 8. 回滚

删除不可逆。回滚点是运行前写入的 `/var/backups/mcs21-daily` 备份集：`mcs21-db-<stamp>.sql.gz`、
`mcs21-files-<stamp>.tar.gz` 与 `mcs21-<stamp>.sha256`。备份集保留 14 天，必须在此期限内处理。

| 被删除的 | 需要恢复吗？ |
|---|---|
| 过期/已吊销的会话、刷新令牌、验证码 | **不需要。** 它们本来就不可用，恢复它们不会授予任何权限，用户重新登录即可 |
| 已失效的限流桶 | 不需要。只有在窗口和任何封禁都已结束后才会删除 |
| 实际仍被需要的孤立密文对象 | **需要。** 这是唯一一种误删会丢失用户数据的类别 |

恢复单个对象（以 root 执行）：

```bash
cd /var/backups/mcs21-daily
sha256sum --check mcs21-<stamp>.sha256
tar -tzf mcs21-files-<stamp>.tar.gz | grep '<file_id>/'
tar -xzf mcs21-files-<stamp>.tar.gz -C /var/lib/fyp-secure-file-platform --keep-old-files \
  './encrypted/<file_id>/<object>.ciphertext'
chown -R fypapp:fypapp '/var/lib/fyp-secure-file-platform/encrypted/<file_id>'
sha256sum '/var/lib/fyp-secure-file-platform/encrypted/<file_id>/<object>.ciphertext'
# 必须等于该行的 files.encrypted_sha256；然后通过应用下载验证
```

无法恢复的：在该次运行之前那份备份之后才创建的对象。计划运行不可能删除这样的对象（§3），手动运行前
也会先做新备份（§7）。如果被清理表中的某行确实需要找回，把 dump 恢复到一次性容器中（做法同
`mcs21-backup-verify`），再复制那几行。不要为此把 dump 直接导入线上数据库：那会回滚其他所有表，
包括审计哈希链。

## 9. 告警

`mcs21-alert@<unit>.service` 会发送邮件，内容包括失败 unit 的名称、主机、时间、
`Result`/`ExecMainStatus` 以及最近 30 行 journal。邮件通过应用已有的 Resend 账户发送（从 `backend.env`
读取 `RESEND_API_KEY`、`EMAIL_FROM_ADDRESS`、`EMAIL_FROM_NAME`），收件人来自另一个仅 root 可读的文件。
脚本只解析这几个键（从不 source 这两个文件），并通过一个 `0600` 的 header 文件把 API key 交给 `curl`，
绝不放在命令行上。邮件服务商的响应正文从不写入日志。

```bash
sudo install -o root -g root -m 0600 /dev/null /etc/fyp-secure-file-platform/alert.env
sudoedit /etc/fyp-secure-file-platform/alert.env
#   ALERT_EMAIL_TO=first.person@example.com,second.person@example.com
sudo systemctl start mcs21-alert@test.service
sudo journalctl -u mcs21-alert@test.service -n 5 --no-pager    # 期望 "sent (HTTP 200)"
```

确认每个收件箱都真的收到了测试邮件。会告警的 unit：`mcs21-reconcile`、`mcs21-backup`、
`mcs21-backup-verify`、`mcs21-offsite-backup`。告警自身失败时不会再告警（否则会循环），它会出现在
`systemctl --failed` 与 `journalctl -u 'mcs21-alert@*'` 中。

## 10. 事故处理流程（收到告警）

1. 从邮件主题确定 unit，然后执行 `systemctl status <unit>` 和
   `journalctl -u <unit> -n 100 --no-pager`。
2. **`mcs21-reconcile.service`：**
   - `ExecMainStatus=3`：数量保护拒绝了运行，**没有删除任何东西**。阅读 journal 中的报告，然后检查时钟
     （`timedatectl`）、`backend.env` 中的 `ENCRYPTED_FILE_DIR` 与 `DB_*`，以及是否刚做过部署或迁移。
     对孤立对象执行 §6 第 3 步。若数量属实（例如一次 E2E 突发），按 §7 手动清理一次；否则停用 timer
     并开 issue。
   - "no mcs21-daily backup from the last 3 hours"：备份失败或延迟，没有删除任何东西。先修好备份；
     备份自己的告警通常也会到达。
   - Python 报错（数据库不可达等）：数据行删除是一个事务，存储只在提交后才会被触碰。修复原因后按 §7
     手动运行。
   - 有人报告文件丢失：执行 `systemctl disable --now mcs21-reconcile.timer`，保留 journal，按 §8 恢复，
     并开一个关联 #57 的事故 issue。
3. **`mcs21-backup.service`：** 检查磁盘空间（`df -h /var/backups`）、`docker ps` 中的 `mcs21-mysql`，
   然后执行 `systemctl start mcs21-backup.service`。在它成功之前，对账清理会拒绝运行。
4. **`mcs21-backup-verify.service`：**
   - "structural verification"：恢复出的 Schema 与已部署 release 不一致。
   - "Live database is at X but the deployed release head is Y"：部署或迁移只做了一半。先完成它
     （docs/DEPLOYMENT.zh-CN.md），再重新运行。
   - "CHECK TABLE"：视该备份为不可用，并上报。
5. **`mcs21-offsite-backup.service`：** 按 docs/BACKUP_AND_RECOVERY.zh-CN.md 处理。
6. 把发生了什么、做了什么记录到相应 issue 中。

## 11. 安装记录

在主机上填写。所有行填完之前，不要把 #57 标记为完成。

| 项目 | 值 |
|---|---|
| 已安装的 release SHA（`/opt/mcs21/current/.mcs21-release`） | `1c0dcf01ff24606df78a06a8c4eba6a250e8c7f2`（之后又安装了 #86 的告警单元修复，`3e7b7f6`） |
| 测试告警收件人（姓名、日期） | 2026-09-24：`mcs21-alert@test` 与一次真实 unit 告警发往 Shuoxun Wen 的邮箱，Resend 均已接受（HTTP 200）；是否收到待确认 |
| `mcs21-backup-verify` 恢复通过（日期、备份时间戳） | 2026-09-24，`mcs21-db-20260923T202022Z.sql.gz`——自 2026-08-16 以来首次通过 |
| report-only 运行：日期时间（UTC）及 `/var/log/mcs21-reconcile/` 中的文件 | 2026-09-24 14:10 UTC，`report-only-20260924-2210.txt` |
| report-only 各类别数量：eligible / crossed last 7d / crosses next 7d | 共 43 条可删。refresh token 3/3/60，会话 3/3/58，登录限流 27/25/11，验证码 10/10/4，存储 0/0/0。会话与验证码数量与 §6 的独立查询完全一致；未来 7 天的高峰是 staging 最早一周的数据（2026-08-20 起）满 30 天，不是时钟问题（时钟已 NTP 同步）。 |
| 孤立对象审查（数量，以及逐个确认未被引用） | 0。磁盘上 24 个对象、24 条有效记录，没有未被引用的对象，也没有缺少对象的记录。 |
| 是否手动清理积压？（使用的上限、日期） | 不需要：43 条低于 1000 的上限。 |
| 第二次 report-only 运行 eligible 为 0（幂等） | `<...>` |
| 审查人 | Shuoxun Wen |
| timer 启用（日期、`systemctl list-timers` 显示的下次运行） | 2026-09-24；下次运行 2026-09-25 05:00 +08 |
| 第一次计划运行结果（journal 摘录、日期） | `<...>` |
