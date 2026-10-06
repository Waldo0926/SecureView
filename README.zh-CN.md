# SecureView

[English](README.md) · **中文**

> 一个安全文件加密与共享平台，由 Monash University Malaysia **FIT3161/FIT3162 MCS21** 四人毕业设计团队开发。

[![在线站点](https://img.shields.io/badge/在线站点-secureview.tech-2563eb?style=for-the-badge&logo=googlechrome&logoColor=white)](https://secureview.tech)
[![API 文档](https://img.shields.io/badge/API-Swagger_UI-85ea2d?style=for-the-badge&logo=swagger&logoColor=black)](https://secureview.tech/docs)
[![状态](https://img.shields.io/badge/状态-Active_FYP-16a34a?style=for-the-badge)](#当前项目状态)
[![源码](https://img.shields.io/badge/源码-评估期间私有-475569?style=for-the-badge)](#源码开放情况)
[![许可证](https://img.shields.io/badge/许可证-保留所有权利-dc2626?style=for-the-badge)](LICENSE)

**公开作品集快照同步于：2026年10月6日。**

## 项目概览

SecureView 会在**浏览器内、上传之前**完成文件加密，服务器只保存密文和被包裹的密钥材料；授权用户可以进行共享、撤销、下载和访问审计。

服务器保存公钥、加密后的私钥包、密文和被包裹的文件密钥。用户的加密口令、明文私钥、明文文件密钥和明文文件不会进入API请求或数据库记录。

浏览器端MVP已经在 **[https://secureview.tech](https://secureview.tech)** 端到端运行。这个公开仓库是经过筛选的作品集镜像：展示当前产品、架构、测试证据、截图、演示媒体和我的贡献，但不公开私有评估仓库、凭据、测试账号或内部运维秘密。

## 当前项目状态

现在的版本已经明显超过最初MVP范围，包括：

- **六种浏览器端AEAD算法**：AES-128-GCM、AES-192-GCM、AES-256-GCM、AES-256-GCM-SIV、ChaCha20-Poly1305和XChaCha20-Poly1305；默认仍为AES-256-GCM。
- **RSA-OAEP密钥包裹**：文件DEK在浏览器内重新包裹给每个授权接收者的公钥。
- **受控共享与撤销**：可按精确用户名或邮箱共享，共享前确认接收者密钥指纹，并可撤销后续经服务器的访问。
- **文件详情与加密证据**：显示明文/密文精确大小、密文SHA-256、访问者、操作记录，并支持下载密文、密文预览和真实加密步骤耗时。
- **完整性保护**：下载前SHA-256校验、AEAD认证标签校验、每日完整性巡检和管理员Integrity视图。
- **防篡改审计记录**：安全敏感事件采用哈希链，管理员可以验证完整链。
- **基于角色的管理**：USER、ADMIN和RECOVERY_OFFICER，并带有受管控的恢复流程。
- **Security Agent**：只读、基于规则的安全管理视图，把审计、完整性和恢复事件整理成带证据和建议操作的发现。
- **账户管理**：管理员可以查看账户元数据，并把用户的**登录密码**重置为一次性临时密码；用户随后可在Settings中改成自己的登录密码。加密口令始终只在客户端，管理员看不到。
- **Help Assistant**：在浏览器本地根据项目内容回答使用方法和产品问题，不调用大模型，也不会把问题发到远程服务。
- **中英双语**：公开页面和登录后的工作区均支持English / 简体中文切换。
- **新版界面**：当前“Sealed”视觉系统包括登录后侧边栏、居中页面标题、上传Seal Receipt、响应式My Files详情侧栏、手机布局，以及重新设计的公开页面。

## 最新图文流程

公开仓库原来的4张截图来自旧版界面，已经移除。下面6张是**2026年10月界面改版完成后重新拍摄**的最新版图文流程，使用虚构演示数据。

| 1. 选择文件 | 2. 浏览器内加密 |
|---|---|
| ![选择文件](https://secureview.tech/walkthrough/01-select-zh.webp) | ![浏览器内加密](https://secureview.tech/walkthrough/02-encrypt-zh.webp) |

| 3. 管理加密文件 | 4. 分享给已确认的接收者 |
|---|---|
| ![管理加密文件](https://secureview.tech/walkthrough/03-file-zh.webp) | ![分享给已确认的接收者](https://secureview.tech/walkthrough/04-recipient-zh.webp) |

| 5. 接收者本地解锁 | 6. 验证并下载 |
|---|---|
| ![接收者本地解锁](https://secureview.tech/walkthrough/05-unlock-zh.webp) | ![验证并下载](https://secureview.tech/walkthrough/06-download-zh.webp) |

### 演示视频

Help页面使用了3段按新版界面重新录制的视频：

- **[SecureView工作流程](https://secureview.tech/videos/how-it-works.mp4)**——整体流程与信任边界。
- **[加密并上传](https://secureview.tech/videos/encrypt-upload.mp4)**——本地加密、封存和上传。
- **[共享并打开](https://secureview.tech/videos/share-open.mp4)**——确认接收者、共享与本地解锁。

更多海报、英文/中文图文流程和媒体清单见 **[docs/DEMO.md](docs/DEMO.md)**。

## 架构

~~~mermaid
flowchart LR
U[用户浏览器<br/>WebCrypto + AEAD] -->|HTTPS| N[Nginx]
N --> F[Vue 3 + TypeScript SPA]
N -->|/api/v1| A[FastAPI]
A --> D[(MySQL 8.4)]
A --> S[(加密对象存储)]
A --> L[审计链、RBAC、完整性与Security Agent]
classDef client fill:#dbeafe,stroke:#2563eb,color:#0f172a
classDef server fill:#ede9fe,stroke:#7c3aed,color:#0f172a
classDef data fill:#dcfce7,stroke:#16a34a,color:#0f172a
class U,F client
class N,A,L server
class D,S data
~~~

Vue前端负责文件内容加密和账户密钥处理。FastAPI后端负责认证授权、请求校验、业务事务、审计追加，以及保存密文和元数据，但不解密用户文件。

| 领域 | 技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Vite、WebCrypto |
| 后端 | FastAPI、Python、Pydantic、SQLAlchemy、Alembic |
| 数据库 | MySQL 8.4 |
| 密码学 | AES-GCM、AES-GCM-SIV、(X)ChaCha20-Poly1305、RSA-OAEP、Argon2id、SHA-256 |
| 测试 | pytest、Vitest、Playwright、自研压测工具、OWASP ZAP、pip-audit、npm audit |
| 基础设施 | Linux、Nginx、Docker、systemd、GitHub Actions自托管runner |

## 安全设计

- 每个文件在浏览器中生成独立的DEK。
- 认证加密同时保护文件机密性和完整性。
- RSA-OAEP（SHA-256）分别为所有者和每个授权接收者包裹文件密钥。
- 登录密码在服务器端使用Argon2id单向哈希。
- 独立的加密口令只在浏览器中用于派生密钥加密材料，不发送到服务器。
- 如果忘记加密口令，可使用用户自行保存的私钥文件恢复访问。
- 审计记录使用哈希链，事后修改历史可以被发现。
- 存储配额、磁盘空间保护和限流用于降低上传滥用风险。
- 由于服务器只保存密文，无法对共享内容进行恶意软件扫描，因此对可执行文件和可含宏文件会向接收者给出风险提醒。

SecureView是**学术原型**，并不等同于经过独立安全审计的生产系统。公开版安全模型与剩余风险见 **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)**。

## 测试与验证

### 自动化测试

- 当前main分支 **503个后端单元测试**、**810个前端测试**通过。
- 连接真实MySQL 8.4的完整后端套件共有 **633个测试**，分支覆盖率约 **85%**。
- 线上端到端测试覆盖：邮件验证码注册、会话续期与重放拒绝、账户解锁、六种算法、上传/下载、共享/撤销、审计可见性、越权拒绝和账户删除。
- Playwright通过真实浏览器跑注册、上传、解锁、下载、逐字节比对、共享、撤销和退出。
- 并发测试覆盖会话上限、审计哈希链、密钥重新包裹、重复共享和恢复竞态。
- 故障注入覆盖数据库提交失败、对象存储失败、损坏信封和伪造签名。
- 密码学向量会与OpenSSL、libsodium和RFC8452参考结果逐字节比对。

### 容量与性能

2026年10月3–4日的预发布环境测试记录：

- **22,264次操作**。
- **5,094次下载验证**，**0次完整性失败**。
- 常见文件类型从1MB到 **500MB** 均逐字节往返一致。
- 实测 **50个并发用户**以内无服务器错误。
- 100用户测试暴露出数据库连接池与线程池之间的相互等待：CPU平均只有3%，上传失败率却一度达到约80%。
- 修复后，100用户上传失败率从 **80%降到0%**，吞吐从 **0.33次/秒提升到56次/秒**，预发布复测 **102/102次上传**成功。

### 安全检查

- OWASP ZAP基线扫描：**0 FAIL、8 WARN、59 PASS**；其发现的静态资源安全响应头问题随后已在Nginx修复。
- pip-audit和npm audit：记录时生产依赖未发现问题。
- 篡改演练会直接修改存储密文，并确认下载被拒绝；即使同时修改记录的SHA-256，AEAD认证仍会拒绝。
- 加密异地备份通过干净主机恢复演练验证。

更多内容见 **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)**。

## 我的贡献

截至 **2026年10月6日**，项目共合并158个PR，其中 **137个由我提交**；我共提交 **145个PR**，并创建 **29个issue**。

### 测试与质量工程

- 编写负载/容量测试工具并完成预发布容量测试。
- 定位并修复100用户数据库连接池故障，以及两个MySQL并发死锁，并补充回归测试。
- 建立CI质量闸门、MySQL 8.4发布闸门、线上端到端测试、并发/故障注入覆盖和Playwright浏览器测试。
- 搭建隔离篡改演练与线上篡改演示。
- 增加手机宽度浏览器检查、布局审计，以及后续全站文字审计。
- 运行OWASP ZAP、pip-audit、npm audit并修复安全响应头问题。

### 安全与产品功能

- 新增AES-256-GCM-SIV和XChaCha20-Poly1305，使文件加密方案扩展到六种。
- 开发Security Agent及后续证据/事件去重能力。
- 搭建完整性与恢复链路、每日检查和单文件恢复视图。
- 实现上传滥用限制、高风险文件提醒和接收者密钥指纹确认。
- 开发Help Assistant、中英文界面、管理员控制台、账户详情/登录密码重置、文件详情、密文预览和可视化加密步骤。
- 实现早期核心浏览器流程，包括下载解密、接收者密钥重新包裹、私钥文件解锁、空闲锁定、会话续期和账户删除。

### 部署、运维与文档

- 搭建并维护只部署CI通过提交的受保护自动部署。
- 部署和加固Nginx/HTTPS、安全响应头、限流和fail2ban。
- 加入加密异地备份、干净主机恢复验证、数据一致性检查、监控和脱敏运维证据。
- 维护中英双语架构、安全、威胁模型、测试、性能和发布文档，以及期末展示证据。

## 公开文档

- **[CHANGELOG.md](CHANGELOG.md)**——筛选后的公开项目里程碑。
- **[docs/README.md](docs/README.md)**——文档与证据索引。
- **[docs/DEMO.md](docs/DEMO.md)**——最新中英文截图与视频。
- **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)**——公开安全模型与局限。
- **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)**——测试策略与性能数据。

## 在线站点

访问 **[https://secureview.tech](https://secureview.tech)**，请保留https://前缀。

## 源码开放情况

主实现仓库在大学团队项目评估期间保持私有。本作品集仓库刻意不包含私有源码、凭据、测试账号秘密、私钥材料和内部部署细节。

在学校和团队要求允许后，可能会进一步公开实现材料。

---

**项目：** SecureView · **学校：** Monash University Malaysia · **课程：** FIT3161 / FIT3162 · **团队：** MCS21 · **团队人数：** 四人
