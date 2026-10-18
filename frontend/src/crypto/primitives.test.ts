import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { bytesToHex, hexToBytes } from './encoding'
import {
  AES_GCM_NONCE_BYTES,
  AES_GCM_TAG_BYTES,
  AuthenticationFailure,
  CHACHA20_NONCE_BYTES,
  CHACHA20_TAG_BYTES,
  ENCRYPTION_ALGORITHMS,
  aesGcmDecryptDetached,
  aesGcmEncryptDetached,
  aesGcmOpenDetached,
  aesGcmSealDetached,
  chacha20Poly1305DecryptDetached,
  chacha20Poly1305EncryptDetached,
  importAesGcmKey,
  importRsaOaepPublicKey,
  publicKeyFingerprint,
  publicKeyPemToDer,
  randomBytes,
  rsaOaepUnwrap,
  rsaOaepWrap,
  rsaPssSign,
  rsaPssVerify,
  sha256Hex,
  libraryAeadDecryptDetached,
  libraryAeadEncryptDetached,
  nobleAesGcmDecryptDetached,
  nobleAesGcmEncryptDetached,
  nonceBytesForAlgorithm,
  platformSupportsAesGcm,
  resetEncryptionCapabilityCache,
  supportedEncryptionAlgorithms,
} from './primitives'

/**
 * Known-answer vectors produced by python-cryptography. Checking this implementation
 * against an independent one is the point; a round trip against itself would pass even if
 * both directions were wrong in the same way.
 */
interface DetachedVector {
  case: string
  key_hex: string
  nonce_hex: string
  aad_hex: string
  plaintext_hex: string
  ciphertext_hex: string
  auth_tag_hex: string
}

const vectorsPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../docs/crypto/test_vectors.json',
)
const vectors = JSON.parse(readFileSync(vectorsPath, 'utf8')) as {
  aes_256_gcm_detached: {
    case: string
    key_hex: string
    nonce_hex: string
    aad_hex: string
    plaintext_hex: string
    ciphertext_hex: string
    auth_tag_hex: string
  }[]
  chacha20_poly1305_detached: {
    case: string
    key_hex: string
    nonce_hex: string
    aad_hex: string
    plaintext_hex: string
    ciphertext_hex: string
    auth_tag_hex: string
  }[]
  aes_256_gcm_siv_detached: DetachedVector[]
  xchacha20_poly1305_detached: DetachedVector[]
  sha256: { case: string; input_utf8: string; digest_hex: string }[]
  public_key_fingerprint: { case: string; public_key_pem: string; fingerprint_hex: string }[]
  file_envelope: {
    case: string
    encryption_algorithm: string
    dek_hex: string
    nonce_hex: string
    aad_hex: string
    plaintext_hex: string
    ciphertext_hex: string
    auth_tag_hex: string
  }[]
}

describe('SHA-256', () => {
  it.each(vectors.sha256)('matches the reference digest for $case', async (vector) => {
    expect(await sha256Hex(new TextEncoder().encode(vector.input_utf8))).toBe(vector.digest_hex)
  })
})

