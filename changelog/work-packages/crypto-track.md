# Crypto track work packages / 密码学线工作包

> **Historical archive / 历史档案:** retained for CT contribution traceability. Do not add new
> work here; record all future team changes in [`../CHANGELOG.md`](../CHANGELOG.md) and synchronize
> README/TODO when their current statements change.
>
> **历史档案：**本文件仅保留 CT 贡献追踪证据，不再新增工作。今后的团队变更统一写入
> [`../CHANGELOG.md`](../CHANGELOG.md)，当前说明改变时同步 README/TODO。

Per-work-package records from the crypto track, oldest first. A work package names the `main`
commit it branched from, the scope it stayed inside, and the limitations it confirmed but
deliberately left for a later package.

These are not release entries. A package can close having changed no code, and its listed
limitations are open on purpose. What actually shipped to the product is recorded in
[`../CHANGELOG.md`](../CHANGELOG.md).

Extracted from `CT_Logs/CHANGELOG.md`, where these entries lived until the changelog moved to
`changelog/`; `git log --follow` still traces them back.

密码学线的分工作包记录，按时间正序。每个工作包写明它从哪个 `main` 提交拉出、范围限定在哪里，
以及确认存在但有意留给后续工作包的限制。

它们不是发布条目：一个工作包可以在未改动任何代码的情况下结束，其中列出的限制也是有意保留的。
真正交付到产品里的变更记录在 [`../CHANGELOG.md`](../CHANGELOG.md)。

本文件由 `CT_Logs/CHANGELOG.md` 拆出——这些条目在更改日志迁到 `changelog/` 之前一直存放在那里；
`git log --follow` 仍可追溯。

---

## CT-1.1

### Baseline / 基线

- Created `CT-1.1` from the merged `main` commit `9593e75`.
- 已从完成合并的 `main` 提交 `9593e75` 创建 `CT-1.1`。
- Verified the existing cryptography baseline with `python -m pytest tests/unit/test_crypto_service.py -q --durations=10`: 4 tests passed in 0.54 seconds.
- 已使用 `python -m pytest tests/unit/test_crypto_service.py -q --durations=10` 验证现有密码学基线：4 项测试全部通过，耗时 0.54 秒。

### Confirmed limitations / 已确认限制

- AES-GCM encryption currently processes the complete plaintext in memory and does not authenticate associated data (AAD).
- 当前 AES-GCM 加密会在内存中处理完整明文，且未认证关联数据（AAD）。
- No versioned encrypted-envelope format or streaming encryption interface exists yet.
- 当前尚无带版本的密文封装格式或流式加密接口。
- No cryptographic implementation code was changed during this baseline step.
- 本基线步骤未修改任何密码学实现代码。

update: 2026/8/12 17:27

-------------------------------------------------------------------------------------------------------------
## CT-1.2

Base `main` @ `c45e54d` · Scope: file encryption only · No backend changes
基线 `main` @ `c45e54d` · 范围：仅文件加密 · 未改动后端

### Added / 新增

- `frontend/src/crypto/encoding.ts` — byte encoding: integers, UUIDs, NFC-normalized UTF-8, canonical Base64, length prefixes.
- `frontend/src/crypto/encoding.ts` — 字节编码：整数、UUID、NFC 归一化 UTF-8、规范 Base64、长度前缀。
- `frontend/src/crypto/primitives.ts` — AES-256-GCM (detached tag), SHA-256, RSA-OAEP-SHA256, RSA-PSS-SHA256.
- `frontend/src/crypto/primitives.ts` — AES-256-GCM（分离 tag）、SHA-256、RSA-OAEP-SHA256、RSA-PSS-SHA256。
- `docs/crypto/test_vectors.json` and 41 vitest cases. Vectors are generated with `python-cryptography`, so the TypeScript is checked against an independent implementation rather than against itself.
- `docs/crypto/test_vectors.json` 与 41 项 vitest 用例。向量由 `python-cryptography` 生成，使 TypeScript 对照独立实现验证，而非自我往返验证。
- `vitest` declared in `package.json` with `package-lock.json` synchronized.
- 已在 `package.json` 声明 `vitest`，并同步 `package-lock.json`。

### Why / 用途

The frontend had no encryption at all; uploads sent plaintext. These are the primitives every
encrypted upload needs: ciphertext, nonce, tag, and RSA-wrapped keys.
前端此前没有任何加密，上传发送的是明文。这些是每次加密上传都需要的底层原语：密文、nonce、tag 与 RSA 包装的密钥。

Three rules the backend already enforces are now caught by tests instead of at runtime:
三条后端已在强制、但此前无人知晓的规则，现在由测试拦截，而不是等到运行时才发现：

- The GCM tag must be detached from the ciphertext, or the upload is rejected.
- GCM tag 必须与密文分离，否则上传被拒。
- Base64 must be standard and padded, or the request is rejected.
- Base64 必须是标准字母表且带填充，否则请求被拒。
- Filenames must be NFC-normalized, or upload succeeds and later decryption fails.
- 文件名必须 NFC 归一化，否则上传成功、之后解密失败。

