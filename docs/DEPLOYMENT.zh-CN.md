# MySQL 部署

[English](DEPLOYMENT.md) | [简体中文](DEPLOYMENT.zh-CN.md)

本文说明如何把数据库部署到 MySQL 8.4。生产及预发布环境只接受经过评审的 SQL；这些环境
不安装、不调用 Alembic，也不创建 `fyp_migrator`。SQLAlchemy metadata 和
Alembic revision 仍用于开发与 CI 中编写、评审及验证 Schema；生产交付物是与当前 head
保持一致的 `database/mysql/02-schema.sql`。

生产首次部署使用以下顺序：

1. 数据库管理员以 root/管理员身份执行 `database/mysql/01-provision.sql`。
2. 同一管理员执行 `database/mysql/02-schema.sql`；该文件只允许用于空应用数据库。
3. 同一管理员执行只读的 `database/mysql/03-verify.sql` 并评审全部结果。
4. 只有核验通过后，应用才以 `fyp_user` 启动。

三个步骤必须分别在 MySQL 客户端的遇错停止 batch 模式下成功。不要使用交互式 `SOURCE`，
不要添加 `--force`，也不要在某一步失败后继续下一步。

## 身份、配置与 Secret

生产只使用两个身份：

- MySQL root/管理员创建数据库和运行时账户、创建 Schema、授予权限并执行最终核验。管理员
  凭据不得写入应用 `.env`、命令参数、Git、日志或工单。
- `fyp_user` 是唯一应用身份。应用通过标准 `DB_USER`/`DB_PASSWORD` 注入其凭据，绝不能
  获得管理员凭据。

应用继续使用以下标准设置：

- `DB_HOST`、`DB_PORT`、`DB_NAME`（所提供 SQL 固定使用
  `fyp_secure_file_platform`）、`DB_USER` 和 `DB_PASSWORD`；
- `DB_SSL_CA`，用于验证服务器证书和 `DB_HOST`；
- 需要双向 TLS 时，同时提供 `DB_SSL_CERT` 和 `DB_SSL_KEY`。

`fyp_user` 带有 `REQUIRE SSL`。非开发环境必须验证服务器证书；CA/client 文件应作为只读
部署 secret 挂载。管理员远程连接同样应使用 `--ssl-mode=VERIFY_IDENTITY` 和受信任 CA。
非开发环境还必须设置 `APP_DEBUG=false`、不少于 32 个字符的非默认 `SECRET_KEY`，并明确
列出允许的 CORS origin。

`APP_DOCS_ENABLED` 是部署时必须明确决定的开关。本地开发保持为 `true`；SecureView 公网预发布
主机同样设为 `true`，因为线上 Swagger UI 是供团队与导师评审、演示的交付内容。从 Swagger 发出
的请求不会获得任何额外权限，仍受 HTTPS、nginx 请求限流、应用登录、授权和审计控制约束。不需要
公开 API 评审的正式生产环境应设为 `false`，此时 `/docs`、`/redoc` 与 `/openapi.json` 会被卸载并
返回 404。

`MYSQL_ROOT_PASSWORD` 和 `MYSQL_PORT` 仅供根目录 Compose 本地开发使用，不是生产管理员
配置。生产不使用任何部署专用的管理员、迁移或账户 Host 环境变量。

### 存储目录

三个存储路径默认指向代码目录内部。staging 的工作目录是 `/opt/mcs21/releases/<sha>` 下的
不可变 release，`fypapp` 无法写入，且每次部署都会被替换。因此 `backend.env` 必须把三者都指向
由 `fypapp` 拥有的持久化数据根目录：

```bash
ENCRYPTED_FILE_DIR=/var/lib/fyp-secure-file-platform/encrypted
TEMP_FILE_DIR=/var/lib/fyp-secure-file-platform/tmp
AVATAR_DIR=/var/lib/fyp-secure-file-platform/avatars
```

应用会在首次上传时创建 `avatars/`。`AVATAR_DIR` 存放明文头像，绝不能与密文对象共用目录。
`mcs21-deploy` 的部署前归档已经包含整个数据根目录。