describe('AES-256-GCM with a detached tag', () => {
  it.each(vectors.aes_256_gcm_detached)('encrypts $case to the reference bytes', async (vector) => {
    const key = await importAesGcmKey(hexToBytes(vector.key_hex))
    const { ciphertext, authTag } = await aesGcmEncryptDetached({
      key,
      nonce: hexToBytes(vector.nonce_hex),
      plaintext: hexToBytes(vector.plaintext_hex),
      aad: hexToBytes(vector.aad_hex),
    })
    expect(bytesToHex(ciphertext)).toBe(vector.ciphertext_hex)
    expect(bytesToHex(authTag)).toBe(vector.auth_tag_hex)
  })

  it.each(vectors.aes_256_gcm_detached)('decrypts $case back to the plaintext', async (vector) => {
    const key = await importAesGcmKey(hexToBytes(vector.key_hex))
    const plaintext = await aesGcmDecryptDetached({
      key,
      nonce: hexToBytes(vector.nonce_hex),
      ciphertext: hexToBytes(vector.ciphertext_hex),
      authTag: hexToBytes(vector.auth_tag_hex),
      aad: hexToBytes(vector.aad_hex),
    })
    expect(bytesToHex(plaintext)).toBe(vector.plaintext_hex)
  })

  it('keeps the tag out of the ciphertext, as the upload size check requires', async () => {
    // file_service rejects an upload whose ciphertext length differs from plaintext_size.
    const key = await importAesGcmKey(randomBytes(32))
    const plaintext = randomBytes(1024)
    const { ciphertext, authTag } = await aesGcmEncryptDetached({
      key,
      nonce: randomBytes(AES_GCM_NONCE_BYTES),
      plaintext,
      aad: new Uint8Array(),
    })
    expect(ciphertext.length).toBe(plaintext.length)
    expect(authTag.length).toBe(AES_GCM_TAG_BYTES)
  })

  it('fails authentication when the AAD differs', async () => {
    const key = await importAesGcmKey(randomBytes(32))
    const nonce = randomBytes(AES_GCM_NONCE_BYTES)
    const { ciphertext, authTag } = await aesGcmEncryptDetached({
      key,
      nonce,
      plaintext: new TextEncoder().encode('confidential'),
      aad: new TextEncoder().encode('file-a'),
    })
    await expect(
      aesGcmDecryptDetached({
        key,
        nonce,
        ciphertext,
        authTag,
        aad: new TextEncoder().encode('file-b'),
      }),
    ).rejects.toBeInstanceOf(AuthenticationFailure)
  })

  it('fails authentication when a single ciphertext bit flips', async () => {
    const key = await importAesGcmKey(randomBytes(32))
    const nonce = randomBytes(AES_GCM_NONCE_BYTES)
    const aad = new Uint8Array()
    const { ciphertext, authTag } = await aesGcmEncryptDetached({
      key,
      nonce,
      plaintext: randomBytes(64),
      aad,
    })
    const tampered = Uint8Array.from(ciphertext)
    tampered[0] ^= 0x01
    await expect(
      aesGcmDecryptDetached({ key, nonce, ciphertext: tampered, authTag, aad }),
    ).rejects.toBeInstanceOf(AuthenticationFailure)
  })

  it('rejects a nonce or tag of the wrong length instead of silently adapting', async () => {
    const key = await importAesGcmKey(randomBytes(32))
    await expect(
      aesGcmEncryptDetached({
        key,
        nonce: randomBytes(16),
        plaintext: new Uint8Array(),
        aad: new Uint8Array(),
      }),
    ).rejects.toBeInstanceOf(RangeError)
    await expect(
      aesGcmDecryptDetached({
        key,
        nonce: randomBytes(AES_GCM_NONCE_BYTES),
        ciphertext: new Uint8Array(),
        authTag: randomBytes(8),
        aad: new Uint8Array(),
      }),
    ).rejects.toBeInstanceOf(RangeError)
  })

  it('accepts every key length a supported algorithm uses', async () => {
    for (const bytes of [16, 24, 32]) {
      await expect(importAesGcmKey(randomBytes(bytes))).resolves.toBeDefined()
    }
  })

  it('rejects a key length no supported algorithm uses', async () => {
    // 20 and 64 are the shapes a truncation or a concatenation bug produces. WebCrypto
    // rejects them too, but as an opaque OperationError at first use rather than here.
    for (const bytes of [0, 8, 20, 31, 33, 64]) {
      await expect(importAesGcmKey(randomBytes(bytes))).rejects.toBeInstanceOf(RangeError)
    }
  })
})