### Not included / 未包含

- Argon2id and the account-key envelopes, while the key-custody model is unresolved on `main`.
- Argon2id 与账户密钥信封 —— `main` 上的密钥托管模型尚未定论。
- File envelope assembly and AAD construction, which follow in the next step.
- 文件信封组装与 AAD 构造，将在下一步完成。

### Notes / 说明

- The existing `file_api.upload` is broken independently of this work: it posts the plaintext file to `/files/upload`, while the backend serves `POST /files` and requires ciphertext plus a metadata envelope.
- 现有 `file_api.upload` 本身即为损坏状态，与本次工作无关：它把明文文件发往 `/files/upload`，而后端提供的是 `POST /files`，且要求密文加元数据信封。
- `vue-tsc` cannot run here; it has drifted from the installed `typescript`. Used `tsc --noEmit` instead. Pre-existing.
- `vue-tsc` 在此无法运行，与已安装的 `typescript` 版本漂移。改用 `tsc --noEmit`。该问题早于本分支存在。

update: 2026/8/20

-------------------------------------------------------------------------------------------------------------
## CT-1.3

Base `main` @ `98f4c64` · Scope: file encryption envelope · No backend changes
基线 `main` @ `98f4c64` · 范围：文件加密信封 · 未改动后端

### Added / 新增

- `frontend/src/crypto/file_envelope.ts` — AAD-3 construction, `encryptFile` / `decryptFile`, DEK wrapping to the owner and recovery keys, and the `POST /files` metadata assembly.
- `frontend/src/crypto/file_envelope.ts` — AAD-3 构造、`encryptFile` / `decryptFile`、DEK 向所有者与恢复密钥的包装，以及 `POST /files` 元数据组装。
- `docs/crypto/FILE_ENVELOPE.md` and its Chinese translation: the normative byte layout.
- `docs/crypto/FILE_ENVELOPE.md` 及其中文译本：规范性字节布局。
- 8 new reference vectors (6 AAD, 2 full envelopes) and 44 tests. 85 tests pass in total.
- 新增 8 组参考向量（6 组 AAD、2 组完整信封）与 44 项测试。累计 85 项测试通过。

### Design decisions / 设计决策

- AAD-3 binds `file_id`, `envelope_version`, `plaintext_size`, `original_filename` and `mime_type`. Those last three are cleartext columns the server could otherwise rewrite, so binding them turns any such edit into a decryption failure.
- AAD-3 绑定 `file_id`、`envelope_version`、`plaintext_size`、`original_filename` 与 `mime_type`。后三者是服务器本可随意改写的明文列，绑定后任何此类修改都会变成解密失败。
- Trade-off: those three fields become immutable for the lifetime of the ciphertext. No rename route exists today, but a future one needs re-encryption or `envelope_version = 2`.
- 代价：这三个字段在密文生命周期内不可变。当前不存在改名路由，但将来若要支持，需要重新加密或升级到 `envelope_version = 2`。
- AAD-3 contains nothing per-recipient. The owner and every share recipient decrypt the same ciphertext with the same DEK, so binding `key_id` would break sharing entirely.
- AAD-3 不含任何按接收方变化的字段。所有者与每个共享接收方使用同一 DEK 解密同一密文，绑定 `key_id` 会彻底破坏共享。
- `encryptFile` self-tests by decrypting its own output before returning. The server cannot check that ciphertext decrypts to anything, so an unopenable envelope would otherwise be discovered only after the plaintext was gone.
- `encryptFile` 在返回前解密自己的输出进行自检。服务器无法验证密文能否解出内容，否则一个打不开的信封只会在明文丢弃之后才被发现。

### Notes / 说明

- The server never computes this AAD, so no server-side check can catch a divergent second implementation; it would simply produce files nobody can decrypt. Hence the normative doc and the locked vectors.
- 服务器从不计算此 AAD，因此没有任何服务端检查能发现第二个实现的分歧，后果只是产出谁也解不开的文件。规范文档与锁定的向量正是为此而存在。
- The recovery wrapping remains unverifiable by any client; `buildUploadPayload` returns the locally recomputed recovery-key fingerprint so the caller can pin it.
- 恢复包装对任何客户端都不可验证；`buildUploadPayload` 会返回本地重算的恢复密钥指纹，供调用方固定比对。

### Not included / 未包含

- Wiring into `file_api.ts` and the upload page, which still send plaintext.
- 接入 `file_api.ts` 与上传页面 —— 它们目前仍在发送明文。
- Argon2id and the account-key envelopes, while the key-custody model is unresolved.
- Argon2id 与账户密钥信封 —— 密钥托管模型尚未定论。

update: 2026/8/20

-------------------------------------------------------------------------------------------------------------
## CT-1.4

Base `main` @ `2003e47` · Scope: wire encryption into the upload path · No backend changes
基线 `main` @ `2003e47` · 范围：将加密接入上传路径 · 未改动后端

### Fixed / 修复