### 同步由环境配置控制的请求上限

`.env.example` 是纳入版本管理的模板，预发布服务不会直接读取它。运行中的后端读取
`/etc/fyp-secure-file-platform/backend.env`，而 nginx 会在 FastAPI 收到任何字节之前先执行自己
的请求体上限。因此，调整页面宣称的上传上限时，以下四处必须一致才算完成：

- `frontend/src/crypto/upload.ts`：浏览器端预检查；
- `backend/app/core/config.py` 与 `.env.example`：应用默认值及模板；
- `/etc/fyp-secure-file-platform/backend.env`：已部署应用的环境覆盖值；
- nginx 当前生效的 `client_max_body_size`。

当前 500 MiB 上限要求预发布环境设置 `MAX_UPLOAD_SIZE_BYTES=524288000`；nginx 使用
`client_max_body_size 501m`，为密文及有界的 multipart metadata 开销留出空间。不要用
`.env.example` 整份覆盖受保护的环境文件：模板含本地开发占位值，也不包含部署 Secret。只修改
已评审的键，保留带时间戳的备份，然后验证并重启／重载：

```bash
sudo nginx -t
sudo systemctl restart fyp-backend
sudo systemctl reload nginx
curl --fail http://127.0.0.1:8000/health/ready
curl --fail https://secureview.tech/health/live
```

必须确认重启后的进程实际加载了新值，不能把“文件已编辑”当成生效证据。若返回 `413`，或 nginx
出现 `client intended to send too large body`，说明边缘层上限仍旧过期；若应用返回
`file_too_large`，说明请求已通过 nginx，但后端上限仍旧过期。文件媒体类型与这两项大小检查无关：
无法识别的类型会以 `application/octet-stream` 存储。

### 按地址的限制与会场网络

nginx、fail2ban 和后端都有按客户端地址计数的限制。在会场或校园 Wi-Fi 上所有访客到服务器都是同一个地址，所以这些限制在
2026-10-09 按"一个房间约一百人"重新设定（数值表见 [THREAT_MODEL.zh-CN.md 第 11.6 节](THREAT_MODEL.zh-CN.md)）。这三份文件
都不由 `mcs21-deploy` 或 CI 的 promote 安装：`deployment/server/` 下的是跟踪副本，要手动装到 VPS 上，服务器上的文件和仓库一致并
且服务重载之后改动才算完成。

```bash
cd /opt/mcs21/current
sudo install -m 0644 deployment/server/nginx-secureview-limits.conf /etc/nginx/conf.d/secureview-limits.conf
sudo install -m 0644 deployment/server/nginx-secureview.conf /etc/nginx/sites-available/fyp-secure-file-platform
sudo nginx -t && sudo systemctl reload nginx
sudo install -m 0644 deployment/server/fail2ban/filter-secureview-auth.conf /etc/fail2ban/filter.d/secureview-auth.conf
sudo install -m 0644 deployment/server/fail2ban/jail-secureview.conf /etc/fail2ban/jail.d/secureview.conf
sudo fail2ban-client -t && sudo systemctl reload fail2ban
sudo fail2ban-client status secureview-auth
```

装 nginx 文件之前先把线上文件和跟踪副本 diff 一下：证书那几行是 certbot 写的，续期可能动过 80 端口块。最后一条命令列出 fail2ban
当前封着的地址；答辩当天应该是空的，不空就用 `sudo fail2ban-client set secureview-auth unbanip <地址>` 解封。

后端自己的按地址阈值是 `backend/app/core/config.py` 里的默认值，发布部署后生效，除非
`/etc/fyp-secure-file-platform/backend.env` 里有覆盖。检查它没有钉住旧值：

```bash
sudo grep -E 'IP_MAX|MAX_ATTEMPTS|PER_WINDOW' /etc/fyp-secure-file-platform/backend.env
```

打印出来的任何一行都会盖过代码默认值；删掉或者改成当前值，然后 `sudo systemctl restart fyp-backend`。

