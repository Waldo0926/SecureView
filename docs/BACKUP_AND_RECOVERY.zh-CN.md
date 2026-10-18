# 备份与恢复

[English](BACKUP_AND_RECOVERY.md) | [简体中文](BACKUP_AND_RECOVERY.zh-CN.md)

本文是 SecureView 预发布环境的恢复方案（issue #56）：备份什么、多久备份一次、需要多快恢复、保留
多久，以及每一项承诺如何被测试。它按项目的真实规模设定——一个 FYP 团队的预发布 VPS，少量用户和
评审——而不是照搬企业模板。云厂商的每周快照仍可作为额外一层，但不属于本方案：快照与生产位于同一
厂商、只能整机回滚而不是恢复到一个一致的应用状态，而且从未做过恢复测试。

实现组成：

| 组件 | 作用 |
|---|---|
| `backend/scripts/backup_encrypted.py` | 生成一个协调一致的备份集：MySQL dump + 密文对象 + manifest，分别用备份**公钥**加密后送往异地 |
| `backend/scripts/restore_drill.py` | 干净主机恢复与校验，记录每一步耗时；任何不一致都拒绝恢复 |
| `backend/scripts/backup_envelope.py` | RSA-OAEP-SHA256 包裹数据密钥 + AES-256-GCM 流式加密 |
| `backend/scripts/db_fingerprint.py` | 逐表 `CHECKSUM TABLE` + `information_schema` Schema 指纹，用于比较两个数据库 |
| `backend/scripts/backup_restore_drill.sh` | 使用一次性密钥和账号的端到端演练；CI（`mysql-gate`）在每个 PR 上运行 |
| `backend/scripts/mysql_release_gate.sh` | 迁移锁竞争、带校验和的恢复、升级前回滚、部分 DDL 恢复 |
| `database/mysql/04-backup-account.sql` | 最小权限账号 `fyp_backup_user` |
| `deployment/server/mcs21-offsite-backup.{service,timer}` | 夜间调度模板（部署工具不会自动安装） |

## 1. 恢复目标

| 资产 | RPO | RTO | 保留 |
|---|---|---|---|
| MySQL 元数据（全部应用表、`alembic_version`） | 24 小时（夜间备份集）；另外 `mcs21-deploy` 在每次发布前都会导出一次 | 数据恢复步骤：1 小时；新主机上恢复整个服务：4 小时 | 异地：每个夜间备份集保留 35 天（`staging/` 上的 R2 生命周期规则，30 天 bucket lock）。发布前 dump：保留在同一主机，由 `mcs21-deploy` 管理 |
| 密文对象（`ENCRYPTED_FILE_DIR`） | 24 小时，**与元数据在同一个备份集中** | 与元数据相同——要么一起恢复，要么都不恢复 | 与元数据相同的备份集 |
| git 中的配置（nginx、systemd、SQL、部署脚本） | 0——每次修改都是一次提交 | 30 分钟（重新部署该提交） | git 历史 |
| 主机 Secret（`backend.env`：`SECRET_KEY`、数据库密码、SMTP） | 不备份——恢复时重新生成 | 包含在 4 小时服务 RTO 内 | 无；见 §6 |
| 数据库中的恢复元数据（`recovery_keys` 公钥、每个文件的恢复包裹密钥） | 随数据库 | 随数据库 | 随数据库 |
| 恢复**私钥**与备份**私钥** | 创建或轮换时离线保存，不做例行备份 | 由保管人取回，一个工作日内（§7） | 所有历史密钥，只要仍有文件或备份集需要它就一直保留 |

取值理由：

- **24 小时 RPO。** 预发布流量是少量、突发的（团队、测试者、评审），不是持续的生产写入。最多丢失一天
  的上传（上传者手里仍有原文件）在这里可以接受；一个夜间任务也不需要团队无力运维的 binlog/时间点
  恢复工具。每次发布前 `mcs21-deploy` 的 dump 额外提供了恢复点。
- **1 小时数据恢复 RTO。** 实测恢复速度是每 GB 几秒（§5）。预算中留出了从异地取回备份集的时间（按
  10 MB/s 约每 GB 100 秒），以及人按本文逐步操作的时间。
