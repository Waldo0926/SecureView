# Project Scope

English | [简体中文](PROJECT_SCOPE.zh-CN.md)

## Final Product

A secure file encryption and sharing platform in which trusted clients create and retain
control of user private keys and file encryption keys. The backend stores client-encrypted
ciphertext, public keys, password-protected private-key envelopes, recipient-specific file-
key wrappings, access policy, recovery workflow state, and tamper-evident audit evidence.

## In Scope

- User registration with an emailed verification code, login, opaque server-side sessions, and
  role-based access control
- Login-password reset by emailed code, password change in Settings, and administrator-issued
  temporary login passwords (#197); none of these touch files or the encryption passphrase
- Separation of login password from the client-only encryption passphrase
- Client-generated RSA public/private key pairs
- Argon2id-derived KEK wrapping of a random account master key (AMK)
- AMK/HKDF-derived AES-256-GCM encryption of the PKCS#8 private-key bundle
- Client-side file encryption with independent random DEKs under one of six authenticated suites
  chosen per upload: AES-128/192/256-GCM (default AES-256-GCM), AES-256-GCM-SIV,
  ChaCha20-Poly1305, XChaCha20-Poly1305
- Bounded encrypted-ciphertext upload, storage, download, deletion, and SHA-256 integrity checks
- RSA-OAEP-SHA256 DEK wrapping for each authorized user
- Client-side DEK rewrapping for sharing, with the recipient's key fingerprint computed in the
  browser and confirmed before sealing (T-S5), plus future-access revocation
- Key-protection profile retrieval and passphrase rewrap protected by optimistic revision plus
  newest-current-private-key RSA-PSS-SHA256 authorization
- Current-private-key-authorized successor key addition with historical bundles retained
- Change of the encryption passphrase with the current one, and reset of a forgotten one by the
  holder of the account's private key file
  (`.pem`, offered once at registration), authorised by an RSA-PSS signature from that key
- Recovery-public-key registration/rotation and mandatory upload recovery wrapping
- Time-bounded, maker-checker recovery requests with isolated offline/HSM DEK unwrap/rewrap
- Scoped audit queries and a serialized tamper-evident audit hash chain
- Administrative user/file listing, account details, enable/disable controls, counts-only
  statistics, the Integrity tab and the security-agent report
- Per-account upload limits (2 GiB stored, 5 GiB per 24 hours) and a free-disk floor
- Daily integrity sweep against audit-anchored digests, single-file restore from encrypted
  backup, external HMAC audit checkpoints, monitoring alerts by email
- MySQL/Alembic schema delivery, production SQL parity, and readiness revision checks

## Out of Scope

- Server-side or administrator reset of a forgotten encryption passphrase (only the holder of
  the private key file can reset it)
- Server-side decryption of user private keys, file DEKs, or file contents
- Metadata anonymity: filenames, MIME types, sizes, timestamps, ownership, and sharing graph
  are visible to the server in the current contract
- Protection from an actively malicious server without client fingerprint/revision pinning or
  an independent trust anchor
- Google Drive-style online document collaboration or real-time multi-user editing
- Large-scale cloud storage optimization or a performance guarantee for 1 GB+ files
- Forced deletion of ciphertext, DEKs, or plaintext already copied before revocation
- Encrypted full-text search, watermarking, and DRM/non-removable content controls (filename
  search on the server is implemented)
- Production-grade KMS/HSM implementation or automated offline-recovery workstation
- MFA and external identity federation

## Core Limitations

The user normally needs to remember only the encryption passphrase because the encrypted
private-key bundle is stored by the service. A forgotten passphrase loses the AMK, which no one
can recover; the private key file offered at registration is the separately held factor: with
it the user sets a new passphrase in Settings and every file stays readable. If **both** the
passphrase and the key file are lost, the account's files are unrecoverable. The administrator
recovery workflow does not help there: it rewraps a file DEK to an already registered user
public key, whose private half is what was lost. The key file is a plaintext master
credential, so its custody is the user's responsibility.

Revocation controls future downloads through this platform. It cannot erase data already
obtained by a recipient.

The backend sees operational metadata and a stolen database permits offline guessing against
the Argon2id-protected key envelope. Strong passphrases and appropriately benchmarked KDF
parameters remain essential.

Recovery private keys are never submitted to the API. The repository implements the public-
key registration and governed request protocol, while real deployment must provide isolated
offline or HSM custody, operator authentication, clean-room logging rules, backup/rotation,
and tested disaster-recovery procedures.
