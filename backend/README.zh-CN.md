# 后端

[English](README.md) | [简体中文](README.zh-CN.md)

安全文件加密与共享平台的 FastAPI 模块化单体后端。

## 当前状态

身份认证、客户端包装密钥托管、加密文件、共享、审计、恢复及管理纵向功能切片均已实现。
它们使用真实 MySQL 事务、公开 UUID 契约、显式 Bearer／RBAC 依赖、加密对象存储及哈希链
审计事件。`/api/v1` 下的核心 Auth 端点为：

| 方法 | 端点 | 身份认证 |
|---|---|---|
| POST | `/auth/verification-codes/send` | 公开 |
| POST | `/auth/register` | 公开 |
| POST | `/auth/password-reset` | 公开 |
| POST | `/auth/login` | 公开 |
| POST | `/auth/refresh` | 刷新凭据 |
| GET | `/auth/me` | Bearer 访问令牌 |
| POST | `/auth/logout` | Bearer 访问令牌 |
| POST | `/auth/logout-all` | Bearer 访问令牌 |
| POST | `/auth/delete-account` | Bearer 访问令牌 + 登录密码确认 |
| POST | `/auth/change-password` | Bearer 访问令牌 |
| GET | `/auth/sessions` | Bearer 访问令牌 |
| POST | `/auth/sessions/{session_id}/revoke` | Bearer 访问令牌 |
| POST | `/auth/avatar/upload` | Bearer 访问令牌 |
| GET | `/auth/avatar` | Bearer 访问令牌 |
| POST | `/auth/avatar/delete` | Bearer 访问令牌 |

`/keys`、`/files`、`/audit-logs`、`/recovery` 和 `/admin` 路由也已启用，并由 OpenAPI
完整描述。`/health/live` 检查进程；`/health/ready` 还会检查数据库连接及精确的
`0011_must_change_password` Schema revision。管理员还可以查看单个账户详情并签发临时登录密码
（`GET /admin/users/{user_id}`、`POST /admin/users/{user_id}/reset-password`，#197），这不会改动
文件、密钥或加密 passphrase。

这些 API 采用客户端密钥托管边界：服务器只保存公钥、加密私钥包、密文及包装密钥，不接收
加密 passphrase、KEK、AMK、明文私钥、文件 DEK 或文件明文。浏览器前端已实现账户密钥登记
（本地生成密钥对、Argon2id 派生 KEK、包装 AMK 并加密私钥，提交前自测信封可重新打开）、
passphrase／私钥文件解锁、上传前加密、下载后本地解密，以及分享时把 DEK 重包装给接收者。
浏览器端还可以凭当前 passphrase 修改 passphrase（#201），或用私钥文件重设 passphrase；后继账户密钥
轮换在 API 中已有，但尚无界面。管理员与恢复专员在 `/admin` 有完整的操作界面（概览、用户、文件、完整性、安全
Agent、审计链、恢复请求、恢复公钥）。

注册与忘记登录密码重置均由发往所声明邮箱的一次性验证码把关，注册同时将账户邮箱标记为已验证。
验证码只以带密钥摘要形式存储，会过期、只能用一次、有尝试次数上界，并按邮箱与 IP 双重限流；
发送端点对已注册与未注册地址返回完全相同的响应。重置绝不触碰账户密钥信封，因此不会让账户
失去对已加密文件的访问能力，也因此无法找回遗忘的加密 passphrase。MFA 与外部身份登录尚未实现。

### 服务端管理的账户密钥信封（format 2）：已移除

服务端管理注册方案试验留下的服务端账户密钥生成代码（`CryptoService.generate_account_key`、
`decrypt_account_private_key`、`rewrap_key_protection_profile`，自回退到客户端托管后一直未被调用）已经删除。
注册接收客户端生成的 `key_material`，因为 `docs/SECURITY_FLOWS.zh-CN.md` 要求后端永远不持有明文私钥，
这段代码没有存在的理由。`CryptoService` 只保留 API 实际使用的部分：公钥加载与指纹、包装密钥长度校验、
RSA-PSS 验签，以及下面的 AAD / HKDF info 构造函数；后者作为文档化的字节布局保留
（`tests/unit/test_crypto_service.py` 逐字节固定了它）。

整数为无符号 32 位大端值，UUID 为 RFC 4122 网络字节序的原始 16 字节，公钥指纹是从 API 十六进制表示解码出
的原始 32 字节 SHA-256 值。`||` 表示拼接；每个 domain 字符串以一个 `0x00` 字节结尾。

- AMK 包装 AAD：`FYP-KEY-PROTECTION || 0x00 || format_version || aad_version || profile_uuid`
- 私钥 HKDF info：`FYP-PRIVATE-KEY-DERIVATION || 0x00 || format_version || profile_uuid || key_uuid || bundle_uuid`
- 私钥 AAD：`FYP-PRIVATE-KEY-BUNDLE || 0x00 || format_version || aad_version || profile_uuid || key_uuid || bundle_uuid || public_key_fingerprint`