- The upload page returned a bare `422`. `POST /files/upload` takes two multipart parts, `file` and `metadata`, and the page sent only `file` — with the plaintext in it. `metadata` is a required form field that cannot be filled without encrypting first, so FastAPI rejected every upload.
- 上传页此前直接返回 `422`。`POST /files/upload` 需要 `file` 与 `metadata` 两个 multipart 部分，而页面只发送了 `file`，且内容是明文。`metadata` 是必填字段，不先加密就无法填写，因此 FastAPI 拒绝了每一次上传。
- Removed the `AES-128 / AES-192 / AES-256 / 3DES` selector, which was wired to nothing, and the "Server-side encryption uses AES-256-GCM" copy, which described the opposite of the design.
- 已移除未接任何逻辑的 `AES-128 / AES-192 / AES-256 / 3DES` 下拉框，以及与设计相反的
  "Server-side encryption uses AES-256-GCM" 文案。
- Dropped the manual `Content-Type: multipart/form-data` header. Naming the type without a boundary leaves the browser unable to generate one.
- 已移除手写的 `Content-Type: multipart/form-data` 头。只写类型而不带 boundary 会导致浏览器无法生成分隔符。

### Added / 新增

- `frontend/src/crypto/upload.ts` — fetches the owner and recovery public keys, encrypts the file, wraps the file key to both, and assembles the multipart payload.
- `frontend/src/crypto/upload.ts` — 获取所有者与恢复公钥、加密文件、将文件密钥包装给两者，并组装 multipart 载荷。
- `frontend/src/api/key_api.ts` — `GET /keys/me`, `/keys/me/{key_id}`, `/keys/users/{user_id}/active`.
- `frontend/src/api/key_api.ts` — `GET /keys/me`、`/keys/me/{key_id}`、`/keys/users/{user_id}/active`。
- `recovery_api.getPublicKey` for the active recovery key, and `fileApi.uploadEncrypted`.
- `recovery_api.getPublicKey` 用于获取活跃恢复密钥，以及 `fileApi.uploadEncrypted`。
- 9 tests, including a full round trip: unwrap the file key with a real RSA private key, rebuild the AAD from the metadata, and decrypt back to the exact input bytes. 109 tests pass in total.
- 新增 9 项测试，含完整往返验证：用真实 RSA 私钥解包文件密钥、从 metadata 重建 AAD、解密回完全一致的输入字节。累计 109 项测试通过。

### Behaviour / 行为

- Recipient keys are fetched once per batch, not per file, and each file reports its own outcome so one rejected filename does not hide the uploads that succeeded.
- 接收方密钥按批次获取一次而非每个文件一次；每个文件单独报告结果，避免一个被拒的文件名掩盖其他成功的上传。
- The recovery key fingerprint is recomputed locally from the PEM and shown in the UI. It is never read from the API response field, because this is the one wrapping no client can verify.
- 恢复密钥指纹由客户端从 PEM 本地重算并在界面显示，绝不读取 API 响应中的该字段 —— 因为这是唯一无法被任何客户端验证的包装。
- Files above the 25 MiB limit are rejected before being read into memory, and `File.type` falls back to `application/octet-stream` when the browser reports nothing usable.
- 超过 25 MiB 限制的文件在读入内存前即被拒绝；当浏览器未能识别类型时，`File.type` 回退为 `application/octet-stream`。

### Verified end to end / 端到端验证

- Ran against a local MySQL 8.4 and backend: `01/02/03` SQL reports schema `OK` at revision `0004`, two files uploaded and accepted, each with an owner and a recovery wrapping, and `file_size_bytes == encrypted_size_bytes` confirming the tag stayed detached.
- 已在本地 MySQL 8.4 与后端上运行：`01/02/03` SQL 报告 schema `OK`、revision 为 `0004`；两个文件上传成功并被接受，各带所有者与恢复两份包装；`file_size_bytes == encrypted_size_bytes`，证明 tag 保持分离。
- Decrypted a stored file with the **offline recovery private key**, rebuilding AAD-3 in Python from the persisted metadata alone. This path touches none of the TypeScript, so it independently confirms both the AAD byte layout and the recovery wrapping — the one envelope no client can ever self-test.
- 已用**离线恢复私钥**解密一个已存储的文件，且仅凭数据库中持久化的元数据在 Python 侧重建 AAD-3。该路径完全不经过 TypeScript，因此独立确认了 AAD 字节布局与恢复包装 —— 后者是任何客户端都无法自检的唯一信封。
- Added `upload.integration.test.ts`, skipped unless `E2E_API_BASE` is set, so `npm test` stays offline while the live check stays reproducible.
- 已新增 `upload.integration.test.ts`，未设置 `E2E_API_BASE` 时自动跳过，使 `npm test` 保持离线，同时让线上检查可复现。

update: 2026/8/20

-------------------------------------------------------------------------------------------------------------
## CT-1.5

Base `main` @ `8e174c6` · Scope: recovery key provisioning · No application code changed
基线 `main` @ `8e174c6` · 范围：恢复密钥的配置工具 · 未修改应用代码

