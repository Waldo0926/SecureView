# 后端架构

[English](ARCHITECTURE.md) | 简体中文

## 决策与当前形态

后端采用**模块化单体**：一个可部署的 FastAPI 应用、一个 MySQL 数据库，以及一个本地加密
对象存储适配器，并保持严格内部边界。这适合 FYP 范围，同时保留数据库、存储、密码学和身份
边界。微服务会增加分布式事务，却不会改善密钥托管模型。

认证、客户端包装账户密钥、加密文件与文件夹、共享、审计查询、恢复、完整性检查及管理（含仅计数
统计与安全 Agent 报告）均已实现为纵向切片，公开 API 已经为这些模块使用真实处理器。

## 依赖方向

```text
HTTP 路由 / 依赖项
          |
          v
应用服务（用例事务所有者）
          |
          +----> repository / SQLAlchemy session
          +----> 加密对象存储端口
          +----> 校验/密码学能力
          +----> 领域策略及审计追加
```

规则：

1. 路由校验 HTTP 输入、解析已认证行为者、调用应用服务，再映射为响应 DTO；路由不包含 SQL、
   文件系统或私钥逻辑。
2. 服务通过构造器注入依赖来协调用例，不在内部创建数据库 Session 或基础设施适配器。
3. 一个命令拥有一个数据库事务。Repository 可以查询、添加和 `flush`，不得自行 `commit`。
   认证限流证据是有意的前置条件例外：它单独提交，避免被失败登录/注册自身回滚。
4. ORM 模型只用于持久化，不直接成为公开响应；Pydantic Schema 是严格传输契约，不包含
   SQLAlchemy 行为。
5. 配置与组合位于 `core/config.py` 和 `main.py`；模块不依赖进程当前工作目录。
6. 应用 HTTP 操作只使用 `GET` 和 `POST`；所有状态变更使用 `POST`，并在适当时采用显式
   命令路径。

## 包职责

