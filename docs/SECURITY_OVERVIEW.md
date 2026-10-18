# SecureView Security Overview

This page is a short summary of SecureView's security model. The full version is in [THREAT_MODEL.md](THREAT_MODEL.md) and [SECURITY_FLOWS.md](SECURITY_FLOWS.md). Neither replaces an independent security audit.

## Trust boundary

The key design decision is that **file plaintext is encrypted in the browser before upload**.

The server is trusted to:

- authenticate users and enforce access-control decisions;
- store ciphertext and wrapped key material;
- serve authorised ciphertext;
- record auditable actions;
- keep metadata and storage available.

The server is **not** intended to receive:

- plaintext user files;
- plaintext per-file data-encryption keys;
- the user's encryption passphrase;
- a plaintext account private key during normal operation.

## Cryptography

### File content

Each file receives a fresh data-encryption key in the browser. Users can select:

- AES-128-GCM
- AES-192-GCM
- AES-256-GCM
- AES-256-GCM-SIV
- ChaCha20-Poly1305
- XChaCha20-Poly1305

AES-256-GCM is the default. All are authenticated-encryption modes, so altered ciphertext is rejected rather than silently decrypted.

### Key sharing

The file key is wrapped with RSA-OAEP using SHA-256. Sharing does not send the plaintext file key to the server: the browser unwraps the owner's copy and re-wraps the same key to the recipient's public key.

The UI asks the sender to verify the intended recipient and key fingerprint before completing the share.

### Passwords and passphrases

The **login password** authenticates the account and is one-way hashed on the server with Argon2id.

The separate **encryption passphrase** protects account key material in the browser and is not a server-side login secret. Users can change it in Settings. Weak, patterned or account-derived passphrases are rejected, and the passphrase is asked again for every download and share.

Administrators can reset a login password, but they do not gain the encryption passphrase or the ability to display it. After a reset the server forces the user to set a new login password.

### Account protections

- Registration does not reveal whether an email is already registered.
- Account deletion is rate limited.
- The last administrator account is protected.
- Per-address limits are sized so a whole venue behind one NAT can still use the site.

## Integrity and tamper evidence

SecureView uses several independent checks:

1. stored ciphertext SHA-256;
2. authenticated-encryption tag verification during decryption;
3. a hash-chained audit trail for security-sensitive events;
4. scheduled integrity checking and administrator integrity views;
5. isolated tamper drills that deliberately modify stored ciphertext and verify refusal.

A changed SHA-256 alone is not enough to make forged ciphertext valid because the AEAD authentication check still fails.

## Access control and recovery

Roles include USER, ADMIN and RECOVERY_OFFICER. Recovery operations are intentionally governed rather than acting as a universal decryption backdoor.

Revocation stops **future server-mediated access**. It cannot erase a plaintext copy that a recipient already downloaded while authorised.

## Upload-abuse and malware limitation

Accounts have storage/upload limits and infrastructure-side safeguards to reduce denial-of-service or storage-exhaustion abuse.

Because the server stores ciphertext, it cannot inspect file contents for malware. Shared executable or macro-capable files therefore produce explicit risk warnings to recipients.

## Security verification

Recorded public evidence includes:

- OWASP ZAP baseline scan with 0 FAIL, 5 WARN and 62 PASS after the Nginx header fix, confirmed again on 12 October 2026;
- pip-audit and npm audit with no findings in production dependencies at the recorded scan;
- live and isolated ciphertext tamper tests;
- cryptographic test vectors checked against independent implementations;
- encrypted off-server backup and clean-host restore verification.

## Important limitations

SecureView is a university team project running in production. It has not been independently audited and does not claim:

- independent professional penetration testing;
- protection against a compromised user's browser or operating system while plaintext is open;
- revocation of a copy already downloaded and decrypted by an authorised recipient;
- server-side malware scanning of encrypted content;
- zero-knowledge protection for all metadata.

The full [threat model](THREAT_MODEL.md) tracks more findings and mitigations.
