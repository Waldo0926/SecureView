# SecureView 优先级 Backlog
[English](BACKLOG.md) | [简体中文](BACKLOG.zh-CN.md)

本文件最初于 2026-09-03 根据 GitHub `main`、共享 changelog、仓库测试及线上预发布环境
完成同步。2026-09-07 再次对照 GitHub `main` 的 `cab44b1` 检查；该版本已合并 500 MiB
上传上限改动，但那次仅同步 backlog，未重新核验线上部署。2026-10-01 再次对照 `main` 的 `70fcb6d` 检查：
该提交上的 CI 全部通过，预发布环境运行的是同一个 SHA，各定时任务健康。2026-10-07 又对照 `main` 的 `e4b3f13` 复核（见下表）。GitHub Issues 是可执行 backlog，
团队通过 [SecureView Development Board](https://github.com/users/Waldo0926/projects/1)
共用 Kanban 视图；本文件只提供带链接的优先级摘要，不再成为另一份会漂移的清单。

下方已交付 MVP 能力继续保持勾选。GitHub Issues 是权威来源；下方未勾选项仍缺产品、运维、
安全评审或部署证据。部分完成不会被误标为完成。

提案对照结果记录在 [`docs/PROPOSAL_TRACEABILITY.zh-CN.md`](PROPOSAL_TRACEABILITY.zh-CN.md)：
24 个 WBS 工作包中 23 个 Done、1 个 In review（安全测试，还缺独立的外部评审）。非专业用户可用性依据非正式真实使用算 Done，
正式研究没有进行，#115 已按 not planned 关闭；产品验收标准全部 Done，最后一条可关闭的分阶段进度提示（AC7）由 [PR #200](https://github.com/jsonrar/fyp-secure-file-platform/pull/200) 完成。
M3 已依据导师看过并签署确认的 MVP/UI 检查点标为 Done；导师所说的全项目约 70–80%
是该历史检查点的判断，不是对当前完成度的精确测量。

## 已交付 MVP 基线

2026-10-08 上线：封存回执的关闭按钮，补完 AC7（[PR #200](https://github.com/jsonrar/fyp-secure-file-platform/pull/200)）；凭当前口令修改口令（[PR #201](https://github.com/jsonrar/fyp-secure-file-platform/pull/201)）；死锁重试写日志
（[PR #202](https://github.com/jsonrar/fyp-secure-file-platform/pull/202)）；为两条 npm 公告升级到 Vue 3.5.43（[PR #203](https://github.com/jsonrar/fyp-secure-file-platform/pull/203)）；部署前备份清理，当天已装到 VPS（删除 175 份旧备份，腾出 73 GB）
（[PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204)）；以及在浏览器中拒绝弱口令，威胁模型 F-04（[PR #205](https://github.com/jsonrar/fyp-secure-file-platform/pull/205)）。

首页图文指南（七张带标记的截图，中英文各一套）和帮助页视频已在“Sealed”改版后重新拍摄并上线 staging（#192）；2026-10-10 又按 #215 之后的上传页重拍了图文指南和两段帮助页演示视频。
横向滚动的 Core Features 在那次改版中已从首页移除（#177）。

- [x] 邮箱验证码注册与重置登录密码、登录与服务端撤销会话的登出、后端会话撤销端点、refresh 轮换、
  会话失效、注销账户、限流、
  Argon2id 密码哈希与 RBAC。
- [x] 浏览器持有的账户密钥登记、passphrase/私钥文件解锁、空闲自动上锁及历史密钥 bundle
  获取；明文私钥不会提交到服务器。
- [x] 浏览器端 AES-128/192/256-GCM、AES-256-GCM-SIV、ChaCha20-Poly1305 与 XChaCha20-Poly1305 文件加密、RSA-OAEP-SHA256 DEK
  包装、认证下载/解密、完整性失败提示及密文存储。
- [x] 文件名搜索、分页、所有者/被分享文件分区、接收者密钥重包装共享、接收者列表、撤销、通知、
  逐文件历史，以及基于所有权的正确审计可见性。
- [x] 条件恢复与管理 API、防篡改审计链、MySQL 最小权限生产 SQL、HTTPS、nginx 限流、
  fail2ban、受保护自动部署及对账实现。
- [x] 公网预发布与评审入口：[应用](https://secureview.tech)、
  [Swagger UI](https://secureview.tech/docs)、
  [OpenAPI JSON](https://secureview.tech/openapi.json)。
- [x] 公开产品页与登录后账户壳层：落地页 `/`、Education（`/education`：算法、演练场、知识库）、
  Help（`/help`：How to Use 操作演示）、Contact us（`/team`：反馈表单 + 导师简介 + 团队卡片）、页头当前标签主题色高亮，
  以及含 `/profile` 与 `/settings` 的头像菜单。证据与理由见
  [`changelog/CHANGELOG.md`](../changelog/CHANGELOG.md) 的 `[Unreleased]`。
- [x] 面向新用户的讲解（2026-10-02）：`/how-it-works` 和首页的可逐步查看的原理动画，Help 页三段从真实产品录制、
  带字幕的视频，与普通网盘的对比，以及四步快速上手。各自内容见更新日志。对比表的问题列已加标签和编号，页脚中间不再空一块（[PR #194](https://github.com/jsonrar/fyp-secure-file-platform/pull/194)）。全站标题和简介：放得下就一行，只在句与句之间换行，不再有两句话的标题，由 `text-audit.mjs` 检查（[PR #195](https://github.com/jsonrar/fyp-secure-file-platform/pull/195)）。
- [x] 访问记录筛选（2026-10-09）：`GET /audit-logs` 支持按事件类型、结果、日期范围和关键词筛选，可见范围规则不变；每页 100 条、点“加载更多”翻页，不再一打开就拉 1,000 条（[PR #213](https://github.com/jsonrar/fyp-secure-file-platform/pull/213)）。
- [x] 所有浏览器都能用全部六种上传套件（2026-10-09）：WebCrypto 不支持 AES-192 时改用 `@noble/ciphers`，实机测试里六种套件都走完分享，后端也自己校验 `docs/crypto/test_vectors.json`（[PR #211](https://github.com/jsonrar/fyp-secure-file-platform/pull/211)）。
- [x] 账户相关修复（2026-10-09）：注册时已注册的邮箱和验证码错误得到相同的回答，注销账户有频率限制并写审计记录，管理员重置密码后本人下次登录必须设置新密码（`must_change_password`，Schema `0011`），并删除了无用的加密代码和 `app/utils`（[PR #212](https://github.com/jsonrar/fyp-secure-file-platform/pull/212)）。
- [x] 按导师反馈修复上传（2026-10-09）：文件不会被上传两次，完成后显示绿色状态而不是按钮，算法下拉框为每个选项标出等级（例如 Max · Recommended）并有说明框，讲解动画每步约 3 秒（[PR #215](https://github.com/jsonrar/fyp-secure-file-platform/pull/215)）。

已交付行为的原因和证据统一写在
[`changelog/CHANGELOG.md`](../changelog/CHANGELOG.md)，不再复制进历史 TODO。

## 2026-10-17 已核验（`main` 位于 `a96fed9`，测试最后一次运行在 `1b1bcce`）

| 门禁 | 结果 | 含义 |
| --- | --- | --- |
| `1b1bcce`（PR #240，2026-10-13）上的 GitHub Actions | 所有测试 Job 和 `promote` 全部通过 | 这是最后一次真正跑测试的 `main` 推送；`a96fed9`（#241）只改文档，测试 Job 和 `promote` 按设计被跳过 |
| 后端（`mysql-gate`） | 786 passed，0 skipped；覆盖率 86.64% | 同时运行 MySQL 发布门禁和备份/恢复演练，均通过 |
| 后端（`backend` Job，无 MySQL） | 718 passed，68 deselected；覆盖率 81.84% | 不需要 MySQL 的单元和 API 测试 |
| 前端（`frontend` Job） | 899 passed，78 skipped；语句覆盖率 77.36% | 被跳过的是真实后端测试套件，在 `e2e-live` 里运行 |
| 前端实时测试（`e2e-live`） | 977 passed，0 skipped；语句覆盖率 79.72% | 全部套件针对一次性 API 与 MySQL 运行 |
| 浏览器测试（`e2e-live`） | 57 passed | Playwright |
| 篡改演练 | 通过 | 隔离的攻击容器（#90） |
| 线上 staging | 运行 `1b1bcce`，schema `0011_must_change_password` | `/opt/mcs21/current` 指向该版本；`/health/ready` 返回 ready（2026-10-17 检查） |

## 2026-10-10 已核验（`main` 位于 `2ffc36c`）

| 门禁 | 结果 | 含义 |
| --- | --- | --- |
| `2ffc36c`（PR #222）上的 GitHub Actions | 所有测试 Job 和 `promote` 全部通过 | 后端、前端、`mysql-gate`、`e2e-live` 和 `tamper-drill` |
| 后端（`mysql-gate`） | 759 passed，0 skipped；覆盖率 86.52% | 同时运行 MySQL 发布门禁和备份/恢复演练，均通过 |
| 后端（`backend` Job，无 MySQL） | 691 passed，68 deselected；覆盖率 81.67% | 不需要 MySQL 的单元和 API 测试 |
| 前端（`frontend` Job） | 886 passed，78 skipped；语句覆盖率 74.97% | 被跳过的是真实后端测试套件，在 `e2e-live` 里运行 |
| 前端实时测试（`e2e-live`） | 964 passed，0 skipped；语句覆盖率 79.12% | 全部套件针对一次性 API 与 MySQL 运行 |
| 浏览器测试（`e2e-live`） | 57 passed | Playwright |
| 篡改演练 | 通过 | 隔离的攻击容器（#90） |
| 线上 staging | 运行 `2ffc36c`，schema `0011_must_change_password` | `/opt/mcs21/current` 指向该版本；`/health/ready` 返回 ready |
| 安全 Agent 每日检查 | 2026-10-10 06:00：退出码 3，43 条 High 发现 | 全部来自 2026-10-09 的压测（压测工具的 User-Agent、测试者的地址、账号已被压测的清理步骤删除）；服务器上无需处理。见 [SECURITY_AGENT.zh-CN.md](SECURITY_AGENT.zh-CN.md#主动告警每日) |

## 2026-10-09 已核验（`main` 位于 `0bb6238`）

| 门禁 | 结果 | 含义 |
| --- | --- | --- |
| `0bb6238`（PR #217）上的 GitHub Actions | 所有测试 Job 全部通过 | 后端、前端、`mysql-gate`、`e2e-live` 和 `tamper-drill` |
| 后端（`mysql-gate`） | 759 passed，0 skipped；覆盖率 86.52% | 同时运行 MySQL 发布门禁和备份/恢复演练，均通过 |
| 后端（`backend` Job，无 MySQL） | 691 passed；覆盖率 81.67% | 不需要 MySQL 的单元和 API 测试 |
| 前端（`frontend` Job） | 881 passed，78 skipped；语句覆盖率 74.89% | 被跳过的是真实后端测试套件，在 `e2e-live` 里运行 |
| 前端实时测试（`e2e-live`） | 959 passed，0 skipped；语句覆盖率 79.05% | 全部套件针对一次性 API 与 MySQL 运行 |
| 浏览器测试（`e2e-live`） | 57 passed | Playwright |
| 篡改演练 | 通过 | 隔离的攻击容器（#90） |
| 线上 staging | 运行 `0bb6238`，schema `0011_must_change_password` | `/health/ready` 返回 ready；按 DEPLOYMENT.md 的要求，部署前先手动执行了 0011 的 SQL |
| Schema head | `0011_must_change_password` | 新增管理员重置标记（#212） |

## 2026-10-07 已核验（`main` 位于 `e4b3f13`）

| 门禁 | 结果 | 含义 |
| --- | --- | --- |
| `e4b3f13` 上的 GitHub Actions | 五个测试 Job 和 `promote` 全部通过 | 运行在 VPS 自建 runner 上；`promote` 移动了 `deploy`，staging 随即部署 |
| 后端（`mysql-gate`） | 632 passed，0 skipped；分支覆盖率 85.27%（下限 82%） | 针对 MySQL 8.4 的完整测试，含并发和故障注入 |
| 后端（`backend` Job，无 MySQL） | 568 passed，64 deselected；覆盖率 80.35%（下限 78%） | 被排除的就是上面那些 MySQL 测试 |
| 前端（`frontend` Job） | 810 passed，56 skipped | 被跳过的是真实后端测试套件 |
| 前端实时测试（`e2e-live`） | 866 passed，0 skipped | 全部套件针对一次性 API 与 MySQL 运行 |
| 浏览器测试（`e2e-live`） | 57 passed | 主流程、篡改视图、手机宽度、问答助手、语言切换、404 页面 |
| Schema head | `0010_shared_file_folders` | 17 张应用表加 `alembic_version` |
| 线上 staging | 运行 `e4b3f13` | `/opt/mcs21/current` 指向该发布；九个 `mcs21-*` timer 全部启用 |

## 2026-10-01 已核验（`main` 位于 `70fcb6d`）

| 门禁 | 结果 | 含义 |
| --- | --- | --- |
| 后端 Pytest | 400 passed, 49 skipped, 1 warning | 被跳过的是 MySQL 集成测试；CI 的 `mysql-gate` Job 会运行它们，并在任何跳过时失败 |
| 前端 Vitest | 284 passed, 51 skipped | 被跳过的是真实后端测试套件；CI 的 `e2e-live` Job 会不跳过地运行它们 |
| 类型检查、生产构建、Ruff | 通过 | `vue-tsc --noEmit`、Vite 构建、`ruff format --check` 与 `ruff check` |
| GitHub Actions | `main` 上五个 Job 全部通过 | `backend`、`frontend`、`mysql-gate`、`e2e-live`、`tamper-drill` |
| 依赖审计 | `pip-audit` 无问题；`npm audit` 曾有一个高危 axios 公告 | 已由 [#112](https://github.com/jsonrar/fyp-secure-file-platform/pull/112) 修复并纳入 CI 门禁 |
| Schema head | `0008_avatars` | 包含文件夹（`0007`）与头像（`0008`） |
| 线上预发布 | 运行 `70fcb6d`，与 `main` 相同 | `/`、`/docs`、`/openapi.json` 返回 200；OpenAPI 列出文件夹与头像路由 |
| 预发布运维 | 备份、异地备份、对账、审计 checkpoint、observer 定时任务均成功运行 | 恢复验证最近一次运行于 2026-09-27（每周一次），对 2026-09-26 的备份通过；对账 2026-09-25 至 2026-10-01 每天运行，0 条可删、0 个孤立对象 |

## 2026-09-03 的历史基线（保留用于对比）

| 门禁 | 结果 | 含义 |
| --- | --- | --- |
| 后端 Pytest | 317 passed, 21 skipped, 1 warning | 单元/API 通过；真实 MySQL 覆盖未运行 |
| 前端 Vitest | 233 passed, 18 skipped | 离线套件通过；集成覆盖被跳过 |
| 前端 typecheck | 通过 | `vue-tsc --noEmit` 可正常运行 |
| 前端 production build | 通过 | Vite 生产 bundle 构建成功 |
| Ruff format/check | **失败** | 4 个文件需格式化，3 个 import block 不合规 |
| GitHub Actions | **不存在** | 当前没有 required CI gate 保护 `main` |
| Schema 基线 | `0007_file_folders` | 生产 SQL 共 18 张表 |
| 线上预发布 | `a085ae4`（PR #51，本次文档同步前） | `/`、health、docs、schema、ReDoc 均为 200 |

带 integration skip 的测试只证明离线子集，不得表述为发布通过。

## P0 — 发布与数据保护阻塞项

- [x] [#52 建立 required CI 门禁并修复当前 Ruff 基线](https://github.com/jsonrar/fyp-secure-file-platform/issues/52)
  ——`.github/workflows/ci.yml` 在每个 PR 及推送到 `main` 时运行 backend（Ruff + 带覆盖率下限、不依赖
  MySQL 的 pytest）与 frontend（带覆盖率的测试/类型检查/构建）；Ruff 基线已真正修复而非压制。当前套餐下**无法**启用
  分支保护：仓库是 GitHub 免费版的私有仓库，分支保护与 rulesets 的 API 都拒绝它（2026-10-01 核实；威胁模型 F-01）。
  需要付费套餐或将仓库公开，所以这些检查目前只靠约定与评审来“必需”。取而代之的是
  [#117](https://github.com/jsonrar/fyp-secure-file-platform/pull/117)：预发布环境只部署由 CI 在某个 commit 上全部 Job
  通过后才向前推进的 `deploy` 分支（[文档](AUTOMATIC_DEPLOYMENT.zh-CN.md#ci-门禁)）。2026-10-01 已核实：`promote`
  作业在合并提交上创建了 `deploy`，新脚本已安装到 VPS，并报告运行中的 release 已与最新通过 CI 的 commit 一致。它不
  要求评审，`mcs21-deploy all main` 仍按设计绕过 CI。自 [#171](https://github.com/jsonrar/fyp-secure-file-platform/pull/171) 起，推送到 `main` 的纯文档改动相对 `deploy` 判断，
  不会再取消代码 commit 的 CI 运行、让那段代码一直得不到部署。
- [x] [#53 在 CI 中运行完整 MySQL 8.4 与 Schema parity 门禁](https://github.com/jsonrar/fyp-secure-file-platform/issues/53)
  ——`mysql-gate` Job 拉起经 TLS 校验的 MySQL 8.4，执行到 head（目前为 `0011_must_change_password`）的每一次迁移，
  运行 `alembic current`/`check`，运行完整后端测试（覆盖率下限 82%），任何测试被跳过即判失败，
  并检查运行时账户与管理员账户的权限边界及线上 Schema 一致性。此前遗留的两处缺口已补上：迁移锁竞争
  现在随机化运行 8 轮，每轮都必须出现一个应用者和一个等待者；恢复结果按逐表 `CHECKSUM TABLE` 加
  Schema 指纹比较，并通过修改单行证明检查有效。仍不是长时间运行的混沌测试。
- [x] [#56 自动化加密异地备份并证明可在洁净主机恢复](https://github.com/jsonrar/fyp-secure-file-platform/issues/56)
  ——2026-09-24 起已在 staging 运行：每晚把加密备份集传到 Cloudflare R2（35 天生命周期、30 天 bucket
  lock），使用最小权限备份账号，失败时发邮件。一个真实备份集已在另一台机器上用离线私钥恢复，用时 6.97
  秒，与线上数据库和文件完全一致（[docs/BACKUP_AND_RECOVERY.zh-CN.md](BACKUP_AND_RECOVERY.zh-CN.md)
  §5）。后续：在全新 VPS 上计时 4 小时整体服务 RTO。清理 `mcs21-deploy` 的发布前 dump 已完成（[PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204)）。
- [x] [#61 保持 README、TODO、Issues、changelog、PR 与部署同步](https://github.com/jsonrar/fyp-secure-file-platform/issues/61)
  ——本次同步 PR 建立统一记录与证据清单；后续变更沿用同一规则。

## P1 — 补全已有后端能力与运维

- [x] [#54 完成浏览器修改 passphrase 与后继密钥轮换](https://github.com/jsonrar/fyp-secure-file-platform/issues/54)
  ——只满足了部分验收标准就被关闭；见下方 P3 条目以及 Issue 上的范围记录。
- [x] [#55 完成管理员、恢复专员及审计验证流程](https://github.com/jsonrar/fyp-secure-file-platform/issues/55)
  ——`/admin` 按角色展示：ADMIN 先看到数字概览（用户、文件、存储、分享、完整性与审计健康度，需要关注的事项置顶），并可管理用户/文件、验证审计链、登记恢复公钥并复核恢复；
  RECOVERY_OFFICER 可复核并执行（离线重封装后回填）；普通用户从 My Files 发起请求，并在此
  跟踪或取消。2026-10-02 起页眉有 “Admin” 入口，各分区分组排成一行并可通过 URL 直达，用户/文件列表默认隐藏已删除记录
  （状态筛选、搜索、禁用前确认）。
- [x] [#89 用户登出时撤销服务端会话](https://github.com/jsonrar/fyp-secure-file-platform/issues/89)
  ——主动 Log out 先调用 `POST /auth/logout` 再清本地；会话过期与注销账户仍只清本地。
- [x] [#57 安全验证并启用 staging 对账 timer](https://github.com/jsonrar/fyp-secure-file-platform/issues/57)
  ——仓库部分已完成：目录宽限期、数量保护（退出码 3）、边界两侧计数报告、MySQL 幂等性测试与不触碰审计/
  密钥/恢复表的语句测试、在同机备份之后 05:00 运行的 timer、邮件告警，以及
  [docs/RECONCILIATION_RUNBOOK.zh-CN.md](RECONCILIATION_RUNBOOK.zh-CN.md)。
  2026-09-24 已在 staging 安装，report-only 审查已记录（43 条可删、
  0 个孤立对象），timer 已启用。2026-09-25 05:00 的第一次计划运行，以及此后到 2026-10-01 的连续七次每日运行全部成功
  （journal 每次均为 0 条可删、0 个孤立对象）。这些重复运行只说明它在空集合上无害；由于此后一直没有可删项，
  真实删除之后的幂等重复运行尚未被观察到。
- [x] [#58 扩展浏览器 E2E、并发、故障注入与覆盖率门禁](https://github.com/jsonrar/fyp-secure-file-platform/issues/58)
  ——`e2e-live` CI Job 针对一次性 API 与 MySQL 不跳过地运行前端全部真实后端测试套件（从注册到
  注销账户、全部六种文件算法、角色拒绝），随后运行 Chromium 冒烟测试，在构建后的页面上点击完成
  注册、验证、登录、解锁、上传、下载、分享、撤销与登出；`mysql-gate` 运行多连接并发与真实故障注入
  测试；覆盖率下限与经脱敏检查的 JUnit/覆盖率产物已就位（[docs/E2E_TESTING.zh-CN.md](E2E_TESTING.zh-CN.md)）。
- [x] [#59 增加脱敏可观测性、事故 runbook 与外部审计 checkpoint](https://github.com/jsonrar/fyp-secure-file-platform/issues/59)
  ——仓库侧实现已就绪：脱敏结构化事件、仅 loopback 的 metrics 与阈值告警、受信 proxy 约束、HMAC 外部审计 checkpoint、最小化告警邮件和双语事故 runbook。2026-09-25 已记录 staging 证据（Issue 的关闭评论，以及[运行手册](OBSERVABILITY_AND_INCIDENT_RESPONSE.zh-CN.md)第 8 节）：
  loopback 绑定、nginx 未暴露 metrics、外部 checkpoint 已在另一台机器下载并完成 HMAC 校验、测试告警不含 journal 内容。
  checkpoint timer 在 2026-10-01 仍在每小时发布。

- [x] [#140 在 staging 上测量服务器容量与性能（会议行动项 4–6）](https://github.com/jsonrar/fyp-secure-file-platform/issues/140)
  — 2026-10-03 至 04 夜间完成，证据已在 [PR #155](https://github.com/jsonrar/fyp-secure-file-platform/pull/155) 合并：
  共 22,264 次操作，5,094 次下载全部 SHA-256 校验、完整性失败 0 次，所有类型在 500 MiB 以内逐字节一致，50 个并发用户
  以内服务器零错误，100 个用户时第一个瓶颈是 15 个数据库连接。[报告](performance/REPORT-2026-10-03.md)；结论见
  [docs/PERFORMANCE_TESTING.zh-CN.md](PERFORMANCE_TESTING.zh-CN.md)。传输类数字受压测端家庭网络限制，引用前先读报告里的测试条件。
  修复后于 2026-10-09 经公网地址重跑（版本 `ac5e2b0`，HTTPS 和 nginx，限流开着）：共 18,256 次操作，7,444 次下载校验、
  完整性失败 0 次，服务器 5xx 为 0；50 个用户以内所有请求成功，100 个用户时服务器错误为 0，唯一的拒绝是按地址上传限制返回的 429。
  [报告](performance/REPORT-2026-10-09.zh-CN.md)。2026-10-03/04 的报告保留，作为修复前的对照。
- [x] [#139 并发使用下两个 MySQL 死锁返回 HTTP 500](https://github.com/jsonrar/fyp-secure-file-platform/issues/139)
  — 已在 [PR #154](https://github.com/jsonrar/fyp-secure-file-platform/pull/154) 中通过对 MySQL 1213/1205 重试修复；
  回归测试在修复前约 7/10 次复现死锁，修复后从未复现。#140 压测的 28,540 个请求中没有出现 1213 或 1205。

- [x] ~~[#115 运行非专业用户可用性研究（WBS 5.4、NFR2）](https://github.com/jsonrar/fyp-secure-file-platform/issues/115)~~
  ——**2026-10-04 按 not planned 关闭。**团队决定不做正式研究。取而代之的是：导师、团队 4 人、FIT3162 Teaching Team
  和其他同学都用自己的账号在 staging 上实际使用过。这属于非正式的真实使用：没有 SUS 分数、没有各任务完成率，
  研究套件（`docs/usability/` 和计分脚本）已于 2026-10-05 删除；以后如果需要正式研究，可以在 git 历史（PR #114）里找回。

- [x] pip 下载卡住不再拖住部署：每次安装有时间上限、最多三次，失败时删除构建目录（[PR #196](https://github.com/jsonrar/fyp-secure-file-platform/pull/196)）。`/usr/local/sbin/mcs21-deploy` 需手工安装。
- [x] 管理员查看账户详情、重置登录密码（临时密码只显示一次、撤销会话、邮件通知本人），设置页可修改登录密码（[PR #197](https://github.com/jsonrar/fyp-secure-file-platform/pull/197)）。

## P2 — 正式安全保障

- [x] [#90 增加带完整性证据的隔离 VPS 对抗性篡改演练](https://github.com/jsonrar/fyp-secure-file-platform/issues/90)
  ——资源受限的攻击容器只能看到一次性实验卷与 MySQL 8.4 `_test` 数据库；它证明
  `MODIFIED`/`CORRUPTED`、下载拒绝、`MISSING`、恢复到 `VALID`/`ACTIVE`，以及 SHA-256 与 AEAD
  的信任边界；CI 会保留脱敏报告（[运行手册](../security-lab/README.md)）。

- [x] [#60 完成正式威胁模型与独立安全评审](https://github.com/jsonrar/fyp-secure-file-platform/issues/60)
  ——已在 [THREAT_MODEL.zh-CN.md](THREAT_MODEL.zh-CN.md) v1.0 中完成：目标与非目标、STRIDE、Argon2id
  实测成本、密钥保管、公钥身份与元数据的决定，对供应链、CSP、上传、令牌与恢复操作的评审，以及含严重度与处置
  的 20 项发现登记表。它是一份经过一次同行评审的自评，而非独立的外部评审，不构成任何认证。登记表已于 2026-10-01
  刷新（v1.1）：F-10、F-11、F-20 已解决，F-12 部分解决，F-19 已缓解；F-01 当天由以 CI 为门槛的部署缓解（#117，见下）。
  还有两项*建议修复*的发现尚未实施：F-02 恢复私钥保管、F-03 在预发布环境关闭 `/docs`。F-04 拒绝弱 passphrase 已于 2026-10-08 缓解（[PR #205](https://github.com/jsonrar/fyp-secure-file-platform/pull/205)）。
  当前版本为 v1.5（2026-10-09），也记录了 F-08 已由 #212 缓解。

## P3 — 计划中的产品 UX

已于 2026-09-07 拆成可执行 Issue 并加入共享 backlog。各项部分实现状态见下文；邻近的 UI
打磨不得视为这些项已完成。每个 Issue 均按
[#61](https://github.com/jsonrar/fyp-secure-file-platform/issues/61) 写明验收标准。

- [x] [#72 高危与破坏性操作二次确认](https://github.com/jsonrar/fyp-secure-file-platform/issues/72)
  ——删除文件与撤销分享使用独立后果确认弹窗；注销账户仍为「登录密码 + 输入 DELETE」，并在
  Profile 与 Settings 均可进入。
- [x] [#71 认证后的密文预览与加密文件下载](https://github.com/jsonrar/fyp-secure-file-platform/issues/71)
  ——所有者和授权接收者无需 passphrase 即可保存存储的密文（#78，#79 中改进）；自 2026-10-01 起每个文件还有 **Encrypted
  preview**：精确大小、已记录的 SHA-256、密文前 128 字节的十六进制转储，并检查存储的字节是否不是以该类型未加密文件的典型
  开头开始。该 Issue 此前在没有它的情况下被关闭，这次补上了预览这一条。原始描述里仍未完成的是：这些操作的手机布局测试。
  两个大小为什么一样、如何演示，见 [docs/ENCRYPTION_EVIDENCE.zh-CN.md](ENCRYPTION_EVIDENCE.zh-CN.md)。
- [x] [#73 My Files 文件架与移动功能](https://github.com/jsonrar/fyp-secure-file-platform/issues/73)——已在 #103 合并并部署（2026-10-01 staging 的 OpenAPI 列出了文件夹路由）。该 Issue 于 2026-09-29 关闭，但没有对受影响流程的书面演示记录。
  ——创建所有者专属文件架，并在文件架与根目录之间移动自己的文件；不改变加密、分享、文件身份
  或审计语义。
- [x] [#54 浏览器修改 passphrase、密钥文件重置与后继密钥轮换](https://github.com/jsonrar/fyp-secure-file-platform/issues/54)
  ——**只完成了密钥文件重置**（#80）：Settings 会用账户公钥验证保存的私钥文件，在新 AMK 与新 passphrase 下重新
  封装它，并以 RSA-PSS 签名证明持有；明文私钥不离开浏览器。记得当前 passphrase 时修改 passphrase 已于 2026-10-08
  补上（[PR #201](https://github.com/jsonrar/fyp-secure-file-platform/pull/201)）：当前 passphrase 在浏览器中打开私钥，再走同一套重新封装和签名流程，有实时测试和浏览器测试。
  **未实现，且不作为未完成工作被跟踪：**浏览器端的后继密钥轮换、规范化的账户信封规范文档，以及重置流程的浏览器 E2E
  （2026-10-01 检索 `frontend/src` 与 `docs`）。该 Issue 在这些未满足时被关闭；项目负责人选择如实记录而不是重新
  打开。见 Issue 上的范围记录。
- [x] [#146 Help assistant：回答操作、原理与对比问题的悬浮助手（v1 不用大模型）](https://github.com/jsonrar/fyp-secure-file-platform/issues/146)
  ——2026-10-02 批准，排在 #74 之前。在浏览器内检索人工整理的意图和现有 Help/Education 内容；无网络请求，
  对比回答附出处。已部署、验证，并于 2026-10-02 关闭。见 [docs/HELP_ASSISTANT.zh-CN.md](HELP_ASSISTANT.zh-CN.md)。
- [x] [#148 Help assistant v2：回答已登录用户关于自己账户的问题](https://github.com/jsonrar/fyp-secure-file-platform/issues/148)
  ——七项只读检查（谁能打开某个文件、单个文件的历史、我分享了什么、别人分享给我什么、被标记为 Modified 的文件、
  最近活动、账户概览），使用 My Files 和 Access Records 已有的请求。不用大模型；面板里不做任何修改。已部署、验证，并于 2026-10-02 关闭。
- [x] [#74 持久化 English / 简体中文语言切换](https://github.com/jsonrar/fyp-secure-file-platform/issues/74)
  ——页头、手机菜单和设置页均可切换 English / 简体中文，按设备记住，并在首次渲染前恢复。公共界面（导航、登录、注册、
  设置等）使用 vue-i18n 键值消息；其余界面通过词典显示中文，词典在构建阶段由智谱 `glm-4-flash` 起草，并由脚本和测试
  按安全术语表校验。**中文为机器起草，尚未经过完整人工审校**；Help assistant 仍只能匹配英文提问。见
  [docs/I18N.zh-CN.md](I18N.zh-CN.md)。
- [x] [#75 经验证的用户头像上传与展示](https://github.com/jsonrar/fyp-secure-file-platform/issues/75)
  ——资料页 / 页头支持可选头像，并包含内容验证、安全提供、清理、限流及首字母 fallback。已合并（#101、#106）并部署（2026-10-01 staging 的 OpenAPI 中有头像路由）；该 Issue 在 2026-09-29 关闭前，没有在
  Issue 上记录上传/展示/删除的短流程演示。
- [x] [#76 修复手机与窄屏下的产品流程](https://github.com/jsonrar/fyp-secure-file-platform/issues/76)
  ——修复公开页面、账户与文件流程在窄屏下的布局和交互问题，并保留可重复的手机浏览器证据。**已于 2026-10-02
  关闭。**用自动化排查对 23 个界面在 360 与 320 px 下检查，发现多处横向滚动（教育页，320 px 下的注册、
  忘记密码与上传页）、My Files 表格把操作按钮推出手机屏幕、高度只有 9–20 px 的页脚链接，以及数十个过小的点击目标；
  这些都已修复（My Files 在 768 px 以下改为卡片列表，被标记的点击目标均不小于 40 px，弹框会让长文件名换行并保持在
  屏幕内），并由三个 Chromium 测试覆盖（[docs/E2E_TESTING.zh-CN.md](E2E_TESTING.zh-CN.md)）。2026-10-02
  这些手机测试又在 WebKit（Safari 内核，模拟 iPhone 13）和 Chromium（模拟 Pixel 7）下全部通过。**未做：**没有在
  实体手机上运行；通知与设置流程只检查了布局。

## Final Presentation 与 FYP Award（12 分钟展示）

优先级、每一项的问题、改法和工作量见 [docs/presentation/REFLECTION.zh-CN.md](presentation/REFLECTION.zh-CN.md)；
要讲什么、证据在哪，见 [docs/presentation/TALKING_POINTS.zh-CN.md](presentation/TALKING_POINTS.zh-CN.md)。

一定要做：

- [x] 4 分钟现场演示的脚本——[docs/presentation/DEMO_SCRIPT.zh-CN.md](presentation/DEMO_SCRIPT.zh-CN.md)
- [x] 在 staging 上建好演示账号 `demo-alice` / `demo-bob`（2026-10-04）
- [x] 录备用视频——[docs/presentation/media/demo-backup.mp4](presentation/media/demo-backup.mp4)
- [x] 按 [PR #215](https://github.com/jsonrar/fyp-secure-file-platform/pull/215) 之后的上传页重录帮助页视频 `frontend/public/videos/encrypt-upload.mp4` 和 `share-open.mp4`，并重拍首页图文指南（2026-10-10）
- [ ] 重录备用视频 [docs/presentation/media/demo-backup.mp4](presentation/media/demo-backup.mp4)：拍到的仍是 PR #215 之前的上传页面，
  也没有访问记录（AC5）和 Security agent（AC8）这两步
- [x] 在 staging 上用 `demo-alice` 上传 `quarterly-results.txt` 并分享给 `demo-bob`（2026-10-08 核实：已分享且有效；现场篡改那一步要用）
- [x] 文件行操作：下载（解密）、分享、删除三个按钮带文字直接显示，其余收进"更多"；修掉约 800 px 宽度下助手按钮压住操作的问题（[PR #159](https://github.com/jsonrar/fyp-secure-file-platform/pull/159)）
- [x] 重新截取首页图文指南：截图里还是旧的六个图标（2026-10-04 已更新；第 5 步现在显示带密钥指纹的接收方确认）
- [x] 现场篡改演示：改掉服务器上密文的一个字节，接收者下载时报错——
  `backend/scripts/demo_tamper.py` 和 [docs/presentation/TAMPER_DEMO.zh-CN.md](presentation/TAMPER_DEMO.zh-CN.md)
- [ ] 幻灯片：架构图、加密流程图、需求完成表、局限（最后做）
- [x] 界面改版（“Sealed”风格：暖白纸色、近黑墨色、薄荷绿强调、Geist 字体），所有功能保留。第 1 步全局风格：已完成（[PR #176](https://github.com/jsonrar/fyp-secure-file-platform/pull/176)）。
  第 2 步公开页：已完成（[PR #177](https://github.com/jsonrar/fyp-secure-file-platform/pull/177)；深色首屏、替换 Core Features 卡片墙，保留“Under the hood”和六步指南）。第 3 步应用页：侧边栏、文件详情栏、上传封存回执、工作区和访问记录已改（PR #178、#180、#182）。第 3 步补充（来自 10-05 巡检）：P1 居中页头、统一内容宽度、设置和资料双栏、登录后所有页面保留侧边栏已完成（[#183](https://github.com/jsonrar/fyp-secure-file-platform/issues/183)）；P2（深色主色改近白、去胶囊标签、登录页分栏）已完成（[#184](https://github.com/jsonrar/fyp-secure-file-platform/issues/184)）；P3（访问记录无失败请求、步骤点点击区域、768px 溢出）代码已完成（[#185](https://github.com/jsonrar/fyp-secure-file-platform/issues/185)；线上 SHA-256 的确认由项目负责人做）。我的文件详情入口（整行、文件名、Details 按钮）和非模态侧边详情栏：已完成（[PR #193](https://github.com/jsonrar/fyp-secure-file-platform/pull/193)）。
  第 4 步重拍图文指南截图（中英文）、帮助页视频和演示备用视频：已完成（[#186](https://github.com/jsonrar/fyp-secure-file-platform/issues/186)）；幻灯片由项目负责人自己做
- [x] 如实说明 NFR2（可用性）——TALKING_POINTS 第 10 条（非正式真实使用，没有正式研究）

强烈推荐（冲 Award）：

- [x] 修掉数据库连接池瓶颈，并在 100 用户下做修复前后对比（本地：失败率 80% → 0%，
  [PR #163](https://github.com/jsonrar/fyp-secure-file-platform/pull/163)）
- [x] PR #163 部署后，在 staging 上重跑 #140 的 `steps`：100 用户从 78% 上传失败变为 102 次全部成功（[证据](performance/pool-fix-2026-10-04/staging-rerun/REPORT.md)）
- [x] 所有修复之后经公网地址重跑压测矩阵（长时间压测除外）（2026-10-09，版本 `ac5e2b0`）：100 用户从 65% 到 78% 的上传返回 HTTP 500 变为服务器错误 0 次，7,444 次校验下载完整性失败 0 次，36 个文件（六种类型，1 到 500 MiB）全部逐字节一致（[报告](performance/REPORT-2026-10-09.zh-CN.md)）
- [x] ~~#115 可用性研究并计算 SUS 分数~~——不再计划执行（#115 已于 2026-10-04 关闭）；改为非正式真实使用
- [x] 分享前确认接收者，并显示对方的密钥指纹（密钥验证）——
  [PR #160](https://github.com/jsonrar/fyp-secure-file-platform/pull/160)；威胁模型 T-S5 已针对数据写入者缓解
- [x] 上传滥用限制和"他人分享程序"警告（威胁模型 F-09）——
  [PR #157](https://github.com/jsonrar/fyp-secure-file-platform/pull/157)；已按该 PR 列出的 nginx 与环境变量改动部署

可选：

- [x] 注册拆成两步，注册后直接登录（[PR #161](https://github.com/jsonrar/fyp-secure-file-platform/pull/161)）
- [x] 首次登录的新手清单（上传 → 分享 → 对方下载）（[PR #162](https://github.com/jsonrar/fyp-secure-file-platform/pull/162)）
- [x] 对 staging 做 OWASP ZAP 基线扫描，并附 `pip-audit` / `npm audit` 报告——
  [docs/security/scans-2026-10-04/](security/scans-2026-10-04/README.zh-CN.md)；响应头已在仓库的 nginx 文件里修复
- [x] 把更新后的 `nginx-secureview.conf` 装到 VPS 上并重跑 ZAP 基线扫描（2026-10-04 已完成：8 个 WARN → 5 个，0 FAIL；[after-nginx](security/scans-2026-10-04/after-nginx/zap-baseline.md)）

已为展示完成：

- [x] 上传页面展示真实的加密步骤、实测耗时和加密前后的字节对比
  （[PR #156](https://github.com/jsonrar/fyp-secure-file-platform/pull/156)）

## 每个 Issue 的完成定义

- 实现与测试满足 Issue 验收标准。
- 经过评审的 PR 链接 Issue，并更新双语 changelog。
- 当功能描述改变时同步 README/TODO 和设计文档；不适用则在 PR 中说明 `N/A`。
- 所有成员统一使用共享 Changelog，不再新增或续写个人/分轨变更日志。
- 合并前通过 Secret 与生成物检查。
- 运行时改动必须由自动部署到达准确 merge SHA，并验证健康检查与受影响用户流程；仅 merge
  不代表部署完成。
- 上述证据全部链接后才关闭 Issue。

## 当前 FYP 明确延期项

- Google Drive 式协同编辑、加密全文搜索及大规模对象存储优化。
- 保证支持 1 GB 以上文件。
- 阻止接收者继续使用已经复制的数据等 DRM 能力。
- 正式生产 KMS/HSM 实现和独立认证；其设计与托管要求仍属于安全评审范围。