describe('AES-GCM from @noble/ciphers, the fallback for a key length WebCrypto lacks', () => {
  // Node's WebCrypto performs all three key lengths, so both implementations can run here
  // side by side. A browser that lacks AES-192 (Chromium) gets the library instead, and
  // the files it writes must open on a browser that has the platform version, and the
  // reverse. Byte equality of ciphertext and tag is the property that makes that true.
  const KEY_LENGTHS = [16, 24, 32] as const

  it.each(KEY_LENGTHS)(
    'produces the same ciphertext and tag as WebCrypto under a %i-byte key',
    async (keyBytes) => {
      for (const length of [0, 1, 15, 16, 17, 1024, 4096 + 17]) {
        const key = randomBytes(keyBytes)
        const nonce = randomBytes(AES_GCM_NONCE_BYTES)
        const aad = randomBytes(37)
        const plaintext = randomBytes(length)
        const platform = await aesGcmEncryptDetached({
          key: await importAesGcmKey(key),
          nonce,
          plaintext,
          aad,
        })
        const library = await nobleAesGcmEncryptDetached({ key, nonce, plaintext, aad })
        expect(bytesToHex(library.ciphertext)).toBe(bytesToHex(platform.ciphertext))
        expect(bytesToHex(library.authTag)).toBe(bytesToHex(platform.authTag))
        expect(library.ciphertext.length).toBe(length)
        expect(library.authTag.length).toBe(AES_GCM_TAG_BYTES)
      }
    },
  )

  it.each(KEY_LENGTHS)('opens what WebCrypto sealed, and the reverse, at %i bytes', async (keyBytes) => {
    const key = randomBytes(keyBytes)
    const nonce = randomBytes(AES_GCM_NONCE_BYTES)
    const aad = new TextEncoder().encode('FYP-FILE-CONTENT')
    const plaintext = randomBytes(777)
    const cryptoKey = await importAesGcmKey(key)

    const byPlatform = await aesGcmEncryptDetached({ key: cryptoKey, nonce, plaintext, aad })
    expect(
      bytesToHex(await nobleAesGcmDecryptDetached({ key, nonce, aad, ...byPlatform })),
    ).toBe(bytesToHex(plaintext))

    const byLibrary = await nobleAesGcmEncryptDetached({ key, nonce, plaintext, aad })
    expect(
      bytesToHex(await aesGcmDecryptDetached({ key: cryptoKey, nonce, aad, ...byLibrary })),
    ).toBe(bytesToHex(plaintext))
  })

  // The primitive vectors are all 256-bit (there is no aes_192_gcm_detached list), which
  // still pins the library to python-cryptography's GCM rather than to WebCrypto alone. The
  // 192-bit answers come from the file_envelope list below, whose two AES-192 cases carry
  // the primitive's inputs and outputs in full.
  it.each(vectors.aes_256_gcm_detached)('encrypts $case to the reference bytes', async (vector) => {
    const { ciphertext, authTag } = await nobleAesGcmEncryptDetached({
      key: hexToBytes(vector.key_hex),
      nonce: hexToBytes(vector.nonce_hex),
      plaintext: hexToBytes(vector.plaintext_hex),
      aad: hexToBytes(vector.aad_hex),
    })
    expect(bytesToHex(ciphertext)).toBe(vector.ciphertext_hex)
    expect(bytesToHex(authTag)).toBe(vector.auth_tag_hex)
  })

  it.each(vectors.aes_256_gcm_detached)('decrypts $case back to the plaintext', async (vector) => {
    const plaintext = await nobleAesGcmDecryptDetached({
      key: hexToBytes(vector.key_hex),
      nonce: hexToBytes(vector.nonce_hex),
      ciphertext: hexToBytes(vector.ciphertext_hex),
      authTag: hexToBytes(vector.auth_tag_hex),
      aad: hexToBytes(vector.aad_hex),
    })
    expect(bytesToHex(plaintext)).toBe(vector.plaintext_hex)
  })

  const aes192Envelopes = vectors.file_envelope.filter((v) => v.encryption_algorithm === 'AES-192-GCM')

  it('has 192-bit known answers to check against', () => {
    expect(aes192Envelopes.length).toBeGreaterThanOrEqual(2)
    for (const vector of aes192Envelopes) expect(hexToBytes(vector.dek_hex).length).toBe(24)
  })

  it.each(aes192Envelopes)('reproduces the 192-bit file envelope $case', async (vector) => {
    const key = hexToBytes(vector.dek_hex)
    const nonce = hexToBytes(vector.nonce_hex)
    const aad = hexToBytes(vector.aad_hex)
    const sealed = await nobleAesGcmEncryptDetached({
      key,
      nonce,
      plaintext: hexToBytes(vector.plaintext_hex),
      aad,
    })
    expect(bytesToHex(sealed.ciphertext)).toBe(vector.ciphertext_hex)
    expect(bytesToHex(sealed.authTag)).toBe(vector.auth_tag_hex)
    const opened = await nobleAesGcmDecryptDetached({
      key,
      nonce,
      ciphertext: hexToBytes(vector.ciphertext_hex),
      authTag: hexToBytes(vector.auth_tag_hex),
      aad,
    })
    expect(bytesToHex(opened)).toBe(vector.plaintext_hex)
  })

  it('refuses a changed byte, tag, AAD or key as an authentication failure', async () => {
    const key = randomBytes(24)
    const nonce = randomBytes(AES_GCM_NONCE_BYTES)
    const aad = new TextEncoder().encode('aad')
    const sealed = await nobleAesGcmEncryptDetached({ key, nonce, plaintext: randomBytes(50), aad })
    const open = (overrides: Partial<{ key: Uint8Array; ciphertext: Uint8Array; authTag: Uint8Array; aad: Uint8Array }>) =>
      nobleAesGcmDecryptDetached({ key, nonce, ...sealed, aad, ...overrides })

    const flipped = sealed.ciphertext.slice()
    flipped[0]! ^= 1
    await expect(open({ ciphertext: flipped })).rejects.toBeInstanceOf(AuthenticationFailure)
    const badTag = sealed.authTag.slice()
    badTag[15]! ^= 1
    await expect(open({ authTag: badTag })).rejects.toBeInstanceOf(AuthenticationFailure)
    await expect(open({ aad: new TextEncoder().encode('other') })).rejects.toBeInstanceOf(AuthenticationFailure)
    await expect(open({ key: randomBytes(24) })).rejects.toBeInstanceOf(AuthenticationFailure)
  })

  it('rejects key, nonce and tag lengths that are not the specified ones', async () => {
    const args = { nonce: randomBytes(AES_GCM_NONCE_BYTES), plaintext: new Uint8Array(), aad: new Uint8Array() }
    for (const badKey of [0, 8, 20, 31, 33]) {
      await expect(nobleAesGcmEncryptDetached({ ...args, key: randomBytes(badKey) })).rejects.toBeInstanceOf(RangeError)
    }
    await expect(
      nobleAesGcmEncryptDetached({ ...args, key: randomBytes(24), nonce: randomBytes(16) }),
    ).rejects.toBeInstanceOf(RangeError)
    await expect(
      nobleAesGcmDecryptDetached({ key: randomBytes(24), nonce: args.nonce, ciphertext: new Uint8Array(), authTag: randomBytes(8), aad: args.aad }),
    ).rejects.toBeInstanceOf(RangeError)
  })
})

