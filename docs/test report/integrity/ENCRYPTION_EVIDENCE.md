# Showing that files are really encrypted

[English](ENCRYPTION_EVIDENCE.md) | [简体中文](ENCRYPTION_EVIDENCE.zh-CN.md)

The file list shows each file's original size and encrypted size, and they are the same.
Someone seeing that for the first time reasonably asks whether anything was encrypted or
whether only the name changed. This page answers that question, shows how to demonstrate the
answer live, and says what the evidence does and does not prove.

## Why the two sizes match

SecureView encrypts with AES-128/192/256-GCM, AES-256-GCM-SIV, ChaCha20-Poly1305 or XChaCha20-Poly1305.
All of them are *stream-style* authenticated ciphers: they encrypt byte for byte, with **no padding**, so the ciphertext is
exactly as long as the original file. Two small things are added, and neither is appended to the
file:

| Item | Size | Where it lives |
| --- | --- | --- |
| Nonce (the "IV") | 12 bytes (24 for XChaCha20-Poly1305) | the file's metadata row in the database |
| Authentication tag | 16 bytes | the file's metadata row, **detached** from the ciphertext |

The backend enforces this: it rejects an upload whose ciphertext length differs from the
declared original size ([`docs/crypto/FILE_ENVELOPE.md`](../../crypto/FILE_ENVELOPE.md) §4).

If you were expecting the file to grow, you were thinking of a block mode such as AES-CBC,
which pads to 16-byte blocks and prepends an IV. The project deliberately offers only
authenticated modes, because AES-CBC and AES-CTR would drop the integrity guarantee.

So **equal size is expected, and unequal size would be the bug.** The file list rounds
("7.54 MB" twice), so hover a size cell to see the exact byte count.

## Showing it live

1. **My Files → Encrypted preview** (under any file, owned or shared with you). It shows the
   algorithm, the exact sizes in bytes, the SHA-256 recorded at upload, and a hex dump of the
   first 128 bytes the server stores. For a `.pdf`, `.docx`, `.zip`, `.png` and similar it also
   checks the start of the bytes against how an *unencrypted* file of that type begins
   (`25 50 44 46` for a PDF, `50 4b 03 04` for a Word document) and says whether that header is
   visible. If it ever were, the panel turns red.
2. **Download encrypted file** saves the whole stored object as `<name>.ciphertext`. It opens
   in no application, which is the point. Then, in a terminal:

   ```bash
   xxd notes.txt.ciphertext | head        # random-looking bytes, no readable text
   shasum -a 256 notes.txt notes.txt.ciphertext   # two different digests
   ls -l notes.txt notes.txt.ciphertext   # the same size, as explained above
   ```

3. **Change one byte** of the `.ciphertext` file and try to decrypt it: authentication fails
   instead of producing garbage. This is what the tamper-state tests and the isolated tamper
   drill demonstrate end to end.

## Evidence from the test suite

`frontend/src/crypto/encryption-evidence.test.ts` pushes a **20 MiB** file made of a repeated
English sentence (the easiest plaintext to recognise) through the real `prepareUpload` path with
each of the six algorithms, and checks the result. A run on an Apple M4, Node 22 (2026-10-02):

| Algorithm | Bytes in → out | Entropy, bits/byte | Bytes equal to the original | Encrypt + self-test |
| --- | --- | --- | --- | --- |
| AES-256-GCM | 20,971,520 → 20,971,520 | 4.441 → 7.99999 | 0.392 % | 0.07 s |
| AES-256-GCM-SIV | 20,971,520 → 20,971,520 | 4.441 → 7.99999 | 0.389 % | 0.51 s |
| ChaCha20-Poly1305 | 20,971,520 → 20,971,520 | 4.441 → 7.99999 | 0.390 % | 0.18 s |
| XChaCha20-Poly1305 | 20,971,520 → 20,971,520 | 4.441 → 7.99999 | 0.390 % | 0.18 s |
| AES-192-GCM | 20,971,520 → 20,971,520 | 4.441 → 7.99999 | 0.391 % | 0.05 s |
| AES-128-GCM | 20,971,520 → 20,971,520 | 4.441 → 7.99999 | 0.391 % | 0.05 s |

The time column is not a benchmark, but it shows a real difference: the AES-GCM rows use the
browser's built-in, hardware-accelerated AES, while AES-256-GCM-SIV and the two ChaCha rows run in
a JavaScript library (`@noble/ciphers`). ChaCha is fast in JavaScript; AES-GCM-SIV is roughly ten
times slower than built-in GCM, which is a few extra seconds for a 500 MB file on a laptop.

Reading the columns: entropy of 8 is the maximum, and the structured plaintext sits at 4.4;
"equal to the original" is the share of positions where ciphertext and plaintext happen to hold
the same byte, and 0.391 % (1 in 256) is what unrelated data gives. For every algorithm the test
also asserts that the SHA-256 differs, that no 64-byte prefix is shared, that decrypting returns
the exact original, and that flipping a single byte in the middle makes authentication fail.
The test runs in CI on every pull request. Re-run it locally with:

```bash
cd frontend && npx vitest run src/crypto/encryption-evidence.test.ts --reporter=verbose
```

## What this does not prove

- **It is not cryptanalysis.** High entropy is necessary for good encryption, not sufficient:
  a weak cipher also looks random. Confidence in the algorithms comes from using the standard
  ones through WebCrypto and a vetted library, and from the known-answer vectors in
  `docs/crypto/test_vectors.json`, not from this table.
- **The numbers come from Node**, which runs the same TypeScript the browser runs but a
  different crypto backend. The Chromium golden-path test (`e2e-live` job) checks the browser
  itself: it uploads a file and asserts the stored bytes do not begin like the original.
- **Size 20 MiB, not 500 MiB.** The upload limit is 500 MiB. Very large files are limited by
  browser memory, not by the cipher (threat-model F-19, and the warning on the upload page).
- **A server that is simply trusted would show the same screen.** The preview reads what the
  server holds; what makes that meaningful is that the server never receives the key, which
  is a property of the design (`docs/SECURITY_FLOWS.md`), not of this page.
