# 首页图文指南截图

[English](README.md) | 简体中文

每张图都有两份：英文 `<name>.webp` 和简体中文 `<name>-zh.webp`；首页按页头所选语言显示对应的一套。
这些 WebP 是真实 Vue 界面在浅色模式下的截图，使用虚构账户（`sam`、`alex`）和 `Project notes.txt`。
蓝色描边和数字标出要点的控件。手机版截图裁出相关的上传栏，或更窄的真实文件列表布局。分享和解锁
对话框另有 `*-mobile.webp`（在手机宽度下对同一弹窗的裁切）。截图里没有真实凭据或用户文件。

界面改动后刷新：

1. 在 `frontend` 中运行 `npm run build`。
2. 运行 `node scripts/capture-workflow.cjs <module-directory> [browser-executable]`。
   模块目录里必须有 Playwright 和 Sharp；可选的可执行文件可指向本地 Chromium。使用当前工作区可用的运行时。
3. 检查所有图片，然后重新构建，让刷新后的资源进入 `dist`。

脚本在一次性浏览器上下文中托管本地构建并拦截 API 请求。上传加密在浏览器中用临时示例公钥真实执行，
但后端结果和接收者列表是固定数据。示例账户密钥用应用自己的 `sealAccountKey`（通过 `jiti` 加载）封装，
所以解锁对话框确实能打开它；分享步骤停在带密钥指纹的接收者确认处。脚本从同一页面状态截取两种语言
（原地切换界面语言，打开的对话框和标签页保持不变），并按 `data-testid`（`encrypt-card`、`files-card`）
而不是类名定位上传卡片和文件卡片。最近一次刷新是 2026-10-05，在“Sealed”改版和 P1–P3 布局修复之后。
这只截取界面状态，不是端到端的后端分享或解密测试。

首页轮播在 `src/components/securfile/workflow-section.vue`；文字与图片映射在 `src/data/workflow-guide.ts`。
帮助页视频是另一套，见 `../videos/README.zh-CN.md`。
