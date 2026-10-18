# API 设计

[English](API_DESIGN.md) | 简体中文

## 当前状态与方法策略

后端在以下基础路径下提供已实现的认证、账户密钥托管、加密文件、共享、审计、恢复和管理路由：

```text
/api/v1
```

这些路由具有真实的授权、持久化、事务、适用时的存储处理及审计事件。

应用层 HTTP 方法仅允许 `GET` 和 `POST`。`GET` 只用于读取；新增、更新、删除、撤销、验证
命令及其他状态变更都使用 `POST`，通常采用显式动作路径。应用路由、客户端、示例、OpenAPI
及 CORS 均不得定义 `PUT`、`PATCH` 或 `DELETE` 业务操作。

未版本化的运维端点：

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/health/live` | 进程存活检查，不检查依赖 |
| GET | `/health/ready` | 数据库连通性及精确应用 Schema revision 标记检查 |

## 响应、认证与错误契约

JSON 应用响应使用统一信封，其中 `data` 是路由专用 DTO。失败示例：

```json
{
  "success": false,
  "status": "fail",
  "message": "Request validation failed",
  "data": {
    "error_code": "request_validation_failed",
    "details": []
  },
  "description": null,
  "code": 422
}
```

`error_code` 对客户端稳定，`message` 可安全展示。校验错误指出字段位置，但不回显被拒值。内部
异常、数据库细节、文件系统路径、凭据、passphrase、明文私钥及明文 DEK 均不会返回。

受保护路由使用 `Authorization: Bearer <opaque-access-token>`；认证失败返回
`WWW-Authenticate: Bearer`。含敏感材料的响应使用 `Cache-Control: no-store, no-cache` 与
`Pragma: no-cache`。自增数据库 ID 不跨越 API 边界；公开资源使用 UUID。

## 认证 API

| 方法 | 端点 | 认证 | 成功 | 说明 |
|---|---|---|---:|---|
| POST | `/auth/verification-codes/send` | 公开 | 200 | 为注册或重置密码发送一次性邮箱验证码 |
| POST | `/auth/register` | 公开 | 201 | 创建 USER 并保存客户端生成的加密密钥材料 |
| POST | `/auth/password-reset` | 公开 | 200 | 校验邮箱验证码后设置新的登录密码 |
| POST | `/auth/login` | 公开 | 200 | 验证登录密码并签发访问/刷新凭据对 |
| POST | `/auth/refresh` | JSON 内刷新凭据 | 200 | 消费并轮换一次性刷新凭据 |
| GET | `/auth/me` | Bearer | 200 | 返回当前账户 |
| POST | `/auth/logout` | Bearer | 200 | 撤销当前会话族 |
| POST | `/auth/logout-all` | Bearer | 200 | 撤销账户所有活跃会话族 |
| POST | `/auth/change-password` | Bearer | 200 | 修改登录密码并撤销所有会话 |
| POST | `/auth/delete-account` | Bearer + 登录密码 | 200 | 关闭账户并删除其拥有的文件；不可逆 |
| GET | `/auth/sessions` | Bearer | 200 | 最多列出最近 100 个服务端会话 |
| POST | `/auth/sessions/{session_id}/revoke` | Bearer | 200 | 按公开 UUID 撤销本账户会话 |
| POST | `/auth/avatar/upload` | Bearer | 200 | 上传经校验的 PNG/JPEG 头像（存放在加密对象目录之外） |
| GET | `/auth/avatar` | Bearer | 200 | 返回调用者的头像图片 |
| POST | `/auth/avatar/delete` | Bearer | 200 | 删除头像，退回显示姓名首字母 |

`POST /auth/verification-codes/send` 接收 `email` 与 `purpose`（`REGISTRATION` 或
`PASSWORD_RESET`）。无论该地址是否已注册，一律返回 `200` 及 `code_sent`、
`expires_in_seconds`、`resend_available_in_seconds`，因此该端点无法用于枚举已注册用户；
只有地址确实符合该用途时才会真正发信。发送按邮箱与 IP 双重限流，冷却期内重发返回 `429`
并带 `Retry-After`。

注册请求包含 `username`、`email`、`password`、`verification_code` 和 `key_material`。
`key_material` 包含客户端生成的 RSA-OAEP-SHA256 公钥、使用 Argon2id 与 AES-256-GCM 的 KEK
包装 AMK 配置，以及使用 AMK/HKDF 派生密钥与 AES-256-GCM 加密的 PKCS8-DER 私钥包。

其中的算法名、格式版本与 AAD 版本、派生密钥长度由 API 固定，不由调用方声明；携带这些字段会被
当作多余字段拒绝。请求真正承载的是只有调用方能产生的材料：公钥、各个盐、KDF 开销参数、连同
nonce 与认证标签的两个信封，以及私钥包的 `ciphertext_sha256`。存储行与所有 `*Out` 响应仍然
记录每个信封由哪种算法封装，以便日后引入第二种算法。缺少验证码时返回 `422`。

各项检查按固定顺序执行，使响应只暴露本来就公开的信息。用户名已被占用时先返回
`409 account_identifier_unavailable`，且在消耗验证码之前：用户名本来就是公开的（分享时按用户名解析），
提前告知可以让调用方换个名字而不必重新发码。接着消耗验证码，错误或过期时 `error_code` 为
`invalid_verification_code`。最后才检查邮箱，已注册的邮箱返回同样的 `422 invalid_verification_code`，
因此无法把"邮箱已注册"和"验证码错误"区分开。（发码接口本来就不会给已注册邮箱发验证码，这一分支
通常只是堵住竞态。）消费验证码即证明该地址受控，因此新账户直接以 `email_verified` 为真写入。
成功响应返回 `user`、`key_id` 和 `public_key_fingerprint`，不返回私钥。

`POST /auth/password-reset` 接收 `username`、`email`、`verification_code` 和
`new_password`。验证码先于用户名/邮箱一致性判断被消费，因此不匹配的组合会消耗一次尝试，而不会
泄露验证码本身是否有效；所有失败都返回同一个 `invalid_verification_code` 响应。重置成功会写入
新的 Argon2id 密码哈希、撤销全部会话族，并返回 `revoked_sessions`。它不会改动账户的密钥保护
配置或加密私钥包：`key_envelopes_unchanged` 恒为 `true`——加密 passphrase 与登录密码
彼此独立，因此重置登录密码绝不会让账户失去对已加密文件的访问能力。

登录密码与加密 passphrase 相互独立；API 从不接收加密 passphrase。登录与修改密码输入先做
Unicode NFC 规范化；新密码须为 8 至 128 个字符、至少包含两类字符，并通过本地常见密码及账户派生检查，再用
Argon2id 哈希。

登录成功数据包含 `user`、`access_token`、`refresh_token`、`token_type`、
`access_expires_at`、`refresh_expires_at` 和 `session_id`。访问与刷新值是独立不透明凭据，
服务器只保存其哈希。刷新凭据重放会撤销完整会话族。

`user`（登录响应和 `GET /auth/me` 中）带有 `must_change_password`。管理员执行
`POST /admin/users/{user_id}/reset-password` 后它为 `true`，直到持有人通过
`POST /auth/change-password` 或 `POST /auth/password-reset` 设置自己的密码。标记存在期间，服务器对除
`GET /auth/me`、`POST /auth/change-password`、`POST /auth/logout`、`POST /auth/logout-all` 之外的所有
需要登录的路由返回 `403 password_change_required`（`POST /auth/refresh` 不带 Bearer 令牌，它签发的令牌
同样受这份清单约束）。删除账户也会被拒绝。前端根据这个标记，以及任何 `password_change_required` 响应，
把持有人带到设置页，直到改好密码。

`POST /auth/delete-account` 在 Bearer 令牌之外还要求 `password`，因为这是 API 里唯一不可逆的操作。
密码校验与修改密码共用同一套重认证限流：密码错误计入 `REAUTH_ACCOUNT` 与 `REAUTH_IP` 桶，审计记录
`ACCOUNT_DELETION_PASSWORD_FAILED`，并返回 `422 invalid_current_password`；桶被封禁期间，在比较任何
密码之前就返回带 `Retry-After` 的 `429 auth_rate_limited`。最后一个在用的管理员不能删除自己的账户：在另一个
管理员账户处于启用状态之前，该调用返回 `409 last_admin`。

邮箱验证与忘记登录密码重置已基于上述一次性邮箱验证码实现；MFA 与外部身份提供商登录仍未实现。

邮箱验证码只是登录密码的找回通道，永远无法找回遗忘的加密 passphrase：服务器不持有任何能打开
AMK 信封的材料，该项丢失在设计上即不可恢复。

## 账户密钥 API

| 方法 | 端点 | 认证 | 说明 |
|---|---|---|---|
| GET | `/keys/me` | Bearer | 返回调用者公钥、KEK 包装 AMK 配置及加密私钥包 |
| GET | `/keys/me/{key_id}` | Bearer | 返回属于调用者的当前或历史加密密钥包 |
| POST | `/keys/me/rewrap/signing-payload` | Bearer | 为完整的拟议保护配置重包装构建规范摘要 |
| POST | `/keys/me/rewrap` | Bearer + 当前密钥签名 | 使用乐观 revision 和当前私钥持有证明替换包装 AMK/KDF 配置 |
| POST | `/keys/me/reset-protection/signing-payload` | Bearer | 为新 AMK 信封与重新封装的私钥包构建规范摘要 |
| POST | `/keys/me/reset-protection` | Bearer + 当前密钥签名 | 重置遗忘的 passphrase：以私钥文件为证明，在新 AMK 下替换两个信封 |
| POST | `/keys/add/signing-payload` | Bearer | 构建必须由当前客户端密钥授权的规范摘要 |
| POST | `/keys/add` | Bearer | 使用当前密钥的 RSA-PSS-SHA256 授权添加后继公钥/加密私钥 |
| GET | `/keys/users/{user_id}/active` | Bearer | 只返回用户用于共享的活跃加密公钥 |
| GET | `/keys/users/by-identifier/{identifier}/active` | Bearer | 同一把密钥，按精确用户名或邮箱地址寻址，让发送方无需浏览用户目录即可解析已知接收人 |
| GET | `/keys/users/by-username/{username}/active` | Bearer | 为仅支持用户名的旧客户端保留的已弃用兼容端点 |

保护配置重包装采用两次调用的持有证明流程。客户端在本地解开 AMK 和最新当前私钥，准备
`authorizing_key_id`、`expected_revision` 及完整拟议保护配置，把这些未签名字段提交至
`POST /keys/me/rewrap/signing-payload`，取得规范 Base64 编码的 32-byte SHA-256 摘要，再在
本地使用 RSA-PSS-SHA256 签名。随后把完全相同的字段、`authorization_algorithm` 和签名提交
至 `POST /keys/me/rewrap`。

摘要绑定行为者 UUID、最新当前密钥 UUID、保护配置 UUID、预期 revision、全部 KDF 参数和
完整的新包装 AMK AEAD 信封。服务在锁内重新检查 profile revision/当前密钥，验证签名后才
原子更新保护配置及审计链。仅有 Bearer Session 或 expected revision 并不足够。两个端点均
不接收新旧 passphrase，也不替换加密私钥包；过期 revision、旧 authorizing key、被修改的
拟议字段及无效签名都会失败关闭。

Passphrase 重置沿用同样的两次调用形态，覆盖重包装无法处理的情形：passphrase 已遗忘、旧 AMK
无从取得，但注册时的私钥文件仍在。客户端生成新 AMK，重新封装 AMK 信封与私钥包，把
`authorizing_key_id`、`expected_profile_revision`、`expected_bundle_revision`、`protection`
与 `private_key_bundle` 提交至 `POST /keys/me/reset-protection/signing-payload`，用密钥文件
签名返回的摘要，再把相同字段与签名提交至 `POST /keys/me/reset-protection`。该摘要带有独立的
域标签（`FYP-KEY-PROTECTION-RESET`），并覆盖两个信封的全部字段。两行在同一事务中更新；密钥对、
key id、profile id 与 bundle id 均不变。持有多把密钥的账户返回 `409
key_protection_reset_unavailable`，因为同一个 AMK 封装着所有私钥包，单个密钥文件无法重新封装
其余私钥包。审计动作为 `KEY_PROTECTION_RESET_WITH_PRIVATE_KEY`。

私钥包、包装 AMK、nonce、tag、盐和密文字段使用规范 Base64。请求 Schema 对 KDF、AEAD、
密钥长度及信封版本使用封闭枚举或范围，并拒绝未知字段。

添加后继密钥是另一个两次调用的客户端流程。客户端先提交未签名的 addition 字段（包含当前密钥/保护配置
UUID 及预期 profile revision），取得确定性的 32-byte 授权 payload；再使用当前私钥在本地
以 RSA-PSS-SHA256 签名，并把相同字段连同签名提交至 `POST /keys/add`。服务器使用最新当前
客户端公钥验证签名，然后原子保存后继公钥及其客户端加密私钥包。旧密钥和其文件包装继续保留，
因此仍可取得历史 bundle。注册与后继密钥的长度必须匹配配置的 `USER_RSA_KEY_SIZE`（默认
3072）。

## 文件 API

| 方法 | 端点 | 认证 | 说明 |
|---|---|---|---|
| POST | `/files/upload` | Bearer | 保存客户端加密密文及带版本密码学信封 |
| GET | `/files` | Bearer | 分页列出同时具备活跃授权和用户包装的文件 |
| GET | `/files/{file_id}` | Bearer | 返回已授权元数据和调用者专属包装 DEK |
| POST | `/files/{file_id}/download` | Bearer | 校验并流式返回存储密文，不在服务端解密 |
| POST | `/files/{file_id}/delete` | Bearer 所有者 | 软删除文件、撤销访问/包装并删除对象 |
| POST | `/files/{file_id}/integrity-check` | Bearer | 重新计算并记录密文存储完整性 |
| POST | `/files/{file_id}/ciphertext-preview` | Bearer，需下载权限 | 以十六进制返回存储密文的固定 128 字节样本，以及精确大小与已记录的 SHA-256。不做校验（不计算完整哈希），也从不解密；以 `FILE_CIPHERTEXT_PREVIEWED` 记入审计，它不算下载 |
| GET | `/files/folders` | Bearer | 列出调用者的文件夹 |
| POST | `/files/folders` | Bearer | 新建文件夹 |
| POST | `/files/folders/{folder_id}/rename` | Bearer，所有者 | 重命名文件夹 |
| POST | `/files/folders/{folder_id}/delete` | Bearer，所有者 | 删除文件夹；其中文件变为“无文件夹”，不删除任何文件 |
| POST | `/files/{file_id}/move` | Bearer + 文件访问权 | 把文件放进调用者自己的文件夹（所有者的归类记在文件上，接收者的记在自己的授权上） |

上传使用 `multipart/form-data`：

- `file`：按 `metadata.encryption_algorithm` 所指套件生成的密文（`AES-128-GCM`、`AES-192-GCM`、
  `AES-256-GCM`（默认）、`AES-256-GCM-SIV`、`ChaCha20-Poly1305` 或 `XChaCha20-Poly1305`）。
  16-byte tag 单独传输，因此密文字节数必须等于声明明文大小。nonce 为 12 字节，
  XChaCha20-Poly1305 为 24 字节。
- `metadata`：JSON 字符串，包含文件 UUID、明文文件名/大小/MIME、信封/AAD 版本、Base64
  nonce/tag、所有者密钥 UUID 及 RSA-OAEP-SHA256 包装 DEK、恢复密钥 UUID 及恢复包装 DEK，
  以及可选的 Base64 加密 manifest。

当前强制要求活跃恢复密钥及匹配恢复包装。服务器从不接收文件明文或私钥。
`GET /files/{file_id}` 提供已授权客户端所需的解密信封；下载以 no-store 标头流式返回
`application/octet-stream` 密文。

若上传会超过账户存储配额（2 GiB）、滚动 24 小时上传额度（5 GiB），或使磁盘剩余空间低于下限，会被拒绝并给出明确提示。

文件列表分页参数为 `page` 和 `page_size`（`1..100`）。未经授权与不存在的文件资源有意采用
不可区分响应。

## 共享 API

| 方法 | 端点 | 认证 | 说明 |
|---|---|---|---|
| POST | `/files/{file_id}/share` | Bearer + SHARE | 创建/重新激活经过授权且能力衰减的目标授权及客户端准备的 DEK 包装 |
| GET | `/files/{file_id}/shared-users` | Bearer + SHARE | 列出活跃被授权用户及其能力 |
| POST | `/files/{file_id}/revoke` | Bearer + REVOKE | 撤销非所有者用户的授权及活跃包装 |

共享请求包含 `target_user_id`、`target_key_id`、由目标公钥包装的 DEK、`can_download` 和
`can_share`。客户端在本地进行解包/重包装。服务器校验目标与密钥关联及 RSA 密文长度，但从不
接收私钥或明文 DEK。委托能力必须衰减：只有行为者自身授权具备对应能力时，请求中的能力才可
设为 `true`。规范所有者授权不可变。已有非所有者授权只能由具备 `can_manage` 的行为者，或该
授权当前记录的 `granted_by` 行为者更新/重新激活；其他委托分享者不能覆盖它。撤销无法删除
接收者已经复制的数据。

## 审计 API

| 方法 | 端点 | 认证 | 说明 |
|---|---|---|---|
| GET | `/audit-logs` | Bearer | 返回范围受限、已脱敏的日志页；ADMIN 可看管理范围。可选筛选参数 `action`、`result`、`from`、`to`、`q` 只会在调用者自己的范围内收窄 |
| GET | `/audit-logs/file/{file_id}` | Bearer + 文件访问 | 返回一个文件的范围化日志 |
| POST | `/audit-logs/verify-chain` | ADMIN | 重新计算完整链并验证单例链头 |

列表使用 `limit`（`1..100`）与 `offset`；返回的 metadata 经过白名单过滤。链验证逻辑上只读，
但依照仓库应用方法策略，有意使用 `POST` 作为安全命令。

`GET /audit-logs` 还接受以下可选参数：`action`（单个事件类型，和 API 写入的名字完全一致，例如
`FILE_SHARED`；其它值返回 422）、`result`（`SUCCESS` 或 `FAIL`）、`from` 和 `to`（ISO 8601 UTC
时间，对 `created_at` 做闭区间筛选，`from` 不能晚于 `to`）以及 `q`（最多 100 个字符的关键词，
不区分大小写地匹配描述和该条记录所涉及文件的文件名；`%` 和 `_` 按字面匹配）。筛选只会收窄：
可见范围规则（自己做的操作、针对自己的操作、自己拥有的文件上的所有操作）先生效，筛选条件叠加在
它之上，所以同一个调用者筛选后的页面永远是未筛选页面的子集。响应仍然带 `limit`、`offset` 和
`has_more`；用 `offset + logs.length` 请求下一页。

## 恢复 API

| 方法 | 端点 | 认证 | 说明 |
|---|---|---|---|
| GET | `/recovery/public-key` | Bearer | 返回新上传使用的活跃恢复公钥 |
| POST | `/recovery/public-key/register` | ADMIN | 登记/轮换由离线流程保管的恢复公钥 |
| POST | `/recovery/public-key/{key_id}/revoke` | ADMIN | 撤销恢复公钥的新用途 |
| POST | `/recovery/request` | Bearer | 在可下载授权及用户包装仍实时有效时创建限时请求 |
| POST | `/recovery/{request_id}/approve` | ADMIN 或 RECOVERY_OFFICER | 批准非本人请求 |
| POST | `/recovery/{request_id}/reject` | ADMIN 或 RECOVERY_OFFICER | 附理由拒绝非本人请求 |
| POST | `/recovery/{request_id}/cancel` | 请求所有者 | 取消自己的待审或已批准请求 |
| GET | `/recovery/{request_id}/execution-package` | ADMIN 或 RECOVERY_OFFICER | 返回隔离离线解包/重包装所需公开数据 |
| POST | `/recovery/{request_id}/execute` | ADMIN 或 RECOVERY_OFFICER | 保存离线生成、由目标密钥包装的 DEK |
| GET | `/recovery/requests` | Bearer | 分页列出自己的请求；复核角色可列出全部 |

恢复端点不接收私钥或 passphrase。执行 package 包含恢复包装 DEK 和公钥身份；离线/HSM 流程
解开 DEK，只返回由请求人公钥包装的 DEK。创建请求、每次读取 execution package 及执行均要求
请求人仍具备 `ACTIVE` 且 `can_download` 的授权，以及由活跃用户密钥支持的 `ACTIVE` 用户包装；
规范所有者也适用同一规则。执行会在改变任何包装前锁定并重新校验该 entitlement，再校验 UUID
和 RSA 密文结构，并有条件地将请求转为 `EXECUTED`。它绝不创建、重新激活、提权或以其他方式
修复已撤销/降权的授权。撤销前已取得并缓存的 package 无法追回，但后续 package 读取及服务端
执行都会默认拒绝。恢复不会重置加密 passphrase，也不会解密账户私钥包。

## 管理 API

| 方法 | 端点 | 认证 | 说明 |
|---|---|---|---|
| GET | `/admin/users` | ADMIN | 分页列出用户记录；可选 `status` = `ACTIVE`、`DISABLED`、`DELETED`，或 `CURRENT`（所有未删除的） |
| GET | `/admin/files` | ADMIN | 分页列出文件元数据记录；可选 `status` = `ACTIVE`、`CORRUPTED`、`DELETED`，或 `CURRENT` |
| GET | `/admin/stats` | ADMIN | 仅含数字的平台汇总：按状态统计的用户、按状态与算法统计的文件、已存储字节数、有效分享数、24 小时内的完整性检查与失败数、待处理恢复请求、审计总数，以及最近五条失败事件（仅含动作、时间、行为者） |
| POST | `/admin/users/{user_id}/disable` | ADMIN | 软禁用账户并撤销活跃会话。不能用于自己的账户（`409`）；如果停用后不再有在用的管理员，返回 `409 last_admin` |
| POST | `/admin/users/{user_id}/enable` | ADMIN | 重新启用已禁用账户 |
| GET | `/admin/users/{user_id}` | ADMIN | 单个账户：邮箱及是否验证、角色、状态、创建时间、最近登录、密码修改时间，以及只含数字的统计（文件数、占用字节、分享出去和收到的数量、在线会话数）。不返回任何密码、哈希或密钥 |
| POST | `/admin/users/{user_id}/reset-password` | ADMIN | 设置一个新的随机登录密码，只在这次响应里返回一次（`no-store`），数据库只存哈希。让该账户在所有设备上退出登录，给账户打上 `must_change_password` 标记直到本人设置自己的密码，审计记录 `ADMIN_PASSWORD_RESET`（不含密码），并发邮件通知本人。不能用于自己的账户或其他管理员。加密口令和文件不受影响 |
| GET | `/admin/integrity` | ADMIN | Integrity 标签页：最近一次巡检结果与损坏文件 |
| POST | `/admin/integrity/scan` | ADMIN | 立即运行一次完整性巡检 |
| GET | `/admin/agent/report` | ADMIN | 安全 Agent 的排序结果（只读、仅元数据、基于规则） |

管理列表使用 `limit`（`1..100`）及 `offset`。状态变更是条件式且有审计；审计链引用的身份不做
硬删除。

## 契约规则

- 路由声明严格请求/响应模型；ORM 对象不跨越 API 边界。
- 公开资源使用 UUID；自增数据库 ID 只供内部使用。
- 集合端点具有稳定排序和有界分页。
- 可重试的状态变更按场景使用 UUID 唯一性、乐观 revision、条件状态迁移或幂等终态处理。
- 认证与资源失败避免暴露不可访问的账户、文件、会话或密钥是否存在。
- 密文及包装密钥按设计需要传输；明文私钥、AMK、KEK、DEK、passphrase、令牌哈希、存储对象
  key 及文件系统路径不得传输。
