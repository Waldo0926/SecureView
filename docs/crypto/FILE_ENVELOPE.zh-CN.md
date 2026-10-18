# 文件加密信封 — v1

[English](FILE_ENVELOPE.md) | 简体中文

本文是文件上传前如何加密的规范性字节级定义。参考实现为
`frontend/src/crypto/file_envelope.ts`，锁定它的测试向量位于同目录的 `test_vectors.json`。

**在编写第二个实现之前请先读本文。** 服务器从不持有数据加密密钥（DEK），因此它从不计算这个
AAD，也从不认证这个 tag。没有任何服务端检查能发现某个实现把这些字节拼错了 —— 后果只是产出
谁也解不开的文件，而且失败发生在下载时，不是上传时。本项目的账户密钥信封已经因为犯过一次
这个错误，同时存在三套互不兼容的 AAD 构造。

## 1. 套件常量

| 字段 | 取值 |
|---|---|
| `envelope_version` | 1 |
| `aad_version` | 1 |
| `encryption_algorithm` | `AES-128-GCM`、`AES-192-GCM`、`AES-256-GCM`、`AES-256-GCM-SIV`、`ChaCha20-Poly1305` 或 `XChaCha20-Poly1305`；默认 `AES-256-GCM` |
| `key_wrapping_algorithm` | `RSA-OAEP-SHA256`，SHA-256 MGF1，**空 label** |
| DEK | 16、24 或 32 随机字节，与算法匹配，每个文件全新生成 |
| Nonce | 12 随机字节（`XChaCha20-Poly1305` 为 24 字节），每次加密全新生成，来自 CSPRNG |
| Tag | 16 字节，与密文**分离**存储 |

这是两个算法族，而不是一个。三个普通 AES-GCM 条目之间只差密钥长度；`ChaCha20-Poly1305`（RFC 8439）
是由 Poly1305 认证的流密码，而 AES-GCM 是由 GHASH 认证的分组密码。每个算法族各有一项针对基本构造的弱点——
nonce 重复：`AES-256-GCM-SIV`（RFC 8452）从消息本身推导 IV，重复时只会暴露“两条消息相同”；
`XChaCha20-Poly1305`（draft-irtf-cfrg-xchacha，按 libsodium 的实现）使用 24 字节 nonce，随机选取时实际上不会重复。
每个文件本来就使用全新的 DEK，所以 SecureView 的安全并不依赖这两项特性；它们作为可选项和对比而提供。

表中每一项都是 AEAD，都产生 16 字节 tag，且密文长度等于明文长度。除 `XChaCha20-Poly1305`（24 字节）外都使用
12 字节 nonce，因此 nonce 长度按算法而定：数据库 CHECK 约束（`ck_files_encryption_envelope`，revision
`0009_more_aead_suites`）与 API schema 列出同一张表，`files.iv` 原本就是 `VARBINARY(32)`。AES-GCM 各项在 WebCrypto 中运行；
`AES-256-GCM-SIV` 与两种 ChaCha 在 `@noble/ciphers` 中运行，其输出在 `docs/crypto/test_vectors.json` 中与 RFC 8452 向量、
OpenSSL 和 libsodium 逐字节比对。

**不得向本表加入任何不带认证的算法。** WebCrypto 提供了 AES-CBC 与 AES-CTR，采用它们会静默地
丢弃这里一切所依赖的完整性保证。3DES 被排除，除上述原因外还有其自身的问题：它根本不是 AEAD，
8 字节分组会破坏上面共用的 nonce 与 tag 长度，且 NIST 已于 2023 年将其用于加密的用途废止。

算法名会被 frame 进 AAD，因此在某一算法下写出的密文无法被重新标注为另一种而不导致 tag 校验失败。
这一点在 `AES-256-GCM`、`AES-256-GCM-SIV` 与 `ChaCha20-Poly1305` 之间尤为关键：三者都使用 32 字节密钥、12 字节
nonce，并产生 16 字节 tag，因此**没有任何长度检查能区分它们，唯一能区分的就是 AAD 绑定**。读取方
必须从文件自身存储的元数据中取得算法名，按精确大小写比较，并拒绝不在上表中的任何名称。

