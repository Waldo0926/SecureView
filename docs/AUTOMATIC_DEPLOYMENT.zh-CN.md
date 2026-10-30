# 预发布环境自动部署

[English](AUTOMATIC_DEPLOYMENT.md) | [简体中文](AUTOMATIC_DEPLOYMENT.zh-CN.md)

MCS21 预发布 VPS 会在新提交合并到 GitHub `main` **并通过 CI** 后自动部署。由 root 管理的 systemd timer
约每两分钟检查一次私有仓库，并把准确的 commit SHA 交给现有、带保护措施的
`mcs21-deploy` 发布命令。团队成员仍按“分支开发、Pull Request 评审、合并 `main`”协作，
不需要共享服务器账户或 Deploy Key。

当前采用服务器主动拉取。GitHub Actions 不负责部署任何东西，它唯一的作用是移动 `deploy` 分支来标记
某个提交是安全的（见[CI 门禁](#ci-门禁)）。只读 Repository Deploy Key 仅保存在 VPS
的专用 `mcs21-deploy` 服务账户中；GitHub 不保存 VPS SSH 私钥或生产 Secret。

## 发布流程与保护措施

```text
开发分支 -> Pull Request -> 合并 main -> 该 commit 通过 CI
         -> CI 把 `deploy` 分支移动到它
         -> systemd timer 拉取 `deploy` -> 部署准确 commit
         -> 数据库备份及只读核验
         -> 构建与预检 -> 原子切换 release
         -> 重启服务及健康检查 -> 写入审计记录
```

底层发布命令会锁定并串行执行部署、保留上一版本，并在切换后的健康检查失败时回滚应用。
健康检查还会把 `GET /health/live` 报告的 `commit`（读自该 release 的 `.mcs21-release` 文件；
设置了 `APP_COMMIT` 时读它）与刚部署的 commit 比较，不一致也会回滚，这样重启后仍在跑旧代码的
情况不会被当作部署成功。
自动数据库步骤只包括备份和生产 SQL 只读核验。运行账户不能修改 Schema，自动部署服务也
没有 MySQL 管理员或迁移凭据。因此，Schema 变化必须按照
[DEPLOYMENT.zh-CN.md](DEPLOYMENT.zh-CN.md) 单独提供并评审 DBA SQL 发布，并且必须在推送依赖
它的代码**之前**先应用到数据库——先推代码会导致部署中止并隔离该 SHA，之后的每一个提交都会卡在
它后面。参见
[对运行中的部署应用 Schema Revision](DEPLOYMENT.zh-CN.md#对运行中的部署应用-schema-revision)。

核验器会区分全新审计链（`OK`）与已经包含应用事件、但状态一致的在线审计链
（`LIVE_DATA`）。在线状态只有在单例链头保留准确的发布 Schema 标记、指向最新审计记录，
且哈希与该记录一致时才会通过；`REVIEW`、`MISSING` 和 `UNEXPECTED` 仍会阻止部署。这样
代码发布不会把正常保留的审计证据误判为 Schema 漂移，同时不会削弱数据库、账户、授权与
结构核验。

如果某个 commit 部署失败，该 SHA 会进入隔离状态。Timer 不会反复部署同一个坏版本；
只有 `main` 出现新 commit，或管理员完成排查后显式清除隔离，才会再次尝试。定时检查再次
遇到同一隔离 SHA 时，会记录跳过并以成功状态退出：原始失败证据仍保留，但 systemd 不会
每两分钟重复产生一条新失败。

## CI 门禁

在 `promote` 作业出现之前，timer 会部署 `main` 上的任何内容：直接推送，或 CI 为红的合并，都会在约两分钟内进入
生产环境（威胁模型发现 F-01）。通常的办法是 GitHub 分支保护，但仓库是免费套餐下的私有仓库，无法使用，所以
门禁用一个分支来实现。

- `.github/workflows/ci.yml` 中的 `promote` 作业只在推送到 `main` 时运行，并且要等 `backend`、`frontend`、
  `mysql-gate`、`e2e-live`、`tamper-drill` 在该 commit 上**全部**通过之后才运行。它通过 GitHub REST API 把
  `deploy` 分支移动到该 commit。该分支只会**向前**移动：较旧的一次运行晚结束也无法把它拉回去；历史分叉时
  作业会失败，而不是强制覆盖任何东西。
- timer 同时拉取 `main` 与 `deploy`，并部署 `deploy` 的 commit。发布命令仍要求该 commit 可从 `main` 到达，
  而它总是满足这一点。
- CI 运行在本 VPS 上项目自建的 runner 上（deployment/ci-runner/），通过独立的 Docker、网络和防火墙规则与线上环境隔离。runner 停止期间不会推进任何部署，恢复后继续。
- 只改文档的 commit（见 `ci.yml` 中的 `changes`）会跳过测试作业，`promote` 也随之跳过，`deploy` 保持不动。
  对外提供的内容没有任何变化，下一个通过 CI 的代码 commit 会把 `deploy` 推进到它之后。
- 推送到 `main` 时，"只改文档"是相对 `deploy` 判断的，而不是相对上一次推送。同一分支的新推送会取消仍在运行的
  CI，所以如果代码合并后紧接着推送一个只改文档的 commit，它会先取消代码那次运行，再因为"只改文档"而跳过测试，
  这段代码要等下一个代码 commit 才会被部署。相对 `deploy` 比较时，这段代码仍在差异里，所以这次文档推送会跑全部
  作业，并把两者一起推进（[#171](https://github.com/jsonrar/fyp-secure-file-platform/pull/171)）。
- CI 为红的 commit 根本不会被推进，下一个绿色 commit 会包含它。代价是延迟：现在合并后要等 CI 结束（约五分钟）
  再加最多两分钟的 timer，而不是两分钟。
- 在 CI 推进过任何 commit 之前，timer 会报告 `deploy` 不存在并且什么都不部署，同时不产生失败的 unit（失败即关闭）。
- timer 绝不会把 release 往回退：如果手动执行 `mcs21-deploy all main` 让服务器领先于 `deploy`，定时检查会保持不动。
- `sudo mcs21-auto-deploy status` 会同时输出 `cached_deploy`（允许上线的版本）和 `cached_main`（已合并的版本）；
  两者不同说明 CI 还在跑或是红的。

门禁**不**做什么。它不要求评审：任何有推送权限的人仍可把 commit 放到 `main`，只要通过 CI 就会部署。它也不会阻止
管理员执行 `sudo mcs21-deploy all main`，这是有意保留的手动应急入口，会绕过 CI 部署。另外，若 `main` 被强制推送，
使 `deploy` 不再是其祖先，`promote` 会以“diverged”失败；修复办法是把 `deploy` 指向 `main` 上已知良好的 commit
（`gh api --method PATCH repos/jsonrar/fyp-secure-file-platform/git/refs/heads/deploy -f sha=<sha> -F force=true`），
这需要写权限，属于管理员的决定。

## 日常运维命令

获得部署权限的队员都可以查看状态和记录：

```bash
sudo mcs21-auto-deploy status
systemctl status mcs21-auto-deploy.timer --no-pager
journalctl -u mcs21-auto-deploy.service --no-pager -n 100
sudo mcs21-deploy history
```

修复临时故障后，清除隔离并重新部署当前通过 CI 的 commit：

```bash
sudo mcs21-auto-deploy retry
```

管理员也可以强制执行一次验证，或继续使用手动发布入口：

```bash
sudo mcs21-auto-deploy force
sudo mcs21-deploy all
```

### 部署前备份会被清理

每次部署前都会把数据库导出和密文对象打包写到 `/var/backups/mcs21-deploy/<UTC 时间戳>-<sha>`。自 [PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204) 起，部署健康后
`mcs21-deploy` 只保留最新的 `MCS21_KEEP_DEPLOY_BACKUPS` 份（默认 10，不少于 3），删除更早的，并在审计日志中记下删了几份。
它只处理符合该命名格式的目录，部署失败时从不清理。异地副本由 `mcs21-offsite-backup` 负责。已于 2026-10-08 安装到 staging；第一次运行（强制重新部署 `f826165`）删除 175 份、保留 10 份：`/var/backups/mcs21-deploy` 从 81 GB 降到 7.5 GB，根盘占用从 69% 降到 51%。

## 安装文件

仓库中的版本化参考文件位于 `deployment/server/`。预发布 VPS 上的安装位置为：

- `mcs21-deploy` -> `/usr/local/sbin/mcs21-deploy`，是手动与自动发布共用的保护流程实现；
- `mcs21-auto-deploy` -> `/usr/local/sbin/mcs21-auto-deploy`，由 root 持有，部署队员不可修改；
- `mcs21-auto-deploy.service` 和 `mcs21-auto-deploy.timer` -> `/etc/systemd/system/`。

### 发布自己安装的运维 unit

发布上线且健康之后，`mcs21-deploy` 会从该发布中安装并启用**两个**运维 unit：`mcs21-integrity-sweep.{service,timer}`
（每日 05:30 的完整性扫描，见 [BACKUP_AND_RECOVERY.zh-CN.md](BACKUP_AND_RECOVERY.zh-CN.md) 第 9 节）和
`mcs21-security-agent.{service,timer}`（每日 06:00 的安全 Agent 检查，有 Critical 或 High 发现时发邮件，见
[SECURITY_AGENT.zh-CN.md](SECURITY_AGENT.zh-CN.md)）。两者都以 `fypapp` 运行且只读：扫描读对象存储，Agent 读数据库。名单在脚本里固定
（`ops_units`），因为放进 `/etc/systemd/system` 的文件会以它指定的账户运行，若发布里任何文件都能变成 unit，
“通过 CI 的提交”就等于“以 root 运行任意代码”。安装前脚本检查：服务以 `fypapp` 运行，只启动
`/opt/mcs21/current/backend/.venv/bin/python scripts/<名称>.py`，没有 `+`/`!` 特权钩子，timer 启动的就是同一服务；
然后与已安装的副本比较，仅在变化时原子替换，运行 `systemd-analyze verify`，重载 systemd，若 timer 尚未启用则启用。
失败只会打印并记审计警告，不会让已经健康的部署变成失败。`test_ops_units.py` 会用脚本自己的检查去验证随附的
两个 unit，以及必须被拒绝的各种变体，并把名单固定为恰好 `(mcs21-integrity-sweep mcs21-security-agent)`。

其余运维 unit（`mcs21-reconcile`、`mcs21-audit-checkpoint`、备份与 observe）仍是有意的手动安装：有的以 root
运行，有的会删除数据。

这要在 VPS 上装上更新后的 `/usr/local/sbin/mcs21-deploy` 之后才生效，只有拥有 root 的人能做。名单写在这个脚本里，
所以名单一变就要重新安装（加入安全 Agent 时就变了）。`install` 成功时不输出任何内容。unit 是在部署过程中安装的，
所以要么等下一次发布，要么把当前版本重新部署一次：

```bash
sudo install -m 0755 -o root -g root /opt/mcs21/current/deployment/server/mcs21-deploy /usr/local/sbin/mcs21-deploy
sudo mcs21-auto-deploy force
systemctl list-timers mcs21-integrity-sweep.timer mcs21-security-agent.timer
```

一定要等 `/opt/mcs21/current` 指向的发布里已经有你要的名单之后再复制
（`grep '^ops_units=' /opt/mcs21/current/deployment/server/mcs21-deploy`）；旧发布还是 current 时复制，装上的就是旧脚本。
告警邮件脚本（`/usr/local/sbin/mcs21-alert`）同样是手动安装；重新安装后，安全 Agent 的告警才会带上“去管理后台查看”的提示，
可用 `sudo systemctl start mcs21-alert@test.service` 测试。

2026-10-07 核对：已安装的 `/usr/local/sbin/mcs21-deploy`、`mcs21-alert`、`mcs21-backup` 和 `mcs21-backup-verify`
与 `e4b3f13` 中 `deployment/server/` 的文件逐字节一致（SHA-256），九个 `mcs21-*` timer（自动部署、observe、
审计检查点、异地备份、备份、对账、完整性巡检、安全 Agent、备份校验）全部处于启用状态。

服务器还单独保存环境专用的 Git mirror、Deploy Key、Secret、备份与 sudo policy；这些
环境专用内容不得复制进 Git。

启用 timer：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcs21-auto-deploy.timer
```

如果以后让 GitHub Actions 自己执行部署，而不只是标记 commit，仍需要取得仓库管理权限、使用受保护的部署环境
Secret，并单独评审凭据方案。绝不能把 VPS 私钥提交到仓库或直接写进 workflow。