describe('choosing WebCrypto or the library for AES-GCM', () => {
  const subtle = globalThis.crypto.subtle

  afterEach(() => {
    vi.restoreAllMocks()
    resetEncryptionCapabilityCache()
  })

  it('offers all six suites and uses WebCrypto for every key length Node provides', async () => {
    resetEncryptionCapabilityCache()
    expect(await supportedEncryptionAlgorithms()).toEqual([...ENCRYPTION_ALGORITHMS])
    for (const keyBytes of [16, 24, 32]) expect(await platformSupportsAesGcm(keyBytes)).toBe(true)

    const encrypt = vi.spyOn(subtle, 'encrypt')
    await aesGcmSealDetached({
      key: randomBytes(24),
      nonce: randomBytes(AES_GCM_NONCE_BYTES),
      plaintext: randomBytes(10),
      aad: new Uint8Array(),
    })
    expect(encrypt).toHaveBeenCalledTimes(1)
  })

  it('still offers six suites when WebCrypto refuses AES-192, and performs it in the library', async () => {
    // What Chromium does: importKey throws for a 24-byte key and only for that length.
    const realImportKey = subtle.importKey.bind(subtle)
    vi.spyOn(subtle, 'importKey').mockImplementation(async (format, keyData, ...rest) => {
      if (format === 'raw' && (keyData as Uint8Array).byteLength === 24) {
        throw new DOMException('AES key data must be 128 or 256 bits', 'OperationError')
      }
      return realImportKey(format, keyData as BufferSource, ...rest)
    })
    const encrypt = vi.spyOn(subtle, 'encrypt')
    const decrypt = vi.spyOn(subtle, 'decrypt')
    resetEncryptionCapabilityCache()

    expect(await supportedEncryptionAlgorithms()).toEqual([...ENCRYPTION_ALGORITHMS])
    expect(await platformSupportsAesGcm(24)).toBe(false)
    expect(await platformSupportsAesGcm(16)).toBe(true)
    expect(await platformSupportsAesGcm(32)).toBe(true)
    // The probes themselves encrypt once per key length the platform accepts; nothing after
    // this point may touch WebCrypto for AES-192.
    encrypt.mockClear()

    const key = randomBytes(24)
    const nonce = randomBytes(AES_GCM_NONCE_BYTES)
    const aad = new TextEncoder().encode('aad')
    const plaintext = randomBytes(300)
    const sealed = await aesGcmSealDetached({ key, nonce, plaintext, aad })
    const opened = await aesGcmOpenDetached({ key, nonce, aad, ...sealed })
    expect(bytesToHex(opened)).toBe(bytesToHex(plaintext))
    expect(encrypt).not.toHaveBeenCalled()
    expect(decrypt).not.toHaveBeenCalled()

    // And what the library wrote is what the platform would have written, so a file from
    // this browser opens anywhere.
    const reference = await nobleAesGcmEncryptDetached({ key, nonce, plaintext, aad })
    expect(bytesToHex(sealed.ciphertext)).toBe(bytesToHex(reference.ciphertext))
    expect(bytesToHex(sealed.authTag)).toBe(bytesToHex(reference.authTag))

    // AES-256 keeps going to the platform regardless.
    await aesGcmSealDetached({ key: randomBytes(32), nonce, plaintext, aad })
    expect(encrypt).toHaveBeenCalledTimes(1)
  })

  it('refuses to run at all when WebCrypto cannot do AES-256-GCM', async () => {
    vi.spyOn(subtle, 'importKey').mockRejectedValue(new DOMException('no', 'OperationError'))
    resetEncryptionCapabilityCache()
    await expect(supportedEncryptionAlgorithms()).rejects.toThrow(/AES-256-GCM/)
  })
})

