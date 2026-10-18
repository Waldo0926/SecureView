# 可观测性与事故响应 Runbook

[English](OBSERVABILITY_AND_INCIDENT_RESPONSE.md) | [简体中文](OBSERVABILITY_AND_INCIDENT_RESPONSE.zh-CN.md)

本文是 issue #59 的运维契约：在不把日志、指标或告警邮件变成第二份用户数据副本的前提下，为
SecureView 增加可观测性、外部审计锚点和事故处理流程。项目仍是 FYP 原型；这些控制用于提升发现与
响应能力，不代表任何外部安全认证。

## 1. 最小化数据的事件模型

应用通过 `secureview.events` logger 输出紧凑 JSON 事件。事件只包含运维元数据，设计上不记录请求/响应
正文、query string、异常原文、文件名、文件内容、邮箱、用户名、Bearer/refresh token、密码、
passphrase、wrapped key、PEM、Cookie 或私钥。`backend/app/core/observability.py` 还会按敏感字段名
再次脱敏，作为最后一道保护。

客户端地址也不按原值记录：Uvicorn 先在受信代理边界内解析真实客户端地址，事件层随后将 IPv4 缩减到
`/24`、IPv6 缩减到 `/64`。路由记录的是 FastAPI 模板，例如
`/api/v1/recovery/{request_id}/approve`，不会写入真实 UUID。每个请求使用随机 16 位十六进制 request
ID 做关联，不使用用户身份作为关联键。

| 事件 | 触发条件 | 安全字段 |
|---|---|---|
| `auth.failure` | 后端认证失败 | request ID、method、路由模板、脱敏后的客户端网段、稳定 error code |
| `auth.rate_limited` | 应用限流触发 | 同上，warning 级别 |
| `storage.unavailable` | 存储不可用 | 路由模板和稳定 error code，不含 object key/文件名 |
| `storage.integrity_failure` | 完整性校验拒绝文件 | 路由模板和稳定 error code，不含文件 ID/内容 |
| `readiness.failed` / `readiness.recovered` | DB 不可用、Schema revision 不一致或恢复 | readiness 状态与 schema revision |
| `recovery.operation` | POST recovery 操作返回 | 路由模板、状态码、耗时、脱敏客户端网段；不含理由、key material 或请求正文 |
| `application.unhandled_error` | 未预期异常 | 只记录异常**类型**，不记录异常字符串 |

部署与回滚结果继续使用独立运维审计：`/var/log/mcs21-deploy/audit.log` 与 journald。`mcs21-deploy`
只写受控字段，如 `caller`、`action`、`result`、commit/backup 路径或受控失败位置，不记录
`backend.env` 或数据库密码。

数据库重试单独记录在 `secureview.db` 上（#202）：每个被重试的事务写一条 warning，形如
`mysql_transaction_retry code=1213 attempt=2 of 3`，只含 MySQL 错误码和第几次尝试，从不包含 SQL 语句或参数。
用 `journalctl -u fyp-backend | grep mysql_transaction_retry` 可以统计死锁（1213）或锁等待超时（1205）被重试的次数。

## 2. 仅宿主机可访问的 Metrics

`GET http://127.0.0.1:8000/internal/metrics` 是仅宿主机使用的运维接口。生产 Uvicorn 绑定
`127.0.0.1`；tracked nginx 只反代 `/api/`、health 与可选 docs 路由，并不反代 `/internal/`。
该 endpoint 不进入 OpenAPI，只返回计数器：

- 进程启动时间与 uptime；
- 请求、4xx、5xx 总数；
- 认证失败与应用限流次数；
- storage / integrity failure 次数；
- 未处理异常次数；
- readiness / schema mismatch 状态切换；
- recovery POST 操作次数。

计数器会在 backend 重启后归零。`backend/scripts/observe_runtime.py` 保存 process start ID，检测到
重启时会建立新基线，不会把归零误判成异常。

### 告警阈值

`mcs21-observe.timer` 每 5 分钟采样一次。新出现的阈值越界会让 `mcs21-observe.service` 失败一次，
从而触发 `mcs21-alert@.service`。同一个持续存在的越界会继续出现在 JSON snapshot 中，但不会每 5 分钟
重复发邮件；若又出现新的 breach，则再次告警。

