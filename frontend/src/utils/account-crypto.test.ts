import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { bytesToHex, fromBase64, hexToBytes, toBase64 } from '@/crypto/encoding'
import { AES_GCM_NONCE_BYTES, AES_GCM_TAG_BYTES, AES_KEY_BYTES } from '@/crypto/primitives'
import {
  AccountKeySelfTestError,
  ARGON2_ITERATIONS,
  ARGON2_MEMORY_KIB,
  ARGON2_PARALLELISM,
  RSA_KEY_SIZE_BITS,
  amkWrapAad,
  assertEnvelopesUnlock,
  deriveKek,
  derivePrivateKeyEncryptionKey,
  enrolAccountKey,
  privateKeyAad,
} from './account-crypto'

const PASSPHRASE = 'a separate encryption passphrase'

/**
 * Argon2id at 64 MiB is deliberately slow, so the whole suite shares one
 * enrolment rather than paying for it in every test.
 */
let enrolment: Awaited<ReturnType<typeof enrolAccountKey>>

async function sharedEnrolment() {
  enrolment ??= await enrolAccountKey(PASSPHRASE)
  return enrolment
}

describe('enrolAccountKey', () => {
  it('produces envelope fields with the exact lengths the API enforces', async () => {
    const { keyMaterial } = await sharedEnrolment()
    const { protection, private_key_bundle: bundle } = keyMaterial

    // The server checks these decoded lengths numerically and rejects anything else.
    expect(fromBase64(protection.wrapped_amk)).toHaveLength(AES_KEY_BYTES)
    expect(fromBase64(protection.amk_nonce)).toHaveLength(AES_GCM_NONCE_BYTES)
    expect(fromBase64(protection.amk_auth_tag)).toHaveLength(AES_GCM_TAG_BYTES)
    expect(fromBase64(bundle.nonce)).toHaveLength(AES_GCM_NONCE_BYTES)
    expect(fromBase64(bundle.auth_tag)).toHaveLength(AES_GCM_TAG_BYTES)

    const kdfSalt = fromBase64(protection.kdf_salt)
    expect(kdfSalt.length).toBeGreaterThanOrEqual(16)
    expect(kdfSalt.length).toBeLessThanOrEqual(32)

    const derivationSalt = fromBase64(bundle.derivation_salt)
    expect(derivationSalt.length).toBeGreaterThanOrEqual(16)
    expect(derivationSalt.length).toBeLessThanOrEqual(32)

    const ciphertext = fromBase64(bundle.encrypted_private_key)
    expect(ciphertext.length).toBeGreaterThanOrEqual(256)
    expect(ciphertext.length).toBeLessThanOrEqual(8192)
  })

  it('declares the KDF parameters the backend schema requires', async () => {
    const { keyMaterial } = await sharedEnrolment()

    // The backend rejects anything below 65536 KiB.
    expect(keyMaterial.protection.kdf_memory_kib).toBe(ARGON2_MEMORY_KIB)
    expect(ARGON2_MEMORY_KIB).toBeGreaterThanOrEqual(65536)
    expect(keyMaterial.protection.kdf_iterations).toBe(ARGON2_ITERATIONS)
    expect(keyMaterial.protection.kdf_parallelism).toBe(ARGON2_PARALLELISM)
    expect(keyMaterial.key_size_bits).toBe(RSA_KEY_SIZE_BITS)
  })

  it('uploads material only, never a label the API pins itself', async () => {
    const { keyMaterial } = await sharedEnrolment()

    // Each of these had exactly one legal value on the wire and is now supplied
    // server-side. `extra="forbid"` means sending one back is a 422, so an
    // enrolment that reintroduces one fails at registration, not at first login.
    expect(Object.keys(keyMaterial).sort()).toEqual([
      'key_id',
      'key_size_bits',
      'private_key_bundle',
      'protection',
      'public_key_pem',
    ])
    expect(Object.keys(keyMaterial.protection).sort()).toEqual([
      'amk_auth_tag',
      'amk_nonce',
      'kdf_iterations',
      'kdf_memory_kib',
      'kdf_parallelism',
      'kdf_salt',
      'profile_id',
      'wrapped_amk',
    ])
    expect(Object.keys(keyMaterial.private_key_bundle).sort()).toEqual([
      'auth_tag',
      'bundle_id',
      'ciphertext_sha256',
      'derivation_salt',
      'encrypted_private_key',
      'nonce',
    ])
  })

  it('uploads a public key only, and returns the private key just to the caller', async () => {
    const { keyMaterial, privateKeyPem } = await sharedEnrolment()
    const uploaded = JSON.stringify(keyMaterial)

    expect(keyMaterial.public_key_pem).toContain('BEGIN PUBLIC KEY')
    expect(keyMaterial.public_key_pem).not.toContain('PRIVATE KEY')
    expect(privateKeyPem).toContain('BEGIN PRIVATE KEY')

    // Neither the passphrase nor any plaintext key may appear in the payload.
    expect(uploaded).not.toContain(PASSPHRASE)
    expect(uploaded).not.toContain('PRIVATE KEY')
  })

  it('binds ciphertext_sha256 to the stored ciphertext', async () => {
    const { keyMaterial } = await sharedEnrolment()
    const bundle = keyMaterial.private_key_bundle

    // The server recomputes this over the decoded ciphertext and rejects a mismatch.
    expect(bundle.ciphertext_sha256).toMatch(/^[0-9a-f]{64}$/)
    const { sha256Hex } = await import('@/crypto/primitives')
    expect(await sha256Hex(fromBase64(bundle.encrypted_private_key))).toBe(
      bundle.ciphertext_sha256,
    )
  })

  it('uses fresh salts, nonces, and identifiers for each account', async () => {
    const first = await sharedEnrolment()
    const second = await enrolAccountKey(PASSPHRASE)

    expect(second.keyMaterial.key_id).not.toBe(first.keyMaterial.key_id)
    expect(second.keyMaterial.protection.profile_id).not.toBe(
      first.keyMaterial.protection.profile_id,
    )
    expect(second.keyMaterial.protection.kdf_salt).not.toBe(first.keyMaterial.protection.kdf_salt)
    expect(second.keyMaterial.protection.amk_nonce).not.toBe(first.keyMaterial.protection.amk_nonce)
    // Same passphrase, different salt, so the wrapped AMK must still differ.
    expect(second.keyMaterial.protection.wrapped_amk).not.toBe(
      first.keyMaterial.protection.wrapped_amk,
    )
  })
})

