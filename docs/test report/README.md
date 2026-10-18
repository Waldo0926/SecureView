# Test report

[简体中文](README.zh-CN.md)

This folder puts all of our test results in one place so they are easy to find for the presentation.
Everything here is a copy. The originals are still in their old folders, so older links, the main README and CI all keep working.
If a number is ever different between a copy and the original, trust the original.

The test counts in TESTING_SUMMARY come from the CI run on main at 1b1bcce (2026-10-13, PR #240): 786 backend tests against real MySQL, 977 frontend tests and 57 browser tests, all passing.

## Overview

| File | What it is |
| --- | --- |
| [TESTING_SUMMARY.md](TESTING_SUMMARY.md) | One page with every test number we have: unit, integration, browser, load and security tests. |
| [TESTING_SUMMARY.zh-CN.md](TESTING_SUMMARY.zh-CN.md) | Chinese version of the testing summary. |
| [E2E_TESTING.md](E2E_TESTING.md) | How our end to end test uses a real backend and two real accounts, and what it proves. |
| [E2E_TESTING.zh-CN.md](E2E_TESTING.zh-CN.md) | Chinese version of the end to end testing page. |
| [PERFORMANCE_TESTING.md](PERFORMANCE_TESTING.md) | Our plan for the load test, the tool we wrote, and the limits we knew about before running it. |
| [PERFORMANCE_TESTING.zh-CN.md](PERFORMANCE_TESTING.zh-CN.md) | Chinese version of the performance testing plan. |

## Load test, large files and file types (2026-10-09)

| File | What it is |
| --- | --- |
| [load-test/REPORT-2026-10-09.md](load-test/REPORT-2026-10-09.md) | Full load test report against staging. It also covers the large file and file type test: pdf, png, jpg, mp4, zip and exe from 1 MiB up to 500 MiB, 36/36 files passed and 72/72 downloads were byte exact. |
| [load-test/REPORT-2026-10-09.zh-CN.md](load-test/REPORT-2026-10-09.zh-CN.md) | Chinese version of the load test report. |
| [load-test/server-metrics-2026-10-09.csv](load-test/server-metrics-2026-10-09.csv) | CPU, memory and disk numbers we sampled on the server while the test ran. |
| [load-test/charts-2026-10-09/](load-test/charts-2026-10-09/) | The charts used in the report. |
| [load-test/raw/](load-test/raw/) | Raw summary.json files for each run (smoke, steps, parallel, logins, mixed, sizes). The sizes runs also keep ops.jsonl with every single upload and download. |

## Security scan (2026-10-12)

| File | What it is |
| --- | --- |
| [security-scan/README.md](security-scan/README.md) | Our notes on the OWASP ZAP baseline scan of the live site and what the result means. |
| [security-scan/README.zh-CN.md](security-scan/README.zh-CN.md) | Chinese version of the scan notes. |
| [security-scan/zap-baseline.html](security-scan/zap-baseline.html) | The ZAP report as ZAP produced it, open it in a browser. |
| [security-scan/zap-baseline.md](security-scan/zap-baseline.md) | The same ZAP report in Markdown. |
| [security-scan/zap-baseline.json](security-scan/zap-baseline.json) | The same ZAP report as raw JSON. |

## Integrity and encryption

| File | What it is |
| --- | --- |
| [integrity/ENCRYPTION_EVIDENCE.md](integrity/ENCRYPTION_EVIDENCE.md) | How we show files are really encrypted on the server, and why the original and encrypted sizes match. |
| [integrity/ENCRYPTION_EVIDENCE.zh-CN.md](integrity/ENCRYPTION_EVIDENCE.zh-CN.md) | Chinese version of the encryption evidence page. |
| [integrity/TAMPER_DEMO.md](integrity/TAMPER_DEMO.md) | Our tamper test: we change the stored file on the server and the download refuses it. |
| [integrity/TAMPER_DEMO.zh-CN.md](integrity/TAMPER_DEMO.zh-CN.md) | Chinese version of the tamper test. |
| [integrity/ac4a-3-admin-integrity-damaged.png](integrity/ac4a-3-admin-integrity-damaged.png) | Screenshot of the admin integrity check finding the damaged file. |
| [integrity/ac4a-4-agent-integrity-damage.png](integrity/ac4a-4-agent-integrity-damage.png) | Screenshot of the security agent reporting the damage. |
| [integrity/ac4a-6-admin-integrity-clean.png](integrity/ac4a-6-admin-integrity-clean.png) | Screenshot of the integrity check coming back clean after the restore. |

Older runs (the 2026-10-03 load test, the 2026-10-04 pool fix reruns and the 2026-10-04 ZAP scan) are still in [docs/performance](../performance/) and [docs/security](../security/).
