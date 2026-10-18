export type AlgorithmId =
  | 'aes128'
  | 'aes256'
  | 'aes256gcmsiv'
  | 'rsa'
  | 'sha'
  | 'chacha20'
  | 'xchacha20'
  | 'argon2id'

export type AlgorithmType = 'symmetric' | 'asymmetric' | 'hash' | 'kdf'

export type AlgorithmFamily = 'aes' | 'chacha'

export interface AlgorithmStep {
  title: string
  description: string
}

/** Optional video URL; when absent the explorer plays a built-in CSS animation. */
export interface AlgorithmDemo {
  kind: 'animation' | 'video'
  title: string
  description: string
  /** Built-in animation scene id rendered by AlgorithmExplorer. */
  animationId:
    | 'aes-rounds'
    | 'siv-flow'
    | 'rsa-keys'
    | 'sha-digest'
    | 'chacha-stream'
    | 'xchacha-nonce'
    | 'argon2-memory'
  /** Optional hosted video (mp4/webm). Leave empty until a clip is ready. */
  videoSrc?: string
  posterLabel: string
}

export interface AlgorithmInfo {
  id: AlgorithmId
  name: string
  shortLabel: string
  /** When set, sidebar groups this topic under a family heading (e.g. AES). */
  family?: AlgorithmFamily
  type: AlgorithmType
  tagline: string
  summary: string
  howItWorks: AlgorithmStep[]
  useCases: string[]
  strengths: string[]
  limitations: string[]
  keyFacts: string[]
  demo: AlgorithmDemo
}

export const algorithmFamilyLabels: Record<AlgorithmFamily, string> = {
  aes: 'AES',
  chacha: 'ChaCha20',
}

