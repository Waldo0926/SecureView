# SecureView

[English](README.md) · **中文**

> 一个安全文件加密与共享平台，由 Monash University Malaysia **FIT3161/FIT3162 MCS21** 四人毕业设计团队开发。

[![在线站点](https://img.shields.io/badge/在线站点-secureview.tech-2563eb?style=for-the-badge&logo=googlechrome&logoColor=white)](https://secureview.tech)
[![API 文档](https://img.shields.io/badge/API-Swagger_UI-85ea2d?style=for-the-badge&logo=swagger&logoColor=black)](https://secureview.tech/docs)
[![状态](https://img.shields.io/badge/状态-已上线运行-16a34a?style=for-the-badge)](#功能)
[![源码](https://img.shields.io/badge/源码-评估期间私有-475569?style=for-the-badge)](#源码开放情况)
[![许可证](https://img.shields.io/badge/许可证-保留所有权利-dc2626?style=for-the-badge)](LICENSE)

![Vue 3](https://img.shields.io/badge/Vue_3-TypeScript-42b883?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?logo=fastapi&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.4-4479a1?logo=mysql&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-pytest,_Vitest,_Playwright-2ead33?logo=playwright&logoColor=white)

**2026年10月18日与团队仓库同步。**

## 项目概览

SecureView 在**浏览器内、上传之前**完成文件加密。服务器只保存密文和被包裹的密钥材料，授权用户可以共享、撤销、下载文件并查看访问记录。

服务器保存公钥、加密后的私钥包、密文和被包裹的文件密钥。用户的加密口令、明文私钥、明文文件密钥和明文文件不会出现在API请求或数据库记录里。

SecureView 已经在 **[https://secureview.tech](https://secureview.tech)** 正式运行（请输入完整的 https:// 地址）。这个仓库是项目的作品集页面，介绍产品、架构、测试结果、截图、视频和我的贡献，不包含团队源码、凭据、测试账号和服务器细节。

### 一览

| | |
|---|---|
| **项目** | 文件在浏览器内加密后再存储和共享的Web应用 |
| **团队** | 四人毕业设计（FIT3161/FIT3162，MCS21组） |
| **我的部分** | 团队合并的203个PR中182个由我提交：测试与CI、安全功能、部署与运维 |
| **技术栈** | Vue 3 + TypeScript、FastAPI、MySQL 8.4、Nginx、Docker、GitHub Actions |
| **测试** | 718个后端单元测试，连接MySQL的786个测试覆盖率86.6%，899个前端测试，977个前端线上测试，57个浏览器测试 |
| **压测** | 22,264次操作，0次完整性失败；修复100用户并发问题，上传失败率从最高78%降到0% |

## 我的贡献

截至 **2026年10月17日**，项目共合并203个PR，其中 **182个由我提交**；我共提交 **190个PR**，并创建 **29个issue**。10月6日以后合并的PR全部是我提交的。

### 测试与质量工程

- 编写负载/容量测试工具并完成预发布容量测试。
- 定位并修复100用户数据库连接池故障，以及两个MySQL并发死锁，并补充回归测试。
- 建立CI质量闸门、MySQL 8.4发布闸门、线上端到端测试、并发/故障注入覆盖和Playwright浏览器测试。
- 搭建隔离环境和线上环境的密文篡改测试。
- 增加手机宽度浏览器检查、布局审计，以及后续全站文字审计。
- 运行OWASP ZAP、pip-audit、npm audit并修复安全响应头问题。

### 安全与产品功能

- 新增AES-256-GCM-SIV和XChaCha20-Poly1305，使文件加密方案扩展到六种。
- 开发Security Agent及后续证据/事件去重能力。
- 搭建完整性与恢复链路、每日检查和单文件恢复视图。
- 实现上传滥用限制、高风险文件提醒和接收者密钥指纹确认。
- 加入修改加密口令和口令强度检查，让AES-192-GCM在所有浏览器可用，并在服务器端也校验加密测试向量。
- 加固账户：注册时不再暴露邮箱是否已存在，删除账户有频率限制，管理员重置后服务器强制改密码，最后一个管理员账户受保护。
- 审计日志加入按事件类型、结果、日期和关键词筛选并分页加载；每次下载和共享都重新输入口令。
- 开发Help Assistant、中英文界面、管理员控制台、账户详情/登录密码重置、文件详情、密文预览和可视化加密步骤。
- 实现早期核心浏览器流程，包括下载解密、接收者密钥重新包裹、私钥文件解锁、空闲锁定、会话续期和账户删除。

### 部署、运维与文档

- 搭建并维护只部署CI通过提交的受保护自动部署。
- 部署和加固Nginx/HTTPS、安全响应头、限流和fail2ban。
- 加入加密异地备份、干净主机恢复验证、数据一致性检查、监控和脱敏运维证据。
- 维护中英双语架构、安全、威胁模型、测试、性能和发布文档，以及期末展示证据。

## 功能

- **六种浏览器端AEAD算法**：AES-128-GCM、AES-192-GCM、AES-256-GCM、AES-256-GCM-SIV、ChaCha20-Poly1305和XChaCha20-Poly1305，默认AES-256-GCM。
- **RSA-OAEP密钥包裹**：浏览器把文件DEK重新包裹给每个授权接收者的公钥。
- **受控共享与撤销**：按精确用户名或邮箱共享，共享前确认接收者密钥指纹，并可撤销之后经服务器的访问。
- **文件详情与加密证据**：显示明文/密文精确大小、密文SHA-256、访问者、操作记录，支持下载密文、密文预览和真实加密步骤耗时。
- **完整性保护**：下载前SHA-256校验、AEAD认证标签校验、每日完整性巡检和管理员Integrity视图。
- **防篡改审计记录**：安全敏感事件采用哈希链，管理员可以验证整条链，日志可以按事件类型、结果、日期和关键词筛选。
- **基于角色的管理**：USER、ADMIN和RECOVERY_OFFICER三种角色，并带有受管控的恢复流程。
- **Security Agent**：只读、基于规则的管理视图，把安全发现按优先级排好，并附上证据和建议操作。
- **口令安全**：用户可以修改加密口令，太弱或和账户信息相关的口令会被拒绝，每次下载和共享都要重新输入口令。
- **账户管理**：管理员可以查看账户元数据，并把用户的**登录密码**重置为一次性临时密码，用户之后在Settings里改成自己的密码。加密口令只在客户端，管理员看不到。
- **Help Assistant**：在浏览器本地根据项目内容回答使用和产品问题，不用大模型，也不会把问题发到别的服务。
- **中英双语**：公开页面和登录后的工作区都能切换English / 简体中文。
- **新版界面**：“Sealed”设计，包括登录后侧边栏、居中页面标题、上传Seal Receipt、响应式My Files详情侧栏、手机布局和重新设计的公开页面。

## 图文流程

2026年10月界面改版后拍摄，使用虚构的示例数据。

| 1. 选择文件 | 2. 浏览器内加密 |
|---|---|
| ![选择文件](https://secureview.tech/walkthrough/01-select-zh.webp) | ![浏览器内加密](https://secureview.tech/walkthrough/02-encrypt-zh.webp) |

| 3. 管理加密文件 | 4. 分享给已确认的接收者 |
|---|---|
| ![管理加密文件](https://secureview.tech/walkthrough/03-file-zh.webp) | ![分享给已确认的接收者](https://secureview.tech/walkthrough/04-recipient-zh.webp) |

| 5. 接收者本地解锁 | 6. 验证并下载 |
|---|---|
| ![接收者本地解锁](https://secureview.tech/walkthrough/05-unlock-zh.webp) | ![验证并下载](https://secureview.tech/walkthrough/06-download-zh.webp) |

### 操作视频

Help页面用了3段在新版界面上录制的1080p视频：

- **[SecureView工作流程](https://secureview.tech/videos/how-it-works.mp4)**：整体流程与信任边界。
- **[加密并上传](https://secureview.tech/videos/encrypt-upload.mp4)**：本地加密、封存和上传。
- **[共享并打开](https://secureview.tech/videos/share-open.mp4)**：确认接收者、共享与本地解锁。

视频封面和英文图文流程见 **[docs/MEDIA.md](docs/MEDIA.md)**。

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

Vue前端负责文件加密和账户密钥。FastAPI后端负责认证授权、请求校验、业务事务、追加审计记录，以及保存密文和元数据，从不解密用户文件。

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
- 登录密码在服务器端用Argon2id哈希。
- 独立的加密口令只在浏览器中用于派生密钥加密材料，不发送到服务器。
- 忘记加密口令时，可以用自己保存的私钥文件恢复访问。
- 审计记录使用哈希链，事后修改历史能被发现。
- 存储配额、磁盘空间保护和限流用来减少上传滥用。
- 服务器只有密文，没法对共享文件做恶意软件扫描，所以接收可执行文件或可含宏文件时会提示风险。

SecureView 是已经上线运行的**大学团队项目**，安全性**没有经过独立审计**。公开版安全模型和已知局限见 **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)**。

## 测试与验证

### 自动化测试

2026年10月13日CI运行结果：

- **718个后端单元测试**通过（覆盖率81.8%）。
- 连接真实MySQL 8.4的完整后端套件共 **786个测试**，0个跳过，覆盖率 **86.6%**。
- **899个前端测试**通过，连接真实后端的前端线上套件跑 **977个测试**，0个跳过。
- **57个Playwright浏览器测试**。
- 线上端到端测试覆盖：邮件验证码注册、会话续期与重放拒绝、账户解锁、六种算法、上传/下载、共享/撤销、审计可见性、越权拒绝和账户删除。
- Playwright通过真实浏览器跑注册、上传、解锁、下载、逐字节比对、共享、撤销和退出。
- 并发测试覆盖会话上限、审计哈希链、密钥重新包裹、重复共享和恢复竞态。
- 故障注入覆盖数据库提交失败、对象存储失败、损坏信封和伪造签名。
- 密码学向量与OpenSSL、libsodium和RFC 8452参考结果比对。

### 容量与性能

2026年10月3日和4日的预发布环境测试记录：

- **22,264次操作**。
- **5,094次下载验证**，**0次完整性失败**。
- 常见文件类型从1MB到 **500MB** 都逐字节往返一致。
- 实测 **50个并发用户**以内无服务器错误。
- 100用户测试暴露出数据库连接池和线程池互相等待：CPU平均只有3%，却有65%到78%的上传返回HTTP 500。
- 修复后，100用户上传失败率降到 **0%**，吞吐从 **0.33次/秒提升到56次/秒**，预发布复测 **102/102次上传**成功。

2026年10月9日通过公网地址又跑了一次：**18,256次操作**、**7,444次下载验证**，**0次完整性失败**，100用户时没有HTTP 500。部分上传收到HTTP 429，因为整个测试来自同一个地址，触发了单地址限流。

### 安全检查

- OWASP ZAP基线扫描：**0 FAIL**。在Nginx补上静态资源安全响应头后，结果是 **0 FAIL、5 WARN、62 PASS**，2026年10月12日复扫结果相同。
- pip-audit和npm audit：记录时生产依赖没有发现问题。
- 篡改演练直接修改存储的密文，确认下载被拒绝；就算同时改掉记录的SHA-256，AEAD认证也会拒绝。
- 加密异地备份用干净主机恢复演练验证。

更多内容见 **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)**。

## 公开文档

- **[CHANGELOG.md](CHANGELOG.md)**：公开里程碑记录。
- **[docs/README.md](docs/README.md)**：文档索引。
- **[docs/MEDIA.md](docs/MEDIA.md)**：中英文截图和视频。
- **[docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md)**：公开安全模型与局限。
- **[docs/TESTING_AND_PERFORMANCE.md](docs/TESTING_AND_PERFORMANCE.md)**：测试策略与性能数据。

## 源码开放情况

主实现仓库在大学团队项目评估期间保持私有。这个仓库不包含团队源码、凭据、测试账号秘密、私钥材料和内部部署细节。

如果学校和团队允许，之后可能会公开更多实现材料。

---

**项目：** SecureView · **学校：** Monash University Malaysia · **课程：** FIT3161 / FIT3162 · **团队：** MCS21 · **团队人数：** 四人

**我的另一个线上项目：** [Monash Hub](https://github.com/Waldo0926/monash-hub)，地址 [monashhub.secureview.tech](https://monashhub.secureview.tech)，是我个人做的项目，放在子域名上，不属于 SecureView 团队的工作。
