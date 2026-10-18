# 安全文件加密与共享平台
[English](DEVELOPER_GUIDE.md) | [简体中文](DEVELOPER_GUIDE.zh-CN.md)

安全文件加密与共享平台的毕业设计（FYP）架构。

## 预发布环境

当前版本运行在 **https://secureview.tech**。线上 API 可通过
[Swagger UI](https://secureview.tech/docs) 查看和演示，机器可读契约位于
[OpenAPI JSON](https://secureview.tech/openapi.json)。

对外书写与分享链接时请**一律带 `https://` 前缀**。`.tech` 不在浏览器 HSTS 预加载名单中，
直接输入裸域名的访客会先经过一次 `http://` 才被跳转，部分应用内置浏览器（含微信）会在这一跳
期间提示不安全。完成一次 HTTPS 访问后，`Strict-Transport-Security` 头会将协议固定一年。

HTTPS 不只关系到地址栏那把锁，而是产品能否运行的前提：浏览器只在安全上下文中暴露
`crypto.subtle`，而注册流程正是用它生成账户 RSA 密钥对并派生 Argon2id 密钥加密密钥。

## 项目目标

本系统允许用户上传文件、在服务器上以加密形式存储文件、与其他授权用户共享文件、撤销后续访问权限、验证文件完整性，并将安全敏感操作记录到可防篡改的审计日志中。

本项目重点关注：

- 客户端文件加密，六种认证加密算法：AES-GCM（128/192/256 位密钥）、AES-256-GCM-SIV、ChaCha20-Poly1305 与 XChaCha20-Poly1305
- 基于 RSA 的文件密钥封装
- 受控共享与撤销
- 基于角色和文件级别的访问控制
- SHA-256 完整性验证
- 可防篡改的审计日志哈希链
- 针对例外访问场景的恢复治理

## 当前状态

后端身份认证、客户端包装密钥托管、加密文件、共享、审计查询、由离线流程治理的恢复及管理／RBAC
API 均已实现。服务器只持久化公钥、加密私钥包、密文和已包装的文件密钥；用户的加密
passphrase、KEK、AMK、明文私钥、文件 DEK 和文件明文都不得出现在 API 请求或数据库记录中。
注册及文件／密钥流程详见 [SECURITY_FLOWS.zh-CN.md](SECURITY_FLOWS.zh-CN.md)；这些流程能防御和不能防御
什么、以及尚未解决的发现，见自评性质的 [THREAT_MODEL.zh-CN.md](THREAT_MODEL.zh-CN.md)。

浏览器 MVP 已端到端可运行：邮箱验证码注册与重置登录密码、客户端账户密钥登记、使用
passphrase 或私钥文件解锁、使用私钥文件重置 passphrase、每次解密下载和每次分享都要输入 passphrase、上传前认证加密、下载后本地解密、文件名搜索、将
文件密钥重新包装给接收者的共享、撤销、逐文件访问历史、静默刷新会话、登出及注销账户。
每个文件可在任何浏览器里选择 AES-128/192/256-GCM、AES-256-GCM-SIV、ChaCha20-Poly1305 或 XChaCha20-Poly1305（WebCrypto 没有 AES-192-GCM 时回退到 `@noble/ciphers`，字节完全相同），默认仍为 AES-256-GCM；旧有硬编码
凭据和演示 token 后备均已移除。

“Sealed”改版（2026-10-05，#176–#182、#188–#195）之后全站统一风格：自托管 Geist 字体，绿色只表示“已验证/已封装”，
红色只表示“被改动/危险”，暗色模式下主按钮接近白色，页头居中、内容宽度统一，所有登录后的页面都有侧边栏。公开产品页与
登录后工作台并列：`/` 开头是深色首屏，把样例文件真实的前几个字节和服务器收到的字节并排展示，下面是所用算法的证明条、
“三步”（离开前封装、只给核对过的公钥、被改动就拒绝）、五个编号对比问题和图文指南；`/how-it-works` 是动画讲解和四步快速上手；`/education` 提供
算法教学、演练场与知识库；`/help` 提供动画讲解、三段从真实产品录制的演示视频和图文指南；`/team`（导航标签为
**Contact us**）有反馈表单（会打开访客的邮件客户端）以及导师和团队介绍。不存在的路径显示 404 页面。`/benchmark/argon2` 不在任何菜单中出现，用于在访问设备上测量解锁时密钥派生的
耗时，是威胁模型中 passphrase 分析的依据。语言切换在宽屏时位于页头栏，手机上在页头菜单里，设置页也提供同样的选择。登录用户可通过页头头像菜单切换主题，并进入
`/profile` 与 `/settings`；未登录访客通过语言切换右边的设置图标打开主题控件。当前导航标签使用主题主色高亮，便于确认所在页。
`/profile` 可上传或移除经验证的 PNG/JPEG 头像（无图时回退首字母）。

每个页面右下角都有 **Help assistant** 按钮（#146）。它回答操作类、原理类以及“为什么不用 Google Drive /
WhatsApp / 邮件”类问题，给出简短摘要、步骤和产品内链接；问题在浏览器内与人工整理的答案以及 Education、讲解动画、
图文引导内容匹配。不使用大语言模型、匹配时不发网络请求，问题不会被发送或记录。登录后，它还能回答关于自己账户的问题
（#148）：谁能打开某个文件、别人分享了什么给你、最近有没有失败的登录。这些回答只读取 My Files 和 Activity Log
本来就能看到的内容，不做任何修改。见
[docs/HELP_ASSISTANT.zh-CN.md](HELP_ASSISTANT.zh-CN.md)。

界面可以在 **English 和简体中文** 之间切换（#74），入口在页头（#166）和设置页；选择按设备记住。文件名、用户名
以及用户自己写的内容一律不翻译。中文在构建阶段由智谱 `glm-4-flash` 起草，并按固定的安全术语表校验；浏览器从不
调用翻译服务。见 [docs/I18N.zh-CN.md](I18N.zh-CN.md)。

登录后的工作台（`/dashboard`）先显示新手清单（#162）。注册分两步：先建账户，再单独设置加密 passphrase，完成后直接登录
（#161）。我的文件中每行带文字显示 **Download**、**Share** 和 **Delete**，其余操作收在 **More** 里（#159）；非模态详情面板
显示加密算法、两种大小、所有者和谁能打开该文件，Access history 位于 Delete 旁（#191、#193）。分享之前，对话框会写明
接收者，并显示文件将要封装给的那把公钥的指纹（在浏览器中计算）；接收者在设置页能看到同一指纹，之后指纹若变化浏览器会
警告（#160）。首页用五个编号问题、每题两种回答来对比 SecureView 和普通网盘；页脚在 Product、Learn 链接旁列出项目信息（莫纳什大学、FIT3161 / FIT3162、MCS21 团队、指导老师）。标题能放一行就放一行，两句话的简介只在句与句之间换行（`SentenceLines`）；`frontend/scripts/text-audit.mjs` 会在每个页面上检查这一点。详见
[changelog/CHANGELOG.md](../changelog/CHANGELOG.md#ui-layout-and-navigation-consistency-junyan9--界面排版与导航一致性junyan9)。

首页图文指南提供七张带定位标记的真实界面截图（中英文各一套），涵盖选文件、选加密算法、加密、分享、解锁和接收者下载。默认自动播放
（每步 8 秒，带进度条），用户可暂停；也可放大图片或在手机上滑动换步；已完成步骤显示勾选。图片使用虚构数据，并提供手机
裁切图；已在 2026-10-05 改版后重新截取（#192），2026-10-10 又按上传页带等级的算法列表（#215）重拍一次。

剩余工作属于生产级加固，而非基础演示尚未闭环：后继密钥的界面（API 已有）、两项未处理的 *建议* 级安全发现（F-02、F-03），以及独立安全评审。运行在自建 runner 上的强制 CI 与
CI 门禁部署、MySQL 8.4 发布门禁、加密异地备份、洁净主机恢复证据、定时对账、每日完整性巡检、外部审计检查点、监控告警、
安全 Agent，以及同 VPS 的隔离篡改演练现均已到位。优先级摘要见
[TODO.zh-CN.md](BACKLOG.zh-CN.md)，带验收标准的可执行工作统一放在
[GitHub Issues](https://github.com/jsonrar/fyp-secure-file-platform/issues) 与团队共用的
[SecureView Development Board](https://github.com/users/Waldo0926/projects/1)。

文件管理页面还允许所有者和具有下载权限的接收者在保险库锁定时、无需 passphrase 或私钥，把已校验的原始密文保存为
`<filename>.ciphertext`（密文预览里的 **Download encrypted file**）。**Encrypted preview** 会显示服务器真正存储的内容：精确大小、已记录的 SHA-256，以及密文前 128 字节的十六进制转储，自己的文件和别人分享给你的文件都适用。
两个大小为什么一样、以及如何现场演示，见 [docs/ENCRYPTION_EVIDENCE.zh-CN.md](ENCRYPTION_EVIDENCE.zh-CN.md)。

上传文件时，上传页面会展示这个文件的真实步骤（在浏览器中读取、加密并自检、用 RSA-OAEP 包装文件密钥、上传密文并显示真实进度），
每一步标出实测耗时，最后把文件的前 16 个字节和服务器收到的前 16 个字节并排显示。这张回执会一直显示，直到用它的关闭按钮收起（#200）。加密只要几十毫秒，以前上传看起来就像根本没加密；
现在的展示没有为了"看起来在忙"而故意放慢。

**实测容量（修复后，2026-10-09，版本 `ac5e2b0`）：** 从家里宽带的笔记本经公网地址 `https://secureview.tech`
（HTTPS 和 nginx，限流开着）压测。共 18,256 次操作，7,444 次下载在客户端解密并做了 SHA-256 校验，完整性失败 0 次，
服务器 5xx 为 0。50 个并发用户以内所有请求都成功（50 人时上传 p95 3.3 s，下载 p95 9.5 s）。100 个用户时服务器仍然没有出错，
被拒绝的只有 nginx"每个地址最多 50 个上传同时进行"返回的 429，因为所有负载都来自同一个地址。pdf、png、jpg、mp4、zip、exe
从 1 MiB 到 500 MiB 都能逐字节一致地往返，包括分享。吞吐稳定在每个方向约 8 到 9 MiB/s，而服务器 CPU 平均只有 4.5%，
所以瓶颈是 VPS 的 100 Mbit/s 网口，不是程序。引用数字前请先读测试条件：
[docs/performance/REPORT-2026-10-09.zh-CN.md](performance/REPORT-2026-10-09.zh-CN.md) 和
[docs/PERFORMANCE_TESTING.zh-CN.md](PERFORMANCE_TESTING.zh-CN.md) 末尾的结论。修复前的对照（100 个用户时 65% 到 78%
的上传返回 HTTP 500）见 [REPORT-2026-10-03.zh-CN.md](performance/REPORT-2026-10-03.zh-CN.md)（#140，由 #163 修复）。所有测试数量、覆盖率和压测结果都汇总在
[docs/TESTING_SUMMARY.zh-CN.md](TESTING_SUMMARY.zh-CN.md)。

**上传限额（威胁模型 F-09）：** 每个账户最多存储 2 GiB、24 小时内最多上传 5 GiB；存储磁盘剩余空间低于底线时停止接受上传；
nginx 限制每个地址同时最多 50 个上传（整个会场的网络到服务器只是一个地址）；安全 Agent 会报告上传突增。服务器始终只保存密文，无法扫描恶意软件，所以接收者在保存
他人分享的程序或可能带宏的文件之前会看到警告。详见 [docs/THREAT_MODEL.zh-CN.md](THREAT_MODEL.zh-CN.md) 第 11.3 节。

**第三方扫描（2026-10-04）：** 用 OWASP ZAP 对 staging 做基线扫描，没有高风险问题（0 FAIL、8 WARN、59 PASS）；它指出的静态代码包
缺少安全响应头的问题已在 nginx 里修复。`pip-audit` 和 `npm audit` 在生产依赖里没有发现问题；仅测试用的 HTTP 客户端有 6 条公告，
已通过升级修复。报告和原始输出见 [docs/security/scans-2026-10-04/](security/scans-2026-10-04/README.zh-CN.md)。2026-10-12 对版本 `1eb56d8` 又扫了一次：0 FAIL、5 WARN、62 PASS，五条和修复后一样，都是已接受或仅供参考的提示（[docs/security/scans-2026-10-12/](security/scans-2026-10-12/README.zh-CN.md)）。

Final Presentation 要讲什么、每一点的证据在哪，见
[docs/presentation/TALKING_POINTS.zh-CN.md](presentation/TALKING_POINTS.zh-CN.md)；目前还有哪些不足、按优先级该怎么改，见
[docs/presentation/REFLECTION.zh-CN.md](presentation/REFLECTION.zh-CN.md)。现场篡改演示（在 staging 上改掉存储的密文，接收方下载时被拒绝）
的步骤见 [docs/presentation/TAMPER_DEMO.zh-CN.md](presentation/TAMPER_DEMO.zh-CN.md)；完整的 4 分钟演示脚本见
[docs/presentation/DEMO_SCRIPT.zh-CN.md](presentation/DEMO_SCRIPT.zh-CN.md)。

## 网站如何使用

### 普通用户流程

1. **注册**：`/register` 分两步（#161）：先填账户信息（用户名、邮箱、邮件验证码和登录密码），再单独设置加密
   passphrase，并说明它为什么存在。常见、有规律或由用户名构成的口令会被拒绝（#205）。注册完成后直接登录。浏览器本地生成 RSA 密钥对、AMK 和加密私钥包；注册完成时应立即把一次性提供的
   `.pem` 私钥文件移出下载目录并安全保存。登录密码用于认证，加密 passphrase 用于解锁文件，
   两者不能互相替代。
2. **登录与工作台**：在 `/login` 登录后进入 `/dashboard`。Access token 即将失效时，前端会
   使用一次性轮换的 refresh token 自动续期；无法续期时才清除会话并返回登录页。
3. **加密上传**：在 `/upload` 选择文件和算法。浏览器先生成每文件 DEK，再在本地执行认证加密，
   用账户 RSA 公钥包装 DEK；服务器收到的是密文、公开元数据和包装后的密钥，不会收到明文文件
   或明文 DEK。
4. **文件管理**：在 `/files` 搜索或翻页查看“我的文件”和“分享给我的文件”。所有者可以创建、
   重命名和删除文件夹，把文件移入不同文件夹或移回“未分类”；删除文件夹不会删除其中的加密文件。点击某一行（或它的 Details 按钮）会在右侧打开详情栏，显示算法、精确大小、密文 SHA-256、谁能打开和全部操作；点另一行即切换。下载时先校验服务端
   密文 SHA-256，再由浏览器解包 DEK、验证 AEAD tag 并保存明文；认证失败时不会保存残缺文件。
   密文预览中的 **Download encrypted file** 则无需解锁，直接保存密文，但仍须登录且具有下载权限。`.ciphertext`
   只包含存储的密文字节，不包含单独存储的 envelope、nonce、tag 或包装后的密钥，因此不是可独立
   离线解密的备份。删除自己的文件会先弹出确认，说明分享会被撤销且不可撤销。
5. **分享与撤销**：所有者在需要时先解锁，再输入现有用户的准确用户名或邮箱地址。对话框随后写明接收者，并显示在浏览器中计算出的接收者公钥指纹，所有者确认
   （**Confirm and share**）；接收者可在设置页看到同一指纹。浏览器使用确认过的公钥重新包装同一个 DEK，
   接收者随后用自己的 passphrase 解密；服务器始终看不到 DEK。撤销会先确认，再阻止今后的服务器介导访问，
   无法收回接收者已经下载并解密的副本。
6. **审计与账户操作**：`/audit-logs` 展示登录、上传、下载、分享、撤销等记录。所有者可以查看
   自己文件上的活动，接收者只能查看与自己有关的记录，ADMIN 可以验证完整哈希链。页面每次加载
   100 条记录并提供"加载更多"按钮，筛选栏可以按事件类型、结果、日期范围和关键词（匹配描述和
   文件名）收窄，且始终限制在调用者本来就能看到的范围内。忘记登录密码
   可通过邮箱验证码重置；忘记加密 passphrase 时只能使用注册时另存的 `.pem`：它可以解锁当前会话，也可以在 `/settings`
   中设置新的 passphrase，而不改变账户密钥或任何文件。还记得 passphrase 时，可在 `/settings` 凭当前 passphrase 修改它（#201）。
   账户身份与偏好在页头头像菜单中：`/profile` 显示当前账户、可上传或移除头像，并可进入注销确认；
   `/settings` 提供主题、语言、账户密钥指纹、修改登录密码、凭当前 passphrase 修改 passphrase、用私钥文件重设 passphrase，以及同一套注销流程（登录密码 +
   输入 `DELETE`）。
7. **未登录也可学习与求助**：`/education` 包含 Algorithm Explorer、Playground 与 Knowledge
   Base；首页图文指南是最快上手路径，`/how-it-works` 是动画讲解，`/help` 另有三段从真实产品录制的演示视频；每个页面右下角
   的圆形按钮会打开问答助手。`/team` 导航标签为 **Contact us**，上方为反馈表单（会打开访客的邮件客户端），下方为导师和
   团队介绍。页头以主题色高亮当前标签。

### 角色与管理流程

- `USER` 使用上传、下载、分享、撤销和个人审计功能。
- `ADMIN` 可在 `/admin` 管理用户/文件、验证审计链、登记恢复公钥并复核恢复请求。标签页还包括仅计数的概览、
  Integrity（每日巡检结果、损坏文件、立即扫描）、安全 Agent 的排序结果，以及单个账户详情（启用/禁用、签发临时登录密码，#197；
  不能作用于自己或其他管理员）。
- `RECOVERY_OFFICER` 可在 `/admin` 参与恢复复核，但不能批准自己创建的请求。
- 任意已登录用户可在 My Files 发起恢复请求，并在 `/admin` 跟踪或取消；执行已批准请求仍需
  离线用恢复私钥重新封装，浏览器 UI 从不接受该私钥。

## HTTP 方法策略

应用 API 只使用 `GET` 和 `POST`。`GET` 仅用于只读操作；新增、更新、删除、撤销及其他所有
会改变状态的动作均使用 `POST`。动作端点应在适当时采用显式路径，例如
`POST /api/v1/files/{file_id}/delete` 和
`POST /api/v1/auth/sessions/{session_id}/revoke`。应用路由和客户端不得使用 `PUT`、`PATCH`
或 `DELETE`，CORS 也只允许 `GET` 和 `POST` 方法。
浏览器或服务器所需的自动协议层处理（例如 CORS 预检）属于基础设施行为，不属于应用 API 操作。

## 推荐技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite |
| 后端 | FastAPI |
| 数据库 | MySQL 8.4 |
| 文件存储 | 用于 FYP 演示的本地加密文件存储 |
| 文件加密 | AES-128/192/256-GCM、AES-256-GCM-SIV、ChaCha20-Poly1305、XChaCha20-Poly1305（默认 AES-256-GCM） |
| 密钥封装 | 使用 SHA-256 的 RSA-OAEP |
| 密码哈希 | Argon2id（`pwdlib`） |

## FastAPI 后端概览

FastAPI 是本项目的 HTTP/API 框架，不负责浏览器端文件解密。它负责校验请求、认证和授权、组织
业务用例、管理数据库事务、访问密文存储，并生成 OpenAPI 契约。应用入口是
`backend/app/main.py`，应用工厂在启动时装配配置、SQLAlchemy Engine/Session 工厂、密码哈希
管理器、中间件、异常处理器和 `/api/v1` 路由；关闭时释放数据库连接池。

一次典型请求按以下方向流动：

```text
浏览器 Axios 请求
  -> FastAPI 中间件（请求体上限、CORS）
  -> Router（路径、Pydantic 请求/响应、Depends）
  -> 身份/RBAC 依赖（Bearer token -> ActorContext）
  -> Service（用例、事务、审计、存储补偿）
  -> Repository / SQLAlchemy Session + 加密对象存储
  -> 统一 JSON 响应
```

各层职责如下：

- `api/v1/routers/`：定义 Auth、Keys、Files、Sharing、Audit、Recovery 和 Admin 端点；只处理
  HTTP 输入输出，不直接写 SQL 或操作文件系统。
- `api/dependencies.py`：为每个请求创建数据库 Session，解析 Bearer token，并提供 ADMIN／恢复
  复核角色检查和各类 Service。
- `schemas/`：使用 Pydantic 严格校验传输 DTO，同时驱动 OpenAPI/Swagger 文档。
- `services/`：拥有一个用例的事务边界，协调 repository、密文存储、领域规则和审计追加。
- `repositories/` 与 `models/`：分别封装数据库操作和 SQLAlchemy 持久化模型；repository 可以
  查询、添加和 `flush`，但不自行 `commit`。
- `core/`：集中管理环境配置、数据库连接和 Argon2id/Bearer 等安全基础能力。

业务 API 统一挂载在 `/api/v1`。公开端点主要是验证码、注册、登录、密码重置和 refresh；其余
端点通过 `Depends` 要求有效 Bearer token，敏感操作再执行角色或资源级授权。成功响应使用
`success/status/message/data/code` 信封；领域异常由统一处理器映射为稳定 HTTP 响应。
`/health/live` 只检查进程是否存活，`/health/ready` 还会执行数据库查询并要求数据库保存的
Schema revision 精确等于 `0011_must_change_password`。本地默认提供 `/docs`、`/redoc` 和
`/openapi.json`，部署环境可通过 `APP_DOCS_ENABLED` 整体卸载这些路由。

## 仓库结构

```text
fyp-secure-file-platform/
|-- backend/
|   |-- app/                 api/v1/routers, core, domain, models, repositories, schemas, services
|   |-- migrations/          Alembic revisions 0001-0011
|   |-- scripts/             ops and drills: reconcile, integrity sweep, restore_file, audit
|   |                        checkpoint, observe, security agent, backups, tamper demo, seeding
|   |-- tests/               unit, api, integration (MySQL 8.4), e2e (live stack)
|   `-- requirements.txt
|-- database/mysql/          01-provision, 02-schema, 03-verify, 04-backup-account (.sql)
|-- deployment/
|   |-- server/              mcs21-deploy, mcs21-auto-deploy, alert/backup scripts, systemd
|   |                        units and timers, nginx and fail2ban config
|   `-- ci-runner/           the self-hosted GitHub Actions runners on the VPS (not published)
|-- frontend/
|   |-- src/                 pages, components, api, crypto, stores, i18n, locales
|   |-- browser-tests/       Playwright specs (golden path, tamper view, phone widths, ...)
|   |-- scripts/             layout/text audits, walkthrough and video recording, i18n tools
|   `-- public/              walkthrough screenshots and Help videos
|-- loadtest/                browser-equivalent load-test client and server sampler
|-- security-lab/            isolated tamper-drill attacker lab (CI job `tamper-drill`)
|-- changelog/
|   |-- CHANGELOG.md
|   |-- README.md
|   `-- work-packages/       read-only historical archives
|-- docs/
|   |-- PROJECT_SCOPE, PROPOSAL_TRACEABILITY, ARCHITECTURE, API_DESIGN, DATABASE_SCHEMA
|   |-- SECURITY_FLOWS, THREAT_MODEL, ENCRYPTION_EVIDENCE, SECURITY_AGENT, HELP_ASSISTANT, I18N
|   |-- DEPLOYMENT, AUTOMATIC_DEPLOYMENT, BACKUP_AND_RECOVERY, RECONCILIATION_RUNBOOK,
|   |   OBSERVABILITY_AND_INCIDENT_RESPONSE, E2E_TESTING, PERFORMANCE_TESTING
|   |                        (each as X.md and X.zh-CN.md)
|   |-- crypto/              FILE_ENVELOPE and test_vectors.json
|   |-- performance/         load-test reports, charts and raw data
|   |-- security/            third-party scan reports
|   |-- benchmarks/          Argon2id measurements
|   `-- presentation/        TALKING_POINTS, REFLECTION, DEMO_SCRIPT, TAMPER_DEMO, media/
|-- recovery_keys/
|-- AGENTS.md, AGENTS.zh-CN.md
|-- README.md, README.zh-CN.md
|-- TODO.md, TODO.zh-CN.md
|-- .env.example
|-- .gitignore
`-- docker-compose.yml
```

## 更改日志：记录什么、怎样维护

[`changelog/CHANGELOG.md`](../changelog/CHANGELOG.md) 是团队唯一仍在维护的变更记录，统一记录
**产品发生了什么变化以及为什么重要**，包括端点、安全修复、契约、测试证据与部署行为。当前内容
位于 `[Unreleased] / [未发布]`，通常越靠上越新。

[`changelog/work-packages/`](../changelog/work-packages/) 仅作为早期密码学与测试工作包的只读
历史档案保留。不要再新增或续写个人/分轨日志；所有成员的新工作都写入共享 Changelog，并在当前
能力或剩余工作改变时同步 README 与 TODO。

现有 Changelog 的主要工作线包括：

1. **客户端密码学**：账户密钥登记、AES-GCM(-SIV)/(X)ChaCha20-Poly1305 文件信封、下载解密、`.pem`
   解锁、分享时 DEK 重包装及跨语言测试向量。
2. **认证和账户安全**：邮箱验证码、密码重置、Argon2id 策略、refresh 轮换、会话失效及账户注销。
3. **文件与共享体验**：分页/搜索、所有者与接收文件分区、完整性状态、分享通知、撤销和逐文件历史。
4. **审计与隐私**：哈希链、审计字段契约、可读标签、文件名解析，以及“只能看见自己相关活动或
   自己拥有文件的活动”的可见性规则。
5. **数据库和运维**：MySQL 最小权限 SQL、Schema revision、对账清理、HTTPS、nginx/fail2ban、
   自动部署、失败 SHA 隔离及备份/上线约束。
6. **界面与开发环境**：登录后导航与账户菜单、主题/品牌、Education / Help / Team 公开页、
   首页主视觉与功能滚动条，以及依赖锁定、typecheck 和测试基线。

新增记录前先阅读 [`changelog/README.md`](../changelog/README.md)：在对应主题下写英文与简体中文
成对条目，说明“为什么重要”，而不只是复述 diff。历史条目描述的是当时状态；若后续条目修复了
旧限制，应以更新的条目、当前 README 和代码为准。

## 团队工作流与唯一事实来源

- `changelog/CHANGELOG.md`：已经交付了什么，以及为什么重要。
- GitHub Issues：剩余可执行工作、负责人、讨论及验收标准。
- [SecureView Development Board](https://github.com/users/Waldo0926/projects/1)：使用五个团队
  视图分别展示当前 backlog、提案 WBS、里程碑、验收标准与 PR 证据，并按 Backlog、Ready、
  In progress、In review 与 Done 管理。历史上直接进入 `main` 的 CT 工作保留在追踪文档和
  历史档案中，不再设个人看板视图，也不会虚构追溯 PR。
- [`docs/PROPOSAL_TRACEABILITY.zh-CN.md`](PROPOSAL_TRACEABILITY.zh-CN.md)：从提案承诺到仓库及部署
  证据的带日期追踪表。
- `TODO.zh-CN.md`：链接到 Issues 的优先级摘要，不再维护第二套独立 backlog。
- `README.zh-CN.md`：面向用户的当前能力、设置步骤与部署入口。
- [`docs/presentation/TALKING_POINTS.zh-CN.md`](presentation/TALKING_POINTS.zh-CN.md) 与
  [`REFLECTION.zh-CN.md`](presentation/REFLECTION.zh-CN.md)：值得展示的内容及其证据，以及按优先级排列的不足。

每份 Markdown 文档都有英文和简体中文两个版本（`X.md`、`X.zh-CN.md`），一起修改。每个 Pull Request 都必须检查以上各处，更新受影响的记录；若不适用则说明 `N/A`。运行时改动不能
在 merge 时就算完成：`main` 部署后还必须记录线上 SHA，并验证健康检查和实际受影响页面。仓库的
Pull Request 模板已包含该清单。

## 本地设置

所有后端业务路由均已可用。存活检查、readiness 和 OpenAPI 也已启用；受保护路由要求
Bearer 身份认证，管理及恢复路由执行 RBAC。Readiness 会检查数据库连接及精确的
`0011_must_change_password` Schema revision。

`MAX_REQUEST_BODY_BYTES` 限制普通 JSON／form 请求体（默认 1 MiB，配置上限 8 MiB）。加密
multipart 上传另受 `MAX_UPLOAD_SIZE_BYTES + MAX_UPLOAD_REQUEST_OVERHEAD_BYTES` 独立上限
约束，因此提高普通请求体上限不会改变允许上传的密文大小。

### 后端

运行下方迁移命令前，请确认目标数据库为空，或已经包含一条 `alembic_version` 记录。目前检查过的本地旧数据库不满足该条件；如果该数据库仍然存在，请跳过常规升级，并遵循下方的接管警告。

```bash
docker compose up -d --wait mysql
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Compose 会在全新本地 volume 上创建数据库及开发账户，因此上述命令只适用于本地开发。
Alembic 在本项目中保留为开发／CI 的 Schema 编写与一致性检查工具；生产和预发布服务器
不得运行 Alembic。对于由历史 `docs/init.sql` 创建的本地数据库，不得直接升级或标记版本；
请遵循 [DATABASE_SCHEMA.zh-CN.md](DATABASE_SCHEMA.zh-CN.md) 中的说明。

### MySQL 部署

生产环境和预发布环境完全由 MySQL root／管理员按顺序执行三份经评审 SQL，不运行
Alembic，也不使用 Python 部署 runner 或 `fyp_migrator`：

```bash
# 数据库服务器仓库根目录；MySQL root 使用本机 socket 认证
sudo mysql < database/mysql/01-provision.sql
sudo mysql < database/mysql/02-schema.sql
sudo mysql < database/mysql/03-verify.sql
```

部署时应把唯一一次生成的 `fyp_user` 密码直接写入 secret store。`02-schema.sql` 是只接受
空数据库的非幂等安装器：它创建 18 张表，对其中 15 张普通状态表授予 CRUD，
对 `audit_logs` 仅授予 `SELECT`／`INSERT`，并把 `audit_chain_heads` 的更新权限限制在
`last_log_id`、`current_hash` 和 `updated_at` 三列，使运行时账户无法修改
`schema_revision`；应用也无权访问 `alembic_version`。`03-verify.sql` 只读核验精确 Schema
和权限，并必须确认已停用的 `fyp_migrator` 身份不存在。只有全部结果通过评审后，应用才
通过标准 `DB_*` 配置以 `fyp_user` 启动。

三份 SQL 的账户 host 默认为 `localhost`。远程部署必须在仓库外制作三份受保护、经评审
副本，并一致替换其中每一个 `localhost` 账户 host 字面量。现有部署若遗留
`fyp_migrator`，须先确认其归属与用途，再显式撤权或删除。备份、串行化、失败恢复、
Compose 差异及未来非空数据库升级规则详见
[DEPLOYMENT.zh-CN.md](DEPLOYMENT.zh-CN.md)。

预发布 VPS 会在经过评审的 Pull Request 合并进 `main` 后自动部署对应 commit。服务器拉取
流程、队员操作命令、失败 SHA 隔离和凭据边界详见
[AUTOMATIC_DEPLOYMENT.zh-CN.md](AUTOMATIC_DEPLOYMENT.zh-CN.md)。

OpenAPI：本地为 <http://localhost:8000/docs>，公网预发布为
<https://secureview.tech/docs>。

在 `backend/` 目录中运行后端质量检查：

```bash
ruff format --check app tests migrations
ruff check app tests migrations
pytest
alembic check
pip-audit -r requirements.txt
```

其中 `alembic check` 只用于开发／CI 漂移检查，不是生产部署步骤。

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端：<http://localhost:5173>

## 持续集成

`.github/workflows/ci.yml` 会在每次 PR 及推送到 `main` 时运行：先跑一个很小的 `changes` Job，再跑五个测试 Job。
如果改动只包含 Markdown 文件，或只包含 `docs/` 下的文件（`docs/crypto/` 除外，测试会读取其中的测试向量），
五个测试 Job 会被跳过：私有仓库的免费 Actions 额度每月只有 2,000 分钟，而完整跑一次约耗 13 分钟。
推送到 `main` 时与 `deploy` 分支比较，而不是与上一次推送比较，所以即使代码那次 CI 被随后的纯文档推送取消，
它仍会被测试并推进部署（[详见](AUTOMATIC_DEPLOYMENT.zh-CN.md#ci-门禁)）。
自 2026-10-04 起，所有 Job 都在 VPS 上项目自建、并与线上环境隔离的 runner 上运行
（deployment/ci-runner/）；三台 runner 并行接任务，一次完整 CI 仍约 5 分钟。`backend` 与
`frontend` 按约定是必需检查：仓库为免费套餐下的私有仓库，无法使用 GitHub 分支保护，所以 CI 变红时除了评审人
之外没有任何机制阻止合并。但部署是有门禁的：staging 只部署 `deploy` 分支，而只有 `main` 上五个 Job 全部通过，
`promote` 才会移动它。推送前请在本地执行相同命令，避免失败在 CI 中才被发现：

```bash
# 后端（在 backend/ 下执行，对应 "backend" Job；分支覆盖率低于 78% 即失败）
uv venv --python /opt/homebrew/bin/python3.12 .venv   # 或任意 Python 3.12 解释器
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt
uv pip install --python .venv/bin/python pip-audit && .venv/bin/pip-audit -r requirements.txt
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest -m "not integration" --cov

# 前端（在 frontend/ 下执行，对应 "frontend" Job；阈值见 vite.config.ts）
npm ci
npm audit --audit-level=high
npm run test:coverage
npm run typecheck
npm run build
```

第三个 Job `mysql-gate` 会拉起一个经过 TLS 校验的一次性 MySQL 8.4 服务，从空数据库依次迁移到
`0011_must_change_password`，再执行 `alembic current` 与 `alembic check`，随后对其运行完整的后端测试
——单元测试加上全部 MySQL 集成测试，包括多连接并发与故障注入测试——只要有任何测试被跳过，或
分支覆盖率低于 82%，该 Job 就直接失败；接着运行授权边界、Schema 一致性、非空数据库拒绝安装、
中断后幂等恢复、并发迁移加锁与备份恢复等检查。开发此门禁本身时，可用
`backend/scripts/mysql_release_gate.sh` 在本地验证较复杂的场景。

第四个 Job `e2e-live` 会针对另一个一次性 MySQL 启动真实 API，并在不跳过任何测试的前提下运行
前端所有依赖真实后端的测试套件：邮箱验证码注册、登录/refresh/重放/登出、解锁、全部六种文件
算法（每种都上传、分享、由接收方解密、完整性检查并撤销）、审计可见性、角色拒绝以及注销账户；随后运行 Chromium 冒烟测试（Playwright），
在构建后的页面上点击走完同一条黄金路径，因此按钮接错处理函数也会让 CI 失败。每个 Job 都会把 JUnit 与覆盖率报告作为
构建产物上传，但前提是 `backend/scripts/check_report_hygiene.py` 确认其中不含密钥、令牌、非示例
邮箱地址或测试夹具明文。

第五个 Job `tamper-drill` 会在仅内部可达的 Docker 网络中构建默认停止的攻击容器。它只针对自己
的 MySQL 8.4 `_test` 数据库与密文卷，证明：修改字节后界面语义为 `MODIFIED`/`CORRUPTED` 且下载
被拒；对象缺失会被报告但不会永久污染状态；恢复对象后回到 `VALID`/`ACTIVE`。它也覆盖更强的攻击者：
若攻击者同时控制对象存储与数据库，就能替换数据库中的 SHA-256，但完整性检查还会与上传审计事件中锚定的摘要
比对，所以文件仍被判为 `MODIFIED`；浏览器的 AEAD 认证标签作为最后一道防线也会拒绝伪造密文。详见 [`security-lab/README.md`](../security-lab/README.md)。

两套数据库测试都可以在笔记本上针对任意一次性 MySQL 8.4 运行，数据库名须带 `_test` 段（切勿
使用共享的 `docker compose` 数据库）：

```bash
docker run -d --name my-test-mysql -e MYSQL_ROOT_PASSWORD=... -p 127.0.0.1:3310:3306 mysql:8.4
# 先创建 utf8mb4_unicode_ci 数据库，例如 fyp_local_test，然后：

# MySQL 集成、并发与故障注入测试（在 backend/ 下执行，需先完成迁移）
AUTH_TEST_DATABASE_URL='mysql+pymysql://USER:PASS@127.0.0.1:3310/fyp_local_test' \
  SECRET_KEY=local-test-secret-key-at-least-32-chars APP_ENV=test \
  .venv/bin/python -m pytest -m integration -rs

# 完整的端到端环境（在仓库根目录执行；自动迁移、创建账户、启动服务并在结束后清理）
DB_HOST=127.0.0.1 DB_PORT=3310 DB_USER=USER DB_PASSWORD=PASS DB_NAME=fyp_local_test \
  bash backend/tests/e2e/run_live_stack.sh
# 加上 E2E_BROWSER=1 同时运行 Chromium 冒烟测试（首次需：cd frontend && npx playwright install chromium）
```

各测试套件证明了什么，参见 [`docs/E2E_TESTING.zh-CN.md`](E2E_TESTING.zh-CN.md)；各检查脚本参见
`backend/scripts/`；尚未完成的部分记录在 `TODO.md`。

### 管理后台里的账户

管理员页面 → **Users** 列出账户及其邮箱；**详情** 显示单个账户的状态、登录和改密时间，以及统计数字（文件数、占用空间、
分享数、在线会话数）。**重置登录密码** 会生成一个只显示一次的随机临时密码，让该账户在所有设备上退出登录，并发邮件通知本人；
本人之后在“设置 → 登录密码”里改成自己的密码。在那之前账户带着 `must_change_password` 标记：一登录就被直接带到那张卡片，
而且服务器除了读取账户信息和退出登录之外，拒绝其他所有需要登录的请求（`403 password_change_required`），
管理员看到过的临时密码不会被一直用下去。最后一个在用的管理员不能删除自己的账户，也不能被停用（`409 last_admin`）。任何界面都不会显示密码：登录密码只以单向哈希保存，加密口令从来不会到达服务器，
所以重置既打不开、也不会弄丢任何人的文件。

### 安全 Agent

管理员页面 → **Security agent** 会根据审计日志、完整性检查和恢复请求，把需要管理员关注的事项排成
Critical / High / Medium / Low 的发现，并附上证据和建议动作。它基于规则、只读、只看元数据；输入、规则、输出与边界见
[docs/SECURITY_AGENT.zh-CN.md](SECURITY_AGENT.zh-CN.md)。

### 备份与恢复演练

MySQL 元数据与密文对象的协调加密备份，以及证明其可用的洁净主机恢复，见
[docs/BACKUP_AND_RECOVERY.zh-CN.md](BACKUP_AND_RECOVERY.zh-CN.md)（RPO/RTO、保留策略、密钥保管、
实测耗时）。`mysql-gate` 在每个 PR 上运行该演练。在本地针对任意一次性 MySQL 8.4 运行（只会操作名称中
包含 `_test` 的数据库，生成的一次性密钥和账号会在退出时删除）：

```bash
docker compose up -d mysql
cd backend
export DB_HOST=127.0.0.1 DB_PORT=3306 ADMIN_DB_USER=root ADMIN_DB_PASSWORD=local_root_password
export SECRET_KEY=local-test-secret-key-at-least-32-chars APP_ENV=test
bash scripts/backup_restore_drill.sh   # 加密备份 -> 洁净恢复 -> 拒绝检查
bash scripts/mysql_release_gate.sh     # 锁竞争、带校验和的恢复、回滚、部分 DDL
```

staging 上的备份任务已安装并在运行：`mcs21-backup`（同机备份，每天 04:15 起）、`mcs21-offsite-backup`（加密异地副本，
每天 02:30 起，使用 `04-backup-account.sql` 创建的最小权限账号），以及每周日的 `mcs21-backup-verify` 恢复校验。最近一次异地
备份（2026-10-08 02:37）成功。每次部署前还会留一份部署前备份，`mcs21-deploy` 只保留最新 10 份（#204）。详见 [docs/BACKUP_AND_RECOVERY.zh-CN.md](BACKUP_AND_RECOVERY.zh-CN.md)。

### 对账清理与运维告警

SecureView 的 #59 可观测性加固已在仓库中实现：结构化且脱敏的安全/运维事件进入仅
loopback 可访问的 metrics snapshot，并由五分钟阈值 watcher 检查；每小时 HMAC 认证的审计链 checkpoint
面向现有 S3 兼容异地存储；告警邮件只发送 unit 状态，不再携带原始 journal 行。受信 proxy 边界仅限
loopback nginx，公网 origin 对 `/internal/` 显式返回 404。安装方式、阈值负责人、checkpoint 独立验证与
事故处理流程见
[`docs/OBSERVABILITY_AND_INCIDENT_RESPONSE.zh-CN.md`](OBSERVABILITY_AND_INCIDENT_RESPONSE.zh-CN.md)。
这些 timer 已在 staging 上安装并启用；staging 证据已于 2026-09-25 记录，[#59](https://github.com/jsonrar/fyp-secure-file-platform/issues/59) 已关闭。

`backend/scripts/reconcile.py` 清除已失效的会话、刷新令牌、限流桶、验证码以及未被引用的密文对象；它从不
触碰审计、身份、密钥保管或恢复相关的表。它默认只报告，从截止线两侧展示每个类别；带 `--apply` 时若数量
异常则拒绝删除任何东西（退出码 3）。`deployment/server/mcs21-reconcile.{service,timer}` 在同机备份之后、
每天 05:00（Asia/Kuala_Lumpur）运行它，`mcs21-alert@.service` 在它或任一备份任务失败时发邮件通知到人。
[docs/RECONCILIATION_RUNBOOK.zh-CN.md](RECONCILIATION_RUNBOOK.zh-CN.md) 中的 report-only 审查记录完成后，
它已于 2026-09-24 安装到 staging，从 2026-09-25 起每天运行（[#57](https://github.com/jsonrar/fyp-secure-file-platform/issues/57)，已关闭）。

## 重要安全说明

本项目仍是 FYP 原型。邮箱验证和忘记**登录密码**后的验证码重置已经实现，但 MFA 与外部身份
提供商尚未实现。加密 passphrase 与登录密码相互独立，且永不发送到服务器；遗忘 passphrase
时仍需用户另行保存的私钥文件，单密钥账户可用它重置 passphrase；管理员恢复流程无法重置它。内置密码拒绝列表有意
保持较小，并非持续维护的已泄露密码语料库。生产部署还需要加密异地备份与恢复演练、通过
KMS/HSM 或等效离线控制加强恢复密钥托管、在数据库外锚定审计 checkpoint，并接受独立专业
安全评审。