### Added / 新增

- `backend/scripts/register_recovery_key.py` — generates an RSA recovery key pair, writes the private half locally at mode 600, and registers only the public half through the ADMIN-only API route.
- `backend/scripts/register_recovery_key.py` — 生成 RSA 恢复密钥对，将私钥以 600 权限写入本地，并仅通过 ADMIN 专用 API 路由注册公钥。

### Why / 用途

- Every upload wraps its file key twice: to the owner's public key and to the active recovery public key. With no recovery key registered, the API answers `No active recovery public key is configured` and nothing can be uploaded. Staging hit exactly this after the browser-side encryption landed.
- 每次上传都会把文件密钥包装两次：给所有者公钥和给活跃的恢复公钥。若未注册恢复密钥，API 返回 `No active recovery public key is configured`，任何文件都无法上传。浏览器端加密上线后，staging 正是卡在这里。

### Safeguards / 保护措施

- Refuses to overwrite an existing private key file. Registering a new key revokes the previous one for new uploads but does not rewrap existing files, so the old private half must be retained.
- 拒绝覆盖已存在的私钥文件。注册新密钥会使旧密钥对新上传失效，但不会重新包装已有文件，因此旧私钥必须保留。
- Checks the account is `ADMIN` before generating anything, so a failed attempt leaves no key material behind.
- 在生成任何密钥材料之前先校验账号为 `ADMIN`，使失败的尝试不会遗留密钥材料。
- Compares the fingerprint the API reports against one computed locally and aborts on any difference.
- 将 API 返回的指纹与本地计算结果比对，不一致即中止。

### Verified / 验证

- Ran against the local backend: rotation moved the previous key to `REVOKED`, a new upload wrapped to the new key, and the new private half decrypted the stored ciphertext. Both guards were exercised and neither wrote a private key on failure.
- 已对本地后端运行：轮换将旧密钥置为 `REVOKED`，新上传包装给新密钥，新私钥成功解密已存储的密文。两道保护均已触发，且失败时都未写出私钥。

### Note / 说明

- The private key is not in offline or HSM custody, as `docs/SECURITY_FLOWS.md` describes for a real deployment. For this demonstration project it lives in `recovery_keys/`, which is gitignored in a private repository. Whoever holds it can decrypt every file uploaded under the matching public key.
- 本项目的私钥并未如 `docs/SECURITY_FLOWS.md` 对真实部署所述那样置于离线或 HSM 保管中。作为展示项目，它存放在 `recovery_keys/`（私有仓库中已被 gitignore）。持有该私钥者可解密以对应公钥上传的每一个文件。

update: 2026/8/20

---

## CT-1.6

### Baseline / 基线

- Created `CT-1.6` from the merged `main` commit `a742330`.
- 已从完成合并的 `main` 提交 `a742330` 创建 `CT-1.6`。

### Scope / 范围

- Making the encrypted files uploaded by CT-1.4 visible on the file page, plus the TLS fix CT-1.5 needed in order to run from a Mac. No change to any envelope format, AAD construction, or algorithm choice.
- 让 CT-1.4 上传的加密文件在文件页面上可见，以及 CT-1.5 在 Mac 上运行所需的 TLS 修复。未改动任何信封格式、AAD 构造或算法选择。

### Fixed / 修复

- The file page read `data.files` from a `GET /files` response whose rows live under `items`, then fell back to `[]`. Uploads had been succeeding and the ciphertext was on disk, but the page reported zero files with no error — the fallback turned a contract mismatch into what looked like an empty account.
- 文件页面从 `GET /files` 响应中读取 `data.files`，而数据行实际在 `items` 下，随后回落为 `[]`。上传其实一直成功、密文也已落盘，但页面显示零个文件且没有任何报错——这个回落把契约不匹配变成了看起来像"账户里没东西"。
- The frontend `FileOut` type declared `file_size`, which the API does not return. Both size columns would have shown `0 Bytes` even after the rows appeared. It now mirrors `FileSummaryOut`: `plaintext_size`, `ciphertext_size`, `mime_type`, `owner`, `created_at`, `updated_at`.
- 前端 `FileOut` 类型声明了 API 并不返回的 `file_size`，即使数据行显示出来，两列大小也都会是 `0 Bytes`。现已对齐 `FileSummaryOut`：`plaintext_size`、`ciphertext_size`、`mime_type`、`owner`、`created_at`、`updated_at`。
- `register_recovery_key.py` now builds its TLS context from the `certifi` bundle when the interpreter has no CA file of its own, which is the default state of a python.org Python on macOS. Verification is never disabled: the script's whole purpose is to establish which recovery public key to trust, and an unverified connection would let anyone on the path choose it.
- `register_recovery_key.py` 现在会在解释器自身没有 CA 文件时改用 `certifi` 证书包构建 TLS 上下文——macOS 上 python.org 版 Python 默认就是这个状态。校验从不关闭：该脚本的全部意义就是确定该信任哪个恢复公钥，而未校验的连接会让链路上的任何人替你选定它。

