# 安全 Agent

[English](SECURITY_AGENT.md) | [简体中文](SECURITY_AGENT.zh-CN.md)

导师对 AI Agent 一项的要求是：Agent 要**解决明确的自动化问题，而不是单纯加聊天框**——定义它的输入数据、
规则或模型、输出格式与边界，并演示 Critical / High / Medium / Low 分类及 Recommended Action。
本文就是这一定义，以及已实现的内容（管理员页面 → **Security agent**）。
v2（[#137](https://github.com/jsonrar/fyp-secure-file-platform/issues/137)）加入了每日运行（有 Critical 或 High 时发邮件给团队）、
“猜测得手”规则，以及登录限流封禁的可见性。

## 它自动化的问题

平台已经记录了很多东西：哈希链审计日志、完整性检查、文件状态、恢复请求。没有哪位管理员会去读几千行记录，
来发现某个账户正被猜密码、某个会话令牌被重复使用、或某个存储文件被改动。Agent 替他们读这些证据，回答一个问题：
**在发生的所有事情里，现在哪些值得我关注，有多紧急，我该做什么？**

## 它是什么，不是什么

| 它是 | 它不是 |
|---|---|
| **基于规则、确定性的。** 每个发现都来自一条有名字、有明确阈值的规则。相同证据得到相同报告，每条规则都用伪造事件做单元测试，管理员能读到某件事为何被标记。 | 让语言模型去判断日志。没有任何模型被询问，所以不会猜测，也没有日志离开服务器。 |
| **只读。** 它从不写入，不改文件或账户，也不能执行恢复。有测试保证它的模块一旦出现数据库写入或审计追加就失败。 | 被允许“修复”问题。它只建议，由管理员执行。 |
| **只用元数据。** 只读取事件类型、时间、次数、账户名、来源地址和文件标识。 | 能看到文件内容、密钥、口令或密文。查询只选取指定的列，并有测试固定这一点。 |
| **坦承自己的局限。** 每份报告都说明读了多少数据，结果为空时也会说明这不等于什么都没发生。 | 声称一切安全。它只能看到平台记录下来的东西。 |

## 输入数据

| 来源 | 读取内容 |
|---|---|
| `audit_logs`（窗口：最近 24 小时或 7 天；每种事件最多读取最新的 5,000 条，达到上限时报告会写明） | `AUTH_LOGIN_FAILED`、`AUTH_LOGIN_SUCCEEDED`、`AUTH_REFRESH_REPLAY_DETECTED`、`FILE_DOWNLOAD_AUTHORIZED`、`FILE_SHARED`、`AUTH_PASSWORD_CHANGE_FAILED`、`RECOVERY_REQUEST_EXECUTED`：动作、时间、账户名与角色、来源地址 |
| 审计哈希链 | 完整重算（`AuditQueryService.verify_chain`；每日运行用 `verify_chain_for_trusted_job`，是同一检查但不需要登录的操作者，任何 HTTP 路由都调用不到）：是否有效，以及第一个失败的条目 |
| `auth_login_throttles` | 此刻被封禁（`blocked_until` 在未来）的地址桶和账户桶数量，按范围分别统计。只有计数：键是哈希值，从不读取 |
| `integrity_checks` 与 `files` | 状态为 `CORRUPTED`，或最新检查为 `MODIFIED`、`MISSING`、`ERROR` 的文件，以及每个文件的检查历史 |
| `recovery_requests` | 超过 24 小时仍待处理的数量 |
| 完整性扫描的覆盖情况 | 最近一次扫描的时间、从未检查过的文件数 |

## 规则

| 规则 | 观察对象 | 触发 |
|---|---|---|
| `INTEGRITY_DAMAGE` | 受损的存储文件 | **MODIFIED = Critical**，MISSING = High，ERROR = Medium |
| `AUDIT_CHAIN_BROKEN` | 审计哈希链 | 任一条目验证失败 = **Critical** |
| `SCAN_NOT_RUNNING` | 最近一次完整性扫描 | 有文件时 36 小时内（或从未）没有扫描 = Medium |
| `LOGIN_GUESSING_SOURCE` | 每个来源地址的登录失败，并列出它尝试过的账户 | 15 分钟内 10 次以上 = Medium，30 次以上 = High |
| `LOGIN_GUESSING_ACCOUNT` | 来自**两个或以上**地址、针对同一账户的登录失败 | 15 分钟内 10 次以上 = Medium |
| `SIGN_IN_AFTER_GUESSING` | 一次成功登录，对照它之前 15 分钟内针对**同一账户**或来自**同一地址**的登录失败 | 任一方式达到 5 次以上 = **High**；该账户是管理员则为 **Critical** |
| `SIGN_IN_THROTTLE_ACTIVE` | 此刻生效的登录限流封禁（只有计数） | 有地址被封 = Medium，只有账户被封 = Low |
| `SESSION_TOKEN_REUSE` | 已使用过的刷新令牌再次出现 | 任意一次 = High |
| `DOWNLOAD_BURST` | 每个账户的下载 | 10 分钟内 20 次以上 = Medium，60 次以上 = High |
| `SHARE_BURST` | 每个账户的分享 | 一小时内 10 次以上 = Low |
| `UPLOAD_BURST` | 每个账户的上传 | 10 分钟内 30 次以上 = Medium，100 次以上 = High |
| `PASSWORD_CHANGE_GUESSING` | 每个账户的改密失败 | 15 分钟内 5 次以上 = Medium |
| `RECOVERY_EXECUTED` | 已执行的恢复、等待超过一天的请求 | 已执行 = Medium，等待 = Low |

同一地址猜同一账户是一起事件，只由来源规则报告一次，并在证据里写明账户；账户规则针对的是分散在多个地址上的猜测，这种情况按地址看会被拆成太小而不显眼的碎片。

`SIGN_IN_AFTER_GUESSING` 是最有价值的检测：**猜中了**的猜测很可能就是账户被接管。除了按账户，也按地址统计失败，
这样能抓到撞库：一个地址试很多账户，最后进去的那个账户本身可能一次失败都没有。成功登录会清空该账户的限流桶，
但失败记录仍留在审计日志里，所以规则照样能看到。它不会重复报告：猜测本身仍可能由 `LOGIN_GUESSING_SOURCE` 报告
（“发生了猜测”和“猜中了”是两件事），但同一账户基于同一批失败的第二次登录会并入第一个发现，不会再报一次。
同一地址基于同一轮失败登进*另一个*账户也一样并入：一个地址试了很多用户名然后进了三十个账户，是一起事件、三十个受害者，
所以只报一条，证据里列出这些账户（前五个加总数）、整轮失败以及第一次和最后一次登录的时间；只要其中有管理员就是 Critical。
2026-10-09 压测的清理步骤说明了为什么要这样：同一地址先对 68 个已删除的用户名登录失败，再登进 32 个账户，
原来会产生 32 条引用同一批失败的发现，五条真正的突增反而被埋在下面。按地址统计的代价是：在共享地址后面
（校园 NAT、CI 运行机），紧接在一轮猜测之后别人的正常登录也会被标记；证据会写明是哪个计数触发的，管理员能分辨。

如果某个账户现在已经不是活跃状态（被本人注销，或被管理员停用），以该账户为主体的突增、猜密码和接管类发现会在证据里写明，
建议动作也随之改变：下载、分享、上传突增改为指向活动日志页，因为已经没有账户可停用；对它猜密码则改为“重新启用之前先让本人重置密码”，
因为账户不活跃时什么都进不去。这个标记是账户现在的状态，不是事件发生时的状态，所以证据里不写先后顺序。以地址为主体的发现从不带这句话。
以前发现里只写着 `deleted-<hex>` 这个墓碑名，还让管理员去停用它。仓库为此多读了 `users.status` 一列；仍然不读元数据、User-Agent 或文件内容。

### 登录限流遮住了什么

限流决定了审计日志能看到的上限。策略（`backend/app/core/config.py`）：**账户**在 15 分钟内失败 **10** 次后封禁 **5 分钟**；
**地址**失败 **500** 次后封禁 **15 分钟**（一个地址往往是整个会场的 NAT 出口，见 THREAT_MODEL 第 11.6 节）。被限流以 429 拒绝的尝试**不写审计日志**，这是有意的：若每个 429 都写审计，
攻击者就能灌满哈希链日志，而每次追加都要拿链头锁。所以封禁期间，上面的规则看不到猜测是否还在继续。
`SIGN_IN_THROTTLE_ACTIVE` 改为读取限流表，报告此刻生效的封禁数量。它单独成为一条规则，而不是作为猜测类发现的附加证据，
是因为限流的键是哈希值：计数无法对应到某个地址或账户，把它写在某个发现下面，就等于声称了一个谁也无法核实的关联。
它反映的是*此刻*的状态，主要在攻击进行中管理员打开标签页时有用；每天 06:00 的运行很少会碰上封禁。

突发用滑动窗口衡量：一天里分散的 40 次失败不算突发；五分钟内的 10 次才算。阈值是
`backend/app/services/security_agent_rules.py` 顶部的常量，修改需要经过代码评审，报告里也会写明。

优先级含义：**Critical** 立即处理，**High** 今天处理，**Medium** 本周查看，**Low** 方便时处理。

## 输出格式

`GET /api/v1/admin/agent/report?window_hours=24|168`（仅管理员）返回、页面展示：

```
generated_at, window_hours
counts:      critical / high / medium / low
findings[]:  rule_id, priority, title, summary,
             evidence[]            （为何被标记：次数、账户、地址、时间）,
             recommended_action    （该做什么）,
             file_id?              （文件类发现）
rules[]:     每条规则、它观察什么、阈值、这次触发了几个发现
inputs:      读取的审计事件数、验证的审计链条目数、可检查/从未检查的文件数、最近一次扫描
boundaries[] Agent 不会做的事
```

## 主动告警（每日）

标签页只有在有人打开时才分析，所以同样的分析每天也自动跑一次：

- `backend/scripts/security_agent_check.py` 通过 `SecurityAgentService.report_for_scheduled_check` 生成最近 **24 小时**的报告
  （没有 HTTP 操作者；管理员路由的权限检查不变）。它**只**输出各优先级的数量、触发了哪些规则 id，以及达到读取上限的事件类型，
  从不输出用户名、地址、文件名或发现标题。`critical + high > 0` 时退出码为 **3**（表示有发现，不是崩溃），否则为 0。
- `deployment/server/mcs21-security-agent.service` 以 `fypapp` 身份运行它，`ProtectSystem=strict`，没有任何写入路径，
  对象存储目录也不可访问；`.timer` 每天 **06:00 Asia/Kuala_Lumpur** 触发，排在 05:30 完整性扫描之后，
  这样扫描刚发现的受损文件会出现在同一个早上的结果里（`Persistent=true` 会在停机后补跑）。
- 退出码 3 会让 unit 失败，`OnFailure=mcs21-alert@%n.service` 随即发出现有的失败告警邮件。邮件仍然**不含任何 journal 内容**，
  只有 unit 状态和一句固定的话：安全 Agent 有 Critical 或 High 发现，请打开 Admin → Security agent。详情留在管理员登录之后。
- **未解决的 Critical 发现会每天发一次邮件，直到修好为止。** 比如一个尚未恢复的受损文件，每天早上都会让检查失败。
  这是有意的：这是提醒，不是噪音。Medium 和 Low 发现从不发邮件。
- **压测会触发它，而且应该触发。** `loadtest/` 从一个地址登录几十个临时账号，几分钟内上传下载几百个文件，正是突增和猜密码规则
  要找的模式。2026-10-09 压测后的第二天早上（2026-10-10 06:00），检查以退出码 3 结束，43 条 High 发现：五个最忙的测试账号各有
  `UPLOAD_BURST` 和 `DOWNLOAD_BURST`，`LOGIN_GUESSING_SOURCE` 对应第一次清理已删掉的账号上的 68 次登录失败，
  `SIGN_IN_AFTER_GUESSING` 则是随后从同一地址登进的 32 个账号各一条（上面说的合并之后只剩一条）。所有事件都带着
  `secureview-loadtest/1.0` 的 User-Agent，来自测试者家里的两个地址，账号也已被压测自己的清理步骤删掉。服务器上什么都没有改；
  24 小时窗口到第二天早上就滑过这次压测，检查会自己恢复。以后跑完压测，要预料到这封邮件，并对照压测报告核对地址和时间之后再放过它。
- 这两个 unit 在 `mcs21-deploy` 固定的 `ops_units` 名单里，健康的发布会像完整性扫描一样自动安装它们
  （见 [AUTOMATIC_DEPLOYMENT.zh-CN.md](AUTOMATIC_DEPLOYMENT.zh-CN.md)）。前提是服务器上由有 root 权限的人装好当前版本的
  `mcs21-deploy`，见 #137 的运维说明。

## 受损文件的恢复指引

对受损文件，建议动作会给出确切的命令（`scripts/restore_file.py --file-id …`，始终是演练模式），并**根据该文件自己的检查历史
推算哪些备份集可能持有原件**：在上传与最后一次通过检查之间生成的备份集*一定*持有；到首次发现损坏为止的备份集*很可能*持有；
更晚的备份集可能已经含有被损坏的字节。`restore_file.py` 会校验 SHA-256 并拒绝不匹配的备份集。这样 Agent 与
[BACKUP_AND_RECOVERY.zh-CN.md 第 9 节](BACKUP_AND_RECOVERY.zh-CN.md) 的恢复流程衔接起来，却不能自己去执行它。

## 演示（用真实事件，不伪造任何东西）

审计日志只能追加且带哈希链，无法注入假事件，也不需要。展示各个级别的方法：

1. **Medium，猜密码：** 从同一地址对同一账户发送十次错误密码。登录限流在十次之后返回 429，这十次都在审计日志里，
   报告会显示一条写明该账户的 `LOGIN_GUESSING_SOURCE`，封禁期间还有 `SIGN_IN_THROTTLE_ACTIVE`（Low）。
2. **High，猜中了：** 对一个账户输错五次密码，再输对一次：`SIGN_IN_AFTER_GUESSING`。换成管理员账户就是 **Critical**。
3. **Critical，文件被篡改：** 在篡改实验室（`security-lab/run.sh`）或一次性环境中翻转一个存储对象的字节，
   在 Integrity 标签点 **Scan now**，再打开 **Security agent**：显示 `INTEGRITY_DAMAGE`、备份窗口和恢复命令。
4. **High，对象丢失：** 把一个对象移出存储后扫描：`INTEGRITY_DAMAGE` 为 High，描述为存储问题而非篡改。
5. **Medium，检测未运行：** 在定时器已 36 小时没有运行的部署上。

## 测试

- `tests/unit/test_security_agent_rules.py`：每条规则的阈值、分级、对正确来源与账户的归因、排序、确定性、
  备份窗口文字，以及只会建议演练模式；v2 新增五次失败的阈值、管理员升级、窗口之外或成功之后的失败不计入、不重复计数，以及限流分级。
- `tests/unit/test_security_agent_check.py`：每日检查的退出码，以及即使每个发现里都写满了用户名、地址和文件名，输出里也一个都没有。
- `tests/unit/test_ops_units.py`：新 unit 通过 `ops_unit_acceptable`，名单恰好是这两个 unit，timer 在扫描之后的 06:00 运行。
- `tests/unit/test_security_agent_service.py`：窗口、请求了哪些事件、检查历史如何变成“最后一次完好”与“首次发现损坏”、
  仅管理员可用、SQL 只选取指定列（限流查询从不选取哈希键）、模块和每日脚本没有写入路径，以及任何 HTTP 路由都调用不到可信任务入口。
- `frontend/src/e2e/live-stack.integration.test.ts`（CI 的 `e2e-live`）：对运行中的 API 做十次真实的登录失败，得到一条排好序的 `LOGIN_GUESSING_SOURCE` 发现，带证据和建议动作；新账户输错五次再输对一次，得到 `SIGN_IN_AFTER_GUESSING`；普通用户被拒绝。
- `tests/integration/test_security_agent_mysql.py`：在真实 MySQL 上，真正被篡改的文件被报告为 Critical 并给出备份窗口，
  真实的失败加一次真实的成功被报告为 `SIGN_IN_AFTER_GUESSING`（普通用户 High，管理员 Critical），所有查询都能运行。
- `frontend/src/utils/agent-report.test.ts`：发现如何展示。

## 局限与下一步

- 它只能看到被记录下来的内容。没有留下审计事件的攻击对它不可见。
- 代理之后的来源地址，只和 API 所信任的代理头一样可靠。
- 它看不到被限流拒绝的登录尝试（见上文），只知道此刻有多少封禁。
- 没有报告历史，也无法确认或忽略某个发现：那需要改数据库结构并增加写入路径，是另一个决定。在那之前，未解决的 Critical 发现每天都会发邮件。
- **Agent 有意不包含语言模型层。** 它唯一合理的用途是为非技术读者改写发现的措辞，而这会把审计元数据（账户名、地址）
  发给第三方。若以后要加，应当是可选、默认关闭，只接收已脱敏的发现文字，且绝不允许它改变优先级或执行动作。
