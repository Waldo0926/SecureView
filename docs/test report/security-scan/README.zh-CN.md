# OWASP ZAP 基线复扫（2026-10-12）

[English](README.md)

到答辩周时，[2026-10-04 的扫描](../../security/scans-2026-10-04/README.zh-CN.md)已经过去八天、合并了 45 个 PR，所以对线上站点
（版本 `1eb56d8`，#224）又跑了一次同样的被动基线扫描。这个目录保存原始输出；每条告警的处理决定写在 2026-10-04 的 README 里，没有变化。

## 结果

| 工具 | 对象 | 结果 |
| --- | --- | --- |
| OWASP ZAP 基线扫描（`zaproxy:stable`，爬取 1 分钟，只用被动规则） | `https://secureview.tech`，版本 `1eb56d8` | **0 FAIL、5 WARN、62 PASS**；没有高风险告警。与 2026-10-04 修复后的扫描完全一致 |

五条 WARN 和 2026-10-04 修好 nginx 之后的五条一样：

| 告警 | 风险 | 状态 |
| --- | --- | --- |
| 缺少 Cross-Origin-Embedder-Policy | 低 | 接受：`require-corp` 会挡掉 `/docs` 页面加载的 CDN，而应用用不到它带来的功能 |
| CSP：`style-src 'unsafe-inline'` | 中 | 接受并写在 nginx 文件里：Vue 的过渡动画要写内联样式；`script-src` 没有 `unsafe-inline` |
| 重新检查 Cache-control 指令 | 信息 | 公开页面和带哈希的代码包本来就该缓存；登录、错误和下载响应自己带 `no-store` |
| 可存储、可缓存的内容 | 信息 | 同上 |
| 现代 Web 应用 | 信息 | ZAP 提示这是单页应用 |

第一次扫描发现静态代码包缺少的响应头（Strict-Transport-Security、X-Content-Type-Options、Permissions-Policy、
Cross-Origin-Opener-Policy、Cross-Origin-Resource-Policy）仍然都在：62 PASS，和 2026-10-04 修复后一样。

和之前一样，基线扫描是被动的：它爬取公开页面并检查响应，不发送攻击载荷，也不登录，所以不能说明 API 的权限逻辑是否正确；
那部分由我们自己的测试和威胁模型覆盖。`npm audit` 在每个 PR 的 `frontend` CI 任务里运行，`1eb56d8` 上没有问题。

## 运行方式

在笔记本上，和 2026-10-04 用同一条命令：

```bash
docker run --rm -v "$PWD":/zap/wrk:rw ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t https://secureview.tech -m 1 -J zap-baseline.json -r zap-baseline.html -w zap-baseline.md -I
```

## 文件

- `zap-baseline.html`、`.md`、`.json`：2026-10-12 的 ZAP 报告