## `localhost` 与远程账户来源

仓库中的三份 SQL 默认使用 ``'fyp_user'@'localhost'``，适用于应用从数据库主机连接的
部署。MySQL 账户中的 Host 表示客户端连接来源，并不是 `DB_HOST` 的值。

若应用远程连接，请在仓库外为三份 SQL 各制作一份受保护、经评审的部署副本，并在三份
副本中一致替换每一个 `localhost` 账户 Host：

- `01-provision.sql` 中的账户创建目标；
- `02-schema.sql` 中的表级及列级授权目标；
- `03-verify.sql` 中的账户与授权期望。

使用部署网络允许的最窄固定主机或模式。不要提交环境专用副本，也不要无条件使用 `%`；
即使网络和防火墙另有限制，数据库账户本身也应限制来源。

## 1. 管理员执行 Provision

在数据库服务器的仓库根目录中，如果 MySQL root 使用本机 socket 认证，执行：

```bash
sudo mysql < database/mysql/01-provision.sql
```

如果 root 使用密码认证，让客户端交互提示密码，不要把密码写进命令：

```bash
mysql --user=root --password < database/mysql/01-provision.sql
```

远程管理员连接使用受保护的环境副本并验证 TLS：

```bash
mysql --host=<mysql-host> --port=3306 --user=<administrator> --password \
  --ssl-mode=VERIFY_IDENTITY --ssl-ca=/path/to/mysql-ca.pem \
  < /protected/path/01-provision.sql
```

`01-provision.sql` 创建固定名称、`utf8mb4`/`utf8mb4_unicode_ci` 的数据库，并创建带
`REQUIRE SSL` 的 `fyp_user`。MySQL 为新账户生成随机密码并在客户端结果集中返回。管理员
必须在不会记录会话输出的受控终端中立即把该明文保存到 secret store；MySQL 之后无法还原
它。禁止截图、复制到聊天或工单，或写入持久化应用 `.env`。

该文件不创建应用表，也不授予尚不存在表上的运行时权限。表和精确表/列级授权由下一步统一
创建，避免给 `fyp_user` Schema 级 DML 或任何 DDL 权限。

脚本使用 `CREATE USER IF NOT EXISTS`：重复执行不会修改已有账户的密码、认证插件或 TLS
策略。已有同名账户必须评审 `SHOW WARNINGS` 及最终核验结果；不要把重复运行 Provision
当作凭据轮换或权限修复。凭据轮换和额外账户清理都必须作为单独、经过协调的运维变更。

## 2. 管理员创建空库 Schema 与最小授权

`02-schema.sql` 是当前生产 Schema 的完整快照，只能用于不含任何应用表和迁移 metadata 的
空数据库。它不是已有数据库的升级脚本。执行前确认目标名称无误，并确认没有需要保留的
数据：

```bash
sudo mysql < database/mysql/02-schema.sql
# root 使用密码认证时：
mysql --user=root --password < database/mysql/02-schema.sql
```

远程执行时使用三份受保护副本中的第二份：

```bash
mysql --host=<mysql-host> --port=3306 --user=<administrator> --password \
  --ssl-mode=VERIFY_IDENTITY --ssl-ca=/path/to/mysql-ca.pem \
  < /protected/path/02-schema.sql
```

该文件负责：

- 在外键依赖允许的顺序中创建当前 head 的 17 张应用表、索引、约束和 Schema 版本标记；
- 创建单例 `audit_chain_heads.id = 1` 初始行；
- 在表已经存在后，只向 `fyp_user` 授予 15 张普通状态表（含 `file_folders` 与 `email_verification_codes`）所需的精确 CRUD、
  `audit_logs` 的 `SELECT`/`INSERT`、`audit_chain_heads` 的表级 `SELECT`，以及仅限
  `last_log_id`、`current_hash`、`updated_at` 三列的 `UPDATE`；运行时账户不能更新
  `schema_revision`；
- 不授予 Schema 级、全局、DDL、`GRANT OPTION`、role 或 proxy 权限。

