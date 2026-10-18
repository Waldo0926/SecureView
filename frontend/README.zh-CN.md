# 前端

[English](README.md) | [简体中文](README.zh-CN.md)

SecureView 的 Vue 3 + TypeScript 前端，对接 FYP 后端 `/api/v1`。界面采用“Sealed”风格（自托管
Geist 字体，绿色只表示已验证/已封装，红色只表示被改动/危险），支持明亮、暗色和跟随系统主题，
可在页头或设置页切换英文与简体中文。

## 运行

```bash
npm install
npm run dev
```

后端需运行在 `http://localhost:8000`。

## 页面

| 路由 | 说明 |
|------|------|
| `/` | 首页：带真实样例字节的首屏、工作原理、对比问答 |
| `/how-it-works` | 动画讲解与七步图文指南 |
| `/login` | 登录 |
| `/register` | 两步注册：先建账户（邮箱、验证码、登录密码），再设置加密 passphrase；一次性提供私钥文件 |
| `/forgot-password` | 使用邮箱验证码重置登录密码 |
| `/dashboard` | 登录后工作台，含新手清单 |
| `/upload` | 文件加密上传，实时显示加密步骤与字节对比（需要身份认证） |
| `/files` | 我的文件：自有与共享文件、文件夹、详情面板、分享、撤销、访问历史、密文预览（需要身份认证） |
| `/audit-logs` | 活动日志：先是账户操作，再是文件访问记录（需要身份认证） |
| `/profile` | 个人资料与头像（需要身份认证） |
| `/settings` | 主题、语言、密钥指纹、修改登录密码、凭当前 passphrase 修改 passphrase、用私钥文件重设 passphrase、注销账户（需要身份认证） |
| `/admin` | 角色感知运维：概览统计、用户（详情、启用/禁用、临时登录密码）、文件、完整性、安全 Agent、审计链、恢复请求、恢复公钥 |
| `/education` | 教育文章与算法浏览器 |
| `/help` | 帮助：动画讲解、真实产品的演示视频、图文指南 |
| `/team` | Contact us：反馈表单、导师与团队 |
| `/benchmark/argon2` | 本机 Argon2id 耗时基准 |
| 其他路径 | 404 页面 |

每个页面右下角的圆形按钮会打开问答助手（[docs/HELP_ASSISTANT.zh-CN.md](../docs/HELP_ASSISTANT.zh-CN.md)）。

## 结构

- `src/pages/`、`src/components/` — 页面与 UI 组件（`securfile/` 为公开站点的各个区块）
- `src/api/` — 与后端 `/api/v1` 对齐的 Axios 客户端
- `src/crypto/` — 文件加解密（六种 AEAD 套件）、分享密钥重包装、密钥指纹、私钥文件解锁与
  passphrase 重设
- `src/stores/` — Pinia 身份认证／文件状态
- `src/i18n/`、`src/locales/` — 英文与简体中文（[docs/I18N.zh-CN.md](../docs/I18N.zh-CN.md)）
- `src/composables/useTheme.ts` — 系统／明亮／暗色主题
- `scripts/layout-audit.mjs`、`scripts/text-audit.mjs` — 按页面、宽度、主题和语言做布局与文字的
  脚本化检查

浏览器已经实现账户密钥登记、passphrase／私钥文件解锁、用私钥文件重设 passphrase、加密上传、
认证下载与本地解密、带接收者密钥指纹确认的分享、撤销、文件夹、搜索、审计历史、refresh 轮换、
会撤销服务端会话的登出、注销账户，以及 `/admin` 上的角色感知管理／恢复／审计操作。设置页还可以凭当前 passphrase 修改 passphrase（#201）。后继密钥轮换 API 已有，但尚无界面。

在 `/files` 中，**Download and decrypt** 会在需要时弹出解锁对话框并保存原文件。**Encrypted
preview** 面板展示服务器保存的字节，并提供 **Download encrypted file**，无需解锁账户密钥即可将
密文保存为 `<filename>.ciphertext`。两者均使用已认证且校验完整性的
`POST /files/{file_id}/download` 端点。密文下载只包含存储的 blob，不包含离线解密所需的完整
envelope。

## 环境变量

默认 API 地址已是 `http://localhost:8000/api/v1`。如需覆盖，请创建不纳入版本管理的
`frontend/.env.local`：

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```