### Verified / 验证

- Frontend suite `122 passed | 3 skipped`, production build clean. End to end on staging: uploaded a 155.43 KB PDF, confirmed the ciphertext directory `<file_id>/<random>.ciphertext` on the server, and confirmed the file now appears on the file page with both sizes and its upload time.
- 前端测试 `122 passed | 3 skipped`，生产构建通过。staging 端到端：上传 155.43 KB 的 PDF，在服务器上确认密文目录 `<file_id>/<random>.ciphertext`，并确认文件现已出现在文件页面，两列大小与上传时间均正确。

### Limitations / 限制

- The list is still fetched as a single page of the API's default size. Pagination controls are not wired up, so an account with more than 25 files will not see the rest.
- 列表目前仍只请求 API 默认大小的第一页。分页控件尚未接入，因此文件超过 25 个的账户看不到其余部分。
- `mapFileStatus` receives the record status (`ACTIVE`), not an integrity verdict, so every row renders as "pending". Real integrity state comes from `POST /files/{id}/integrity-check`, which the page does not call.
- `mapFileStatus` 收到的是记录状态（`ACTIVE`）而非完整性判定，因此每一行都显示为 "pending"。真正的完整性状态来自 `POST /files/{id}/integrity-check`，而页面并未调用它。
- Download still returns ciphertext the page cannot open: unwrapping the file key needs the account private key, and no passphrase-unlock path exists yet. That is the next package.
- 下载目前仍返回页面无法打开的密文：解包文件密钥需要账户私钥，而 passphrase 解锁路径尚不存在。这是下一个工作包的内容。

update: 2026/8/23

---

## CT-1.7

### Baseline / 基线

- Created `CT-1.7` from the merged `main` commit `8b0b4e5`.
- 已从完成合并的 `main` 提交 `8b0b4e5` 创建 `CT-1.7`。

### Scope / 范围

- Turning the file content algorithm into a selectable parameter across all four layers that pin it: the browser, the API schema, the ORM model, and the database CHECK constraint. Key length only — no new construction, no new dependency.
- 把文件内容算法变成一个可选参数，覆盖将其写死的全部四层：浏览器、API schema、ORM 模型、数据库 CHECK 约束。仅涉及密钥长度，不引入新构造，也不引入新依赖。

### Added / 新增

- An algorithm registry in `primitives.ts`: the legal names, their key lengths, a narrowing predicate, and `supportedEncryptionAlgorithms()`, which probes the browser rather than assuming.
- `primitives.ts` 中的算法注册表：合法名称、对应密钥长度、收窄用的类型谓词，以及 `supportedEncryptionAlgorithms()`——它探测浏览器实际能力，而不做假设。
- Alembic revision `0005_selectable_aes_key_length`, and the matching production `02-schema.sql` DDL.
- Alembic revision `0005_selectable_aes_key_length`，以及配套的生产 `02-schema.sql` DDL。
- Four cross-implementation vectors covering AES-128 and AES-192, including an empty file and a CJK filename.
- 四组跨实现测试向量，覆盖 AES-128 与 AES-192，其中包含空文件与中文文件名两种情况。

### Why it needed no format change / 为什么无需改变格式

- AAD-3 already framed the algorithm name. That was designed in from the start, and it is what makes this extension safe: a relabelled file fails its tag rather than decrypting to something else. Had the name not been bound, adding a second algorithm would have required `aad_version = 2` and would have left every existing file on the old construction.
- AAD-3 此前就已经把算法名 frame 了进去。这是一开始就设计好的，也正是本次扩展得以安全进行的原因：被重新标注的文件会 tag 校验失败，而不是解密成别的东西。如果当初没有绑定这个名字，增加第二种算法就必须提升到 `aad_version = 2`，并会把所有已有文件留在旧构造上。

### Verified / 验证

- Frontend `211 passed | 18 skipped`; backend `269 passed`; Ruff clean on every file this package touched.
- 前端 `211 passed | 18 skipped`；后端 `269 passed`；本工作包触及的每个文件 Ruff 均通过。
- On disposable MySQL 8.4: `0001 -> 0005` upgrade, a `0005 -> 0004 -> 0005` round trip, and `alembic check` parity. The constraint was exercised directly — AES-128 and AES-192 rows insert, `AES-512-GCM` is refused with error 3819 — and the downgrade guard refused while those rows existed, then succeeded once they were gone.
- 在一次性 MySQL 8.4 上：`0001 -> 0005` 升级、`0005 -> 0004 -> 0005` 往返，以及 `alembic check` 一致性。约束本身也做了直接验证——AES-128 与 AES-192 数据行可以插入，`AES-512-GCM` 被 3819 错误拒绝——降级保护在这些数据行存在时拒绝执行，删除后则正常执行。
- The production SQL path `01 -> 02 -> 03` reports `schema_structure_status OK`, `readiness_marker_default_status OK`, `audit_singleton_status OK`, and `schema_compatibility_status OK` at `0005_selectable_aes_key_length`.
- 生产 SQL 路径 `01 -> 02 -> 03` 报告 `schema_structure_status OK`、`readiness_marker_default_status OK`、`audit_singleton_status OK`，`schema_compatibility_status` 在 `0005_selectable_aes_key_length` 上为 `OK`。
- The Python vectors were generated first and the TypeScript matched them byte for byte, in that order. Generating them from the browser output would have proved only that the code agrees with itself.
- Python 向量先生成，TypeScript 再逐字节匹配，顺序如此。若反过来由浏览器输出生成向量，就只能证明代码与自身一致。