账户密钥信封（包装后的 AMK 与加密私钥包）**始终是 AES-256-GCM**，不受此选择影响。它们不记录任何
读取方可能产生分歧的算法名，因此既无从选择，也无需绑定。

Nonce 必须随机，绝不能用计数器。计数器无法在多个标签页或多台设备之间协调，而 GCM 下重复的
(key, nonce) 组合会泄露两段明文的异或值，并可通过恢复认证密钥实现伪造。

## 2. 编码原语

全程无符号大端序。变长字段加长度前缀，定长字段不加。加 frame 正是编码具备单射性的原因 ——
否则可以让相邻字段互相移位，产生相同的字节串。

| 原语 | 定义 |
|---|---|
| `u8(n)` / `u32(n)` / `u64(n)` | 1 / 4 / 8 字节，无符号大端 |
| `uuid16(u)` | RFC 4122 UUID 的 16 个原始字节，不是文本形式 |
| `ascii(s)` | ASCII 字节；非 ASCII 输入报错 |
| `utf8_nfc(s)` | Unicode NFC 归一化后的 UTF-8 字节 |
| `frame(b)` | `u32(len(b)) || b` |
| `||` | 连接 |

这些与后端 `key_service._frame` 一致，因此同一份编码器可同时服务本信封与账户密钥授权摘要。

## 3. AAD-3 —— 文件内容

```
AAD-3 = ascii("FYP-FILE-CONTENT") || 0x00 || u8(aad_version)
      || uuid16(file_id)
      || u32(envelope_version)
      || frame(ascii(encryption_algorithm))
      || u64(plaintext_size)
      || frame(utf8_nfc(original_filename))
      || frame(ascii(lowercase(mime_type)))
```

label 之后的 `0x00` 用于防止某个域分隔标签成为另一个的前缀。

### 不得包含任何按接收方变化的字段

所有者与每个共享接收方使用**同一把 DEK 解密同一份密文**，因此他们必须重建出完全相同的 AAD
字节。故 `key_id`、`wrapped_file_key`、`owner_key_id`、`recovery_key_id` 及授权状态全部排除
—— `FileCryptoEnvelopeOut` 返回的是**调用者自己的** key id，绑定它会导致每个共享文件对接收方
都无法解密。

### 文件名、MIME 类型与大小是刻意绑定的

服务器以明文列存储这三项，本可随意改写：把某份文档以另一个名字提供给接收方，或通过错误标注
类型来影响客户端的处理方式。绑定它们之后，任何此类修改都会变成解密失败。

代价是**这三个字段在密文的整个生命周期内不可变**。当前这是成立的 —— `file_router` 只暴露
上传、列表、获取、下载、删除与完整性检查，不存在改名或元数据更新路由 —— 但将来的改名功能无法
就地修改这些列，只能以新信封重新加密，或升级到 `envelope_version = 2` 把文件名移入
`encrypted_manifest`。**在设计任何改名功能之前，必须先记录这条约束。**

### 归一化是规范的一部分

必须施加与 `FileUploadMetadata` 相同的规则，并发送归一化后的取值，以保证上传时参与哈希的
字符串与下载时返回的字符串逐字节一致：

- `original_filename`：Unicode **NFC**，1–255 字符，无首尾空白，不含 `/ \` 路径分隔符，
  不含 Unicode `Cc` 类字符，不为 `.` 或 `..`，且不以空格或句点结尾。
- `mime_type`：**转为小写**，匹配 `^type/subtype$` 且不带参数，3–150 字符。

## 4. 分离 tag

`crypto.subtle` 返回 `ciphertext || tag` 拼接成的单一缓冲区。API 单独存储 tag，且存储的密文
不含 tag，因此实现必须在加密后拆分、解密前重新拼接：

```
encrypt:  out        = AES-GCM(dek, nonce, plaintext, AAD-3)
          ciphertext = out[0 .. len-16]
          auth_tag   = out[len-16 .. len]