describe('public key identity', () => {
  const [vector] = vectors.public_key_fingerprint

  it('reproduces the reference fingerprint over DER SubjectPublicKeyInfo', async () => {
    expect(await publicKeyFingerprint(vector.public_key_pem)).toBe(vector.fingerprint_hex)
  })

  it('is stable across whitespace differences in the PEM', async () => {
    const reflowed = `${vector.public_key_pem.trim()}\n\n`
    expect(await publicKeyFingerprint(reflowed)).toBe(vector.fingerprint_hex)
  })

  it('refuses a private key or a non-PEM string', () => {
    expect(() => publicKeyPemToDer('-----BEGIN PRIVATE KEY-----\nAAA=\n-----END PRIVATE KEY-----')).toThrow(
      TypeError,
    )
    expect(() => publicKeyPemToDer('not a pem')).toThrow(TypeError)
  })
})

describe('RSA-OAEP-SHA256 key wrapping', () => {
  it('wraps and unwraps a 256-bit data encryption key', async () => {
    const pair = (await globalThis.crypto.subtle.generateKey(
      {
        name: 'RSA-OAEP',
        modulusLength: 2048,
        publicExponent: new Uint8Array([0x01, 0x00, 0x01]),
        hash: 'SHA-256',
      },
      true,
      ['encrypt', 'decrypt'],
    )) as CryptoKeyPair
    const dek = randomBytes(32)

    const wrapped = await rsaOaepWrap(pair.publicKey, dek)

    expect(wrapped.length).toBe(2048 / 8)
    expect(await rsaOaepUnwrap(pair.privateKey, wrapped)).toEqual(dek)
  })

  it('produces a different ciphertext each time, as OAEP randomization requires', async () => {
    const pair = (await globalThis.crypto.subtle.generateKey(
      {
        name: 'RSA-OAEP',
        modulusLength: 2048,
        publicExponent: new Uint8Array([0x01, 0x00, 0x01]),
        hash: 'SHA-256',
      },
      true,
      ['encrypt', 'decrypt'],
    )) as CryptoKeyPair
    const dek = randomBytes(32)
    const first = await rsaOaepWrap(pair.publicKey, dek)
    const second = await rsaOaepWrap(pair.publicKey, dek)
    expect(bytesToHex(first)).not.toBe(bytesToHex(second))
  })

  it('imports a PEM public key for wrapping', async () => {
    const key = await importRsaOaepPublicKey(vectors.public_key_fingerprint[0].public_key_pem)
    expect(key.algorithm.name).toBe('RSA-OAEP')
    expect((key.algorithm as RsaHashedKeyAlgorithm).modulusLength).toBe(3072)
  })

  it('reports a failed unwrap as an authentication failure', async () => {
    const pair = (await globalThis.crypto.subtle.generateKey(
      {
        name: 'RSA-OAEP',
        modulusLength: 2048,
        publicExponent: new Uint8Array([0x01, 0x00, 0x01]),
        hash: 'SHA-256',
      },
      true,
      ['encrypt', 'decrypt'],
    )) as CryptoKeyPair
    await expect(rsaOaepUnwrap(pair.privateKey, randomBytes(256))).rejects.toBeInstanceOf(
      AuthenticationFailure,
    )
  })
})