chain-head 列默认值和初始行都先使用 `0002_auth_identity_sessions`。运行时授权和
`alembic_version` 标记成功后，脚本先把列默认值恢复为最终 Schema 值，再由最后一条语句
显式发布 singleton 的 `0011_must_change_password`。因此部分完成的安装不能通过 readiness，完整
安装后的 Schema 又与 ORM 和 Alembic head 等价。

空库保护失败、任何对象已存在或任何 DDL 报错时，必须立即停止。MySQL DDL 可能部分提交；
失败后不得加入 `IF NOT EXISTS`、不得覆盖或盲目重跑脚本。应保持应用停止、保留现场供诊断，
并从已验证备份恢复；若这是全新的无数据目标，也只能在确认完整清理范围后重新创建空库。

生产环境不运行 `alembic upgrade`、`alembic current`、`alembic check` 或
`alembic stamp`。`alembic_version` 若作为快照中的 Schema 标记存在，只表示该快照与哪个
开发/CI head 对齐，不表示生产曾执行 Alembic。

## 3. 管理员执行只读核验

只有前两份 SQL 都成功后，执行：

```bash
sudo mysql < database/mysql/03-verify.sql
# root 使用密码认证时：
mysql --user=root --password < database/mysql/03-verify.sql
```

远程部署使用包含同一窄 Host 的第三份受保护副本：

```bash
mysql --host=<mysql-host> --port=3306 --user=<administrator> --password \
  --ssl-mode=VERIFY_IDENTITY --ssl-ca=/path/to/mysql-ca.pem \
  < /protected/path/03-verify.sql
```

操作员必须逐项确认：

- 服务器为 MySQL 8.4、严格 SQL mode 已启用、Session 时区符合部署预期，数据库字符集和
  排序规则正确；
- `fyp_user` 只有一个预期 Host 行，凭据、认证插件、锁定/过期状态和 TLS 要求符合预期；
- 不存在任何 Host 的旧 `fyp_migrator` 账户；
- `fyp_user` 没有全局或 Schema 级权限，只有 `02-schema.sql` 定义的精确表/列级权限，且
  `IS_GRANTABLE=NO`；
- 表级权限差集为空；列级权限差集也为空，且只包含
  `audit_chain_heads.last_log_id/current_hash/updated_at` 的 `UPDATE`，绝不包含
  `schema_revision`；routine、role、default-role 和 proxy 结果为空，服务器没有会向应用
  账户附加权限的 mandatory role；
- 应用表集合、关键 Schema metadata、版本标记及约束符合当前快照；
- `alembic_version` 恰好为 `0011_must_change_password`；
- `audit_chain_heads` 恰好包含一个 `id = 1`、空 `last_log_id`、64 个零哈希且
  `schema_revision = '0011_must_change_password'` 的单例行。

任何 `REVIEW`、缺失项、多余账户或多余权限都必须阻止应用启动。核验 SQL 只读取状态，不会
自动修复账户、权限或 Schema。

## 4. 退役旧 `fyp_migrator` 并启动应用

从旧流程升级运维规范时，可能仍存在一个或多个 `fyp_migrator@Host`。先确认没有发布 Job、
定时任务或外部服务仍依赖它，记录其所有 Host 和 grant，再由管理员显式撤权并 `DROP USER`。
不要让 Provision 自动删除来源不明的账户。必须重复运行 `03-verify.sql`，直到所有旧 migrator
行都消失且其权限不再存在。

核验完全通过后，只向应用进程注入 `fyp_user` 的标准 `DB_*` 和 TLS secret，再启动新版本。
应用不得持有 root/管理员凭据，也不得获得 DDL 或账户管理权限。

启动后，实例加入服务前必须同时通过 `GET /health/live` 与 `GET /health/ready`。
Readiness 会探测数据库并要求精确 Schema revision `0011_must_change_password`；它只诊断漂移，
不会执行 migration 或 stamp。

## 5. 在 nginx 终止 TLS

