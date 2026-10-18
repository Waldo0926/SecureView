# 端到端验证

[English](E2E_TESTING.md) | 简体中文

`frontend/src/crypto/mvp.integration.test.ts` 按用户的方式使用产品——客户端里是真实的密码学、通过 HTTP
访问真实后端、两个真实账户——并断言单元测试触及不到的事情。

只有环境变量指定了后端和两个账户时它才会运行，所以 `npm test` 保持离线和确定性。

## 它证明了什么

| 步骤 | 被检验的说法 |
| --- | --- |
| 登录 | 会话同时带有两种令牌，因此可以续期，而不是 30 分钟后失效 |
| 上传 | 元数据信封是 API 真正接受的格式，且每个文件除了包装给所有者，也包装给了恢复公钥 |
| 列表 | 文件显示为自有，并标明所有者 |
| 下载 | 放进去的字节能原样取回，依据只是服务器保存的内容加上 passphrase |
| 分享 | 文件密钥被重新包装给按用户名或邮箱解析出的接收者 |
| 共享用户 | 接收者拥有 `can_download`，没有 `can_share`，也不是所有者 |
| 接收者的列表 | 同一文件显示为**非**自有，并标明发送者 |
| 接收者下载 | **他们用自己的 passphrase 解密**——这正是项目提案原话承诺的 |
| 跨账户拒绝 | 发送者的 passphrase 打不开接收者的账户密钥 |
| 审计记录 | 所有者能看到接收者的下载，每一行都有姓名和时间 |
| 撤销 | 授权被收回 |
| 撤销之后 | 文件从接收者列表中消失，直接请求得到统一的 404 |
| 所有者不受影响 | 撤销别人不会让所有者失去自己的访问 |

两个账户必须使用**不同的加密 passphrase**。如果 passphrase 相同，最重要的断言——接收者用的是自己的密钥而不是
发送者的——就无法与另一种情况区分，测试会悄悄地什么也证明不了。这套测试第一次运行时恰好就有这个缺陷。

## 运行

在目标部署上创建两个账户：

```bash
cd backend
set -a && . /etc/fyp-secure-file-platform/backend.env && set +a
PYTHONPATH=$PWD .venv/bin/python scripts/seed_test_account.py \
  --username e2e-sender --email e2e-sender@secureview.tech \
  --password '<password>' --passphrase '<one passphrase>'
PYTHONPATH=$PWD .venv/bin/python scripts/seed_test_account.py \
  --username e2e-recipient --email e2e-recipient@secureview.tech \
  --password '<password>' --passphrase '<a different passphrase>'
```

然后在 `frontend/` 下：

```bash
E2E_API_BASE=https://secureview.tech/api/v1 \
E2E_SENDER=e2e-sender E2E_SENDER_PASSWORD='...' E2E_SENDER_PASSPHRASE='...' \
E2E_RECIPIENT=e2e-recipient E2E_RECIPIENT_PASSWORD='...' E2E_RECIPIENT_PASSPHRASE='...' \
npx vitest run src/crypto/mvp.integration.test.ts
```

这套测试上传一个文件，结束时再删掉，所以运行后部署保持原样。

## 一次性环境：CI 中运行所有实时测试，一个都不跳过

四个前端测试套件会连接真实后端，缺少环境变量时各自跳过：`crypto/mvp`、`crypto/upload`、
`crypto/passphrase-reset` 和 `e2e/live-stack`。CI 的 `e2e-live` 任务针对全新的 API 进程和一次性 MySQL 8.4
运行全部四个，只要 JUnit 报告里有一个被跳过的测试就判失败（`backend/scripts/check_no_skips.py`）。`crypto/passphrase-reset` 同时覆盖私钥文件重设和凭当前口令修改（#201）。

具体工作由 `backend/tests/e2e/run_live_stack.sh` 完成，所以本地同样一条命令即可：