describe('assertEnvelopesUnlock', () => {
  it('accepts the envelopes it just produced', async () => {
    const { keyMaterial } = await sharedEnrolment()
    const der = fromBase64(
      enrolment.privateKeyPem
        .replace(/-----(BEGIN|END) PRIVATE KEY-----/g, '')
        .replace(/\s+/g, ''),
    )

    await expect(assertEnvelopesUnlock(keyMaterial, PASSPHRASE, der)).resolves.toBeUndefined()
  })

  it('rejects a wrong passphrase', async () => {
    const { keyMaterial } = await sharedEnrolment()
    const der = fromBase64(
      enrolment.privateKeyPem
        .replace(/-----(BEGIN|END) PRIVATE KEY-----/g, '')
        .replace(/\s+/g, ''),
    )

    // AES-GCM authentication fails before any length comparison happens.
    await expect(assertEnvelopesUnlock(keyMaterial, 'the wrong passphrase', der)).rejects.toThrow()
  })

  it('rejects a tampered auth tag', async () => {
    const { keyMaterial } = await sharedEnrolment()
    const der = fromBase64(
      enrolment.privateKeyPem
        .replace(/-----(BEGIN|END) PRIVATE KEY-----/g, '')
        .replace(/\s+/g, ''),
    )
    const tampered = structuredClone(keyMaterial)
    const tag = fromBase64(tampered.protection.amk_auth_tag)
    tag[0] ^= 0xff
    tampered.protection.amk_auth_tag = toBase64(tag)

    await expect(assertEnvelopesUnlock(tampered, PASSPHRASE, der)).rejects.toThrow()
  })

  it('reports a self-test failure when the recovered key does not match', async () => {
    const { keyMaterial } = await sharedEnrolment()

    // Correct passphrase and intact envelopes, but the wrong expected key.
    await expect(
      assertEnvelopesUnlock(keyMaterial, PASSPHRASE, new Uint8Array([1, 2, 3])),
    ).rejects.toBeInstanceOf(AccountKeySelfTestError)
  })
})