describe('RSA-PSS-SHA256 signatures', () => {
  it('signs and verifies with a 32-byte salt', async () => {
    const pair = (await globalThis.crypto.subtle.generateKey(
      {
        name: 'RSA-PSS',
        modulusLength: 2048,
        publicExponent: new Uint8Array([0x01, 0x00, 0x01]),
        hash: 'SHA-256',
      },
      true,
      ['sign', 'verify'],
    )) as CryptoKeyPair
    const digest = randomBytes(32)

    const signature = await rsaPssSign(pair.privateKey, digest)

    expect(signature.length).toBe(2048 / 8)
    expect(await rsaPssVerify(pair.publicKey, digest, signature)).toBe(true)

    const otherDigest = Uint8Array.from(digest)
    otherDigest[0] ^= 0x01
    expect(await rsaPssVerify(pair.publicKey, otherDigest, signature)).toBe(false)
  })
})

describe('ChaCha20-Poly1305 with a detached tag', () => {
  // The first case is RFC 8439 section 2.8.2, so this suite is anchored to the standard
  // rather than only to two implementations agreeing with each other.
  it.each(vectors.chacha20_poly1305_detached)(
    'encrypts $case to the reference ciphertext',
    async (vector) => {
      const { ciphertext, authTag } = await chacha20Poly1305EncryptDetached({
        key: hexToBytes(vector.key_hex),
        nonce: hexToBytes(vector.nonce_hex),
        plaintext: hexToBytes(vector.plaintext_hex),
        aad: hexToBytes(vector.aad_hex),
      })
      expect(bytesToHex(ciphertext)).toBe(vector.ciphertext_hex)
      expect(bytesToHex(authTag)).toBe(vector.auth_tag_hex)
      // Like GCM, the ciphertext is the same length as the plaintext once the tag is
      // detached. This is what lets one stored column layout serve both constructions.
      expect(ciphertext.length).toBe(hexToBytes(vector.plaintext_hex).length)
    },
  )

  it.each(vectors.chacha20_poly1305_detached)(
    'decrypts $case back to the plaintext',
    async (vector) => {
      const plaintext = await chacha20Poly1305DecryptDetached({
        key: hexToBytes(vector.key_hex),
        nonce: hexToBytes(vector.nonce_hex),
        ciphertext: hexToBytes(vector.ciphertext_hex),
        authTag: hexToBytes(vector.auth_tag_hex),
        aad: hexToBytes(vector.aad_hex),
      })
      expect(bytesToHex(plaintext)).toBe(vector.plaintext_hex)
    },
  )

  it('rejects a tampered tag, ciphertext, or AAD as an authentication failure', async () => {
    const key = randomBytes(32)
    const nonce = randomBytes(CHACHA20_NONCE_BYTES)
    const aad = new TextEncoder().encode('FYP-FILE-CONTENT')
    const plaintext = new TextEncoder().encode('confidential')
    const sealed = await chacha20Poly1305EncryptDetached({ key, nonce, plaintext, aad })

    const flipFirstByte = (b: Uint8Array) => {
      const copy = b.slice()
      copy[0] ^= 0x01
      return copy
    }

    for (const altered of [
      { ...sealed, authTag: flipFirstByte(sealed.authTag) },
      { ...sealed, ciphertext: flipFirstByte(sealed.ciphertext) },
    ]) {
      await expect(
        chacha20Poly1305DecryptDetached({ key, nonce, aad, ...altered }),
      ).rejects.toBeInstanceOf(AuthenticationFailure)
    }

    // A changed AAD must fail too: that is the property the whole envelope relies on.
    await expect(
      chacha20Poly1305DecryptDetached({ key, nonce, ...sealed, aad: flipFirstByte(aad) }),
    ).rejects.toBeInstanceOf(AuthenticationFailure)

    // And a different key, which is what a substituted wrapping would produce.
    await expect(
      chacha20Poly1305DecryptDetached({ key: randomBytes(32), nonce, aad, ...sealed }),
    ).rejects.toBeInstanceOf(AuthenticationFailure)
  })

  it('rejects key, nonce and tag lengths that are not the specified ones', async () => {
    const key = randomBytes(32)
    const nonce = randomBytes(CHACHA20_NONCE_BYTES)
    const args = { plaintext: new Uint8Array(), aad: new Uint8Array() }

    for (const badKey of [16, 24, 31, 33]) {
      await expect(
        chacha20Poly1305EncryptDetached({ ...args, key: randomBytes(badKey), nonce }),
      ).rejects.toBeInstanceOf(RangeError)
    }
    for (const badNonce of [8, 11, 13, 24]) {
      await expect(
        chacha20Poly1305EncryptDetached({ ...args, key, nonce: randomBytes(badNonce) }),
      ).rejects.toBeInstanceOf(RangeError)
    }
    await expect(
      chacha20Poly1305DecryptDetached({
        key,
        nonce,
        ciphertext: new Uint8Array(),
        authTag: randomBytes(CHACHA20_TAG_BYTES - 1),
        aad: new Uint8Array(),
      }),
    ).rejects.toBeInstanceOf(RangeError)
  })

  it('produces the same shapes AES-GCM does, which is why one envelope serves both', async () => {
    const sealed = await chacha20Poly1305EncryptDetached({
      key: randomBytes(32),
      nonce: randomBytes(CHACHA20_NONCE_BYTES),
      plaintext: new TextEncoder().encode('same shape as AES-GCM'),
      aad: new Uint8Array(),
    })
    expect(sealed.authTag.length).toBe(AES_GCM_TAG_BYTES)
    expect(CHACHA20_NONCE_BYTES).toBe(AES_GCM_NONCE_BYTES)
  })
})