预发布 VPS 通过 Let's Encrypt 证书以 HTTPS 提供 `secureview.tech`。线上 server 块的版本化副本
位于 `deployment/server/nginx-secureview.conf`。

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d secureview.tech -d www.secureview.tech --redirect
```

`certbot --nginx` 会重写 80 端口块，因此任何改动过配置的续期之后，都必须重新应用下面的回环
探针例外，并与版本化副本比对。

这里的 HTTPS 不是装饰。浏览器只在安全上下文中暴露 `crypto.subtle`，而注册流程依赖它生成账户
RSA 密钥对并派生 Argon2id KEK。在明文 HTTP 下客户端登记代码根本拿不到该 API，注册无法完成。

### 80 端口块与发布探针

`mcs21-deploy` 会带 `Host: <public_host>`（即服务器裸 IP）探测
`http://127.0.0.1/health/live` 与 `http://127.0.0.1/`。certbot 生成的跳转只匹配两个域名，
其余一律返回 `404`，会导致部署后的存活检查失败并回滚发布。

因此 80 端口块保留且仅保留这两个路径，并限制为回环访问：

```nginx
location = /health/live {
    allow 127.0.0.1;
    allow ::1;
    deny all;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/proxy_params;
}

location = / {
    allow 127.0.0.1;
    allow ::1;
    deny all;
    error_page 403 = @canonical;
    try_files /index.html =404;
}

location @canonical {
    return 308 https://secureview.tech$request_uri;
}

location / {
    return 308 https://secureview.tech$request_uri;
}
```

回环访问两个探针仍然得到 `200`。80 端口上的其余请求一律跳转到规范的 HTTPS 源，裸 IP 也不例
外——`error_page` 把访问阶段的 `403` 转成同一个跳转。两种情况下都不会有任何内容以明文送出。

跳转用的是 `308` 而非 `301`，这样对 `/api/` 的 `POST` 会保留方法与请求体，而不会变成 `GET`
再以 `405` 失败。

### 用 IP 访问这台机器

443 端口块的 `server_name` 里带了裸 IP，所以 `https://<server-ip>/` 确实能打开站点；但
Let's Encrypt 证书只覆盖 `secureview.tech` 与 `www.secureview.tech`，浏览器会给出证书名称不
匹配的警告。Let's Encrypt 不为 IP 地址签发证书——IP 没有可供校验的名称。

请统一使用 `https://secureview.tech`。`http://<server-ip>/<路径>` 会跳转过去，这才是受支持
的入口：例如直接输入 IP 访问 API 文档，会落到 `https://secureview.tech/docs`。

团队演示与导师评审请直接使用规范地址：`https://secureview.tech/docs`。不要分享包含裸 IP 的
HTTPS 地址，因为 TLS 证书验证的是域名，而不是该 IP 地址。

在这个跳转存在之前，以 HTTP 访问裸 IP 时，除两个回环探针外的所有路径都由 nginx 返回 `404`。
那个页面很容易被读成"后端挂了"，而实际上只是明文请求找不到可跳转的名称而被拒绝。

### 首次访问的 HTTP 跳转

`.tech` 不在浏览器 HSTS 预加载名单中，因此不带协议直接输入 `secureview.tech` 的访客会先经过
一次 `http://` 才被跳转。此后 `Strict-Transport-Security` 头会将 HTTPS 固定一年。对外发布与
分享链接时请一律写作 `https://secureview.tech`，即可完全避免这一跳——部分应用内置浏览器会
在该跳转期间提示不安全。

## 依赖安装卡住时

`mcs21-deploy` 每次都在新的 `.build-*` 目录里构建发布、建独立的虚拟环境，所以每次部署都要下载后端依赖。
2026-10-05 有一个 pip 连接以约 29 kB/s 的速度慢慢下载一个 4.7 MB 的 wheel（同一台机器单独下载不到一秒），
部署因此卡了七分多钟；因为一直有字节进来，pip 自己的 `--timeout` 始终没有触发。