应用层 HTTP 端点仅使用 `GET` 和 `POST`：读取操作使用 `GET`，新增、更新、删除、撤销及其他
会改变状态的动作使用 `POST`。不得新增 `PUT`、`PATCH` 或 `DELETE` 路由；CORS 方法配置也
仅允许 `GET` 和 `POST`。

登录密码策略使用 Unicode NFC 进行规范化，要求长度为 8 至 128 个字符，并至少组合大写字母、
小写字母、数字和符号四类中的两类；同时拒绝由账户信息派生的值和常见值，再使用 Argon2id
哈希。独立且仅存在于客户端的加密 passphrase 最低要求为 10 个字符。有效的旧版 bcrypt 哈希会
被透明升级；当配置的单工作进程容量已满时，内存密集型操作会快速失败。随附的常见密码列表只是
小型本地安全基线，并非持续维护的已泄露密码语料库。邮箱验证与忘记登录密码重置已经实现；
MFA 和外部身份登录尚未实现。

加密 passphrase 与登录密码相互独立，只在客户端用于派生 KEK。用户通常只需记住该
passphrase，服务端则保存加密私钥包。passphrase 遗失时服务器无法重置或恢复它；持有注册时
一次性提供的私钥文件（`.pem`）的用户可在设置页自行设置新 passphrase，两者都丢失则文件无法恢复。恢复 API 只治理单个文件 DEK 向已登记活跃公钥的重新
包装，不会恢复 passphrase、AMK 或解密私钥包。

## 前置要求

- Python 3.11 或更高版本（CI 与 staging 使用 3.12）
- 带 Compose 的 Docker（推荐用于 MySQL 8.4）

后端命令的规范执行目录是 `backend/`。配置始终从仓库根目录的 `.env` 加载，配置中的相对存储路径也会相对于仓库根目录解析，而不是相对于进程工作目录。

`MAX_REQUEST_BODY_BYTES` 限制普通 JSON/form 请求体（默认 1 MiB，配置上限 8 MiB）。加密文件的
multipart 上传路由独立使用 `MAX_UPLOAD_SIZE_BYTES + MAX_UPLOAD_REQUEST_OVERHEAD_BYTES` 上限，
因此调整普通请求体上限不会改变允许上传的密文大小。

## 首次设置

在仓库根目录中，仅当 `.env` 尚不存在时才创建它：

以下 Alembic 步骤仅限本地开发。执行 `alembic upgrade head` 前，请确认目标数据库为空，
或已经包含一条 `alembic_version` 记录。目前检查过的本地旧数据库不满足该条件；请遵循
[数据库接管策略](../docs/DATABASE_SCHEMA.zh-CN.md)，不要在该数据库上执行或强制标记常规
迁移历史。

```powershell
Copy-Item .env.example .env
docker compose up -d --wait mysql
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
alembic upgrade head
```

Compose 只提供本地开发便捷环境：它会在全新 volume 上按 `DB_NAME`、`DB_USER` 和
`DB_PASSWORD` 创建数据库及开发账户，但不会执行生产用的账户 Provision 或权限核验 SQL。
生产／预发布环境必须遵循下方由 root／管理员执行的 SQL-only 流程。

macOS/Linux 激活命令：

```bash
source .venv/bin/activate
```

不要提交 `.env`、私钥、恢复密钥、运行时文件或加密测试数据。

## 运行

开发环境：

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

OpenAPI：<http://localhost:8000/docs>

存活检查：<http://localhost:8000/health/live>

`--reload` 仅用于本地开发。部署时必须注入非默认密钥、设置 `APP_DEBUG=false`、明确配置 CORS 来源，并使用受监管的进程或容器。

## 质量检查

在 `backend/` 目录中运行：

```bash
ruff format --check app tests migrations
ruff check app tests migrations
pytest
alembic check
pip-audit -r requirements.txt
```

用于验证 ORM 行为的集成测试必须使用 MySQL 8.4，因为该架构使用了 MySQL 特有的无符号整数、枚举、二进制列、排序规则、JSON 和引用操作。不得使用 SQLite 替代这些测试的数据库。

### 针对真实数据库的集成测试

单独执行 `pytest` 会跳过 `tests/integration/` 下的全部测试，因此一次全绿的运行并不代表它们通过了。把 `AUTH_TEST_DATABASE_URL` 指向一个一次性的、已完成迁移的数据库即可让它们真正运行。库名必须包含独立的 `_test` 片段，fixture 会拒绝其他名称——因为这些测试会写入并删除数据行。

```bash
mysql --user=root --password -e "CREATE DATABASE fyp_secure_file_platform_test \
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
AUTH_TEST_DATABASE_URL='mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/fyp_secure_file_platform_test?charset=utf8mb4' \
  alembic upgrade head
AUTH_TEST_DATABASE_URL='mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/fyp_secure_file_platform_test?charset=utf8mb4' \
  pytest
```

`test_file_lifecycle_mysql.py` 针对该数据库以及 `tmp_path` 下的真实存储根目录，覆盖上传、列表、下载、完整性校验、共享状态与删除。它之所以存在，是因为有若干缺陷只出现在服务、SQL 与对象存储三者交汇的地方，伪造的存储或伪造的会话根本看不到它们。每次运行都会创建自己的身份，并在结束后清理自己产生的文件数据行；审计行及其引用的身份有意保留——审计链是只追加的，从哈希链中间删除记录会破坏它本就用来提供的那个性质。