### Limitations / 限制

- The choice is per upload and cannot be changed afterwards. Re-encrypting an existing file under a different algorithm would need a new envelope, because the algorithm name is inside the AAD.
- 该选择按每次上传生效，事后无法更改。将已有文件改用其他算法重新加密需要新的信封，因为算法名位于 AAD 之内。
- Nothing stops a user choosing AES-128 for material that warrants AES-256. There is no per-account or per-role floor, and no record of who chose what beyond the file's own metadata.
- 目前没有任何机制阻止用户为需要 AES-256 的内容选择 AES-128。既没有按账户或按角色的下限，除文件自身元数据外也没有记录谁选了什么。
- AES-192 availability is probed but not reported: a user on a browser without it simply sees two options rather than three, with no explanation.
- AES-192 的可用性会被探测但不会被说明：在不支持它的浏览器上，用户只会看到两个选项而不是三个，且没有任何解释。
- Key wrapping remains RSA-OAEP-SHA256 at every strength. The DEK is wrapped, not the plaintext, so the wrapping algorithm is unaffected by this choice.
- 密钥包装在任何强度下仍是 RSA-OAEP-SHA256。被包装的是 DEK 而非明文，因此包装算法不受此选择影响。
- ChaCha20-Poly1305 remains out of scope. WebCrypto does not provide it, so it needs a vetted third-party library; that is a team decision about dependencies, not a purely cryptographic one.
- ChaCha20-Poly1305 仍不在范围内。WebCrypto 未提供该算法，需要引入经过审计的第三方库；这属于团队关于依赖的决策，而非纯粹的密码学问题。

update: 2026/9/1

---

## CT-1.8

### Baseline / 基线

- Created `CT-1.8` from the merged `main` commit `e04f5fc`.
- 已从完成合并的 `main` 提交 `e04f5fc` 创建 `CT-1.8`。

### Scope / 范围

- Step 1 of adding ChaCha20-Poly1305: bring in the library, wrap it as a primitive, and prove it agrees with an independent implementation. Nothing is wired into the envelope, the API, the database, or the UI yet, so this package ships no user-visible change and no CHANGELOG entry.
- 加入 ChaCha20-Poly1305 的第一步：引入库、包装成原语、并证明它与独立实现一致。尚未接入信封、API、数据库或界面，因此本工作包没有用户可见的改动，也不写 CHANGELOG 条目。

### Why a library at all / 为什么必须引入库

- WebCrypto has no ChaCha20-Poly1305. Its only AEAD is AES-GCM; AES-CBC and AES-CTR are unauthenticated, and using one of those would discard the integrity guarantee the whole envelope rests on. So genuine algorithm diversity — as opposed to another AES key length — cannot be had from the platform alone.
- WebCrypto 不提供 ChaCha20-Poly1305。它唯一的 AEAD 是 AES-GCM；AES-CBC 与 AES-CTR 不带认证，采用其中之一等于丢弃整个信封赖以成立的完整性保证。因此真正的算法多样性（区别于再加一种 AES 密钥长度）无法仅靠平台自身获得。
- `@noble/ciphers@2.4.0` was chosen for having **zero transitive dependencies** — the supply-chain surface is one package — and for being audited, pure TypeScript, and free of WASM. The ChaCha20-Poly1305 path costs about 4.7 KB gzipped.
- 选择 `@noble/ciphers@2.4.0` 的理由是它**没有任何传递依赖**——供应链面就这一个包——并且经过审计、纯 TypeScript、不含 WASM。ChaCha20-Poly1305 这条路径的体积代价约为 gzip 后 4.7 KB。

### Added / 新增

- `chacha20Poly1305EncryptDetached` and `chacha20Poly1305DecryptDetached`, deliberately mirroring the AES-GCM pair: same parameter names, same detached-tag split, and the same `AuthenticationFailure` on a bad tag, so callers handle one failure mode rather than two.
- `chacha20Poly1305EncryptDetached` 与 `chacha20Poly1305DecryptDetached`，有意与 AES-GCM 那一对保持镜像：相同的参数名、相同的分离式 tag 切分方式、tag 校验失败时抛出同一个 `AuthenticationFailure`，使调用方只需处理一种失败模式而不是两种。
- Vectors under `chacha20_poly1305_detached`, the first of which is **RFC 8439 section 2.8.2** — the standard's own test vector. python-cryptography reproduces it exactly, and the TypeScript then reproduces python-cryptography exactly, so the suite is anchored to the specification rather than to two implementations agreeing with each other.
- `chacha20_poly1305_detached` 下的测试向量，其中第一组是 **RFC 8439 第 2.8.2 节**——标准自带的测试向量。python-cryptography 精确复现了它，TypeScript 又精确复现了 python-cryptography，因此整套向量锚定在规范上，而不是锚定在两个实现彼此一致上。