```bash
DB_HOST=127.0.0.1 DB_PORT=3310 DB_USER=... DB_PASSWORD=... DB_NAME=fyp_local_test \
  bash backend/tests/e2e/run_live_stack.sh      # 加 E2E_COVERAGE=1 统计覆盖率
```

它会迁移 Schema，用 `seed_test_account.py` 创建发送者、接收者和 passphrase 重设账户（各自随机且不同的
passphrase，`@example.com` 地址），提升一个新管理员，启动 `backend/tests/e2e/live_server.py serve`，通过管理员
接口登记恢复公钥，运行 vitest，并在退出时删除所有密钥、邮箱消息和上传的对象。数据库名必须带 `_test`
段，否则服务器拒绝启动。

`live_server.py` 就是未改动的 `create_app()`，只替换了一处：验证邮件写入一个目录而不是真的发送，这样
`e2e/live-stack` 可以完成真实注册。`console` 邮件提供方会把验证码打印到服务器日志里，而 CI 会保留日志。

`e2e/live-stack.integration.test.ts` 不需要预先创建用户。它覆盖：

| 方面 | 断言内容 |
| --- | --- |
| 注册与验证 | 错误验证码被拒绝且不创建任何东西；邮件里的验证码可以注册；已被占用的用户名返回 409 |
| 登录 | 密码错误和账户不存在返回无法区分的 401 |
| 刷新 | 轮换后旧访问令牌失效；重放已用过的刷新令牌会撤销整个会话族，包括刚签发的令牌 |
| 登出 | 访问令牌和刷新令牌都失效 |
| 解锁 | 别人的 passphrase 被拒绝；正确的能打开密钥 |
| 文件算法 | AES-128/192/256-GCM、AES-256-GCM-SIV、ChaCha20-Poly1305 和 XChaCha20-Poly1305 都能往返二进制内容、报告正确的算法，且只提供密文 |
| 分享与撤销 | 对六种套件各做一次：接收者在列表里看到文件、用自己的 passphrase（而不是发送方的）解出相同字节、服务器完整性检查返回 VALID、接收者不能再分享，撤销后读取、下载和完整性检查都得到统一的 404 |
| 审计可见性 | 所有者看到接收者的下载；接收者只看到与自己有关的行 |
| 角色拒绝 | 匿名调用得到 401；普通用户访问管理员、链校验和恢复公钥接口得到 403；管理员可以进入且链校验通过 |
| 注销账户 | 密码错误时账户不受影响；注销会结束会话和登录、销毁自有文件，并保持审计链有效 |

### 浏览器冒烟测试

Node 测试套件通过真实 HTTP 运行浏览器自己的代码——API 客户端、WebCrypto 和 Argon2 密钥处理、上传、下载和
分享模块——安全性质就在这些地方。它们看不到的是页面标记：一个接错处理函数的按钮能通过它们全部。
`frontend/browser-tests/golden-path.browser.ts` 补上这个缺口。由 Playwright 驱动的 Chromium 在构建出的页面上
点完整条主流程：

| 步骤 | 驱动方式 |
| --- | --- |
| 注册两个账户 | 两步注册表单：填写账户信息并点 **Send code**、**Next**，再设置加密 passphrase 并点 **Register** |
| 邮箱验证 | 从环境的邮箱目录（与 `e2e/live-stack` 读取的是同一个）读出验证码并填入表单；不会真的发送 |
| 登录 | 登录表单 |
| 上传 | `/upload` 上的文件选择器和 **Start Encryption**，然后 **View Encrypted Files**；在此之前用 **Close the seal receipt** 关闭封存回执，并确认它从页面上消失（#200）。测试会统计 `POST /files/upload` 请求，必须正好一次；完成状态必须是状态提示而不是按钮，点击它也不能发出任何请求（#215） |
| 密文预览 | 行上的 **Encrypted preview** 显示服务器保存的字节，且开头与原文件不同 |
| 文件夹 | 把文件放进文件夹，再移回 **All files** |
| 解锁密钥库 | **Download and decrypt** 弹出的 passphrase 对话框 |
| 下载 | 浏览器自己的下载，与原文件逐字节比对 |
| 分享 | 行上的 **Share** 按钮、分享对话框，然后在接收者与密钥指纹确认处点 **Confirm and share** |
| 接收者看到文件 | 第二个账户的 **Shared with me** 列表，然后用它自己的 passphrase 解密下载 |
| 接收者的文件夹 | 接收者把共享文件放进自己的文件夹；该行提供 **Download and decrypt** 和 **More actions**，没有 **Share** 或 **Delete** |
| 撤销 | 分享对话框中的 **Revoke**，再在确认框点 **Revoke access** |
| 接收者不再看到 | 刷新后接收者的列表 |
| 修改口令 | 设置页 → **Change your encryption passphrase**：输入当前和新口令，看到成功提示（#201） |
| 登出 | 账户菜单里的 **Log out**；之后访问受保护页面会被送回登录页 |