## 对账清理

有四张表会随日常流量无上限增长——会话、刷新令牌、限流桶、验证码——而它们一旦失效就不会再被读取，因为过期是在请求时从时间戳判定的，而不是依赖某个存储的标志位。存储侧存在镜像问题：某个进程若在发布密文对象之后、提交对应数据行之前崩溃，就会留下一个没有任何数据行指向的对象。

```bash
.venv/bin/python scripts/reconcile.py            # 仅报告，默认行为
.venv/bin/python scripts/reconcile.py --apply    # 实际删除
```

默认仅报告是有意为之：对账任务的 bug 往往要靠"它删掉了什么"才被发现，因此在某个部署上的首次运行应当被阅读，而不是被信任。它绝不触碰 `audit_logs` 与 `audit_chain_heads`（只追加、有哈希链，且运行时授权仅为 `SELECT, INSERT`，因此不可能误删）、文件相关表、身份与密钥托管表，以及 `recovery_requests`。

`deployment/server/mcs21-reconcile.{service,timer}` 会每日运行它。在 staging 上，阅读过一次仅报告的运行结果之后，它们已于 2026-09-24 安装，定时器从 2026-09-25 起每天运行（#57，已关闭）。新的部署也应先阅读一次仅报告的运行结果，再启用它们。

## 数据库变更

Alembic revision 和 ORM metadata 用于本地开发／CI 中编写、评审和测试 Schema 变更。
应用程序绝不会调用 `create_all()`，Compose 也不再挂载会破坏数据的表初始化脚本。

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe the change"
alembic check
```

提交前必须审查每一个自动生成的 revision，并在 CI 中验证 Alembic head 与生产
`02-schema.sql` 的最终 Schema 一致。上述 Alembic 命令不是生产部署步骤。

预发布和生产环境不运行 Alembic，也不创建 `fyp_migrator`。数据库 root／管理员从仓库
根目录以遇错停止的 batch 模式依次执行：

```bash
# 数据库服务器仓库根目录；MySQL root 使用本机 socket 认证
sudo mysql < database/mysql/01-provision.sql
sudo mysql < database/mysql/02-schema.sql
sudo mysql < database/mysql/03-verify.sql
```

`01-provision.sql` 只创建固定数据库和带 `REQUIRE SSL` 的 `fyp_user`，并为新账户返回一个
随机密码；密码必须直接写入 secret store。仅接受空库的 `02-schema.sql` 会安装完整的
16 张应用表及 1 张 `alembic_version` 兼容表，并设置精确运行时权限：14 张普通状态表拥有
CRUD，`audit_logs` 只有 `SELECT`／`INSERT`，而 `audit_chain_heads` 的 `UPDATE` 仅限 `last_log_id`、
`current_hash` 和 `updated_at` 三列，明确排除 `schema_revision`；应用也无权访问
`alembic_version`。只读的 `03-verify.sql` 必须核验精确 Schema 和权限，并确认不存在旧版
`fyp_migrator` 账户。全部核验通过后，应用才通过标准 `DB_*` 以 `fyp_user` 启动；root 凭据
绝不能进入应用 `.env`。

三份 SQL 都以 `localhost` 为账户 host 默认值；远程部署应在仓库外制作三份受保护、经
评审的副本，并一致替换其中每一个 `localhost` 账户 host 字面量。若执行 02 时任何语句
失败，不得在部分 Schema 上重跑；应查明原因后重建一次性空库或恢复已验证备份。已有
非空生产库的后续升级必须使用新的、版本化且经 DBA 评审的 root SQL，不能重跑 02，
也不能在服务器上改用 Alembic。现有环境若遗留 `fyp_migrator`，须确认归属后显式撤权或
删除。停止写入、发布串行化、备份／恢复演练、DDL 超时和失败处置均由发布编排器与操作员
负责。完整要求见
[DEPLOYMENT.zh-CN.md](../docs/DEPLOYMENT.zh-CN.md)。

如果旧版本地数据库是由历史 `docs/init.sql` 创建的，请阅读
[数据库接管策略](../docs/DATABASE_SCHEMA.zh-CN.md)；不要对它执行 `upgrade head`，也不要
盲目标记版本。该警告仅说明本地开发接管；生产非空库必须走单独的 DBA SQL 升级方案。

## 架构规则

精简的规则以及安全／事务边界记录于：

- [后端架构](../docs/ARCHITECTURE.zh-CN.md)
- [数据库架构策略](../docs/DATABASE_SCHEMA.zh-CN.md)
- [安全流程](../docs/SECURITY_FLOWS.zh-CN.md)
- [API 设计](../docs/API_DESIGN.zh-CN.md)

关键依赖规则是：路由器 -> 用例服务 -> 仓库／存储／加密策略。路由器不包含 SQL 或文件系统逻辑；仓库绝不提交事务；每个用例负责其自身的事务和存储补偿行为。
