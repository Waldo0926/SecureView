# Testing track work packages / 测试线工作包

> **Historical archive / 历史档案:** retained as evidence of the original testing sweeps. Do not
> add new work here; record future team changes in [`../CHANGELOG.md`](../CHANGELOG.md) and
> synchronize README/TODO when their current statements change.
>
> **历史档案：**本文件仅保留早期测试扫查证据，不再新增工作。今后的团队变更统一写入
> [`../CHANGELOG.md`](../CHANGELOG.md)，当前说明改变时同步 README/TODO。

Per-work-package records from the testing track, oldest first. A work package names the `main`
commit it branched from, the scope it stayed inside, and the limitations it confirmed but
deliberately left for a later package.

These are not release entries. A package can close having changed no code, and its listed
limitations are open on purpose. What actually shipped to the product is recorded in
[`../CHANGELOG.md`](../CHANGELOG.md).

This track owns verification across the whole project rather than one vertical slice, so its
packages tend to read as sweeps: a baseline, a method, what the method could and could not
see, and what it found. A sweep that finds nothing is still worth recording — it is the only
way a later reader can tell an untested area from a tested one.

测试线的分工作包记录，按时间正序。每个工作包写明它从哪个 `main` 提交拉出、范围限定在哪里，
以及确认存在但有意留给后续工作包的限制。

它们不是发布条目：一个工作包可以在未改动任何代码的情况下结束，其中列出的限制也是有意保留的。
真正交付到产品里的变更记录在 [`../CHANGELOG.md`](../CHANGELOG.md)。

本条线负责的是整个项目的验证，而非某一个垂直切片，因此它的工作包通常呈现为一次"扫查"：基线、
方法、该方法能看见与看不见什么，以及查到了什么。一次什么都没查到的扫查同样值得记录——那是后来
的读者区分"未测过的区域"与"测过的区域"的唯一依据。

---

## TT-1.1

Base `main` @ `aa4e858` · Scope: the encrypted-file path, end to end · Backend, frontend, and deployment SQL
基线 `main` @ `aa4e858` · 范围：加密文件路径的端到端验证 · 涉及后端、前端与部署 SQL

### Baseline / 基线

- Created `TT-1.1` from the merged `main` commit `aa4e858`. Backend `248 passed, 5 skipped`; frontend `122 passed | 3 skipped`; production build clean.
- 已从完成合并的 `main` 提交 `aa4e858` 创建 `TT-1.1`。后端 `248 passed, 5 skipped`；前端 `122 passed | 3 skipped`；生产构建通过。
- All five backend skips were the MySQL integration tests. A default `pytest` run reports green while skipping every test that needs a database, which is how a suite of skipped tests comes to be read as a suite of passing ones.
- 五个后端跳过项全部是 MySQL 集成测试。默认的 `pytest` 运行会在跳过所有需要数据库的测试的同时报告全绿，一套被跳过的测试正是这样被读成一套通过的测试的。
- Reproduced the deployment shape locally rather than trusting the developer default: MySQL 8.4 in the Compose container, `alembic upgrade head`, and an account seeded through `scripts/seed_test_account.py` so the identity is one the real registration path would have produced.
- 已在本地复现部署形态，而不是依赖开发默认配置：Compose 容器中的 MySQL 8.4、`alembic upgrade head`，以及通过 `scripts/seed_test_account.py` 播种的账户，使该身份与真实注册路径产生的身份一致。

### Method / 方法

- Drove the whole lifecycle against a live database and a real storage root: upload, list, metadata, integrity check, download, decrypt, recovery unwrap, share, revoke, re-share, delete. Then the same for the edge cases — a zero-byte file, a 255-character name, unicode and emoji names, a quote in a filename, pagination past the end, the size-limit boundary, a declared size that disagrees with the body, and four concurrent uploads racing on one `file_id`.
- 已针对真实数据库与真实存储根目录跑完整个生命周期：上传、列表、元数据、完整性检查、下载、解密、恢复密钥解封、分享、撤销、重新分享、删除。随后以同样方式覆盖边界情况——0 字节文件、255 字符文件名、Unicode 与 emoji 文件名、文件名含引号、翻页越界、大小上限边界、声明大小与实际请求体不一致，以及四个并发上传争用同一个 `file_id`。
- Verified the deployment SQL against the migrations empirically rather than by reading both: installed `02-schema.sql` into one database and `alembic upgrade head` into another, then diffed `information_schema` for columns, indexes, check constraints, and foreign keys.
- 已以实证方式而非对照阅读来验证部署 SQL 与迁移的一致性：把 `02-schema.sql` 安装到一个数据库、把 `alembic upgrade head` 应用到另一个，然后针对列、索引、CHECK 约束与外键 diff `information_schema`。
- Ran the full lifecycle a second time as the real runtime account, created from the sixteen `GRANT` statements at the end of `02-schema.sql`, after dropping the blanket database privilege Compose grants in development. A developer running as `root` cannot discover a missing grant; only this can.
- 已以真实运行时账号再跑一遍完整生命周期。该账号由 `02-schema.sql` 末尾的十六条 `GRANT` 语句创建，并已先移除 Compose 在开发环境授予的整库权限。以 `root` 身份运行的开发者不可能发现缺失的授权，只有这样才能。