decrypt:  plaintext  = AES-GCM-open(dek, nonce, ciphertext || auth_tag, AAD-3)
```

这一点在数值上被强制：`file_service` 会拒绝密文长度与 `plaintext_size` 不一致的上传。拼接后的
缓冲区正好多出 16 字节，会在那里被拒。

## 5. 上传载荷

`POST /files` 接收 multipart：密文主体加一个 JSON metadata 部分。

| metadata 字段 | 来源 |
|---|---|
| `file_id` | 客户端生成的 RFC 4122 v4 UUID |
| `original_filename`、`mime_type`、`plaintext_size` | 按 §3 归一化 |
| `encryption_algorithm`、`envelope_version`、`aad_version` | 见 §1 |
| `nonce`、`auth_tag` | 规范 Base64，12 与 16 字节 |
| `owner_key_id`、`wrapped_file_key` | DEK 包装给所有者的活跃公钥 |
| `recovery_key_id`、`recovery_wrapped_file_key` | DEK 包装给活跃的恢复公钥 |
| `key_wrapping_algorithm` | `RSA-OAEP-SHA256` |

所有二进制字段一律使用带 `+/` 与强制 `=` 填充的标准 Base64 —— 绝不使用 URL-safe，绝不省略
填充。API 会拒绝任何重新编码后与原字符串不一致的取值。

## 6. 强制自检

服务器无法验证这份密文能否解出任何东西。写出一个结构合法却打不开的信封，明文一旦丢弃，该
文件就永久丢失。因此以下检查是强制要求，而非防御性措施。

**上传前**：用该 DEK、nonce、tag 与 AAD-3 解密刚生成的密文，确认明文与输入逐字节一致；确认
密文长度等于 `plaintext_size`。上限 `MAX_UPLOAD_SIZE_BYTES` 默认为 500 MiB，接近该上限时这一步
会成为上传的主要开销，并同时在内存中保留文件的多份副本。

**共享前**：从自己的包装中解出 DEK，再 rewrap 给接收方。客户端不会先把文件解密一遍。这一节
早先的版本要求这样做，但 `verifyDekOpensFile` 需要整份密文，于是每次分享都得先把文件完整下载
下来，大文件时这一步比分享本身还慢。而且安全上也不需要这一步：

- RSA-OAEP 解密本身是带认证的。用别的密钥包装的、或传输中被改过的 wrapping 会直接解不开，
  不会解出一串错误的字节；随后 `unwrapDek` 还会检查结果长度是否等于该套件要求的密钥长度。
  能走到 rewrap 这一步的 DEK，就是上传时封装的那把。
- rewrap 本身无法验证，因为接收方的私钥不在手上。服务器会检查发送内容的形状（3072 位密钥
  对应 384 字节的 RSA-OAEP 密文）。
- 就算真的分享了一把错的 DEK，接收方的下载也会安全地失败。服务器先把存储的密文和记录的
  SHA-256 比对，然后接收方浏览器用解出的 DEK 验证 AEAD tag。错的 DEK 过不了 tag 校验，接收方
  看到的是报错而不是明文。文件内容不会泄露：授权一旦存在密文本来就允许他们下载，而他们手里
  的 DEK 什么也打不开。

所以分享错 DEK 的代价是一个不生效的授权，接收方马上就会发现，而不是一次泄露。接收方公钥指纹
仍然要从 PEM 重算并展示。除此之外没有任何机制把那把密钥绑定到目标本人。

**完全无法验证**：恢复包装。恢复私钥保存在离线环境，客户端无从确认
`recovery_wrapped_file_key` 能解出该 DEK。错误或被替换的恢复密钥只有在真正尝试恢复时才会被
发现，可能已是数年之后。缓解方式：固定并显示恢复公钥指纹，在其未经带外公告而变化时拒绝上传，
并定期对真实上传演练恢复流程。

## 7. 版本迁移

`envelope_version` 与 `aad_version` 相互独立：新的 AAD 布局未必意味着信封形状发生变化。必须
拒绝任何自身未实现的版本，并报告为「版本不受支持」，不得猜测也不得回退 —— 能够通过声明某个
较弱套件把客户端拉过去的服务器，就掌握了一次降级攻击。文件信封实际上不可变，因此只要还存在
任何 v1 文件，就必须保留 v1 的解密能力。