describe.each([
  // Each list begins with its specification's own vector (RFC 8452 appendix C.2; the XChaCha
  // draft's appendix A.3.1); the rest come from OpenSSL and libsodium respectively.
  ['AES-256-GCM-SIV', vectors.aes_256_gcm_siv_detached],
  ['XChaCha20-Poly1305', vectors.xchacha20_poly1305_detached],
] as const)('%s with a detached tag', (algorithm, cases) => {
  it.each(cases)('encrypts $case to the reference ciphertext', async (vector) => {
    const { ciphertext, authTag } = await libraryAeadEncryptDetached({
      algorithm,
      key: hexToBytes(vector.key_hex),
      nonce: hexToBytes(vector.nonce_hex),
      plaintext: hexToBytes(vector.plaintext_hex),
      aad: hexToBytes(vector.aad_hex),
    })
    expect(bytesToHex(ciphertext)).toBe(vector.ciphertext_hex)
    expect(bytesToHex(authTag)).toBe(vector.auth_tag_hex)
    expect(ciphertext.length).toBe(hexToBytes(vector.plaintext_hex).length)
  })

  it.each(cases)('decrypts $case back to the plaintext', async (vector) => {
    const plaintext = await libraryAeadDecryptDetached({
      algorithm,
      key: hexToBytes(vector.key_hex),
      nonce: hexToBytes(vector.nonce_hex),
      ciphertext: hexToBytes(vector.ciphertext_hex),
      authTag: hexToBytes(vector.auth_tag_hex),
      aad: hexToBytes(vector.aad_hex),
    })
    expect(bytesToHex(plaintext)).toBe(vector.plaintext_hex)
  })

  it('refuses a changed byte, tag or AAD, and the wrong nonce length', async () => {
    const key = randomBytes(32)
    const nonce = randomBytes(nonceBytesForAlgorithm(algorithm))
    const aad = new TextEncoder().encode('aad')
    const sealed = await libraryAeadEncryptDetached({
      algorithm, key, nonce, plaintext: new TextEncoder().encode('secret file'), aad,
    })
    const open = (overrides: Partial<{ ciphertext: Uint8Array; authTag: Uint8Array; aad: Uint8Array }>) =>
      libraryAeadDecryptDetached({ algorithm, key, nonce, ...sealed, aad, ...overrides })

    const flipped = sealed.ciphertext.slice()
    flipped[0]! ^= 1
    await expect(open({ ciphertext: flipped })).rejects.toBeInstanceOf(AuthenticationFailure)
    const badTag = sealed.authTag.slice()
    badTag[15]! ^= 1
    await expect(open({ authTag: badTag })).rejects.toBeInstanceOf(AuthenticationFailure)
    await expect(open({ aad: new TextEncoder().encode('other') })).rejects.toBeInstanceOf(
      AuthenticationFailure,
    )
    const wrongLength = algorithm === 'XChaCha20-Poly1305' ? 12 : 24
    await expect(
      libraryAeadEncryptDetached({ algorithm, key, nonce: randomBytes(wrongLength), plaintext: new Uint8Array(1), aad }),
    ).rejects.toBeInstanceOf(RangeError)
  })
})