现在每次 `pip install` 除了 pip 的 `--timeout 30 --retries 5`，还有一个总时长上限
（`MCS21_PIP_ATTEMPT_SECONDS`，默认 240 秒）；卡住或失败的一次会重新开始，最多 `MCS21_PIP_ATTEMPTS` 次
（默认 3 次，间隔 `MCS21_PIP_RETRY_PAUSE` 秒，默认 10 秒）。正常安装不到一分钟。只有每一次都失败，部署才算失败，
并且会删掉自己的 `.build-*` 目录，不再留在服务器上。`backend/tests/unit/test_ops_units.py` 会用一个“卡一次”的假 pip
实际运行这个函数。

`mcs21-deploy` 本身放在 `/usr/local/sbin`，是手工安装的：这个文件改动后，要从新的发布里复制过去
（`install -m 0755 /opt/mcs21/current/deployment/server/mcs21-deploy /usr/local/sbin/`）。

## 对运行中的部署应用 Schema Revision

`mcs21-deploy` 从不修改 Schema。它只做数据库备份并以只读方式运行 `03-verify.sql`——脚本自己的
帮助文本就是这么写的，而且自动部署身份不持有任何 MySQL 管理员凭据。因此，携带新 Alembic revision
的发布必然包含一个手动步骤，而**顺序**弄错会导致站点不可用或发布被隔离。

### 为什么顺序是被迫的

`GET /health/ready` 会把 `audit_chain_heads.schema_revision` 与运行中代码的
`EXPECTED_SCHEMA_REVISION` 比较，并要求二者**精确相等**——不是「不低于」。因此不存在两边同时正确
的顺序，一段 `503 schema_incompatible` 的窗口无法避免。两种顺序的区别在于失败方式：

- **先推代码。** `verify_database()` 会在核验日志中搜索 `REVIEW`、`MISSING` 或 `UNEXPECTED`，
  命中即 `die`，部署当场中止。随后部署后健康检查失败、发布回滚、该 SHA 被隔离——而
  `mcs21-auto-deploy` **不会重试被隔离的 SHA**，因此之后的每一个提交都会一起卡在它后面。
- **先改数据库。** 运行中的代码会短暂返回 `503`，因为它仍期待上一个 revision。最多两分钟后的
  下一次自动部署会把代码跟上，窗口自行关闭。

**先改数据库。** 它的失败形态是一次短暂中断，而不是一条卡死的发布管线。

另需注意：revision 字符串出现在大约三十处——`config.py`、`audit_chain_head.py`、
`02-schema.sql`、`03-verify.sql` 以及若干测试文件。只更新其中一部分正是此前隔离过一次发布的原因；
`tests/unit/test_migration_metadata.py` 与 `tests/unit/test_mysql_sql_deployment.py` 正是为
捕捉这种「改了一半的重命名」而存在，因此在开始上述任何操作之前，先跑一遍后端单元测试。

### 生成 SQL

不要手写这些语句。从 revision 本身渲染出来，使服务器上运行的内容与迁移所述一致：

```bash
cd backend
.venv/bin/alembic upgrade <上一个 revision>:<新 revision> --sql
```

迁移内部的保护性查询在该模式下无法执行——没有连接可供查询——因此会被跳过，渲染出的脚本依赖约束
本身。运行前先读一遍输出，并把其中任何保护性检查作为显式的前置检查复现在第 3 步中。

### 步骤

1. **准备好代码但先不要推。** 提交、合并到 `main`，在 `git push` 之前停住。推送应当是一条随时
   可以触发的命令，因为正是它关闭 `503` 窗口。

2. **备份。** 在服务器上执行 `sudo mcs21-deploy database`。它同时会针对**当前已部署**的发布
   运行只读核验，因此应当通过；若未通过，请停下排查，而不要在已有问题之上叠加 Schema 变更。

3. **前置检查，只读。** 确认 `alembic_version` 与 `audit_chain_heads` 两处的起始 revision，
   并确认新约束将要校验的每一行都已经满足它们。MySQL 的 DDL 按语句提交且无法回滚，因此
   `DROP CHECK` 成功之后 `ADD CONSTRAINT` 失败，会让该表处于完全没有约束的状态。前置检查正是
   为了避免走到那一步。