每一步都通过界面驱动，没有一步走 API。界面的 **Log out** 会调用 `POST /auth/logout` 撤销服务端会话族，再清除
浏览器中的令牌和已解锁的密钥。测试断言的是按钮的效果——令牌消失、受保护页面重定向——不再单独核对服务端
撤销（该契约仍由 `e2e/live-stack` 覆盖）。

选择器使用角色、标签和可见文字，在可见文字不唯一的地方用少量 `data-testid`。测试里没有 sleep：每次等待都是
Playwright 的 web-first 断言，邮箱用 `expect.poll` 轮询。它以单 worker、不重试、`failOnFlakyTests` 运行，所以
第二次才通过的测试会让整次运行失败。

#### 本地运行

前置条件：后端 venv、在 `frontend/` 中执行过 `npm ci`、名字带 `_test` 段的一次性 MySQL 8.4 数据库，以及
Playwright 用的 Chromium（只需一次）：

```bash
cd frontend && npx playwright install chromium   # 全新 Linux 主机加 --with-deps
```

然后在仓库根目录：

```bash
# 先跑 Node 实时测试，再跑浏览器测试，共用一个环境
E2E_BROWSER=1 DB_HOST=127.0.0.1 DB_PORT=3310 DB_USER=... DB_PASSWORD=... DB_NAME=fyp_local_test \
  bash backend/tests/e2e/run_live_stack.sh

# 只跑浏览器测试（环境仍会迁移、初始化并在结束时拆除）
E2E_BROWSER=only DB_HOST=... bash backend/tests/e2e/run_live_stack.sh
```

脚本会以指向一次性 API 的 `VITE_API_BASE_URL` 构建前端，Playwright 用 `vite preview` 在 `127.0.0.1:5173` 上
提供这份构建——是生产包而不是开发服务器，且这个源 API 默认就允许。8000 和 5173 端口必须空闲。结果写入
`E2E_BROWSER_REPORT_DIR`（默认 `./e2e-browser-reports`）：`junit.xml` 和 `html/`
（`npx playwright show-report e2e-browser-reports/html`）。每次运行都会注册新账户，而验证码限制为每个 IP 每个
时间窗 20 次，所以反复运行多次时请在中间重建数据库。

#### 幻灯片截图（`E2E_BROWSER=capture`）

`E2E_BROWSER=capture E2E_CAPTURE_DIR=docs/presentation/screenshots` 不跑任何测试套件，只用单独的配置
（`playwright.capture.config.ts`）运行 `frontend/browser-tests/capture/ac4a-recovery.capture.ts`，截下 AC4a 的七张图：
文件 Verified、翻转一个字节后 Modified、被拒绝的下载、Admin → Integrity、安全代理的 Critical `INTEGRITY_DAMAGE` 发现、
写回原始字节后重新 Verified、Admin → Integrity 恢复干净。只有这个模式会把种子管理员的密码交给浏览器，CI 从不使用它。
翻转字节和篡改测试一样有一次性目录的保护。

#### CI 保留什么、从不记录什么