describe('associated data', () => {
  it('is rebuildable from stored non-secret metadata', async () => {
    const { keyMaterial } = await sharedEnrolment()

    // A later unlock reconstructs these from the profile and bundle rows alone.
    expect(amkWrapAad(keyMaterial.protection.profile_id)).toEqual(
      new TextEncoder().encode(`secureview:amk-wrap:v1:${keyMaterial.protection.profile_id}`),
    )
    expect(
      privateKeyAad(keyMaterial.private_key_bundle.bundle_id, keyMaterial.key_id),
    ).toEqual(
      new TextEncoder().encode(
        `secureview:private-key:v1:${keyMaterial.private_key_bundle.bundle_id}:${keyMaterial.key_id}`,
      ),
    )
  })

  it('separates the two envelopes so one key cannot open the other', () => {
    expect(amkWrapAad('same-id')).not.toEqual(privateKeyAad('same-id', 'same-id'))
  })
})

describe('key derivation', () => {
  it('derives a deterministic 32-byte KEK from passphrase and salt', async () => {
    const salt = new Uint8Array(16).fill(7)

    const first = await deriveKek('passphrase', salt)
    const second = await deriveKek('passphrase', salt)

    expect(first).toHaveLength(AES_KEY_BYTES)
    expect(first).toEqual(second)
  })

  it('produces a different KEK for a different passphrase or salt', async () => {
    const salt = new Uint8Array(16).fill(7)
    const otherSalt = new Uint8Array(16).fill(9)

    const base = await deriveKek('passphrase', salt)

    expect(await deriveKek('other passphrase', salt)).not.toEqual(base)
    expect(await deriveKek('passphrase', otherSalt)).not.toEqual(base)
  })

  it('binds the private-key key to its associated data', async () => {
    const amk = new Uint8Array(AES_KEY_BYTES).fill(3)
    const salt = new Uint8Array(32).fill(5)

    const bound = await derivePrivateKeyEncryptionKey(amk, salt, privateKeyAad('b', 'k'))
    const other = await derivePrivateKeyEncryptionKey(amk, salt, privateKeyAad('b', 'different'))

    expect(bound).toHaveLength(AES_KEY_BYTES)
    expect(bound).not.toEqual(other)
  })
})

describe('Argon2id KEK against the native reference implementation', () => {
  // Generated with argon2-cffi -- the C reference an offline attacker would run. Matching it
  // byte for byte means the threat model's attacker benchmark measures the same function the
  // browser computes at unlock, so its guesses-per-second figures apply to real envelopes.
  const vectors = JSON.parse(
    readFileSync(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/crypto/test_vectors.json'),
      'utf8',
    ),
  ) as {
    argon2id_kek: {
      case: string
      passphrase_utf8: string
      salt_hex: string
      memory_kib: number
      iterations: number
      parallelism: number
      kek_hex: string
    }[]
  }

  it.each(vectors.argon2id_kek)('derives the reference KEK for $case', async (vector) => {
    const kek = await deriveKek(vector.passphrase_utf8, hexToBytes(vector.salt_hex), {
      memorySize: vector.memory_kib,
      iterations: vector.iterations,
      parallelism: vector.parallelism,
    })
    expect(bytesToHex(kek)).toBe(vector.kek_hex)
  }, 30_000)
})
