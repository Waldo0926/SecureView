# 第三方安全扫描（2026-10-04）

[English](README.md)

“安全”不能只靠我们自己说。2026-10-04 用三个外部工具检查了项目：OWASP ZAP 扫描线上 staging 站点，
`pip-audit` 检查 Python 依赖，`npm audit` 检查前端依赖。这个目录保存它们的原始输出。

## 结果汇总

| 工具 | 对象 | 结果 | 处理 |
| --- | --- | --- | --- |
| OWASP ZAP 基线扫描（`zaproxy:stable`，爬取 1 分钟，只用被动规则） | `https://secureview.tech` | **0 FAIL、8 WARN、59 PASS**；没有高风险告警 | 缺失的响应头已在 nginx 里补上；其余见下文说明 |
| `pip-audit` | `backend/requirements.txt`（生产环境实际运行的依赖） | 没有已知漏洞 | — |
| `pip-audit` | `backend/requirements-dev.txt`（测试和工具） | `httpx2` / `httpcore2` 2.7.0 有 6 条公告 | 升级到 2.12.0 后无问题；后端 570 个单元和 API 测试全部通过 |
| `npm audit` | `frontend/`（245 个包） | 0 个漏洞 | — |

基线扫描是被动的：它爬取公开页面并检查响应，不发送攻击载荷，也不登录，所以它不能说明 API 的权限
逻辑是否正确；那部分由我们自己的测试和威胁模型覆盖。

## ZAP 发现的问题及处理

| 告警 | 风险 | 处理 |
| --- | --- | --- |
| 没有设置 Strict-Transport-Security（`/assets/*.js`、`*.css`） | 低 | **已修复。** nginx 的规则是：某个 location 只要自己写了 `add_header`，server 级别的 `add_header` 就全部失效。`/assets/` 加了 `Cache-Control`，所以前端代码包返回时没有 HSTS 和 nosniff。现在在这里重复写了这些头，并加了单元测试：任何自己加响应头的 location 如果漏掉安全头，测试就会失败。 |
| 缺少 X-Content-Type-Options（同一批文件） | 低 | **已修复**，原因同上。 |
| 没有设置 Permissions-Policy | 低 | **已修复。** 关闭摄像头、麦克风、定位、支付和 USB，应用一个都不用。 |
| 缺少 Cross-Origin-Opener-Policy / Cross-Origin-Resource-Policy | 低 | **已修复**，都设为 `same-origin`。应用不会打开其他站点的窗口，也不从其他站点加载任何东西。 |
| 缺少 Cross-Origin-Embedder-Policy | 低 | **接受。** `require-corp` 会连 `/docs` API 文档页加载的 CDN 一起拦掉；而我们不用跨源隔离相关的功能，加了也没有额外好处。 |
| CSP：`style-src 'unsafe-inline'` | 中 | **接受，并已在 nginx 文件里写明原因**：Vue 做过渡动画时会写内联样式。`script-src` 没有放开，所以被注入的标记仍然无法执行脚本。 |
| 重新检查 Cache-control / 可存储、可缓存的内容 | 信息 | 符合预期：被标出的 URL 都是公开页面、`robots.txt`、`sitemap.xml` 或带哈希的不可变代码包，本来就应该缓存。登录、错误和文件下载的响应自己会发送 `no-store`。 |
| 现代 Web 应用 | 信息 | 仅提示：ZAP 识别出这是一个单页应用。 |

## 修复之后（2026-10-04 复扫）

更新后的 nginx 文件已装到 VPS，并重新扫描（[`after-nginx/`](after-nginx/zap-baseline.md)）：**0 FAIL、5 WARN、62 PASS**
（修复前：8 个 WARN、59 PASS）。Strict-Transport-Security、X-Content-Type-Options、Permissions-Policy、
Cross-Origin-Opener-Policy 和 Cross-Origin-Resource-Policy 的告警都消失了，也用 `curl -I` 直接检查过代码包的响应头。
剩下的 5 个就是上文已接受的（COEP、`style-src 'unsafe-inline'`）和信息级提示。

## 应用 nginx 改动（已完成）

仓库里的文件是 `deployment/server/nginx-secureview.conf`，VPS 上的线上副本是
`/etc/nginx/sites-available/fyp-secure-file-platform`。自动部署不会安装 nginx 配置，需要有 VPS root
权限的人复制文件、运行 `nginx -t`，再重载 nginx。新文件在加 COOP/CORP 两行之前已在 VPS（nginx 1.24.0）
上通过 `nginx -t`；新增的两行只是普通的 `add_header`。重载之后重新扫描：

```bash
docker run --rm -v "$PWD":/zap/wrk:rw ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t https://secureview.tech -m 1 -J zap-baseline.json -r zap-baseline.html -w zap-baseline.md -I
```

## 文件

- `zap-baseline.html`、`.md`、`.json`：修复前的 ZAP 报告
- `pip-audit-runtime.json`：运行时依赖，无问题
- `pip-audit-dev-before.txt`、`pip-audit-dev-after.txt`：开发依赖升级前后的结果
- `npm-audit.json`：前端依赖，无问题