### The shapes line up / 形状恰好一致

- ChaCha20-Poly1305 takes a 32-byte key, a 12-byte nonce, and produces a 16-byte tag — the same as AES-256-GCM, and the ciphertext is the same length as the plaintext once the tag is detached. One stored column layout, one `ck_files_encryption_envelope` length check, and one envelope can therefore serve both constructions. A test asserts this rather than leaving it as a comment, because the next step depends on it.
- ChaCha20-Poly1305 使用 32 字节密钥、12 字节 nonce，产生 16 字节 tag——与 AES-256-GCM 完全相同，且分离 tag 之后密文长度等于明文长度。因此一套存储列布局、一条 `ck_files_encryption_envelope` 长度检查、一个信封即可同时服务两种构造。这一点由测试断言而非仅写在注释里，因为下一步依赖于它。

### A property that is genuinely lost / 一个确实失去的性质

- The AES path imports its key as a **non-extractable** `CryptoKey`: once imported, the page can decrypt with it but can no longer read the bytes back out, so a later bug cannot serialise a key into a log line or a request body. A library implementation cannot offer that — it must read the key material to work — so a ChaCha key stays a plain `Uint8Array`. This is a real reduction in defence in depth, documented at the function rather than discovered later. It does not affect the confidentiality of the ciphertext itself.
- AES 那条路径把密钥导入为**不可导出**的 `CryptoKey`：导入之后页面能用它解密，却再也读不出密钥字节，因此后续的 bug 无法把密钥序列化进日志或请求体。库实现做不到这一点——它必须读取密钥材料才能工作——所以 ChaCha 的密钥只能是普通的 `Uint8Array`。这是纵深防御上的实际削弱，已写在函数处而非留待日后发现。它不影响密文本身的机密性。

### Verified / 验证

- Frontend `222 passed | 18 skipped`, `vue-tsc --noEmit` clean, production build unchanged.
- 前端 `222 passed | 18 skipped`，`vue-tsc --noEmit` 通过，生产构建产物未变。
- The bundle is byte-identical to before, hash included: nothing in the application reaches this code yet, so it is tree-shaken away. The 4.7 KB will appear only when the next step wires it in.
- 打包产物与之前逐字节相同，连 hash 都一样：目前应用代码还没有到达这段代码的路径，因此被 tree-shake 掉了。那 4.7 KB 只有在下一步接入后才会出现。

### Next / 下一步

- Add the algorithm to the registry, the AAD, the API `Literal`, and the database CHECK, following the shape CT-1.7 established. The database work is smaller than CT-1.7's: only the algorithm name widens, because the nonce and tag lengths already match.
- 按 CT-1.7 建立的形态，把该算法加入注册表、AAD、API 的 `Literal` 以及数据库 CHECK。数据库改动比 CT-1.7 更小：只需放宽算法名，因为 nonce 与 tag 长度本就一致。

update: 2026/9/1

---

## CT-1.8 step 2 / 第二步

### Scope / 范围

- Wiring ChaCha20-Poly1305 through the registry, the envelope, the API schema, the database, and the upload page. Revision `0006_chacha20_poly1305`.
- 把 ChaCha20-Poly1305 接入注册表、信封、API schema、数据库与上传页面。Revision 为 `0006_chacha20_poly1305`。

### Changed / 变更

- Replaced the flat key-length table with a suite table carrying key, nonce and tag lengths per algorithm. Every current suite uses a 12-byte nonce, but nothing assumes it any more -- `encryptFile` now draws its nonce from the suite rather than from the AES constant, so a future suite with a different nonce length cannot silently inherit the wrong one.
- 已将原先扁平的密钥长度表替换为套件表，按算法记录密钥、nonce 与 tag 长度。当前所有套件都使用 12 字节 nonce，但代码不再假定这一点——`encryptFile` 现在从套件而非 AES 常量取 nonce 长度，因此未来若加入 nonce 长度不同的套件，不会静默继承错误的取值。
- The construction is chosen in exactly two functions, `sealWith` and `openWith`. Everything above them -- the AAD, the detached tag, the length checks, the mandatory self-test -- is shared, so a third suite is added in one place.
- 构造的选择只发生在 `sealWith` 与 `openWith` 两个函数中。它们之上的一切——AAD、分离式 tag、长度检查、强制自测——都是共用的，因此加入第三种套件只需改一处。
- `NormalizedIdentity` now types its algorithm as `EncryptionAlgorithm` rather than `string`. The narrowing already happened inside `normalizeIdentity`; encoding it in the type means the dispatch needs no cast that could outlive the check.
- `NormalizedIdentity` 现在把算法字段的类型标注为 `EncryptionAlgorithm` 而非 `string`。收窄本来就发生在 `normalizeIdentity` 内部，把它写进类型意味着分发处不需要一个可能比检查存活更久的类型断言。