| 信号（除特别注明外均按 5 分钟区间） | 阈值 | 主要负责人 |
|---|---:|---|
| backend readiness | 任何非 `ready` | 运维/部署负责人 |
| 应用 rate-limit | 5 次 | 安全负责人，运维协助 |
| 认证失败 | 50 次 | 安全负责人 |
| storage unavailable | 3 次 | 运维/部署负责人 |
| integrity refusal | 3 次 | 安全 + 运维 |
| 未处理应用异常 | 3 次 | Backend 负责人 |
| schema mismatch 状态切换 | 任意 1 次 | Backend + 运维 |
| 文件系统占用 | >= 85% | 运维/部署负责人 |
| 外部 audit checkpoint 年龄 | 缺失或 > 2 小时 | 安全 + 运维 |

这些是 staging 阈值，适合当前 FYP 测试量；若未来要宣称生产用途，应先用实际流量重新校准。不要为了让
告警消失而静默提高阈值。

## 3. Trusted Proxy 边界

Backend 绝不能无条件相信来自任意客户端的 `X-Forwarded-For`。staging 拓扑是：

```text
Internet -> nginx :443 -> Uvicorn 127.0.0.1:8000
```

Uvicorn 启动参数必须同时包含：

```text
--proxy-headers --forwarded-allow-ips=127.0.0.1
```

因此只有 loopback 上的 nginx peer 能通过 proxy header 改变 `request.client`。应用事件层读取该已解析地址，
然后进一步缩减为网段。启用 #59 前必须在真实主机核验，而不能只假设 tracked preflight 与 live unit 一致：

```bash
sudo systemctl cat fyp-backend | grep -E -- '--proxy-headers|--forwarded-allow-ips'
sudo ss -ltnp | grep ':8000'
# 预期：127.0.0.1:8000，且 forwarded-allow-ips=127.0.0.1。
```

如果将来 backend 放到其他 proxy、load balancer、container bridge 或 CDN 后面，必须重新明确受信来源；
Internet 可达 listener 上禁止使用 `--forwarded-allow-ips='*'`。

## 4. 数据库外部的 Audit Chain Checkpoint

数据库内 audit hash chain 能发现普通篡改，但若有权限的攻击者同时重写 `audit_logs` 与
`audit_chain_heads`，可以制造一条内部自洽的新链。`backend/scripts/audit_checkpoint.py` 因此把当前链头
发布到应用数据库之外。

checkpoint 只包含：

- format version 与 UTC 创建时间；
- 精确部署 Git commit；
- `last_log_id`、`current_hash`、`schema_revision`、chain-head 更新时间；
- 对规范化 payload 做的 HMAC-SHA256。

不包含 audit row、用户数据或文件内容。HMAC key 是独立的 root-only 256-bit 随机值，不会传给 backend
进程。staging 应把 checkpoint 放进现有 Cloudflare R2 object-lock 备份 bucket 的独立 prefix。保留下来的
旧 checkpoint 就是数据库外的信任锚点：在保留/锁定窗口内，后续 VPS/DB compromise 不能无痕重写这些
已认证记录。

### Key 与 destination 设置

HMAC key 必须另存一份离线副本用于独立验证。VPS 上：

```bash
sudo install -d -o root -g root -m 0700 /etc/fyp-secure-file-platform
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/fyp-secure-file-platform/audit-checkpoint.key'
sudo chmod 0400 /etc/fyp-secure-file-platform/audit-checkpoint.key

sudo sh -c 'cat > /etc/fyp-secure-file-platform/audit-checkpoint.env <<EOF
AUDIT_CHECKPOINT_DEST=s3://<bucket>/<prefix>/audit-checkpoints
EOF'
sudo chmod 0600 /etc/fyp-secure-file-platform/audit-checkpoint.env
sudo install -d -o fypapp -g fypapp -m 0750 /var/lib/mcs21-observe
```

`mcs21-audit-checkpoint.service` 只读取 `backup.env` 中已有的最小权限 backup DB/S3 设置，以及
`audit-checkpoint.env` 中的独立 destination；它**不读取** `backend.env`。service 以 root 运行只是为了
让 app account 无权读取 HMAC key；systemd hardening 让其余文件系统保持只读。

### 安装并先手工跑一次