### Verified clean / 验证通过

- Storage holds what it should: the bytes on disk are identical to the uploaded ciphertext, the recorded `sha256` and size match them, no plaintext appears anywhere under the object root, and no staged file or orphaned object survives a rejected upload.
- 存储持有的内容正确：磁盘字节与上传的密文完全一致，记录的 `sha256` 与大小与之匹配，对象根目录下任何位置都不出现明文，被拒绝的上传也不留下暂存文件或孤儿对象。
- Concurrency holds: four simultaneous uploads of one `file_id` produced exactly one `201` and three `409`, one row, and no orphaned object.
- 并发行为正确：四个同时上传同一 `file_id` 的请求恰好产生一个 `201` 与三个 `409`，一行数据，无孤儿对象。
- Sharing holds: a recipient receives their own `key_id` in the envelope rather than the owner's, the permission ceiling refuses to grant more than the sharer holds, revocation removes access from both the list and download, re-sharing restores it, and deleting the file removes it from everyone.
- 分享行为正确：接收方在信封中拿到的是自己的 `key_id` 而非所有者的，权限上限拒绝授予超出分享者自身的权限，撤销会同时从列表与下载中移除访问权，重新分享可恢复，删除文件则对所有人移除。
- Tamper detection holds: a single flipped bit in a stored object is reported as `MODIFIED` and the download is refused.
- 篡改检测正确：存储对象中翻转一个比特即被报告为 `MODIFIED`，下载被拒绝。
- The deployment SQL and the migrations agree. Indexes and foreign keys are byte-identical; columns and check constraints differ only in how MySQL renders an equivalent declaration (`now()` against `CURRENT_TIMESTAMP`, and a literal's `_utf8mb4` against `_latin1` charset annotation, both artifacts of the client charset at DDL time). Only `alembic_version.version_num` differs materially, in collation, on a table the runtime account cannot read by design.
- 部署 SQL 与迁移一致。索引与外键完全相同；列与 CHECK 约束的差异仅在于 MySQL 对等价声明的渲染方式（`now()` 与 `CURRENT_TIMESTAMP`，以及字面量的 `_utf8mb4` 与 `_latin1` 字符集标注，两者都是 DDL 执行时客户端字符集的产物）。唯一实质差异是 `alembic_version.version_num` 的排序规则，而该表按设计运行时账号本就无法读取。
- The runtime grants are exactly sufficient. Every lifecycle assertion passed under the restricted account, `/health/ready` answered `ready`, and `alembic_version` remained unreadable — which is the intended arrangement, since readiness deliberately reads `audit_chain_heads.schema_revision` instead.
- 运行时授权不多不少刚好够用。受限账号下所有生命周期断言均通过，`/health/ready` 返回 `ready`，且 `alembic_version` 仍不可读——这正是预期安排，因为就绪检查有意改读 `audit_chain_heads.schema_revision`。

### Found / 查到

- Two defects that no existing test could have seen, both living where the service, the SQL, and the object store meet. A failed integrity check wrote `CORRUPTED` to `files.status`, which every authorized-access query filtered out and nothing ever moved back — and a `MISSING` result, raised whenever the object could not be opened, counted the same as a digest mismatch, so one unmounted volume could permanently hide a file whose ciphertext was intact. Separately, `POST /files/upload` answered with a `created_at` carrying microseconds the second-resolution column cannot hold, so MySQL rounded it and every later read disagreed with the response. Shipped as PR #20 and PR #21.
- 两个既有测试都不可能发现的缺陷，均位于服务、SQL 与对象存储的交汇处。完整性检查失败会把 `CORRUPTED` 写入 `files.status`，而所有授权访问查询都会过滤掉该状态，且没有任何位置会把它改回——同时，只要对象打不开就会产生的 `MISSING` 结果与摘要不匹配被同等对待，因此一次未挂载的存储卷就能永久隐藏一个密文完好的文件。另外，`POST /files/upload` 返回的 `created_at` 带有秒级精度列无法保存的微秒，MySQL 会将其四舍五入，导致此后每次读取都与该响应不一致。已作为 PR #20 与 PR #21 交付。
- One resource leak: `publish` creates a directory per `file_id` and `delete_object` only unlinked the object inside it, so every file ever uploaded left a permanent empty directory behind. Shipped in PR #21.
- 一处资源泄漏：`publish` 为每个 `file_id` 创建一个目录，而 `delete_object` 只解除其中对象文件的链接，因此每上传过一个文件都会永久留下一个空目录。已在 PR #21 中交付。
- Confirmed and closed two limitations CT-1.6 had recorded a day earlier: the file list fetched a single page of the API's default size, and `mapFileStatus` was receiving `files.status` rather than an integrity verdict. Measured against a real account holding 122 files, the first meant 97 files no control on the page could reach, and the search box filtered only the fetched rows, so searching for the 30th file answered "no results" for a file that existed. Shipped in PR #22.
- 已确认并关闭 CT-1.6 在一天前记录的两条限制：文件列表只请求 API 默认大小的第一页，以及 `mapFileStatus` 收到的是 `files.status` 而非完整性判定。在一个持有 122 个文件的真实账户上度量，前者意味着有 97 个文件是页面上任何控件都无法到达的；搜索框又只过滤已取回的行，因此搜索第 30 个文件会对一个确实存在的文件返回"无结果"。已在 PR #22 中交付。
- Confirmed and closed the `vue-tsc` drift CT-1.2 had recorded as pre-existing, and established its cause: sixteen of the eighteen frontend dependencies were declared `"latest"`, `npm install` was resolving TypeScript 7, and `vue-tsc` loads the `typescript/lib/tsc` path that version no longer exports. Because `vite build` does not type check, the build stayed green and nothing announced that type checking had stopped running. Restarting it surfaced ten accumulated errors, two of them real contract mismatches. Shipped in PR #23.
- 已确认并关闭 CT-1.2 记录为既存问题的 `vue-tsc` 版本漂移，并查明其成因：前端十八个依赖中有十六个声明为 `"latest"`，`npm install` 解析到 TypeScript 7，而 `vue-tsc` 加载的正是该版本不再导出的 `typescript/lib/tsc` 路径。由于 `vite build` 不做类型检查，构建始终通过，没有任何信号表明类型检查已经停止运行。恢复运行后暴露出十个累积的错误，其中两个是真实的契约不一致。已在 PR #23 中交付。

### Added / 新增

- `backend/tests/integration/test_file_lifecycle_mysql.py`, sixteen tests over the same path this sweep drove by hand, so the next regression is caught by CI rather than by someone repeating this work. Run against `main` at the baseline commit it fails exactly five tests, all of them the two defects above; run against the fixes, all sixteen pass.
- `backend/tests/integration/test_file_lifecycle_mysql.py`，十六个测试覆盖本次扫查手工走过的同一条路径，使下一次回归由 CI 拦截，而不是由某人重做一遍这项工作。在基线提交的 `main` 上运行恰好有五个测试失败，且全部对应上述两个缺陷；在修复之上运行，十六个全部通过。
- Both backend READMEs gained a section on pointing the suite at a disposable database, stating plainly that a green `pytest` without one does not mean the integration tests passed.
- 两份后端 README 均新增一节，说明如何将测试套件指向一次性数据库，并明确指出：在没有数据库的情况下 `pytest` 全绿并不代表集成测试通过了。

### Not included / 未包含

- No HTTP-layer tests were added. `tests/api/` already covers the contract, and the new file deliberately tests service + repository + MySQL + filesystem, which is the seam the defects lived in.
- 未新增 HTTP 层测试。`tests/api/` 已覆盖该契约，而新文件有意测试的是服务 + 仓储 + MySQL + 文件系统，那才是这些缺陷所在的接缝。
- No authentication, session, or recovery-request flows. This package stayed inside the encrypted-file path; the auth path has its own integration file.
- 未涉及认证、会话或恢复请求流程。本工作包限定在加密文件路径内；认证路径有其自己的集成测试文件。
- No load or timing work. Nothing here says anything about behaviour under concurrency beyond the single four-way `file_id` race.
- 未做负载或时序方面的工作。除了那一次四路 `file_id` 竞争之外，这里的内容对并发下的行为不作任何论断。

### Confirmed limitations / 已确认限制

- The second-resolution rounding fixed for the file domain still applies to `user_sessions`, `session_refresh_tokens`, `auth_login_throttles`, `email_verification_codes`, and `recovery_requests`. Left open deliberately: correcting it there touches authentication timing and belongs in a change that can be reviewed on those terms.
- 已为文件领域修复的秒级舍入问题，在 `user_sessions`、`session_refresh_tokens`、`auth_login_throttles`、`email_verification_codes` 与 `recovery_requests` 上依然存在。有意保留：在那些位置修正会触及认证时序，应当放进一个可以按其自身条件评审的改动中。
- A file uploaded through the browser still cannot be downloaded and decrypted through the browser. `TODO.md` records this as P0 and this sweep confirms it: no component anywhere calls `decryptFile` or `unwrapDek`, and the download button fetches the ciphertext and discards it.
- 通过浏览器上传的文件，目前仍无法通过浏览器下载并解密。`TODO.md` 已将其记为 P0，本次扫查予以确认：任何组件都没有调用 `decryptFile` 或 `unwrapDek`，下载按钮取回密文后即将其丢弃。
- `GET /files` has no search parameter, so the file page can only filter the rows it has already fetched. PR #22 renames the control to say so rather than implying otherwise; server-side search remains unbuilt.
- `GET /files` 没有搜索参数，因此文件页面只能过滤它已经取回的行。PR #22 将该控件改名以如实说明这一点，而非暗示相反；服务端搜索仍未实现。
- The reconciliation jobs `TODO.md` lists for stale staged objects, orphaned ciphertext, expired sessions and throttle buckets do not exist. This sweep found no orphan or leftover in normal operation, which is a statement about the paths exercised here, not about a process that dies mid-upload.
- `TODO.md` 中列出的针对陈旧暂存对象、孤儿密文、过期会话与限流桶的对账任务尚不存在。本次扫查在正常操作下未发现任何孤儿或残留，但这是关于此处所走路径的结论，而非关于一个在上传中途崩溃的进程的结论。
- `lucide-vue-next` is deprecated upstream in favour of `@lucide/vue`. Pinned rather than swapped, because changing packages is not a version pin.
- `lucide-vue-next` 在上游已废弃，官方建议改用 `@lucide/vue`。此处选择固定版本而非更换，因为更换依赖包不属于版本固定的范畴。

### Closed / 收尾

- PRs #20 through #24 merged to `main` as `197bcd7`, `9d8b32c`, `66bbc25`, `23487b1`, `89263ef`. On merged `main` the backend reports `288 passed` with the integration suite actually running, Ruff and `alembic check` are clean, and the frontend passes `typecheck`, `128 passed`, and a production build from a fresh `npm ci` — which also confirms the newly committed lockfile installs.
- PR #20 至 #24 已合入 `main`，对应 `197bcd7`、`9d8b32c`、`66bbc25`、`23487b1`、`89263ef`。在合并后的 `main` 上，后端报告 `288 passed` 且集成测试为真实执行，Ruff 与 `alembic check` 均通过，前端 `typecheck` 通过、`128 passed`，并可从全新的 `npm ci` 完成生产构建——这同时验证了新提交的 lockfile 确实可安装。
- Staging auto-deployed the merge and passed its own release gate: `result=success commit=89263ef`, with `backend=active`, `mysql=healthy`, `mysql_tls_required=1`, `nginx=active`, `health=ok`. The service reports `NRestarts=0` and `/health/ready` answers `ready`. Two `502` probes appear in the deploy log inside the backend restart window, before the gate's health check succeeded; they are the restart, not a failure.
- staging 已自动部署该合并并通过其自身的发布门禁：`result=success commit=89263ef`，其中 `backend=active`、`mysql=healthy`、`mysql_tls_required=1`、`nginx=active`、`health=ok`。服务报告 `NRestarts=0`，`/health/ready` 返回 `ready`。部署日志中出现的两次 `502` 探测位于后端重启窗口内、发生在门禁健康检查成功之前，那是重启本身，不是失败。

update: 2026/8/24
