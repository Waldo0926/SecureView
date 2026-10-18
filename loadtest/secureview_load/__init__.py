"""SecureView load and performance testing: a client that behaves like the browser.

Every upload is encrypted on the client exactly as `frontend/src/crypto/file_envelope.ts`
does, and every download is decrypted and compared, by SHA-256, with what went in. So a
run measures the real request path and proves on every operation that the bytes survived.
"""