export const algorithms: AlgorithmInfo[] = [
  {
    id: 'aes128',
    name: 'AES-128',
    shortLabel: 'AES-128',
    family: 'aes',
    type: 'symmetric',
    tagline: '128-bit key AES — fast, NIST-approved, and still considered secure for most uses.',
    summary:
      'AES-128 uses a 128-bit secret key and always processes data in 128-bit blocks. It runs 10 transformation rounds (SubBytes, ShiftRows, MixColumns, AddRoundKey). SecureView offers AES-128-GCM as one of the upload choices; AES-256-GCM is the default.',
    howItWorks: [
      {
        title: '128-bit key setup',
        description: 'Sender and receiver share a 128-bit (16-byte) secret. The key schedule expands it into 11 round keys (one for the initial AddRoundKey plus 10 rounds).',
      },
      {
        title: '10 encryption rounds',
        description: 'Each 128-bit block passes through 10 rounds. Rounds 1–9 use all four transformations; the final round skips MixColumns.',
      },
      {
        title: 'Block transformations',
        description: 'SubBytes substitutes bytes, ShiftRows permutes rows, MixColumns mixes columns, and AddRoundKey XORs a round key into the state.',
      },
      {
        title: 'Decryption',
        description: 'The raw block cipher decrypts by running the inverse operations in reverse order with the same key. (In GCM mode, as SecureView uses it, AES only ever runs forwards: see AES-256.) Security rests on keeping the key secret — the algorithm itself is public.',
      },
    ],
    useCases: ['TLS cipher suites', 'Lightweight device encryption', 'Teaching AES round structure', 'Systems that need AES with shorter keys'],
    strengths: ['Fewer rounds than AES-256 — often faster', 'Still no practical attack against full AES-128', 'Widely hardware-accelerated (AES-NI)'],
    limitations: ['Smaller security margin than AES-256', 'Same key-sharing problem as any symmetric cipher', 'Not the default for SecureView file encryption'],
    keyFacts: [
      'Key length: 128 bits · Rounds: 10 · Block size: 128 bits',
      'AES-192 sits in between (12 rounds); SecureView offers it in every browser, using a JavaScript library where WebCrypto lacks it',
      'NIST approved AES in 2001; AES-128 remains approved for many uses',
    ],
    demo: {
      kind: 'animation',
      title: 'AES-128 round flow',
      description: 'Watch a 128-bit block move through the 10-round AES pipeline.',
      animationId: 'aes-rounds',
      posterLabel: 'AES-128 · 10 rounds',
    },
  },
  {
    id: 'aes256',
    name: 'AES-256',
    shortLabel: 'AES-256',
    family: 'aes',
    type: 'symmetric',
    tagline: '256-bit key AES — SecureView’s default for encrypting files in the browser.',
    summary:
      'AES-256 uses a 256-bit secret key with the same 128-bit block size as other AES variants, but runs 14 rounds instead of 10. The larger key and extra rounds give a higher security margin. SecureView encrypts file content with AES-256-GCM in the browser before upload.',
    howItWorks: [
      {
        title: '256-bit key setup',
        description: 'A 256-bit (32-byte) secret is expanded into 15 round keys. In SecureView your browser makes a new random key for every file, and the server only ever holds it sealed with RSA-OAEP.',
      },
      {
        title: '14 encryption rounds',
        description: 'Each block goes through 14 rounds of SubBytes, ShiftRows, MixColumns, and AddRoundKey — four more rounds than AES-128.',
      },
      {
        title: 'Authenticated mode (GCM)',
        description: 'SecureView uses AES-GCM so encryption also produces an authentication tag. Tampering is detected on decrypt, not only confidentiality.',
      },
      {
        title: 'Decryption',
        description: 'GCM runs AES forwards over a counter to make a keystream, so decryption repeats the same rounds and XORs the keystream off again — no inverse rounds. The tag is checked first; a wrong key or one altered byte makes decryption fail instead of returning damaged data.',
      },
    ],
    useCases: ['SecureView file encryption', 'Disk encryption', 'Government and enterprise at-rest data', 'Long-term archival of sensitive files'],
    strengths: ['Largest AES key size in common use', 'Extra rounds increase security margin', 'Hardware accelerated on modern CPUs'],
    limitations: ['Slightly more computation than AES-128', 'A GCM nonce must never repeat under the same key (SecureView makes a new key for every file, so it cannot happen here)', 'Key compromise exposes all data under that key (SecureView limits this to one file per key)'],
    keyFacts: [
      'Key length: 256 bits · Rounds: 14 · Block size: 128 bits',
      'AES-256-GCM is SecureView’s default file encryption suite, run by the browser’s built-in (usually hardware-accelerated) WebCrypto',
      'AES-192 sits in between (12 rounds); SecureView offers it in every browser, using a JavaScript library where WebCrypto lacks it',
    ],
    demo: {
      kind: 'animation',
      title: 'AES-256 round flow',
      description: 'Watch a block move through the longer 14-round AES-256 pipeline used by SecureView.',
      animationId: 'aes-rounds',
      posterLabel: 'AES-256 · 14 rounds',
    },
  },
  {
    id: 'aes256gcmsiv',
    name: 'AES-256-GCM-SIV',
    shortLabel: 'AES-256-GCM-SIV',
    family: 'aes',
    type: 'symmetric',
    tagline: 'AES-GCM made forgiving: a repeated nonce reveals only that the same file was encrypted twice.',
    summary:
      'AES-GCM-SIV (RFC 8452, 2019) is an authenticated mode of AES designed to survive a mistake that breaks plain GCM: encrypting two messages with the same key and the same nonce. It computes the IV from the message itself (a “synthetic IV”), so the only thing a repeated nonce can reveal is that two messages were identical. SecureView offers AES-256-GCM-SIV as an upload choice.',
    howItWorks: [
      {
        title: 'Per-message keys',
        description: 'From the 256-bit key and the 96-bit nonce, AES derives two fresh keys for this message: one to authenticate it and one to encrypt it.',
      },
      {
        title: 'Authenticate first (POLYVAL)',
        description: 'POLYVAL, a GHASH-like hash, runs over the associated data and the plaintext. The result, mixed with the nonce and encrypted with AES, becomes the 128-bit tag.',
      },
      {
        title: 'The tag is the IV',
        description: 'That tag also seeds the AES counter mode that encrypts the plaintext. Because it depends on the whole message, two different messages get different counters even under a repeated nonce.',
      },
      {
        title: 'Decryption',
        description: 'The receiver decrypts with the counter taken from the tag, recomputes the tag over the result and compares. Any changed byte, wrong key or wrong associated data makes the comparison fail and nothing is returned.',
      },
    ],
    useCases: ['Systems that cannot guarantee unique nonces (many devices, no shared counter)', 'Key wrapping', 'Google Tink and BoringSSL offer it', 'Teaching what “nonce misuse” means and how to survive it'],
    strengths: ['A repeated nonce leaks only “these two messages are equal”, never the key or the plaintext', 'Same 256-bit AES core and 128-bit tag as AES-GCM', 'Standardised (RFC 8452) with published test vectors'],
    limitations: ['Two passes over the data, so it cannot start returning output before it has read everything', 'Browsers have no built-in implementation: SecureView runs it in JavaScript, which is noticeably slower than built-in AES-GCM on large files', 'Less widely deployed than AES-GCM'],
    keyFacts: [
      'Key: 256 bits · Nonce: 96 bits · Tag: 128 bits · RFC 8452',
      'In SecureView every file already gets its own random key, so nonce reuse cannot happen either way; here GCM-SIV is a second line of defence and a way to compare designs',
      'SecureView’s implementation (@noble/ciphers) is checked byte for byte against the RFC 8452 test vectors and OpenSSL',
    ],
    demo: {
      kind: 'animation',
      title: 'Synthetic IV',
      description: 'The tag is computed from the message first, then used as the starting counter for encryption.',
      animationId: 'siv-flow',
      posterLabel: 'AES-256-GCM-SIV · tag = IV',
    },
  },
  {
    id: 'rsa',
    name: 'RSA (Rivest–Shamir–Adleman)',
    shortLabel: 'RSA',
    type: 'asymmetric',
    tagline: 'Public-key cryptography for secure key exchange and digital signatures.',
    summary:
      'RSA uses a mathematically linked key pair: a public key anyone can use to encrypt, and a private key only the owner holds to decrypt. Security relies on how hard it is to factor the product of two large primes back into those primes.',
    howItWorks: [
      {
        title: 'Key pair generation',
        description: 'Two large prime numbers produce a public key (shared openly) and a private key (kept secret).',
      },
      {
        title: 'Encryption with public key',
        description: "Anyone encrypts using the recipient's public key. Only the matching private key can decrypt.",
      },
      {
        title: 'Digital signatures',
        description: 'The owner signs data with their private key. Others verify authenticity using the public key.',
      },
      {
        title: 'Hybrid use with AES',
        description: 'RSA encrypts a random AES session key; AES encrypts the actual file — combining speed with secure key delivery.',
      },
    ],
    useCases: ['Encrypting AES keys for file sharing', 'TLS/HTTPS handshake', 'Code signing', 'Email encryption (PGP)'],
    strengths: ['No pre-shared secret needed for key delivery', 'Enables digital signatures', 'Foundation of PKI infrastructure'],
    limitations: ['Slow for large files', 'Vulnerable if key size is too small', 'Requires secure key storage'],
    keyFacts: ['Minimum 2048-bit keys recommended today', 'Real systems always add padding (OAEP for encryption, PSS for signatures)', 'SecureView seals each file key with 3072-bit RSA-OAEP (SHA-256)', 'SecureView also signs with RSA-PSS: changing your passphrase or adding a key needs a signature from your private key'],
    demo: {
      kind: 'animation',
      title: 'RSA key exchange sketch',
      description: 'See how a public key locks data that only the matching private key can open.',
      animationId: 'rsa-keys',
      posterLabel: 'RSA · public / private',
    },
  },
  {
    id: 'sha',
    name: 'SHA (Secure Hash Algorithm)',
    shortLabel: 'SHA',
    type: 'hash',
    tagline: 'One-way fingerprinting — verify integrity, not confidentiality.',
    summary:
      'The SHA family (SHA-256, SHA-384, SHA-512) produces a fixed-size digest from any input. It is one-way: you cannot recover the input from the hash. Any change to the input produces a completely different digest.',
    howItWorks: [
      {
        title: 'Padding the message',
        description: 'Input is padded to a multiple of the block size (512 bits for SHA-256, 1024 for SHA-512), with its length appended at the end.',
      },
      {
        title: 'Process in blocks',
        description: 'Each block (512 bits for SHA-256, 1024 for SHA-512) is mixed into the running state through 64 rounds of bitwise operations (80 for SHA-512).',
      },
      {
        title: 'Produce fixed output',
        description: 'SHA-256 outputs 256 bits (64 hex chars); SHA-512 outputs 512 bits.',
      },
      {
        title: 'Verification',
        description: 'Hash the received file and compare it with a digest you trust. A match shows the file was not altered — but only if the reference digest itself could not have been changed too, which is why SecureView also records it in its tamper-evident audit log.',
      },
    ],
    useCases: ['File integrity checks on SecureView', 'Building block for HMAC, HKDF and signatures', 'Blockchain', 'Digital signature inputs'],
    strengths: ['Deterministic and fast', 'No practical collision is known for SHA-256', 'Fixed output size regardless of input'],
    limitations: ['Not encryption — cannot decrypt a hash', 'Too fast for passwords: use a slow, salted KDF such as Argon2id', 'Not a substitute for AES/RSA'],
    keyFacts: ['SHA-256 output is always 64 hex characters', 'SecureView records a SHA-256 of every stored (encrypted) file, re-checks it on download and in a daily scan, and keeps a copy in the audit log', 'Part of the SHA-2 family (SHA-224/256/384/512)'],
    demo: {
      kind: 'animation',
      title: 'SHA digest flow',
      description: 'Any input collapses to a fixed-length fingerprint — change one bit and the digest changes completely.',
      animationId: 'sha-digest',
      posterLabel: 'SHA · one-way digest',
    },
  },
  {
    id: 'chacha20',
    name: 'ChaCha20-Poly1305',
    shortLabel: 'ChaCha20',
    family: 'chacha',
    type: 'symmetric',
    tagline: 'Modern stream cipher — fast in software and widely used in TLS, VPNs and SSH.',
    summary:
      'ChaCha20 generates a pseudorandom keystream from a 256-bit key and 96-bit nonce, then XORs it with plaintext. Combined with Poly1305 (ChaCha20-Poly1305), it provides authenticated encryption used by Google, WireGuard, and TLS 1.3.',
    howItWorks: [
      {
        title: 'Initialize state',
        description: 'A 512-bit state matrix is filled with constants, the key, nonce, and a block counter.',
      },
      {
        title: 'Generate keystream',
        description: '20 rounds of quarter-round operations (ARX: Add, Rotate, XOR) scramble the state to produce keystream bytes.',
      },
      {
        title: 'XOR with plaintext',
        description: 'Each plaintext byte is XORed with a keystream byte. Decryption XORs the same keystream again.',
      },
      {
        title: 'Authentication (Poly1305)',
        description: 'Poly1305 produces a MAC tag so tampering is detected. ChaCha20-Poly1305 is an AEAD mode.',
      },
    ],
    useCases: ['TLS 1.3 cipher suites', 'WireGuard VPN', 'OpenSSH', 'Alternative to AES-GCM on devices without AES hardware'],
    strengths: ['Fast in software without AES-NI hardware', 'Resistant to timing side-channel attacks', 'Simple, auditable design'],
    limitations: ['Nonce must never be reused with the same key (SecureView uses a new key per file)', 'A 96-bit nonce is short for random choice when one key encrypts billions of messages — XChaCha20 fixes that', 'Requires Poly1305 for integrity in practice'],
    keyFacts: ['Designed by Daniel Bernstein (2008)', 'RFC 8439 standardizes ChaCha20-Poly1305 · 256-bit key · 96-bit nonce · 128-bit tag', 'Offered in SecureView as ChaCha20-Poly1305 for file encryption; XChaCha20-Poly1305 is the same with a longer nonce'],
    demo: {
      kind: 'animation',
      title: 'ChaCha20 keystream XOR',
      description: 'A keystream is generated, then XORed with plaintext to produce ciphertext.',
      animationId: 'chacha-stream',
      posterLabel: 'ChaCha20 · stream XOR',
    },
  },
  {
    id: 'xchacha20',
    name: 'XChaCha20-Poly1305',
    shortLabel: 'XChaCha20',
    family: 'chacha',
    type: 'symmetric',
    tagline: 'ChaCha20-Poly1305 with a 192-bit nonce — long enough to pick at random without ever worrying about a repeat.',
    summary:
      'XChaCha20-Poly1305 is ChaCha20-Poly1305 with an extended 192-bit (24-byte) nonce. A 96-bit nonce chosen at random starts to risk a repeat after a few billion messages under one key; a 192-bit one never realistically repeats. It is what libsodium recommends for encrypting with random nonces. SecureView offers it as an upload choice.',
    howItWorks: [
      {
        title: 'Split the long nonce',
        description: 'The 24-byte nonce is split: the first 16 bytes are used to derive a key, the last 8 bytes become part of an ordinary ChaCha20 nonce.',
      },
      {
        title: 'Derive a subkey (HChaCha20)',
        description: 'HChaCha20 runs the ChaCha20 rounds over the main key and the first 16 nonce bytes and outputs a fresh 256-bit subkey for this message.',
      },
      {
        title: 'Encrypt as ChaCha20-Poly1305',
        description: 'The message is then encrypted and authenticated exactly as ChaCha20-Poly1305, under the subkey, producing ciphertext and a 128-bit tag.',
      },
      {
        title: 'Decryption',
        description: 'The receiver derives the same subkey from the same nonce, checks the tag, and only then returns the plaintext. One changed byte makes it fail.',
      },
    ],
    useCases: ['Encrypting many messages under one long-lived key with random nonces', 'libsodium-based applications', 'Encrypted backups and file formats', 'Protocols where nonce counters are hard to keep in sync'],
    strengths: ['Random nonces are safe: a collision is practically impossible', 'Same speed and side-channel resistance as ChaCha20', 'Fast in JavaScript, so large files encrypt quickly in the browser'],
    limitations: ['Specified in an IETF draft (draft-irtf-cfrg-xchacha), not a final RFC', 'Not in browsers’ built-in WebCrypto: SecureView uses @noble/ciphers', 'Nonce is 24 bytes, so formats must allow a longer nonce than AES-GCM'],
    keyFacts: [
      'Key: 256 bits · Nonce: 192 bits · Tag: 128 bits',
      'In SecureView each file already has its own random key, so the longer nonce is extra margin rather than a fix for a problem we have',
      'SecureView’s implementation is checked byte for byte against libsodium and the draft’s test vector',
    ],
    demo: {
      kind: 'animation',
      title: 'Extended nonce',
      description: 'Part of the long nonce derives a subkey; the rest is used by ordinary ChaCha20-Poly1305.',
      animationId: 'xchacha-nonce',
      posterLabel: 'XChaCha20 · 192-bit nonce',
    },
  },
  {
    id: 'argon2id',
    name: 'Argon2id',
    shortLabel: 'Argon2id',
    type: 'kdf',
    tagline: 'Memory-hard password hashing — winner of the Password Hashing Competition (2015).',
    summary:
      'Argon2id converts passwords into cryptographic keys or stored hashes. It deliberately consumes memory and CPU time, making brute-force and GPU/ASIC attacks expensive. It is the recommended algorithm for password storage today.',
    howItWorks: [
      {
        title: 'Salt and parameters',
        description: 'A unique random salt is generated per password. Parameters include memory cost, time iterations, and parallelism.',
      },
      {
        title: 'Memory filling',
        description: 'Argon2 fills a large memory block with pseudorandom data derived from the password and salt.',
      },
      {
        title: 'Pass over memory',
        description: 'Multiple passes read and write the memory block in a password-dependent pattern, resisting parallel attacks.',
      },
      {
        title: 'Output hash',
        description: 'The final memory state is compressed into a fixed-length hash stored in the database — never store plaintext passwords.',
      },
    ],
    useCases: ['User password storage', 'Key derivation from passphrases', 'Secure credential databases', 'Replacing bcrypt/scrypt/PBKDF2'],
    strengths: ['Memory-hard — defeats GPU/ASIC brute force', 'Argon2id resists both side-channel and GPU attacks', 'Configurable cost parameters scale with hardware'],
    limitations: ['Higher memory use than bcrypt', 'Wrong parameters can be too fast or too slow', 'Not for encrypting files directly — use for passwords/KDF'],
    keyFacts: ['Winner of Password Hashing Competition (2015)', 'Argon2id = hybrid of Argon2i and Argon2d', 'SecureView uses it twice: on the server for login passwords, and in your browser to turn your passphrase into the key that opens your private key (64 MiB)'],
    demo: {
      kind: 'animation',
      title: 'Argon2id memory-hard pass',
      description: 'Password and salt fill a large memory region before a compact hash is emitted.',
      animationId: 'argon2-memory',
      posterLabel: 'Argon2id · memory-hard',
    },
  },
]

export function getAlgorithm(id: AlgorithmId): AlgorithmInfo | undefined {
  return algorithms.find((a) => a.id === id)
}