```bash
R=/opt/mcs21/current
sudo install -o root -g root -m 0644 \
  "$R/deployment/server/mcs21-audit-checkpoint.service" \
  "$R/deployment/server/mcs21-audit-checkpoint.timer" \
  "$R/deployment/server/mcs21-observe.service" \
  "$R/deployment/server/mcs21-observe.timer" \
  /etc/systemd/system/
sudo install -o root -g root -m 0755 "$R/deployment/server/mcs21-alert" /usr/local/sbin/mcs21-alert
sudo systemctl daemon-reload
sudo systemd-analyze verify \
  /etc/systemd/system/mcs21-audit-checkpoint.service \
  /etc/systemd/system/mcs21-audit-checkpoint.timer \
  /etc/systemd/system/mcs21-observe.service \
  /etc/systemd/system/mcs21-observe.timer

sudo systemctl start mcs21-audit-checkpoint.service
sudo journalctl -u mcs21-audit-checkpoint.service -n 20 --no-pager
sudo cat /var/lib/mcs21-observe/audit-checkpoint.latest

sudo systemctl start mcs21-observe.service
sudo journalctl -u mcs21-observe.service -n 20 --no-pager

sudo systemctl enable --now mcs21-audit-checkpoint.timer mcs21-observe.timer
systemctl list-timers mcs21-audit-checkpoint.timer mcs21-observe.timer
```

首次 observer run 是建立计数器基线；应看到 `health_status=ready`、磁盘低于阈值，并且 checkpoint 新鲜。

### 独立验证

从 R2 下载一个 checkpoint 到另一台可信机器，并通过**独立的运维通道**复制 HMAC key。不要把 key 放进
Git、聊天、CI artifact 或 R2 bucket。从相同代码 checkout 执行：

```bash
cd backend
python scripts/audit_checkpoint.py verify /path/to/audit-checkpoint-....json \
  --key-file /offline/path/audit-checkpoint.key
```

若要在事故调查中与数据库副本或 live read-only backup connection 对比：

```bash
# 先设置只读 CHECKPOINT_DB_* 或 BACKUP_DB_*。
python scripts/audit_checkpoint.py verify-live /path/to/audit-checkpoint-....json \
  --key-file /offline/path/audit-checkpoint.key
```

`verify-live` 会确认 checkpoint 中的 `last_log_id` 在当前 audit log 中仍对应完全相同的外部认证 hash，且
live chain 没有倒退。因此，即使攻击者重写了一条内部自洽的新链，只要它不再包含旧 anchor，就会被发现。

## 5. 告警邮件刻意保持最小化

`mcs21-alert` 不再把原始 journal 行发送到邮件。journal 适合在 VPS 本地调查，但把它经第三方邮件服务
传输，会让任何未来的 logging regression 都可能变成数据泄露路径。告警邮件只包含 unit、host、时间、
systemd result/exit status、runbook，以及应在本地执行的精确 `journalctl` 命令。

Resend API key 仍然只通过 mode-0600 header 文件传给 `curl`，不会进入 argv 或日志；Resend response body
也不写日志，因为它可能回显收件人地址。

## 6. 事故处理流程

### A. Backend / 网站宕机

1. `systemctl status fyp-backend nginx --no-pager`。
2. 请求 `http://127.0.0.1:8000/health/live` 与 `/health/ready`。
3. `journalctl -u fyp-backend -n 100 --no-pager`，关注 structured readiness/unhandled-error 事件。
4. 若事故紧跟部署发生，执行 `sudo mcs21-deploy status` 并检查 `/var/log/mcs21-deploy/audit.log`。
5. 只有 Schema 未变化时才能只回滚代码；Schema change 按 `docs/DEPLOYMENT.md` 处理，否则 code-only rollback
   本身可能造成 `schema_incompatible`。
6. 反复 restart 前先保留 journal 与 deployment audit 证据。

### B. Ciphertext storage 损坏 / integrity 告警

1. **不要**删除或覆盖对象。通过认证 UI/API 调查并私下记录时间和受影响 public file UUID，不要贴到公开 issue。
2. 停止任何手工 cleanup；必要时 `sudo systemctl disable --now mcs21-reconcile.timer`。
3. 执行应用 integrity check，对比 `files.encrypted_sha256` 与实际对象 SHA-256。
4. 检查最近的同机/异地备份与 tamper drill；只恢复经过验证的单个 ciphertext 对象，不要为了一个对象恢复整个
   live DB。
5. 若 DB/object SHA-256 一致但客户端 AEAD authentication 失败，在证据排除前按“DB + storage 同时失陷”处理。

### C. 怀疑 Credential / Token 泄露

1. 先确定凭据类别：用户 session、runtime DB、backup account、Resend key、S3/R2 key 或 SSH credential。
2. 优先在真正的 authority 处 revoke/rotate；只改本地 env 文件而旧凭据仍有效不算轮换。
3. 用户 session 应撤销服务端 session family；基础设施凭据更换 root-only env 后，只重启消费它的 unit。
4. 在本地 structured log 中按**事件类型和时间窗口**查，不要按 secret 值搜索；正常情况下 secret 根本不应存在于日志。
5. 若任何 secret 出现在日志、邮件、CI artifact 或 Git history，立即轮换，保存证据，并开 incident issue；不要把值贴进 issue。

