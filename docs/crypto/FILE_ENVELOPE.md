# File Encryption Envelope — v1

English | [简体中文](FILE_ENVELOPE.zh-CN.md)

Normative byte-level definition of how a file is encrypted before upload. The reference
implementation is `frontend/src/crypto/file_envelope.ts`; the vectors that lock it are in
`test_vectors.json` beside this file.

**Read this before writing a second implementation.** The server never holds a data
encryption key, so it never computes this AAD and never authenticates this tag. No
server-side check can catch an implementation that builds these bytes differently — it will
simply produce files that nobody can decrypt, and the failure appears at download, not at
upload. This project already carries three mutually incompatible AAD constructions for the
account-key envelopes because that mistake was made once.

## 1. Suite constants

| Field | Value |
|---|---|
| `envelope_version` | 1 |
| `aad_version` | 1 |
| `encryption_algorithm` | `AES-128-GCM`, `AES-192-GCM`, `AES-256-GCM`, `AES-256-GCM-SIV`, `ChaCha20-Poly1305` or `XChaCha20-Poly1305`; `AES-256-GCM` by default |
| `key_wrapping_algorithm` | `RSA-OAEP-SHA256`, SHA-256 MGF1, **empty label** |
| DEK | 16, 24, or 32 random bytes to match the algorithm, fresh per file |
| Nonce | 12 random bytes (24 for `XChaCha20-Poly1305`), fresh per encryption, from a CSPRNG |
| Tag | 16 bytes, stored **detached** from the ciphertext |

Two families, not one. The three plain AES-GCM entries differ only in key length;
`ChaCha20-Poly1305` (RFC 8439) is a stream cipher authenticated by Poly1305, where AES-GCM is
a block cipher authenticated by GHASH. Each family has one entry that answers the basic
construction's weak point, a repeated nonce: `AES-256-GCM-SIV` (RFC 8452) derives its IV from
the message, so a repeat reveals only that two messages were equal, and `XChaCha20-Poly1305`
(draft-irtf-cfrg-xchacha, as libsodium implements it) takes a 24-byte nonce that never
realistically repeats when chosen at random. Every file already gets a fresh DEK, so neither
property is needed to keep SecureView safe; they are offered as alternatives and for comparison.

Every entry is an AEAD, produces a 16-byte tag, and yields ciphertext the same length as the
plaintext. All take a 12-byte nonce except `XChaCha20-Poly1305` (24 bytes), so the nonce length
is per suite: the database CHECK constraint (`ck_files_encryption_envelope`, revision
`0009_more_aead_suites`) and the API schema state the same table, and `files.iv` was already
`VARBINARY(32)`. The AES-GCM entries run in WebCrypto; `AES-256-GCM-SIV` and both ChaCha
entries run in `@noble/ciphers`, whose output is checked against RFC 8452's vectors, OpenSSL and
libsodium in `docs/crypto/test_vectors.json`.

**Nothing unauthenticated may be added to this table.** AES-CBC and AES-CTR are available in
WebCrypto and would silently discard the integrity guarantee everything here rests on. 3DES is
excluded for that reason and its own: it is not an AEAD, its 8-byte block would break the
shared nonce and tag lengths, and NIST withdrew it for encryption in 2023.

The name is framed into the AAD, so ciphertext written under one algorithm cannot be
relabelled as another without the tag failing. This matters most between `AES-256-GCM`,
`AES-256-GCM-SIV` and `ChaCha20-Poly1305`: all take a 32-byte key and a 12-byte nonce and
produce a 16-byte tag, so **no length check distinguishes them and the AAD binding is the only
thing that does.** A
reader must take the algorithm from the file's own stored metadata, compare the name exactly
including case, and reject anything not in this table.

The account-key envelopes — the wrapped AMK and the encrypted private-key bundle — are
**always AES-256-GCM** and are not affected by this choice. They record no algorithm a reader
could disagree with, so there is nothing to select and nothing to bind.

Nonces must be random, never a counter. A counter cannot be coordinated across tabs or
devices, and a repeated (key, nonce) pair under GCM discloses the XOR of both plaintexts and
allows forgery through authentication-key recovery.

## 2. Encoding primitives

Unsigned big-endian throughout. Variable-length fields are length-prefixed; fixed-width
fields are not. Framing is what makes the encoding injective — without it, adjacent fields
can be shifted against each other to produce a colliding byte string.

| Primitive | Definition |
|---|---|
| `u8(n)` / `u32(n)` / `u64(n)` | 1 / 4 / 8 bytes, unsigned big-endian |
| `uuid16(u)` | the 16 raw bytes of an RFC 4122 UUID, not its text form |
| `ascii(s)` | ASCII bytes; non-ASCII input is an error |
| `utf8_nfc(s)` | UTF-8 bytes after Unicode NFC normalization |
| `frame(b)` | `u32(len(b)) || b` |
| `||` | concatenation |

These match `key_service._frame` in the backend, so one encoder serves both this envelope and
the account-key authorization digests.

## 3. AAD-3 — file content

```
AAD-3 = ascii("FYP-FILE-CONTENT") || 0x00 || u8(aad_version)
      || uuid16(file_id)
      || u32(envelope_version)
      || frame(ascii(encryption_algorithm))
      || u64(plaintext_size)
      || frame(utf8_nfc(original_filename))
      || frame(ascii(lowercase(mime_type)))
```

The `0x00` after the label prevents one domain label from being a prefix of another.

### Nothing per-recipient may appear here

The owner and every share recipient decrypt the **same ciphertext with the same DEK**, so
they must all rebuild identical AAD bytes. `key_id`, `wrapped_file_key`, `owner_key_id`,
`recovery_key_id` and grant state are therefore excluded — `FileCryptoEnvelopeOut` returns
the *caller's* key id, so binding it would make every shared file undecryptable for the
recipient.

