# 需求与演示对照表

[English](RTM_DEMO_MAP.md)

[PROPOSAL_TRACEABILITY.zh-CN.md](../PROPOSAL_TRACEABILITY.zh-CN.md) 里的每一条验收标准，以及观众在答辩时在哪里看到它。
步骤编号对应 [DEMO_SCRIPT.zh-CN.md](DEMO_SCRIPT.zh-CN.md)。“屏幕上看到什么”是评审实际看到的东西，也就是证据；
“测试证据”是背后的自动化检查。

| AC | 需求 | 答辩中的位置 | 屏幕上看到什么（证据） | 测试证据 |
| --- | --- | --- | --- | --- |
| AC1 | 注册并得到受保护的 RSA 私钥 | 只有早上测试时注册邮件能收到才现场做（见下文）；否则放在密钥保管那页幻灯片 | 现场：收到验证码，输入口令，然后是只显示一次私钥的 “Save Your Private Key” 页面。幻灯片：同一页面的截图，加一句“服务器只保存用你的口令封装过的私钥” | `backend/tests/unit/test_auth_service.py`、`backend/tests/integration/test_auth_mysql.py`；每个浏览器用例都通过真实注册页注册（`frontend/browser-tests/golden-path.browser.ts`） |
| AC2 | 可选算法，只上传密文 | 第 1 步，上传 | 算法列表（六种套件）、四个计时阶段，以及字节对比：文件开头是 `%PDF`，服务器收到的看起来是随机字节 | `frontend/src/crypto/upload.integration.test.ts`、`frontend/src/crypto/primitives.test.ts`（已知答案向量）、`backend/tests/unit/test_crypto_vectors.py`；golden-path 浏览器用例 |
| AC3 | 接收方用自己的口令解密 | 第 2、3 步，分享和打开 | Alice 分享前看到 Bob 的密钥指纹，Bob 的设置页显示同一个值；Bob 输入自己的口令，PDF 打开 | `frontend/src/e2e/live-stack.integration.test.ts` 在真实 API 和 MySQL 上对六种套件都做分享、解密和撤销；`frontend/src/crypto/share.test.ts`、`share-confirm.test.ts` |
| AC4 | 被篡改的文件在解密前被拒绝 | 第 4 步，篡改 | Bob 点 `quarterly-results.txt`（前一天已 flip）的下载：提示 “The encrypted file could not be verified”，该行显示 **Modified**，没有保存任何文件 | `frontend/browser-tests/tamper-visibility.browser.ts`；CI 的 `tamper-drill` 每次合并都翻转一个字节并确认服务器拒绝 |
| AC4a | 篡改后的恢复 | 演示之后的幻灯片 | `docs/presentation/screenshots/` 里的截图：Modified 行、被拒绝的下载、Admin → Integrity 列出损坏文件、安全代理的 Critical 发现、恢复后该行回到 Verified、Admin → Integrity 恢复干净 | `backend/tests/unit/test_restore_file.py`、`mysql-gate` 里的恢复演练步骤、`tamper-visibility.browser.ts` 的恢复步骤 |
| AC5 | 带时间戳的操作审计 | 第 3b 步，审计 | Alice 打开该共享文件的访问记录：Bob 的下载，带他的名字和时间，旁边是她自己的上传和分享 | `backend/tests/unit/test_audit_log_service.py`、`test_audit_checkpoint.py`、`backend/tests/integration/test_file_lifecycle_mysql.py`；`frontend/src/utils/audit-trail.test.ts` |
| AC6 | 交互式密码学教育 | 演示开头，几秒钟 | 介绍场景时窗口 A 停在 Education 页，打开一张算法卡片 | `frontend/browser-tests/language-switch.browser.ts` 和 `mobile-public-pages.browser.ts` 用两种语言和手机宽度打开 `/education` |
| AC7 | 可关闭的四阶段进度条 | 第 1 步过程中 | 四个阶段按真实耗时依次完成，然后用关闭按钮关掉回执 | `frontend/browser-tests/golden-path.browser.ts` 检查回执在关闭前一直显示（#200）；`frontend/src/crypto/upload.test.ts` |
| AC8 | 解决明确自动化问题的 AI 代理 | 第 5 步，代理发现了 | Admin → Security agent：一条 **Critical** 的 `INTEGRITY_DAMAGE` 发现，点名 `quarterly-results.txt`，建议操作是恢复命令 | `backend/tests/unit/test_security_agent_rules.py`、`test_security_agent_service.py`、`backend/tests/integration/test_security_agent_mysql.py` |

## 当天的 AC1

注册需要邮件验证码。答辩当天早上，用答辩电脑在 staging 上注册一个临时账号 `demo-carol-<日期>`：

- 如果一分钟内收到验证码，就在演示时段开头现场注册（约 40 秒；结束语改为在安全代理页面上说，不再单独占时间）。
- 如果收不到，台上不要尝试。在密钥保管那页幻灯片上放 “Save Your Private Key” 的截图，并说明它证明了什么：密钥对在浏览器里生成，
  服务器只保存用口令封装过的私钥。

## 触发的是哪条代理规则

篡改这一步由安全代理规则 `INTEGRITY_DAMAGE`（`backend/app/services/security_agent_rules.py`）发现：任何最新一次完整性检查为
`MODIFIED`、`MISSING` 或 `ERROR`，或状态为 `CORRUPTED` 的文件。`MODIFIED` 是 **Critical**。第 4 步被拒绝的下载会记录一次
`MODIFIED` 检查，所以管理员一按 **Run analysis** 就能看到这条发现；05:30 的扫描和 06:00 的每日报告在夜里也会自己发现它
（这就是答辩当天早上会收到的告警邮件）。