- **4 小时整体服务 RTO。** 在全新主机上，慢的是人工步骤：开 VM、安装 Docker 与 MySQL、保管人带来离线
  密钥、重新部署。这部分**尚未**在真实 VPS 上端到端计时（见“尚未完成”）。
- **异地保留 35 天的夜间备份集。** 近期的点覆盖“这周弄坏了东西”，一个月覆盖“一个月内才发现”，大致是
  一个教学周期。staging 的恢复校验曾六周无人察觉，说明这里的问题往往发现得晚。R2 生命周期规则只能按
  存放时间删除，所以每个夜间备份集都保留 35 天（约 26 GB，超出 R2 免费 10 GB 的部分每月约 0.25 美元）。
  30 天的 bucket lock 让任何人（包括被入侵主机上的备份凭据）都无法删除 30 天内的备份集。`--prune` 对
  本地或挂载的目标仍执行 7 个每日 + 4 个每周。

## 2. 一个备份集包含什么，以及元数据与对象如何保持一致

`backup_encrypted.py` 每次运行写出一个备份集，以 **manifest id** 命名（UTC 时间戳 + 随机后缀，例如
`20260924T091500Z-3f9c2a1b`）：

```
<dest>/<manifest-id>/db.sql.enc          mysqldump；第一行是 "-- fyp-backup-manifest-id: <id>"
<dest>/<manifest-id>/objects.tar.enc     密文对象；成员 MANIFEST_ID 中写有 <id>
<dest>/<manifest-id>/manifest.json.enc   <id>、dump 时间窗、每个对象和产物的 SHA-256
<dest>/<manifest-id>/index.json          明文：<id>、各产物 SHA-256、密钥指纹
```

**一致性机制。** dump 是单个 InnoDB 快照（`--single-transaction`）。所有表都是 InnoDB，因此不需要锁表，
也不需要 `RELOAD`/`LOCK TABLES` 权限。对象在 dump **之后**打包。这个顺序是安全的，原因在于应用写存储
的方式（`FileService`）：

- 上传会先发布只写一次的对象，**然后**才提交数据行，所以快照中可见的每一行都已有对象；
- 删除会先提交 `status = 'DELETED'`，**然后**才删除对象文件，所以快照中 ACTIVE 的行只有一种方式会丢失
  对象：在 dump 和打包之间的几秒内被删除。

备份用校验而不是侥幸来关闭这个缺口。打包完成后，它读取所有可能在快照中为 ACTIVE 的 `files` 行：dump
结束前创建、且未被删除或在 dump 开始后才被删除的行。每一行都必须在归档中找到对象，且哈希等于
`files.encrypted_sha256`。只要有一行不满足，本次运行就**失败**且不送出任何内容。这种失败说明要么有删除
与备份竞争（重新运行即可），要么存储已损坏（需要调查）。

**恢复时强制校验。** `restore_drill.py` 只有在以下全部成立时才会恢复：

1. 每个产物与 `index.json` 中的 SHA-256 一致；
2. 每个产物都能在私钥**以及**本备份集的 manifest id 和角色下通过认证。这两者被绑定进 AES-GCM 的关联
   数据，所以即使有人修改 `index.json`，周一的 `db.sql.enc` 也无法与周二的对象拼在一起；
3. manifest 中、dump 第一行、归档 `MANIFEST_ID` 成员中的 id 都等于 index 的 id，并且 dump 以 mysqldump
   的完成标记结尾；
4. 载入后，每个 ACTIVE 的 `files` 行都能在归档中找到 SHA-256 正确的对象。没有任何行引用的对象不会被
   恢复，因此恢复出的元数据引用的正好是恢复出的对象集合；
5. 恢复后的 `alembic_version` 等于备份时记录的 revision，且 `alembic check` 与模型之间没有差异。

任何一项失败，演练都会删除自己创建的数据库、清空自己写入的对象目录，并以非零状态退出。目标数据库
或对象目录非空时也会拒绝恢复。CI 会逐一验证这些拒绝路径（§5）。

