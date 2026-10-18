# 提案到交付的可追溯性

[English](PROPOSAL_TRACEABILITY.md) | 简体中文

最初于 **2026-09-05** 对照 FIT3161 MCS21 项目提案报告、GitHub `main`、全部 pull request 和提交、当时的
仓库测试以及公开 staging 部署进行审计。**2026-09-07** 复核了仓库和看板记录；那次只更新记录，没有重新验证
公开部署。**2026-10-01** 对照 `main` 的 `70fcb6d` 再次复核：下面的状态依据 Issue、CI 运行、staging 主机和线上
站点刷新，并确认公开部署运行的正是同一 SHA。**2026-10-07** 对照 `main` 的 `e4b3f13`（也是当天 staging 部署的
SHA）复核了各项状态。

这是一张证据地图，并不代表每项已完成的实现都已获得最终的学术或独立安全认可。

实时的权威来源是 [SecureView Development Board](https://github.com/users/Waldo0926/projects/1)。它的五个团队视图
分别是当前待办、提案 WBS、里程碑、验收标准和 PR 证据。PR 证据视图包含全部 56 个已合并 PR 和当时未合并的
PR #49（看板最后一次同步在 2026-09-07，此后未再同步）；关闭且未合并的 PR #2、#3、#17 被有意排除，因为它们
没有交付代码。早期直接提交到 `main` 的 CT 工作通过下文的精确提交表和归档的 crypto-track 记录署名，而不是
通过个人看板视图或虚构的 PR 历史。

## 状态规则

| 状态 | 证据规则 | 完成度 |
| --- | --- | ---: |
| Backlog | 提案要求，但找不到实现或测试产物 | 0% |
| Ready | 已定义并排好优先级，但尚未开始实现 | 10% |
| In progress | 已有部分实现或证据，验收未完成 | 50% |
| In review | 实现已存在，但缺少明确的评审/签字产物 | 90% |
| Done | 仓库/部署证据满足该工作包的要求 | 100% |

提交是工作包的证据，不作为独立任务。GitHub 的 Issue 和 PR 共用一套编号。2026-10-01 仓库共有 **95 个 PR**：
87 个已合并、2 个未合并、6 个关闭未合并（#2、#3、#17、#95、#97、#100）。复核时的 `70fcb6d` `main` 基线含 241 个
提交。2026-10-07 共有 **168 个 PR**（158 个已合并、10 个关闭未合并、无未合并的打开 PR），`main` 的 `e4b3f13`
含 317 个提交。

## 提案 WBS 审计

| WBS | 工作包 | 状态 | 主要证据或剩余缺口 |
| --- | --- | --- | --- |
| 1.1 | 功能与非功能需求 | Done | 提案第 3–4 节；`docs/PROJECT_SCOPE.md`；PR #62 |
| 1.2 | 范围定义与导师审阅 | Done | 导师审阅了 MVP 演示、签署了提交的提案材料、认可了该检查点，并评估当时整个项目完成约 70–80% |
| 1.3 | 目标与核心愿景 | Done | README 中的目标和已部署产品 |
| 2.1 | 竞品分析 | Done | 提案中的背景研究和选定的差异点 |
| 2.2 | 隐私与 OWASP 威胁建模 | Done | [THREAT_MODEL.zh-CN.md](THREAT_MODEL.zh-CN.md) v1.0：STRIDE 威胁模型、实测 Argon2id 成本、密钥保管与元数据决策，以及 20 项发现登记表（Issue #60）。属于自评加一次同伴评审，没有独立外部评审 |
| 2.3 | 目标用户与相关方 | Done | 提案中的相关方，以及已实现的用户/RBAC 角色 |
| 3.1 | UI/UX 与 Figma 原型 | Done | 已实现并部署的用户流程和 PR #46 |
| 3.2 | REST API 与 FastAPI 模块设计 | Done | `docs/API_DESIGN.md` 和公开的 OpenAPI/Swagger 契约 |
| 3.3 | MySQL Schema 与迁移设计 | Done | Alembic head `0011_must_change_password`、生产 SQL、PR #1、#24、#103、#106 和 #145 |
| 3.4 | AES/RSA 混合流程设计 | Done | `docs/SECURITY_FLOWS.md` 和带认证的信封实现 |
| 3.5 | 教育页面设计 | Done | `/education`、算法浏览器、练习区和知识搜索 |
| 4.1 | Vue 前端 | Done | Vue 3/TypeScript 应用、测试、类型检查和构建 |
| 4.2 | FastAPI 后端模块 | Done | 认证、密钥、文件与文件夹、分享、审计、管理（统计、账户详情、完整性、安全 Agent）和恢复 API |
| 4.3 | MySQL 与 Alembic 实现 | Done | MySQL 8.4 staging、迁移和最小权限生产 SQL |
| 4.4 | AES-GCM 加密 | Done | 浏览器端 AES-128/192/256-GCM（CT-1.7）和 AES-256-GCM-SIV（#145），另有 ChaCha20-Poly1305 和 XChaCha20-Poly1305 |
| 4.5 | RSA-OAEP 密钥包装 | Done | 所有者/恢复/接收者的 DEK 包装；PR #34 |
| 4.6 | SHA-256 与篡改检测 | Done | 带认证的信封、下载校验和完整性提示界面 |
| 4.7 | Argon2id 与受保护私钥 | Done | 密码哈希和浏览器保护的账户密钥包 |
| 4.8 | RBAC 与会话管理 | Done | 服务器端强制、refresh 轮换、登出撤销（#89）和按角色显示的管理/恢复界面（#55） |
| 4.9 | 审计日志 | Done | 哈希链事件、单文件历史和修正后的可见性规则 |
| 5.1 | 功能与端到端测试 | Done | `e2e-live` 不跳过地运行所有实时后端测试和 Chromium 主流程测试；`mysql-gate` 在 MySQL 8.4 上运行全部测试，含并发和故障注入，有任何跳过即失败；CI 中运行篡改演练（Issue #53、#58、#90、#93）；另有 Chromium 测试覆盖篡改视图、手机宽度、问答助手和语言切换；2026-10-03/04 对 staging 做了压测（#140），100 用户时的失败已修复并重测（#163、#172）；修复之后于 2026-10-09 经公网地址重跑压测，100 个用户时服务器错误为 0，7,444 次校验下载完整性失败 0 次（[报告](performance/REPORT-2026-10-09.zh-CN.md)）。仍不是长时间运行的混沌测试 |
| 5.2 | 密码学正确性测试 | Done | 原语、信封、篡改、上传/下载和实时集成测试 |
| 5.3 | OWASP 与安全测试 | In review | 已有加固/回归测试、隔离篡改演练、OWASP ZAP 基线扫描（2026-10-04，2026-10-12 复扫，两次都是 0 FAIL）和 [THREAT_MODEL.zh-CN.md](THREAT_MODEL.zh-CN.md) 自评加一次同伴评审（Issue #60）。要变成 Done 还缺**独立的外部评审**：团队以外没有人审过威胁模型或测过部署。另外，F-01 已通过 CI 门禁部署（#117）缓解，两项 *建议* 级发现（F-02、F-03）仍未处理，F-04 已由 #205 缓解 |
| 5.4 | 非专业用户可用性测试 | Done | 证据是非正式的真实使用，不是正式研究：导师、四位组员、FIT3162 教学团队和其他同学用自己的账户使用过 staging，遇到的问题都公开修掉了（例如 #209：错误样式、完整性检查进度、还在操作时密钥被重新锁上、中文措辞）。正式研究**没有进行**（Issue #115 于 2026-10-04 以 not planned 关闭），所以没有 SUS 分数，也没有各任务完成率，NFR2 也从不说成已正式验证。研究材料于 2026-10-05 删除（保留在 git 历史中，PR #114） |

**WBS 汇总：** 23 项 Done、1 项 In review、0 项 In progress、0 项 Backlog（5.4 于 2026-10-09 依据上面的非正式使用证据改为 Done）。
看板的简单平均完成度为 99.6%（(23 × 100 + 90) / 24）；这是追踪指标，不是评分，也不是按工作量加权的挣值。2026-09-07 的汇总写的是
20 Done、3 In progress、1 Backlog（89.6%），与它自己的表格不一致（表中当时已是 21 项 Done）。

## 里程碑审计

| 里程碑 | 状态 | 证据或退出条件 |
| --- | --- | --- |
| M1 范围确定 | Done | 已评估的提案和持续维护的范围文档 |
| M2 REST API 契约 | Done | 有文档的线上 OpenAPI 契约 |
| M3 Figma 原型评审 | Done | 导师审阅了 MVP/界面演示、签署了提交材料、认可了检查点，并评估当时整个项目完成约 70–80%；这些界面现在也已实现并部署 |
| M4 核心密码学模块 | Done | AES、RSA、SHA/完整性、Argon2id 和 ChaCha20 的实现与测试 |
| M5 功能冻结 | Done | 浏览器 MVP 完成；剩余工作明确归类为加固/保证 |
| M6 全系统集成 | Done | 公开 HTTPS 环境和线上双账户 MVP 测试 |
| M7 最终演示就绪 | Done | P0 的 CI、MySQL 和备份阻碍都已带证据关闭；演示脚本、脚本化篡改演示、预先分享的演示文件和备用视频已就绪（#167、#164、#173）；最后一条验收标准（AC7）由 #200 完成。可用性只有非正式真实使用；正式研究（#115）已以 not planned 关闭 |

**里程碑汇总：** 7 项全部 Done。导师 70–80% 的评估是已完成历史检查点的证据，不代表当前仓库
的完成度恰好是 70–80%。

## 陈泰（Chen Tai）密码学贡献追溯

九个 CT 工作包是在团队采用 PR 评审之前直接提交到 `main` 的。它们已经是当前 `main` 的祖先提交，不能再
cherry-pick 或重复合并。下表通过精确提交把每个工作包署名给**陈泰**；`changelog/work-packages/crypto-track.md`
保留为只读历史档案。新的 CT 工作和其他贡献者的工作记在团队 changelog、README 和 TODO 中，而不是单独的个人
追踪视图。

| 工作包 | 核实的范围 | 提交 |
| --- | --- | --- |
| CT-1.0 | 准备密码学开发环境和文档；未改动应用或密码学实现 | [`9593e753`](https://github.com/jsonrar/fyp-secure-file-platform/commit/9593e753ecadfcc37f3afb56c5f1f92bf3aaea29) |
| CT-1.1 | 审计已有密码学基线并记录限制；未实现新原语 | [`99e2f972`](https://github.com/jsonrar/fyp-secure-file-platform/commit/99e2f972862c55d5f39d066152bb491cac8164bc) |
| CT-1.2 | 实现浏览器密码学原语 | [`415202e6`](https://github.com/jsonrar/fyp-secure-file-platform/commit/415202e661b8c8da30b40458424a8361d6febdb5) |
| CT-1.3 | 定义并验证加密文件信封 | [`9f89ea56`](https://github.com/jsonrar/fyp-secure-file-platform/commit/9f89ea56867ec086f1d2a721942a10c4868a128d) |
| CT-1.4 | 完成浏览器加密上传 | [`8e174c6e`](https://github.com/jsonrar/fyp-secure-file-platform/commit/8e174c6e10ff601e06b8f60243ec8b64e8369380) |
| CT-1.5 | 提供恢复公钥包装 | [`f3c36a20`](https://github.com/jsonrar/fyp-secure-file-platform/commit/f3c36a20aa88fd8395b224a9b495d745dc1be62e) |
| CT-1.6 | 接通加密文件列表 | [`aa4e8589`](https://github.com/jsonrar/fyp-secure-file-platform/commit/aa4e858965c61af06e2390bff2a8d55092abfd84) |
| CT-1.7 | 新增可选 AES 密钥长度 | [`e04f5fcd`](https://github.com/jsonrar/fyp-secure-file-platform/commit/e04f5fcdd170e1dad2c62b91139af93a02da97fe) |
| CT-1.8 | 新增 ChaCha20-Poly1305 | [`6c8821a5`](https://github.com/jsonrar/fyp-secure-file-platform/commit/6c8821a5dd00edc58b8c6dce7ef7a5bad749b4a9) |

当前代码的回归证据比历史提交信息更有力：针对性的前端原语、信封、上传、下载和分享测试通过 **147 个测试**，
针对性的后端迁移/模型/生产 SQL 测试通过 **10 个测试**。这不能代替仍需的 CI、浏览器 E2E、MySQL 或独立安全证据。

## 产品验收审计

| 标准 | 状态 | 证据或剩余缺口 |
| --- | --- | --- |
| AC1 注册与受保护的 RSA 私钥 | Done | 浏览器生成密钥和受保护的私钥包 |
| AC2 算法选择与只上传密文 | Done | 六种可选认证加密算法和客户端加密；上传时显示真实的加密步骤和明文与密文的字节对比（#156） |
| AC3 接收者用自己的 passphrase 解密 | Done | 接收者公钥重包装和线上双账户证明；分享前发送者确认接收者的密钥指纹（#160） |
| AC4 解密成功前检测篡改 | Done | 认证解密/完整性拒绝和界面错误提示 |
| AC4a 篡改后的恢复（老师提出的完整性与恢复要求） | Done | 每日巡检（由健康发布自动安装，#134；staging 每天 05:30 运行）、管理员 Integrity 标签页、`restore_file.py`、`mysql-gate` 中的演练步骤（BACKUP_AND_RECOVERY 第 9 节）；现场篡改演示（#164） |
| AC8 解决明确自动化问题的 AI agent（导师建议） | Done（v2，基于规则） | 管理员 → Security agent：输入、十三条规则、Critical/High/Medium/Low 输出及建议操作、明确的边界；v2（#137）每天运行，出现 Critical/High 时邮件通知团队，能发现猜密码后成功的登录，并报告当前的登录限流 —— [SECURITY_AGENT.zh-CN.md](SECURITY_AGENT.zh-CN.md) |
| AC5 带时间戳的操作者/访问审计 | Done | 上传/下载/分享/撤销事件和单文件历史 |
| AC6 交互式密码学教育 | Done | AES/RSA/SHA/Argon2id 内容和练习区 |
| AC7 可关闭的四阶段进度流程 | Done | 四个计时阶段（#156）：在浏览器读取文件 → 加密并自检 → 包装文件密钥 → 上传密文，然后完成；没有任务运行时回执可用关闭按钮收起（#200），由主流程浏览器测试检查 |

## 近期证据优先级

1. 安全签核（WBS 5.3）：唯一缺的是独立的外部评审。非专业用户可用性（WBS 5.4）依据非正式真实使用已是 Done；NFR2 只能这样描述，
   绝不说成已正式验证（正式研究 Issue #115 已按 not planned 关闭）。
2. 决定两项未处理的 *建议* 级安全发现（F-02、F-03）：把恢复私钥移入提议的保管方式、演示后关闭 `/docs`。（F-01，CI 门禁
   部署，已于 2026-10-01 完成；F-04，拒绝已知弱 passphrase，已于 2026-10-08 由 #205 完成。）
3. 在全新 VPS 上实测 4 小时整站恢复（Issue #56 的后续）。

2026-10-01 复核之后已完成：staging 容量与性能测试（#140，PR #155）、两个并发死锁（#139，PR #154），以及 100 用户时的
数据库连接池失败及其 staging 重测（PR #163、#172），2026-10-09 经公网地址的修复后压测
（[报告](performance/REPORT-2026-10-09.zh-CN.md)），以及 AC7 关闭按钮（#200）。

这些记录应在改变其证据的同一个 PR 中更新。运行时改动只有在合并的 SHA 部署完成且受影响的线上路径验证过之后才算 Done。