在 CI 中，这个测试在 `e2e-live` 任务里紧跟 Node 测试运行，使用同一个环境。只安装 Chromium
（`npx playwright install --with-deps chromium`），浏览器下载按包含确切 Playwright 版本的键缓存。

**CI 中从不记录 trace。** Playwright trace 会保存每个请求的标头和请求体、DOM 快照和输入值：bearer 令牌、
注册页只显示一次的私钥、包装后的密钥材料。本地失败时会保留一份（`retain-on-failure`）用于调试，它不会离开
本机。

HTML 报告只在任务失败时上传，且必须先通过 `backend/scripts/check_report_hygiene.py`。报告里确实包含测试输入的
值——用户名、`@example.com` 地址、密码和 passphrase——因为 Playwright 的步骤标题会带上它们；这些全部由测试
为一次性账户生成，所在数据库随任务一起销毁（`Throwaway!<uuid>` 形式的密码、`throwaway … passphrase <uuid>`
形式的 passphrase），上传的文件是随机字节。测试从不打印文件字节。失败截图由测试自己拍摄，并遮住私钥框。
卫生检查脚本会解开 ZIP 附件和报告中内嵌的 base64 结果（逐字节扫描读不到这两者），并直接拒绝任何 Playwright
trace，所以即便有人打开了 trace，带 trace 的报告也永远不会被发布。

### 其他浏览器测试

实时环境里的 `npx playwright test` 会运行 `frontend/browser-tests/` 下的每一个测试，所以 CI 也会运行这些：

| 测试 | 断言内容 |
| --- | --- |
| `tamper-visibility.browser.ts` | 在一次性环境中改动存储对象的一个字节；页面随后把文件显示为已被改动，并拒绝下载、说明原因（#94、#164）。它拒绝在环境的临时目录之外运行 |
| `help-assistant.browser.ts` | 向问答助手提问、点击答案中的链接、用键盘关闭；在手机上圆形按钮放得下，且从不遮住 Start Encryption 或我的文件里的操作 |
| `language-switch.browser.ts` | 切换到简体中文再切回、记住选择、回退逻辑，以及手机宽度下的中文公开页面 |
| `not-found.browser.ts` | 未知路径显示 404 页面 |

## 布局与文字巡检

`frontend/scripts/` 中的两个脚本用测量代替肉眼判断界面（#183、#195）。它们需要本地环境和一个从不提交的本地
账户文件，所以在合并界面改动前手动运行，不在 CI 中运行。

- `layout-audit.mjs` 以五种配置（1440 浅色、1440 深色、768、390 手机、1440 中文）打开每个页面，截取整页截图，
  并记录被挤压的标题、水平溢出、被截断的文字、小于 12 px 的文字、小于 32 px 的点击目标、未翻译的英文，以及
  控制台或 HTTP 错误。
- `text-audit.mjs` 在两种语言、六种宽度下测量每个标题和短段落，检查宽度被限制、句子被拦腰截断、标题含两个
  句子和末行只剩一个词的情况。

被挤压的标题和溢出都为零时，界面改动才算完成。脚本测量的是布局；页面读起来好不好，仍要靠人判断。

## 后端并发与故障注入

`backend/tests/integration/test_concurrency_mysql.py` 让真实线程各自使用独立 MySQL 连接，由屏障同时放行后
相互竞争：会话数量限制、登录失败计数、刷新令牌复用、审计哈希链（含在事务中途回滚的写入者）、并发的密钥
重包装、重复分享、分享与删除竞争、重复恢复请求，以及恢复执行与撤销竞争。每一项都验证过：去掉它依赖的行锁
后，测试确实会失败。

`backend/tests/integration/test_fault_injection_mysql.py` 用真实会导致故障的机制制造每一种故障：密文发布后服务器
在 COMMIT 时断开连接（随后 `scripts/reconcile.py` 清理孤儿对象）、对象存储拒绝发布或删除、信封被截断或指向
错误的密钥、签名被伪造、由错误的密钥生成或覆盖了不同的载荷。