## 3. 加密

每个产物单独加密：使用新生成的随机 256 位数据密钥和 AES-256-GCM。该数据密钥用 RSA-OAEP-SHA256 包裹，
收件密钥是一把专用的**备份** RSA 密钥（至少 3072 位），与恢复密钥和所有用户密钥都不同。执行备份的
主机只持有公钥，所以该主机或异地存储被攻破时，攻击者只能拿到密文，拿不到任何能打开它的东西。未加密
内容不会离开私有临时目录（权限 0700，运行结束即删除）。

为什么不用 `age` 或 `gpg`：预发布主机和 CI 上都没有安装它们，而 `cryptography` 已经是后端固定版本的
依赖。`openssl enc` 被否决，因为它没有带认证的模式，翻转一个字节也会“成功”解密。格式说明在
`backup_envelope.py` 中，单元测试固定了篡改、错误密钥和错误上下文时的行为。

备份密钥对只生成一次，在保管人的离线机器上：

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -aes-256-cbc -out backup_priv.pem
openssl pkey -in backup_priv.pem -pubout -out backup_pub.pem   # 只有公钥放到服务器上
```

## 4. 最小权限凭据与备份去向

**数据库。** `database/mysql/04-backup-account.sql` 创建 `fyp_backup_user`：服务器生成密码、`REQUIRE SSL`、
最多两个连接，权限恰好是 `GRANT SELECT ON fyp_secure_file_platform.*`。它有意作为独立、可重复执行的
文件。`02-schema.sql` 是只执行一次的空库安装脚本，如果在其中 GRANT 给 `01-provision.sql` 从未创建的
账号，全新安装会在中途中止（MySQL 错误 1410）。授权是库级别的，这样未来版本新增的表不会被悄悄排除
在备份之外：mysqldump 会跳过它看不到的表。CI 中 `check_runtime_grants.py` 以该账号连接，证明它能读取
所有表，但不能 INSERT、UPDATE、DELETE、CREATE、ALTER、DROP、GRANT、LOCK TABLES、FLUSH TABLES、
CREATE USER，也不能读取 `mysql.*`。故意放宽授权会让该检查失败。

**主机。** systemd 模板让任务使用独立的 `backup.env`，其中只有 `BACKUP_*` 变量。它从不读取应用的
`backend.env`，因此看不到 `SECRET_KEY` 或运行时数据库密码。文件系统除任务私有临时目录外都是只读的。

**目标**（`--dest`）：

- `user@host:/path`——通过 SSH 使用 rsync。接收端应为专用密钥设置限制（例如 `rrsync -wo`），让备份主机
  只能新增备份集，不能读取或删除。
- `s3://bucket/prefix`——使用 `aws s3 cp`（S3 兼容服务设置 `BACKUP_S3_ENDPOINT_URL`）。使用只能写入对象
  的凭据，并用生命周期规则执行保留策略。
- 本地目录——CI 与本地演练使用它。**在同一台机器上，它只是异地存储的替身，不是真正的异地。** 挂载的
  远程文件系统可以接受。

`index.json` 总是最后写入，所以没有它的备份集按定义就是不完整的。恢复会拒绝这类备份集，清理与新鲜度
检查也会忽略它。