### Filename, MIME type and size are bound deliberately

The server stores these three in cleartext columns and could otherwise rewrite them freely,
serving a recipient a document labelled as something it is not, or mislabelling a payload's
type to influence how the client handles it. Binding them turns any such edit into a
decryption failure.

The cost is that **the three fields become immutable for the lifetime of the ciphertext**.
That is currently sound — `file_router` exposes upload, list, get, download, delete and
integrity-check, with no rename or metadata-update route — but a future rename feature cannot
edit these columns in place. It would need re-encryption under a new envelope, or
`envelope_version = 2` moving the filename into `encrypted_manifest`. Record this constraint
before designing any rename feature.

### Normalization is part of the specification

Apply the same rules `FileUploadMetadata` applies, and send the normalized values, so the
string hashed at upload is byte-identical to the one returned at download:

- `original_filename`: Unicode **NFC**, 1–255 characters, no surrounding whitespace, no
  `/ \` path separators, no Unicode `Cc` characters, not `.` or `..`, and not ending in a
  space or period.
- `mime_type`: **lowercased**, matching `^type/subtype$` with no parameters, 3–150
  characters.

## 4. Detached tag

`crypto.subtle` returns `ciphertext || tag` as one buffer. The API stores the tag separately
and the stored ciphertext excludes it, so implementations must split on encrypt and rejoin on
decrypt:

```
encrypt:  out        = AES-GCM(dek, nonce, plaintext, AAD-3)
          ciphertext = out[0 .. len-16]
          auth_tag   = out[len-16 .. len]

decrypt:  plaintext  = AES-GCM-open(dek, nonce, ciphertext || auth_tag, AAD-3)
```

This is enforced numerically: `file_service` rejects an upload whose ciphertext length
differs from `plaintext_size`. A joined buffer is 16 bytes too long and fails there.

## 5. Upload payload

`POST /files` takes multipart: the ciphertext body plus a JSON metadata part.

| Metadata field | Source |
|---|---|
| `file_id` | client-generated RFC 4122 v4 UUID |
| `original_filename`, `mime_type`, `plaintext_size` | normalized per §3 |
| `encryption_algorithm`, `envelope_version`, `aad_version` | §1 |
| `nonce`, `auth_tag` | canonical Base64, 12 and 16 bytes |
| `owner_key_id`, `wrapped_file_key` | DEK wrapped to the owner's active public key |
| `recovery_key_id`, `recovery_wrapped_file_key` | DEK wrapped to the active recovery key |
| `key_wrapping_algorithm` | `RSA-OAEP-SHA256` |

Every binary field is standard Base64 with `+/` and mandatory `=` padding — never URL-safe,
never unpadded. The API rejects anything that does not re-encode to the identical string.

## 6. Required self-tests

The server cannot verify that this ciphertext decrypts to anything. A client that writes a
well-formed but unopenable envelope produces a file that is lost the moment the plaintext is
discarded, so these checks are mandatory, not defensive.

**Before upload:** decrypt the ciphertext with the DEK, nonce, tag and AAD-3 and confirm the
plaintext is byte-identical to the input; confirm the ciphertext length equals
`plaintext_size`. The ceiling is `MAX_UPLOAD_SIZE_BYTES`, 500 MiB by default, so near the
top of that range this second pass dominates the cost of an upload and holds several copies
of the file in memory at once.

**Before sharing:** unwrap the DEK from your own wrapping and rewrap it to the recipient.
The client does not decrypt the file first. An earlier version of this section asked for that,
but `verifyDekOpensFile` needs the whole ciphertext, so a share would have to download the
file in full before it could start, and for a large file that is slower than the share itself.
It is also not needed for safety:

- RSA-OAEP decryption is authenticated. A wrapping made under a different key, or altered in
  transit, fails to unwrap rather than yielding wrong bytes, and `unwrapDek` then checks that
  the result has the key length the suite requires. A DEK that reaches the rewrap step is the
  one that was sealed at upload.
- The rewrapping itself cannot be checked, because the recipient's private key is not
  available. The server checks the shape of what is sent (an RSA-OAEP ciphertext of 384
  bytes for a key of 3072 bits).
- If a wrong DEK were shared anyway, the recipient's download fails closed. The server first
  compares the stored ciphertext against its recorded SHA-256, then the recipient's browser
  verifies the AEAD tag under the DEK it unwrapped. A wrong DEK fails that tag check, so the
  recipient sees an error and no plaintext. Nothing about the file leaks, because the
  ciphertext was already theirs to download the moment the grant existed, and the DEK they
  hold opens nothing.

So the cost of a bad share is a grant that does not work, which the recipient notices at
once, and not a disclosure. Do recompute the recipient's public key fingerprint from the PEM
and show it. Nothing else binds that key to the intended person.

**Not verifiable at all:** the recovery wrapping. The recovery private key is held offline,
so a client cannot confirm `recovery_wrapped_file_key` decrypts to the DEK. A wrong or
substituted recovery key is discovered only when a recovery is attempted, possibly years
later. Mitigate by pinning and displaying the recovery public-key fingerprint, refusing to
upload if it changes without an out-of-band announcement, and rehearsing recovery on real
uploads periodically.

## 7. Version migration

`envelope_version` and `aad_version` are independent: a new AAD layout does not necessarily
change the envelope shape. Reject any version you do not implement, and report it as an
unsupported-version error rather than guessing or falling back — a server that can move a
client to a weaker suite by advertising it has a downgrade attack. File envelopes are
effectively immutable, so v1 decryption must be retained for as long as any v1 file exists.