### The test that matters most / 最要紧的那条测试

- `AES-256-GCM` and `ChaCha20-Poly1305` agree on every structural property: 32-byte key, 12-byte nonce, 16-byte tag, ciphertext the length of the plaintext. No length check can tell them apart, so the AAD binding is the sole separator. Two tests assert that a file written under either name fails authentication when opened as the other. Without them, removing the algorithm from AAD-3 would leave the whole suite green.
- `AES-256-GCM` 与 `ChaCha20-Poly1305` 在每一项结构性质上都一致：32 字节密钥、12 字节 nonce、16 字节 tag、密文长度等于明文。没有任何长度检查能区分它们，因此 AAD 绑定是唯一的分隔手段。两条测试断言：以任一名称写出的文件，被当作另一种打开时必须认证失败。若没有它们，把算法名从 AAD-3 中移除会让整个测试套件依然全绿。

### Found while testing / 测试中发现

- `ck_files_encryption_envelope` compared the algorithm name case-insensitively, because the column collates as `utf8mb4_unicode_ci`. `aes-256-gcm` inserted cleanly. This predates ChaCha20-Poly1305 and predates CT-1.7 -- the original `= 'AES-256-GCM'` had the same property -- and was found only by probing the constraint directly rather than trusting that it read correctly. Fixed here because this revision rewrites the same constraint. It was never reachable through the API, so this is a defence-in-depth repair rather than a vulnerability fix.
- `ck_files_encryption_envelope` 此前按大小写不敏感的方式比较算法名，因为该列的排序规则是 `utf8mb4_unicode_ci`，`aes-256-gcm` 可以直接插入。这个问题早于 ChaCha20-Poly1305、也早于 CT-1.7——原来的 `= 'AES-256-GCM'` 具有同样的性质——它是通过直接戳约束而非相信它「读起来正确」才被发现的。由于本 revision 正好重写同一条约束，因此在此一并修复。通过 API 永远走不到这一步，所以这属于纵深防御的修补，而非漏洞修复。

### Verified / 验证

- Frontend `233 passed | 18 skipped`, `vue-tsc --noEmit` clean; backend `269 passed`, Ruff clean on every file touched.
- 前端 `233 passed | 18 skipped`，`vue-tsc --noEmit` 通过；后端 `269 passed`，本次触及的每个文件 Ruff 均通过。
- Python generated the ChaCha20-Poly1305 envelope vectors first and the TypeScript reproduced them byte for byte, so the offline recovery path is known to open files written under the new suite -- the check that decides whether a file can ever be recovered.
- ChaCha20-Poly1305 的信封向量由 Python 先生成，TypeScript 再逐字节复现，因此可以确认离线恢复路径能打开以新套件写出的文件——这是决定一个文件将来能否被恢复的那道检查。
- On disposable MySQL 8.4: `0001 -> 0006`, a `0006 -> 0005 -> 0006` round trip, and `alembic check` parity. All four names insert; `chacha20-poly1305` is refused with error 3819; the downgrade guard refused while a ChaCha file existed. The production SQL path reports `schema_structure_status OK`, `readiness_marker_default_status OK`, `audit_singleton_status OK`, and `schema_compatibility_status OK` at `0006_chacha20_poly1305`.
- 在一次性 MySQL 8.4 上：`0001 -> 0006`、`0006 -> 0005 -> 0006` 往返，以及 `alembic check` 一致。四个名称均可插入；`chacha20-poly1305` 被 3819 错误拒绝；存在 ChaCha 文件时降级保护拒绝执行。生产 SQL 路径报告 `schema_structure_status OK`、`readiness_marker_default_status OK`、`audit_singleton_status OK`，`schema_compatibility_status` 在 `0006_chacha20_poly1305` 上为 `OK`。

### Limitations / 限制

- The account key envelopes stay AES-256-GCM. They record no algorithm a reader could disagree with, so there is nothing to select and nothing to bind; giving them a choice would create a downgrade surface for no benefit.
- 账户密钥信封仍为 AES-256-GCM。它们不记录任何读取方可能产生分歧的算法名，因此既无从选择也无需绑定；给它们加上选择只会凭空造出一个降级面，而没有任何收益。
- A ChaCha key is a plain `Uint8Array`, not a non-extractable `CryptoKey`, because a library implementation must read the key material. Documented at the function in step 1; unchanged here.
- ChaCha 的密钥是普通 `Uint8Array` 而非不可导出的 `CryptoKey`，因为库实现必须读取密钥材料。这一点在第一步已写在函数处，本步未改变。
- There is still no per-account or per-role floor on the choice, and no record of who chose what beyond the file's own metadata.
- 目前仍没有按账户或按角色的算法下限，除文件自身元数据外也没有记录谁选了什么。

update: 2026/9/2
