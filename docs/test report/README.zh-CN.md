# 测试报告

[English](README.md)

这个文件夹把我们所有的测试结果放在一起，答辩时方便找。
这里的文件都是复制过来的，原文件还在原来的位置，所以旧链接、主 README 和 CI 都不受影响。
如果复制件和原文件的数字不一样，以原文件为准。

TESTING_SUMMARY 里的测试数量来自 main 上 1b1bcce 的 CI（2026-10-13，PR #240）：后端在真实 MySQL 上跑 786 个测试，前端 977 个测试，另有 57 个浏览器测试，全部通过。

## 总览

| 文件 | 内容 |
| --- | --- |
| [TESTING_SUMMARY.md](TESTING_SUMMARY.md) | 一页汇总所有测试数字：单元测试、集成测试、浏览器测试、压力测试和安全测试。 |
| [TESTING_SUMMARY.zh-CN.md](TESTING_SUMMARY.zh-CN.md) | 测试汇总的中文版。 |
| [E2E_TESTING.md](E2E_TESTING.md) | 端到端测试怎样用真实后端和两个真实账号来跑，以及它证明了什么。 |
| [E2E_TESTING.zh-CN.md](E2E_TESTING.zh-CN.md) | 端到端测试说明的中文版。 |
| [PERFORMANCE_TESTING.md](PERFORMANCE_TESTING.md) | 压力测试的计划、我们写的测试工具，以及测试前就知道的限制。 |
| [PERFORMANCE_TESTING.zh-CN.md](PERFORMANCE_TESTING.zh-CN.md) | 性能测试计划的中文版。 |

## 压力测试、大文件和文件类型（2026-10-09）

| 文件 | 内容 |
| --- | --- |
| [load-test/REPORT-2026-10-09.md](load-test/REPORT-2026-10-09.md) | 对 staging 的完整压力测试报告，也包括大文件和文件类型测试：pdf、png、jpg、mp4、zip、exe，从 1 MiB 到 500 MiB，36/36 个文件通过，72/72 次下载逐字节一致。 |
| [load-test/REPORT-2026-10-09.zh-CN.md](load-test/REPORT-2026-10-09.zh-CN.md) | 压力测试报告的中文版。 |
| [load-test/server-metrics-2026-10-09.csv](load-test/server-metrics-2026-10-09.csv) | 测试期间在服务器上采样的 CPU、内存和磁盘数据。 |
| [load-test/charts-2026-10-09/](load-test/charts-2026-10-09/) | 报告里用到的图表。 |
| [load-test/raw/](load-test/raw/) | 每一轮测试的原始 summary.json（smoke、steps、parallel、logins、mixed、sizes）。sizes 两轮还保留了 ops.jsonl，记录每一次上传和下载。 |

## 安全扫描（2026-10-12）

| 文件 | 内容 |
| --- | --- |
| [security-scan/README.md](security-scan/README.md) | 对线上网站做 OWASP ZAP baseline 扫描的说明和结论。 |
| [security-scan/README.zh-CN.md](security-scan/README.zh-CN.md) | 扫描说明的中文版。 |
| [security-scan/zap-baseline.html](security-scan/zap-baseline.html) | ZAP 生成的原始报告，用浏览器打开。 |
| [security-scan/zap-baseline.md](security-scan/zap-baseline.md) | 同一份 ZAP 报告的 Markdown 版。 |
| [security-scan/zap-baseline.json](security-scan/zap-baseline.json) | 同一份 ZAP 报告的原始 JSON。 |

## 完整性和加密

| 文件 | 内容 |
| --- | --- |
| [integrity/ENCRYPTION_EVIDENCE.md](integrity/ENCRYPTION_EVIDENCE.md) | 怎样证明文件在服务器上确实是加密的，以及为什么原始大小和加密后大小一样。 |
| [integrity/ENCRYPTION_EVIDENCE.zh-CN.md](integrity/ENCRYPTION_EVIDENCE.zh-CN.md) | 加密证明的中文版。 |
| [integrity/TAMPER_DEMO.md](integrity/TAMPER_DEMO.md) | 篡改测试：在服务器上改掉存储的文件，下载时会被拒绝。 |
| [integrity/TAMPER_DEMO.zh-CN.md](integrity/TAMPER_DEMO.zh-CN.md) | 篡改测试的中文版。 |
| [integrity/ac4a-3-admin-integrity-damaged.png](integrity/ac4a-3-admin-integrity-damaged.png) | 管理员完整性检查发现文件被破坏的截图。 |
| [integrity/ac4a-4-agent-integrity-damage.png](integrity/ac4a-4-agent-integrity-damage.png) | 安全代理报告文件被破坏的截图。 |
| [integrity/ac4a-6-admin-integrity-clean.png](integrity/ac4a-6-admin-integrity-clean.png) | 恢复之后完整性检查结果正常的截图。 |

更早的结果（2026-10-03 压力测试、2026-10-04 连接池修复前后的重跑、2026-10-04 的 ZAP 扫描）仍在 [docs/performance](../performance/) 和 [docs/security](../security/)。