```text
backend/app/
|-- api/                 FastAPI 路由、依赖、错误/响应映射
|   `-- v1/              认证、密钥、文件与文件夹、共享、审计、恢复、管理
|-- core/                配置、数据库/Session 工厂、安全基础能力
|-- domain/              可信上下文、枚举、领域输入/结果/错误
|-- models/              SQLAlchemy 持久化模型
|-- repositories/        不独立提交的持久化操作
|-- schemas/             严格 Pydantic 传输 DTO
|-- services/            用例协调器及能力服务
`-- main.py              应用工厂与组合根

backend/migrations/      开发/CI 的 Alembic 编写历史
database/mysql/          生产交付所用、经评审的管理员 SQL
backend/tests/
|-- unit/                策略、校验、密码学、存储及服务测试
|-- api/                 HTTP 契约/依赖替换测试
|-- integration/         MySQL、migration、repository 及存储测试
`-- e2e/                 供前端实时后端测试使用的真实 API 服务及运行脚本
```

每个请求范围内的 SQLAlchemy `Session` 是工作单元。各服务负责 commit/rollback，并通过同一个
Session 追加对应安全事件。

## 身份与授权边界

会话模型使用相互独立的高熵不透明凭据，而不是 JWT：

- Session 行只保存访问令牌 SHA-256。统一依赖将其解析为 `ActorContext`，其中包含可信的内部/
  公开身份及会话字段。
- 刷新令牌使用独立哈希和单调递增 generation。成功刷新会消费一代，并同时轮换两种凭据；
  重放会撤销整个会话族，绝对到期时间防止永久会话。
- 登出、全部登出、密码修改、管理员禁用及会话数量限制会撤销相应服务端会话族。

登录密码使用 Unicode NFC 规范化、8 至 128 字符且至少包含两类字符的策略、本地常见/账户派生检查，以及 `pwdlib`
推荐的 Argon2id。有效旧 bcrypt 哈希会在登录时升级；未知用户仍执行虚拟校验。MySQL 中由 HMAC
标识的账户/IP 桶协调多工作进程限流，每个工作进程另外限制并发内存困难操作。

每个非公开端点都需要可信行为者。角色检查位于 API/服务边缘；资源检查在用例内使用内部行为者
ID。文件访问始终同时要求：

1. 具有所需能力的 ACTIVE 逻辑授权；
2. 同一用户与文件的 ACTIVE 用户密钥包装，且绑定 ACTIVE 用户公钥。

不存在与未授权文件采用相同公开 not-found 行为。ADMIN 操作显式声明。恢复复核只允许 ADMIN
和 RECOVERY_OFFICER，且请求人不能复核自己的请求。

## 客户端账户密钥托管

加密 passphrase 不跨越 API 边界，并与登录密码相互独立。可信客户端在注册前生成 RSA 密钥对
及 AMK：

```text
passphrase --Argon2id + 随机盐--> 256-bit KEK
KEK --AES-256-GCM--> 已包装 256-bit AMK
AMK --HKDF-SHA256--> 私钥加密密钥
私钥加密密钥 --AES-256-GCM--> 加密 PKCS8-DER RSA 私钥
```

注册在同一事务中保存账户、RSA 公钥/指纹、公开 KDF/AEAD 参数、已包装 AMK、加密私钥包和
审计事件。后端校验 RSA 类型/长度及信封结构，但从不生成、接收、解密或持久化明文私钥。

`GET /keys/me` 向所有者返回加密包。修改 passphrase 无需重新加密 RSA 私钥包，但替换 KDF/
包装 AMK 配置不能只依赖 Bearer Session 和乐观 revision。客户端先从
`POST /keys/me/rewrap/signing-payload` 取得覆盖完整拟议配置的规范摘要，使用最新当前私钥在
本地以 RSA-PSS-SHA256 签名，再把签名提交至 `POST /keys/me/rewrap`。共享客户端通过仅公钥
端点取得接收者活跃公钥。

Rewrap 摘要采用独立 domain，并对可变数据使用长度前缀；它覆盖行为者、authorizing key 和
profile UUID、预期 revision、KDF suite/version/salt/cost 参数、派生密钥长度、包装 suite、
wrapped AMK、nonce、tag 及 AAD version。服务在构建/验证摘要前锁定账户 profile 和最新当前
客户端密钥，因此 revision/密钥变化或签名失败都会拒绝命令；成功更新和审计追加共享一个事务。
Signing-payload 端点只返回 32-byte 摘要和算法标识，绝不返回明文密钥材料。

添加后继密钥同样不仅依赖 Bearer Session，还要求证明持有最新当前私钥。服务器构造一个带长度前缀
的规范 SHA-256 摘要，覆盖行为者、当前密钥、profile/revision、新公钥/指纹及加密 bundle
字段；客户端使用 RSA-PSS-SHA256 签名。服务验证签名后才保存新公钥和 bundle。旧密钥继续
用于解密历史文件包装，所有者专属端点可按 UUID 返回相应历史加密包；新共享只公布最新活跃公钥。

每个账户只有一行保护配置。所有客户端包装私钥包预期继续由该 AMK 派生的密钥保护；由于服务端
从不获知 AMK，它无法用密码学方式证明这一点。因此后继密钥流程是在现有 AMK 下轮换 RSA
密钥，并不是安全的新 AMK 重置或版本管理机制。

**忘记 passphrase** 由另一个会生成新 AMK 的流程处理。注册时浏览器会一次性提供账户私钥的明文
PKCS#8 `.pem` 文件。用户持有该文件并已登录时，客户端用新 passphrase 派生的 KEK 包装一个新
AMK，用它重新加密同一把私钥，再对两个替换信封的规范摘要（取自
`POST /keys/me/reset-protection/signing-payload`）做 RSA-PSS-SHA256 签名，提交到
`POST /keys/me/reset-protection`。密钥对和所有文件包装都不变，因此不需要重新加密任何文件。
仅凭会话无法重设 passphrase；passphrase 与私钥文件都丢失时，该账户的文件无法恢复（见
[SECURITY_FLOWS.zh-CN.md](SECURITY_FLOWS.zh-CN.md)）。修改仍记得的 passphrase 也使用同一个端点：浏览器用当前 passphrase
打开私钥，而不是读取私钥文件（#201）。上文的 `/keys/me/rewrap` 路径仍保留在 API 中，但设置页并不调用它。

这是密钥托管边界，不是对恶意服务器的证明。数据库被盗后，已存 KDF 材料可用于离线猜测口令；
客户端需要固定指纹/revision 或采用外部信任锚，才能发现恶意公钥替换或回滚。

## 加密对象与事务边界

文件在上传前由客户端加密。每个文件使用独立随机 DEK，以及每次上传选定的六种认证加密套件之一
（AES-128/192/256-GCM、AES-256-GCM-SIV、ChaCha20-Poly1305、XChaCha20-Poly1305，默认
AES-256-GCM）及其 nonce 和分离存放的 tag、带版本信封/AAD 契约、所有者公钥的 RSA-OAEP-SHA256 包装，以及恢复公钥包装。API 接收密文和这些
信封，从不接收文件明文、私钥或明文 DEK。

MySQL 无法与本地存储对象原子提交，因此上传使用暂存与补偿：

1. 校验公开元数据、算法版本、密钥归属、恢复密钥及 RSA 密文长度；
2. 将有界密文流写入随机暂存对象，同时计算 SHA-256；
3. 在一个数据库工作单元中创建文件元数据、所有者授权、所有者/恢复包装及审计项；
4. 将暂存对象发布到不透明最终 object key，然后提交；
5. 在尝试 COMMIT 前发生的失败会回滚，并尽力删除暂存/已发布对象；发出 COMMIT 后连接失败时
   结果不确定，因此保留已发布对象，由对账任务判断其已被引用还是属于孤儿。

数据库行只保存不透明 object key，不保存主机文件系统路径。存储适配器在配置根目录内解析并
检查其 containment。

上传还按账户设限：默认最多存储 2 GiB、每滚动 24 小时最多上传 5 GiB（`USER_STORAGE_QUOTA_BYTES`、
`USER_DAILY_UPLOAD_BYTES`），磁盘剩余空间将低于下限时拒绝所有上传。上传请求处理不在事件循环上
执行阻塞的数据库操作，因此慢速请求体不会耗尽连接池（#163）。

下载不进行解密。它要求授权加包装，校验密文哈希后流式返回密文。另一个元数据响应向已授权
客户端提供 nonce、tag、包装 DEK、算法版本及可选加密 manifest。解密和 GCM 认证在客户端
完成。因此后端能验证存储完整性，但若不获知 DEK，就无法验证客户端生成的 GCM 语义。

软删除会先持久化标记文件，并撤销授权/包装，再幂等清理存储。完整性检查重新计算对象哈希并
追加检查结果：每次下载都会校验；每日巡检（`mcs21-integrity-sweep.timer`）将每个存储对象与上传
审计事件中锚定的摘要比对，因此只改数据库里的摘要也藏不住被改动的对象。损坏文件显示在管理员的
Integrity 标签页，可逐个从备份恢复（`backend/scripts/restore_file.py`）。

## 共享边界

发送方在本地解锁账户私钥、解开文件 DEK、取得接收者公钥，并生成新的
RSA-OAEP-SHA256 DEK 包装。服务只接收目标 UUID、能力及 RSA 密文；它校验目标与密钥关联，
并原子创建或重新激活逻辑授权、密码学包装和审计事件。请求能力会依据行为者授权进行衰减：
委托分享者只有自身具备 `can_download` 或 `can_share` 时才能授予对应能力。规范所有者授权不可变；
更新或重新激活已有非所有者授权还要求行为者授权具备 `can_manage`，或行为者是该授权当前的
`granted_by`。

撤销在同一事务中改变授权及活跃包装，且不能撤销规范所有者。它控制未来由服务器介导的访问，
但无法删除已经复制的数据。

## 恢复边界

ADMIN 登记恢复**公钥**。新登记会轮换未来上传使用的活跃密钥，但不会改写现有恢复包装，因此
匹配的历史私钥必须继续安全离线保存。

请求目标是请求人自己的一个活跃公钥，并在有限时间后到期（默认 24 小时）。创建时要求实时
存在 `ACTIVE` 且 `can_download` 的授权，以及由活跃用户密钥支持的活跃用户包装；请求人是所有者
时也适用同一规则。非请求人的 ADMIN 或 RECOVERY_OFFICER 进行批准或拒绝。每次读取 execution
package 前都会重新校验同一 entitlement，随后才返回恢复包装 DEK、恢复公钥身份和目标用户公钥。
隔离的离线/HSM 流程使用恢复私钥解开并立即重包装 DEK。

执行采用每文件 `File -> Grant/UserKey/Wrapping -> Request -> Audit` 锁顺序，并在改变任何包装前
重新校验实时 entitlement。API 只接收新的 RSA 密文，创建或更新目标密钥包装，再标记请求已执行；
它不会创建、重新激活或提升逻辑授权，所以批准后的撤销或降权不能被恢复流程撤回。撤销前缓存的
package 无法追回；后续 package 读取和执行仍会默认拒绝。

普通端点和恢复端点均不接收恢复私钥，应用在恢复时也不解密。该流程恢复的是文件包装，不会
重置加密 passphrase、解密账户私钥包或创建替代用户密钥。当前经办-复核规则隔离请求人与
复核者，但不要求批准与执行由两个不同人员完成。

## 元数据与威胁边界

服务器有意保留运营元数据：账户标识、公钥和指纹、KDF/信封参数、明文文件名与 MIME、声明
明文/密文大小、时间戳、所有权/共享关系、会话 IP/user-agent、恢复状态及审计动作。密文大小
和流量时机也会泄露信息。可选加密 manifest 是不透明的，但当前文件名/MIME 列并非如此。

因此，本项目的“零知识”是指合规客户端执行密码学时，普通 API 不获知明文密钥材料或文件内容；
它不代表元数据匿名、抵御流量分析，或抵御能够替换数据库对象和公钥的主动恶意服务端。

## 审计完整性

安全敏感变更在同一事务中追加哈希链。单例 `audit_chain_heads` 行通过
`SELECT ... FOR UPDATE` 锁定，并记录最终日志 ID、哈希及 Schema revision，防止并发事务分叉。
规范化持久化 `DATETIME(6)` 与 `{}` metadata 允许确定性重算。

审计读取按行为者/文件限定，返回 metadata 经白名单过滤；ADMIN 可验证完整链与链头。限制性
身份外键保护已哈希历史，因此账户移除采用状态软删除。数据库内普通哈希链不能阻止管理员重写
并重算全部历史，因此 staging 还会把经 HMAC 认证的链头检查点发布到外部 S3 兼容存储
（`backend/scripts/audit_checkpoint.py`、`mcs21-audit-checkpoint.timer`）；应用进程从不持有
该 HMAC 密钥。

MySQL 因死锁（1213）或锁等待超时（1205）中止的事务会从头重试，最多三次
（`app/core/db_retry.py`，#139）。

## Schema 与交付规则

- ORM metadata 及截至 `0011_must_change_password` 的有序 Alembic revision 是开发/CI Schema
  编写权威。
- `database/mysql/02-schema.sql` 是由该权威派生、经评审的生产空库工件；奇偶校验测试比较表、
  列、索引及约束。
- 应用不调用 `create_all()`，启动时不执行 DDL。`/health/ready` 校验连通性和精确预期 revision，
  但不迁移。
- 生产安装仍为 `01-provision.sql -> 02-schema.sql -> 03-verify.sql -> fyp_user`；运行时身份
  不拥有 migration 权限。
- 非空部署需要独立评审且版本化的 DBA 升级，配合停止写入、串行化、已验证备份及发布专用核验。
- MySQL 专用集成测试使用 MySQL 8.4，不使用 SQLite 替代。

## 用例完成定义

一个用例只有同时具备以下内容才算完成：

- 严格请求/响应 Schema，不含明文秘密或内部字段；
- 认证、角色及资源策略；
- 明确事务所有者及回滚/补偿行为；
- 稳定错误及同事务审计事件；
- 适用时的有界存储和分页行为；
- 对成功、拒绝、冲突及相关重试路径的单元/API/集成覆盖。