**失败监控。** 任何失败都会以非零状态退出，并输出一行 `backup_encrypted: FAILED -- …`。在 systemd 下
该单元会进入 failed 状态（`systemctl --failed` 和 journal 可见）。
`backup_encrypted.py --check-freshness <dest> --max-age-hours 26` 在最新完整备份集过旧时失败，可以从任何
能访问目标的机器上运行。该单元的 `OnFailure=mcs21-alert@%n.service` 会把失败连同最近 30 行 journal 通过邮件发送给
`/etc/fyp-secure-file-platform/alert.env` 中配置的人；同一告警也覆盖同机的 `mcs21-backup` 与
`mcs21-backup-verify`。配置与测试见 [RECONCILIATION_RUNBOOK.zh-CN.md §9](RECONCILIATION_RUNBOOK.zh-CN.md#9-告警)。

## 5. 干净主机恢复演练与实测耗时

在新主机上真实恢复的步骤（与演练执行的命令相同）：

1. 准备 MySQL 8.4 并执行 `database/mysql/01-provision.sql`（创建空数据库和 `fyp_user`）。
2. 从异地存储复制选定的备份集；保管人带来 `backup_priv.pem`（§7）。
3. 恢复到空数据库和空对象目录：
   ```bash
   cd backend
   DB_HOST=127.0.0.1 DB_PORT=3306 ADMIN_DB_USER=root ADMIN_DB_PASSWORD=... \
     .venv/bin/python scripts/restore_drill.py \
       --backup-set /restore/20260924T091500Z-3f9c2a1b --private-key /media/custodian/backup_priv.pem \
       --target-db fyp_secure_file_platform --objects-dir /var/lib/fyp-secure-file-platform/encrypted_files \
       --report restore-report.json
   ```
4. 重新应用运行时授权（`02-schema.sql` 末尾的 GRANT 段落，数据 dump 中不包含它）：
   ```bash
   .venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from check_runtime_grants import *; \
     print('\n'.join(extract_grants(SCHEMA_SQL_PATH, PRODUCTION_RUNTIME_USER, PRODUCTION_DATABASE_NAME, 'fyp_user', 'localhost')))" \
     | sudo mysql
   ```
   然后执行 `03-verify.sql`，写入新的 `backend.env`（§6），部署应用，并调用 `POST /audit-logs/verify-chain`
   确认审计哈希链完好。

**实测**于 2026-09-24，本地 Apple 芯片笔记本，Docker MySQL 8.4.11（`restore_drill.py` 计时；种子数据中
90% 的文件为 ACTIVE，10% 为 DELETED 且对象已删除）：

| 运行 | Dump | 对象 | 备份总计 | 恢复总计 | 恢复分解 |
|---|---|---|---|---|---|
| CI 规模演练：200 个文件 × 64 KiB | 131 KB | 180 个 / 12 MB | 0.18 秒 | 0.96 秒 | 载入数据库 0.31 秒，对象 0.05 秒，校验 0.45 秒 |
| 1 000 个文件 × 1 MiB，同一服务器 | 506 KB | 900 个 / 945 MB | 6.5 秒 | 3.96 秒 | 解密 0.44 秒，载入数据库 0.46 秒，对象 1.53 秒，校验 0.68 秒 |
| **干净主机：**同一备份集恢复到第二个空的 MySQL 8.4 服务器 | 506 KB | 900 个 / 945 MB | 5.3 秒 | **4.27 秒** | 校验密文 0.38 秒，解密 0.46 秒，manifest 0.42 秒，载入数据库 0.76 秒，对象 1.55 秒，校验 0.67 秒 |

干净主机运行中，恢复后数据库的数据与 Schema 摘要（`db_fingerprint.py digest`）与源服务器完全一致，
`diff -r` 也确认恢复的对象树与源完全相同。机器耗时约每 GB 4.5 秒，再加上传输时间，对本部署可能出现的
任何数据量（即使达到数十 GB），1 小时数据恢复 RTO 都有很大余量。尚未实测的是 4 小时整体服务 RTO
中的人工部分。

**Staging 演练，2026-09-24（真实密钥与真实异地备份集）。** staging 上的
`mcs21-offsite-backup.service` 将备份集 `20260924T141906Z-7c503f93`（24 个对象，738 MB）写入
Cloudflare R2，用时 70.9 秒，其中上传 67.4 秒。该备份集在 VPS 上从 R2 下载（66 秒；R2 token 只接受
VPS 的地址），再拷贝到一台 MacBook（326 秒），在那里用保管人受密码保护的私钥恢复到空的 Docker
MySQL 8.4.11：总计 **6.97 秒**（校验密文 0.32 秒，解密 4.49 秒，manifest 0.32 秒，载入数据库 0.46 秒，
对象 0.71 秒，校验 0.65 秒）。独立于演练脚本的核对：恢复后 17 张表的 `CHECKSUM TABLE` 与线上数据库
完全一致，24 个恢复对象的 SHA-256 与线上文件完全一致。传输（从 R2 到 VPS 以外的机器约 6.5 分钟）占
主要时间，仍在 1 小时数据恢复 RTO 之内。

在新主机上恢复需要单独的 R2 读取 token：staging 的 token 只允许 VPS 的 IP 使用，因此恢复时由账户
所有者在 Cloudflare 控制台为新主机创建读取 token。

CI（`mysql-gate` → “Encrypted backup, clean restore, and refusal drill”）在每个 PR 上运行
`backup_restore_drill.sh`。它在任务内生成一次性 RSA 密钥和备份账号，以该最小权限账号备份，并检查目标
中没有明文、没有私钥。然后恢复到一个尚不存在的数据库，比较内容、Schema 和每个对象。最后证明它会
拒绝：被篡改的产物、来自其他备份集的产物、错误的密钥、不完整的备份集、归档缺少 ACTIVE 行所需对象的
备份集、非空目标；并证明当某行对应的对象缺失时，备份本身会停止。恢复报告（只含 id、数量与耗时）作为
workflow artifact 保留 90 天。

## 6. 配置与主机 Secret

所有可复现的内容都在 git 中，重新部署某个提交即可恢复。主机上的 `backend.env` 被有意**排除**在备份之外：
否则每个异地备份集里都会带着线上凭据。恢复时应生成新值：`01-provision.sql` 会为 `fyp_user` 生成新密码，
`04-backup-account.sql` 会生成新的备份密码，并写入新的 `SECRET_KEY`。轮换 `SECRET_KEY` 只会让现有会话
和未过期的邮箱验证码失效（它用于签发令牌和对短期验证码做 HMAC，不加密任何静态数据）。SMTP 凭据从
服务商控制台获取。

## 7. 恢复密钥保管

以下均对照代码核实，而非假设：

- `recovery_keys` 只保存 `public_key_pem`、指纹、长度和状态。任何表都没有保存恢复私钥的列。Schema 中
  仅有的私钥相关列属于 `encrypted_private_key_bundles`，其中是用户在客户端、用由其口令派生的密钥加密
  后的私钥，服务器从不接触明文。如果这一点改变，单元测试
  `test_backup_scope_holds_no_plaintext_private_key_columns` 会失败。
- `register_recovery_key.py` 在操作员机器上生成恢复密钥对，只发送公钥，私钥写到本地（默认
  `recovery_keys/`，已被 gitignore）。它从不接触数据库或对象存储。
- `backup_encrypted.py` 只打包路径是合法存储对象 key 的文件；如果对象目录中有任何看起来像 PEM 私钥的
  文件，它会**中止**。因此即使密钥被误放到那里，也不会混入例行备份。

所以，恢复私钥在设计上就不在例行在线备份的范围内。

**如实说明保管方式（提议方案，启用定时任务前需团队确认）。** 团队没有 HSM。恢复私钥和备份私钥各自只导出一次，用口令保护，存放在两个加密
U 盘上，离线保存在两个不同地点。指定保管人是 **Testing & Deployment Lead**（目前是 Shuoxun Wen），
**Crypto & Security Lead**（目前是 Tai Chen）是第二持有人。两把密钥都不会存放在联网主机、云存储或本仓库
中。它们的 SHA-256 指纹记录在团队的私有记录里，持有人可以据此核对上传页面和 `index.json` 显示的指纹。
如果项目超出预发布规模，应改用 HSM 或云 KMS。

**历史密钥。** 注册新的恢复密钥不会重新包裹已有文件，因此每一把退役的恢复私钥都要保留到不再有任何文件
使用它为止；实际上就是整个部署的生命周期，因为目前还没有工具能证明某把密钥已不再被任何文件使用。每一把
退役的备份私钥保留到最后一个用它加密的备份集超出保留期（轮换后约五周）。密钥从不被自动删除；删除任何
一把都需要两位持有人书面决定。

## 8. 升级前回滚与部分应用的 DDL

`mysql_release_gate.sh` 在 CI 中针对 MySQL 8.4 验证两者：

1. **升级前回滚**（`rollback before a schema upgrade` 阶段）。门禁先备份一个处于 `0005` 的数据库，迁移到
   `0006`，再写入一行。然后用备份替换已迁移的数据库，证明 revision 回到 `0005`，数据和 Schema 指纹与
   升级前一致。升级之后的写入会丢失，这是回滚的代价，也是它必须是一个明确决定的原因。之后从恢复的
   状态重新升级也能成功。
2. **多 revision 发布中途中断**（发布内容 = 在 `0004` 上应用 `0005` + `0006`）：
   - 在 revision **之间**中断（0005 已应用并记录，0006 未应用）：用 `migrate.sh upgrade head` **向前续跑**
     是受支持的，并已验证；
   - 在 revision **内部**中断：MySQL DDL 逐条自动提交，所以进程若在 0005 删除
     `ck_files_encryption_envelope` 之后、重建之前被杀掉，约束会消失，而 `alembic_version` 仍是 `0004`。
     门禁证明此时向前续跑会**失败**（MySQL 错误 3821），然后证明受支持的路径可行：恢复发布前备份
     （指纹一致，revision 为 `0004`），再完整重跑整个发布。

**预发布环境的受支持路径。** 生产通过经过评审、由 root 执行的 SQL 应用 Schema 变更，而不是 Alembic
（见 `docs/DEPLOYMENT.zh-CN.md`），`mcs21-deploy` 也会在每次发布前导出数据库。对任何部分应用的生产 DDL
发布，受支持的恢复方式是**向后恢复**：保持应用停止，恢复发布前备份，再完整重跑发布。向前续跑只适用于
运行 Alembic 和 `migrate.sh` 的环境（开发、CI、一次性数据库），且只适用于在 revision 边界上的中断。

## 9. 发现并恢复单个受损文件

第 1 至 8 节恢复的是整个服务。本节回答一个更窄的问题：*存储的某个文件被修改了，怎样发现，怎样把原件找回来？*

**没有版本历史，也不需要。** 存储的密文对象只写一次，正常情况下永远不会变化。所以只要某个备份副本的 SHA-256
等于系统记录的该文件摘要，它就与原件逐字节相同。“最后一个已知良好版本”就是一个持有正确字节的备份集。
起决定作用的摘要是上传时写入审计哈希链的那个（`FILE_UPLOADED.metadata.ciphertext_sha256`），而不只是
`files.encrypted_sha256` 这一列，因为能改写对象的人往往也能改写这一列。在记录该摘要之前上传的文件没有审计摘要，
退回使用这一列。

**“我的文件”里的“申请恢复”按钮不是干这个的。** 恢复申请是请恢复专员把文件*密钥*重新封装到申请人当前的账户密钥上
（口令丢了、密钥换了）。它不能把被改掉的字节放回去，所以对完整性检查已标记的文件，这个按钮是禁用的；真进了对话框，
服务器也会回答“由管理员从备份恢复”。在 PR #226 之前这里返回的是“未找到”，看起来像文件不见了。

### 发现

| 位置 | 作用 |
|---|---|
| 下载 | 服务器在流式输出前对对象做哈希，不一致就拒绝（原有） |
| **每日扫描** `scripts/integrity_sweep.py`、`mcs21-integrity-sweep.timer`（吉隆坡时间 05:30） | 按最久未检查优先，对每个存储对象做哈希；每个发现写入 `integrity_checks` 并记审计；有受损对象时退出码为 3，使失败告警触发 |
| **管理员 → Integrity** | 列出受损文件与已检查的覆盖情况；“Scan now” 在 20 秒内最多验证 50 个文件，并说明还剩多少 |

结果 `MODIFIED` 是关于字节内容的证据，会把文件标为 `CORRUPTED`。`MISSING` 与 `ERROR` 描述的是存储环境
（卷未挂载、I/O 错误），不会改变文件状态，因此短暂故障不会误判完好的文件。下一次检查通过后状态自动恢复。

定时器会**自动安装**：每次健康的发布之后，`mcs21-deploy` 会从该发布中安装并启用 `mcs21-integrity-sweep.timer`（白名单固定，见 [AUTOMATIC_DEPLOYMENT.zh-CN.md](AUTOMATIC_DEPLOYMENT.zh-CN.md)）。这在 VPS 上装上更新后的 `mcs21-deploy` 之后生效。若想手动安装，或想在依赖它之前先读一次运行结果：

```bash
sudo systemd-run --pipe --wait --quiet --uid=fypapp --gid=fypapp \
  --working-directory=/opt/mcs21/current/backend \
  --property=EnvironmentFile=/etc/fyp-secure-file-platform/backend.env \
  /opt/mcs21/current/backend/.venv/bin/python scripts/integrity_sweep.py
R=/opt/mcs21/current/deployment/server
sudo install -m 0644 "$R/mcs21-integrity-sweep.service" "$R/mcs21-integrity-sweep.timer" /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/mcs21-integrity-sweep.service
sudo systemctl daemon-reload && sudo systemctl enable --now mcs21-integrity-sweep.timer
```

### 把原件放回去

`backend/scripts/restore_file.py`，在服务器上运行。Admin → Integrity 会针对受损文件显示这两条命令，原样粘贴即可：

```bash
cd /opt/mcs21/current/backend
sudo .venv/bin/python scripts/restore_file.py --file-id <文件 uuid>            # 演练（不写入）
sudo .venv/bin/python scripts/restore_file.py --file-id <文件 uuid> --apply    # 写入
```

不带 `--backup-set` 时，脚本使用 `mcs21-backup` 写在 `/var/backups/mcs21-daily` 的**同机每夜备份**（对象存储的明文 tar，
只有 root 可读，保留 14 天）：从最新的归档开始，每份先对照自己的 `.sha256` 清单，再从中读出这一个对象与记录的摘要比对，
已经含有受损字节的归档会被跳过、改用更早的一份。这条路不需要密钥。以 root 运行时它会自己加载
`/etc/fyp-secure-file-platform/backend.env`，并把恢复后的对象、隔离副本和隔离目录交还给服务账户。在 staging VPS 上，
对 780 MB 的归档做一次演练约 1.5 秒。

如果服务器磁盘已丢失，或每夜备份本身也不可信，则退回**加密的异地备份集**，**离线备份私钥**由保管人在恢复期间带来：

```bash
.venv/bin/python scripts/restore_file.py --file-id <文件 uuid> \
    --backup-set /path/to/<manifest-id> --private-key /path/to/backup_priv.pem          # 演练（不写入）
.venv/bin/python scripts/restore_file.py ... --apply                                      # 写入
```

第一条命令不改变任何东西，只报告将使用哪份备份。加上 `--apply` 后依次：

1. 除非该集的各 artifact 与 `index.json` 一致、能在此密钥和此集的 manifest id 下解密并认证、归档与 manifest
   一致，否则拒绝；
2. 除非该集持有这个对象，**并且**其 SHA-256 与大小等于记录值，否则拒绝（上传之前的备份集，或本身已含被篡改字节的
   备份集都不会被采用）；
3. 把受损字节复制到隔离目录（`<存储目录的上级>/quarantine`，或 `--quarantine-dir`），因为被篡改的对象是证据；
4. 把原件写在对象旁边，再原子地重命名到位；
5. 若数据库中的摘要被改写得与被篡改对象一致，则把审计链中的摘要写回 `files.encrypted_sha256`；
6. 用当初判定它受损的同一规则重新验证，这会记录一条 `VALID` 检查并把状态恢复为 `ACTIVE`，同时把
   `FILE_RESTORED_FROM_BACKUP` 写入审计链。

异地备份的私钥不会长期放在服务器上，也没有网页按钮：管理员页面显示哪些文件受损以及要运行的命令，决定权留给有 root 权限的人。

### 明确的限制

- 最近一次夜间备份之后上传的文件不在任何备份里，无法用这种方式恢复。窗口就是第 1 节的 24 h RPO。
- 为取出一个对象需要解密 `objects.tar.enc`，代价与完整恢复中对象部分的解密相同，因为归档是一整个经认证的流。
- 如果备份集本身已含被篡改的字节，摘要检查会拒绝它；请换更早的集（异地保留 35 个夜晚）。
- 只有上传时记录了审计摘要的文件，扫描才能发现被改写的摘要。
- `scripts/backup_restore_drill.sh`（CI 的 `mysql-gate`）会篡改一个对象，要求扫描退出码为 3 并标记 `CORRUPTED`，
  拒绝错误的密钥，确认演练不改变任何东西，然后恢复，并要求对象逐字节一致、受损副本已隔离、状态为 `ACTIVE`、
  审计行存在。

## 本地运行

```bash
docker compose up -d mysql                      # 或任何一次性的 MySQL 8.4
cd backend
export DB_HOST=127.0.0.1 DB_PORT=3306 ADMIN_DB_USER=root ADMIN_DB_PASSWORD=local_root_password
export SECRET_KEY=local-test-secret-key-at-least-32-chars APP_ENV=test
bash scripts/backup_restore_drill.sh            # 加密备份 -> 干净恢复 -> 拒绝路径
DRILL_FILES=1000 DRILL_FILE_BYTES=1048576 bash scripts/backup_restore_drill.sh   # 约 1 GB 的计时运行
bash scripts/mysql_release_gate.sh              # 锁竞争、带校验和的恢复、回滚、部分 DDL
```

两个脚本只创建和删除名称中包含 `_test` 的数据库，并把密钥、dump 和对象放在退出时删除的私有临时目录中。

## 尚未完成

- 4 小时整体服务 RTO 尚未在全新 VPS 上端到端计时；目前只实测了数据恢复（§5）。
- rsync 目标已接好，但尚未对真实目标测试。S3 已在 R2 上投入使用。
- ~~`mcs21-deploy` 的发布前备份从不清理。~~ **2026-10-08 已完成**（[PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204)）：
  因为每份都会把所有密文对象一起打包，它们在 2026-09-24 已有 81 份、5.6 GB，到 2026-10-08 增至 184 份、81 GB。它们仍是同一
  主机上的明文（仅 root 可读，0700），是快速回滚点而不是异地副本。现在部署健康后 `mcs21-deploy` 只保留最新 10 份
  （`MCS21_KEEP_DEPLOY_BACKUPS`，不少于 3 份）。第一次运行（强制重新部署 `f826165`）删除了 175 份：81 GB → 7.5 GB，根盘占用 69% → 51%。

## Staging 安装记录（2026-09-24）

- 备份账号 `fyp_backup_user@172.29.21.1`，由 `04-backup-account.sql` 改 host 后创建：MySQL 运行在 Docker
  中，主机发起的 TCP 连接来自 Docker 网关 `172.29.21.1`（与 staging 上其他账号相同），`localhost` 账号无法
  登录。已以 `fypapp` 身份验证：走 TLS（`TLS_AES_256_GCM_SHA384`）、可读、`DELETE` 被拒绝。
- `/etc/fyp-secure-file-platform/backup.env`（root，0600）与 `backup_pub.pem`（root:fypapp，0640；公钥
  SHA-256 为 `4ac77119…`，与每个备份集 `index.json` 中记录的一致）。
- `aws` CLI 1.46.1 装在 `/opt/awscli` 的 venv 中，并链接到 `/usr/local/bin/aws`。Ubuntu 24.04 没有 `awscli`
  apt 包，而 snap 版在 unit 的 `NoNewPrivileges=true` 下无法启动。
- 目标为 Cloudflare R2 上的 `s3://<backup-bucket>/staging`。token 只对该 bucket 有 Object Read & Write 权限，
  并且只允许 VPS 的 IP 使用。
- 已启用 `mcs21-offsite-backup.timer`（每天 02:30）；失败时发邮件到 `alert.env` 中的地址。
- `/var/lib/fyp-secure-file-platform` 中只有 `encrypted/`（24 个密文对象）与 `tmp/`；该目录及主机其他位置均
  未发现私钥。
- 重新安装后的 `mcs21-backup-verify` 自 2026-08-16 以来首次通过。