两者都和其余集成测试一起在 `mysql-gate` 任务中运行。

## CI 门禁

每个 pull request 和每次推送都运行五个任务：`backend`、`frontend`、`mysql-gate`、`e2e-live`（实时测试和上面
所有浏览器测试）以及 `tamper-drill`（`security-lab/` 中的隔离攻击机实验）。自 2026-10-04 起它们运行在 VPS 上的
三个自建 runner 上（deployment/ci-runner/README.zh-CN.md）；只改文档的
推送会跳过测试任务。在 `main` 上，只有五个任务全部通过，`promote` 任务才会把 `deploy` 分支快进到该提交，而
staging 从 `deploy` 部署，因此 CI 失败的提交永远不会被部署（[AUTOMATIC_DEPLOYMENT.zh-CN.md](../AUTOMATIC_DEPLOYMENT.zh-CN.md)）。

## 手机宽度

三个 Chromium 测试检查产品在手机上是否放得下（360 px，以及仍在使用的最窄屏幕 320 px），使用
`frontend/browser-tests/viewport.ts` 中的辅助函数：

| 测试 | 需要 | 断言内容 |
| --- | --- | --- |
| `mobile-public-pages.browser.ts` | 无 | `/`、`/login`、`/register`、`/forgot-password`、`/education`、`/help`、`/team` 和 404 页面不横向滚动，没有控件超出屏幕边缘（有意滚动或裁切的区域除外），登录和注册控件完整显示且至少 40 px 高便于点按 |
| `mobile-file-flow.browser.ts` | 实时环境 | 在 360 px 下针对真实后端走主要文件流程：注册、上传一个名字很长且不断行的文件、在我的文件中找到它（手机上是卡片，768 px 起是表格）、点按每个操作、打开密文预览、打开恢复/历史/删除/解锁/分享对话框并检查每个都完整位于屏幕内，最后下载回原始字节 |
| `team-page.browser.ts` | 无 | Contact us 页面，包括 360 px 下不横向滚动 |

公开页面测试不需要后端，所以任何能构建应用的地方都能运行：

```bash
cd frontend && npm run build
E2E_MAILBOX_DIR=/tmp E2E_WEB_DIR="$PWD/dist" npx playwright test browser-tests/mobile-public-pages.browser.ts
```

也反向验证过：针对 Issue #76 修复之前的代码运行，它有六个测试失败（教育页横向滚动、注册页和忘记密码页的
验证码行超出 320 px 屏幕、登录和注册的点按目标过小）。

### 未在真机上验证

CI 中上述一切都是 Chromium 加手机尺寸视口和触控模拟。2026-10-02 还在本地用 Playwright WebKit（Safari 的引擎）
模拟 iPhone 13、用 Chromium 模拟 Pixel 7 运行了公开页面和 404 测试，全部通过（证据在 Issue #76 上）。**没有在
实体手机或 Mobile Safari 本身上运行过任何测试**，`mobile-file-flow` 也只在 Chromium 中跑过，因为它需要一次性
环境。两个已知在 Mobile Safari 中表现不同的行为是提前修好的，而不是观察到的：触屏上输入框字号从不小于 16 px
（更小时 Mobile Safari 会在聚焦时放大整页），对话框高度使用动态视口单位（`dvh`），避免地址栏把对话框挤出
底部。安全区域内边距不需要代码，因为 viewport meta 标签没有使用 `viewport-fit=cover`，浏览器会把内容保持在
刘海之内。真实 iPhone 或 Android 手机上出现的其他问题都应作为缺陷提交到 Issue #76，而不是本节已经排除的。

## 不覆盖的内容

浏览器冒烟测试只在一种浏览器（Chromium）、一种视口下走一条路径。它不覆盖每个页面、每种错误状态、Firefox 或
WebKit，也不做视觉回归；上面的手机宽度测试补充了移动布局，但只在 Chromium 中。Node 测试套件覆盖每个流程的
边界情况，冒烟测试只证明页面正确接到了它们。