4. **执行 SQL**，以两个就绪标记与 `alembic_version` 结尾。标记要放在最后抬升：中途失败绝不能
   对外宣告一个数据库并不具备的 Schema。

5. **立刻推送。** 从这一刻起站点返回 `503`，直到部署完成，通常为两到三分钟。

6. **确认。** `journalctl -u mcs21-auto-deploy` 中出现 `result=success` 与 `health=ok`，且
   `https://secureview.tech/health/ready` 返回 `{"status":"ready"}`。

### 回退

`sudo mcs21-deploy rollback` **只回退代码发布，从不改动数据库**。在 Schema 变更之后单独使用它，
会造成旧代码对新 Schema 的局面，也就是 `503 schema_incompatible` 状态——因此回退必须同时撤销
两半：先执行回退 SQL，再对合并提交执行 `git revert`。

此外，只要某个 revision 放宽了列的取值范围，可回退性就是有时限的。一旦有数据行使用了新取值，
再次收窄就会失败，而那些行通常是完好的数据而非损坏数据——`0005` 与 `0006` 中的保护正是因此拒绝
降级，而不是删除它们。要么尽快决定，要么接受「回退意味着重新加密或删除真实文件」。

恢复第 2 步的备份是最后手段，而非计划的一部分。它会丢弃自转储以来写入的一切——上传、注册、审计
记录、会话——而磁盘上的密文仍然存在，导致两者失去对应关系。

## 后续非空生产数据库升级

不得在非空生产数据库上重跑 `02-schema.sql`，也不得运行 Alembic。每次 Schema 变化必须提供
独立、按版本命名、经过 DBA 评审的前向 SQL，并明确：

1. 唯一允许的前置 Schema 版本和完整预检；
2. 停止/排空写入以及同一数据库只允许一个升级执行者；
3. 已验证可恢复的加密备份、整体期限和有限 metadata-lock 等待；
4. DDL 执行顺序、数据回填、发布后核验以及部分提交时的恢复步骤；
5. 成功后更新 Schema 版本标记，并运行当前 `03-verify.sql` 或该升级配套的核验 SQL。

Alembic revision 可继续在开发/CI 中表达同一变化，但生产 DBA SQL 必须单独评审，且 CI 必须
证明它产生的最终 Schema 与当前 Alembic head/ORM metadata 等价。

备份必须在仓库外加密保存、限制访问并定期演练恢复。数据库 dump 包含登录密码哈希、公开
Argon2id 参数、已包装 AMK、客户端加密私钥包、安全审计证据、明文运营文件 metadata 及包装
文件密钥。它们不是明文私钥或 DEK，但仍能用于离线猜测 passphrase，并暴露所有权/共享关系，
因此必须作为高度敏感数据保护。

## Compose、本地开发与历史 `init.sql`

根目录 `docker-compose.yml` 只用于本地开发。MySQL 官方镜像会在全新 volume 上根据
`MYSQL_ROOT_PASSWORD`、`DB_NAME`、`DB_USER` 和 `DB_PASSWORD` 创建数据库及开发账户；
开发者可在该一次性环境中运行 Alembic。这不等同于生产表级权限，也不会自动执行三份生产
SQL。已有 volume 不会因为环境变量变化而重新初始化。

不要在普通 Compose 开发 volume 上随意执行生产 Provision/Schema SQL。同名开发账户可能
已有更宽权限，已有表也应触发空库保护。三份生产 SQL 和 Alembic revision 都不应挂载到
`/docker-entrypoint-initdb.d`；官方镜像只在全新 volume 初始化时执行该目录，无法承担持续
版本升级。

历史版本曾包含 `docs/init.sql`。它不是当前 Schema 来源，现已从部署流程移除。由它创建的
非空、无已知版本标记数据库仍属于未受管理旧数据库，不能运行 `02-schema.sql`，也不能在
生产环境运行 Alembic；应按[数据库接管策略](DATABASE_SCHEMA.zh-CN.md)重建，或使用单独、
经评审的 DBA 接管 SQL。