### D. Migration 失败 / Schema mismatch

1. 停止对目标 SHA 的自动 deploy 重试。
2. 保存 `/health/ready`、`alembic current`、`alembic heads` 和 deploy audit entry。
3. 按 `docs/DEPLOYMENT.md` 的 reviewed forward/rollback SQL 流程处理；禁止为了让 readiness 变绿而盲目 stamp DB。
4. 重跑 `database/mysql/03-verify.sql` 与常规 health probe 后再解除事故状态。

### E. Audit chain / 外部 checkpoint 不一致

1. 暂停高风险 admin/recovery 操作，并保留数据库和外部 checkpoint。
2. 在离线环境先用 `audit_checkpoint.py verify` 验证至少一个较旧 checkpoint。
3. 执行既有 audit-chain verifier，再用外部认证 checkpoint 做 `verify-live`。
4. 如果内部链自洽但外部 anchor 不匹配，应视为链被重写的证据；不要在原库中“修好”它。保留 DB、checkpoint、
   deployment log 和 backup 供复核。
5. 只有怀疑 HMAC key custody 失陷时才轮换 key；轮换不会让历史 checkpoint 失效，旧 key 在相应验证窗口内仍需离线保留。

### F. Recovery key 事故

1. 通过授权流程 disable/revoke 受影响 recovery public key；禁止把 recovery private material 上传服务器。
2. custody 调查完成前暂停 recovery execution。
3. 检查 `recovery.operation` structured event 与 tamper-evident audit record。observability stream 故意不包含
   reason、wrapped key 或 PEM。
4. 若轮换 recovery public key，遵守 requester/reviewer separation，并在撤销旧 key 前确认哪些 file recovery wrapping
   需要 successor 处理。
5. 记录 finding/disposition，但绝不发布 recovery private key 或 execution package。

## 7. 证明敏感数据没有进入日志/告警

CI/unit test 应持续证明：

- observability 会脱敏 token/password/passphrase/private-key/filename/content 字段；
- recovery event 使用 route template，不包含真实 request ID；
- alert email 不包含 journal output；
- alert API key 不进入 `curl` argv；
- audit checkpoint document 只含 anchor metadata；
- checkpoint HMAC key 不在 `backend.env`，且 checkpoint service 不把它暴露给应用进程；
- metrics state file 只包含计数器和 breach code。

真实 staging 还应使用**人工合成 marker** 发起 throwaway test request，然后确认这些 marker 不出现在
`journalctl`、告警邮件、metrics state file 与 external checkpoint 中。不要拿真实密码、token、private key
或用户文件做 marker。

## 8. Staging 证据记录

以下各行已根据 Issue #59（2026-09-25）中记录的主机实测结果填写，该 Issue 已据此关闭；2026-10-01 再次观察过预发布环境的地方已注明：

| 项目 | 证据 |
|---|---|
| 精确 merged/deployed SHA | `0beb967949442a72b9553e7842d82041e39ff27b`，2026-09-25 在预发布环境健康运行（此后预发布环境已前进，2026-10-01 运行的是 `70fcb6d`） |
| Live Uvicorn bind + trusted proxy 参数已核验 | 后端仅监听 loopback，且仅信任来自 `127.0.0.1` 的转发头，2026-09-25；2026-10-01 再次观察到 127.0.0.1:8000 与 127.0.0.1:3306 |
| `/internal/metrics` 仅 loopback 可访问，nginx 未暴露 | 本地可访问；同一路径经 HTTPS 访问时 nginx 返回 404，2026-09-25 |
| 首个 external checkpoint 已上传且 stamp 新鲜 | 2026-09-25 已发布到 R2；2026-10-01 timer 仍在每小时发布（`audit-checkpoint-20261001T011600Z-602.json`） |
| checkpoint 已在另一台机器独立验证 | 下载后 SHA-256 一致，并在另一台 Mac 上完成 HMAC 校验，2026-09-25 |
| `mcs21-observe` 基线健康，两个 timer 已启用 | 基线 `health_status=ready`、无活动告警、checkpoint 新鲜、磁盘正常；两个 timer 均已启用并运行，2026-09-25；2026-10-01 无活动告警 |
| synthetic redaction marker 在 local/alert/checkpoint 输出中均不存在 | 本地失败单元 journal 中的合成 marker 没有出现在告警邮件或原始 journal 输出中，2026-09-25 |
| 测试告警已收到且邮件不含 journal 内容 | 已送达；收到的邮件既不含该 marker，也不含原始 journal 输出，2026-09-25 |
