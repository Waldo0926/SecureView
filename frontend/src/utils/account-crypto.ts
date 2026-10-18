/**
 * Client-side account key enrolment.
 *
 * The encryption passphrase never leaves this module. The browser generates the
 * RSA key pair and a random account master key (AMK), wraps the AMK under an
 * Argon2id-derived key-encryption key (KEK), and encrypts the PKCS#8 private key
 * under an AMK/HKDF-derived key. Only the public key and the two sealed
 * envelopes are uploaded, which is the client-custody boundary described in
 * docs/SECURITY_FLOWS.md.
 *
 * Low-level operations come from `@/crypto/primitives` and `@/crypto/encoding`
 * so this module and the file-envelope code share one vetted implementation.
 * Only the pieces those modules do not provide live here: RSA key-pair
 * generation, the Argon2id KEK, and the HKDF-SHA256 private-key key.
 *
 * The associated data for both envelopes is rebuildable from stored non-secret
 * metadata, so a later unlock can reconstruct it without extra server state.
 */
import { argon2id } from 'hash-wasm'

import { bytesEqual, fromBase64, toBase64, utf8Bytes } from '@/crypto/encoding'
import {
  AES_GCM_NONCE_BYTES,
  AES_KEY_BYTES,
  aesGcmDecryptDetached,
  aesGcmEncryptDetached,
  importAesGcmKey,
  importRsaOaepPrivateKey,
  randomBytes,
  randomUuid,
  sha256Hex,
} from '@/crypto/primitives'

/** Must match the backend USER_RSA_KEY_SIZE setting. */
export const RSA_KEY_SIZE_BITS = 3072

/** Backend KeyProtectionProfileIn requires at least 65536 KiB. */
export const ARGON2_MEMORY_KIB = 65536
export const ARGON2_ITERATIONS = 3
export const ARGON2_PARALLELISM = 1

const KDF_SALT_BYTES = 16
const HKDF_SALT_BYTES = 32

/**
 * The uploaded shape carries material only. Algorithm names, format versions and
 * the derived key length had one legal value each, so the API pins them and no
 * longer accepts them; sending one back is a 422. The stored rows and the
 * `GET /keys/me` response still spell them out, which is what a second algorithm
 * would eventually need.
 */
export interface KeyProtectionProfilePayload {
  profile_id: string
  kdf_salt: string
  kdf_memory_kib: number
  kdf_iterations: number
  kdf_parallelism: number
  wrapped_amk: string
  amk_nonce: string
  amk_auth_tag: string
}

export interface EncryptedPrivateKeyBundlePayload {
  bundle_id: string
  derivation_salt: string
  encrypted_private_key: string
  nonce: string
  auth_tag: string
  ciphertext_sha256: string
}

export interface ClientKeyMaterial {
  key_id: string
  public_key_pem: string
  key_size_bits: number
  protection: KeyProtectionProfilePayload
  private_key_bundle: EncryptedPrivateKeyBundlePayload
}

export interface EnrolmentResult {
  /** Upload this. It contains no passphrase, AMK, or plaintext private key. */
  keyMaterial: ClientKeyMaterial
  /**
   * Shown to the user once so they can keep an offline copy. This is never
   * transmitted and is dropped as soon as the page navigates away.
   */
  privateKeyPem: string
}

export class AccountKeySelfTestError extends Error {
  constructor() {
    super('Account key self-test failed; registration was not attempted')
    this.name = 'AccountKeySelfTestError'
  }
}

function subtle(): SubtleCrypto {
  const api = globalThis.crypto?.subtle
  if (!api) {
    throw new Error('WebCrypto is unavailable; a secure context (HTTPS or localhost) is required')
  }
  return api
}

function toPem(label: string, der: ArrayBuffer): string {
  const base64 = toBase64(new Uint8Array(der))
  const lines = base64.match(/.{1,64}/g) ?? []
  return `-----BEGIN ${label}-----\n${lines.join('\n')}\n-----END ${label}-----\n`
}

/** AAD for the wrapped AMK, rebuildable from the stored protection profile. */
export function amkWrapAad(profileId: string): Uint8Array {
  return utf8Bytes(`secureview:amk-wrap:v1:${profileId}`)
}

/** AAD for the private-key bundle, rebuildable from the stored bundle and key. */
export function privateKeyAad(bundleId: string, keyId: string): Uint8Array {
  return utf8Bytes(`secureview:private-key:v1:${bundleId}:${keyId}`)
}

/** The Argon2id cost an account was enrolled with, as its protection profile records it. */
export interface Argon2Cost {
  memorySize: number
  iterations: number
  parallelism: number
}

export const DEFAULT_ARGON2_COST: Argon2Cost = {
  memorySize: ARGON2_MEMORY_KIB,
  iterations: ARGON2_ITERATIONS,
  parallelism: ARGON2_PARALLELISM,
}

/**
 * Argon2id KEK derivation. `hash-wasm` supplies what WebCrypto does not.
 *
 * The cost is a parameter rather than a constant because it is a per-account choice
 * carried on the wire: raising it later must not lock out accounts enrolled under the old
 * one. Deriving with today's constants against yesterday's profile produces a different
 * key and reads as a wrong passphrase, which is the least debuggable failure available.
 */
export async function deriveKek(
  passphrase: string,
  salt: Uint8Array,
  cost: Argon2Cost = DEFAULT_ARGON2_COST,
): Promise<Uint8Array> {
  return argon2id({
    password: passphrase,
    salt,
    parallelism: cost.parallelism,
    iterations: cost.iterations,
    memorySize: cost.memorySize,
    hashLength: AES_KEY_BYTES,
    outputType: 'binary',
  })
}

/** HKDF-SHA256 private-key encryption key, bound to the bundle AAD as `info`. */
export async function derivePrivateKeyEncryptionKey(
  amk: Uint8Array,
  salt: Uint8Array,
  info: Uint8Array,
): Promise<Uint8Array> {
  const hkdfKey = await subtle().importKey('raw', amk as BufferSource, 'HKDF', false, [
    'deriveBits',
  ])
  const bits = await subtle().deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt: salt as BufferSource, info: info as BufferSource },
    hkdfKey,
    AES_KEY_BYTES * 8,
  )
  return new Uint8Array(bits)
}

/**
 * Generate an account key pair and seal it under the passphrase.
 *
 * Throws if the self-test cannot recover the private key, so a broken envelope
 * is never registered against a new account.
 */
export async function enrolAccountKey(passphrase: string): Promise<EnrolmentResult> {
  const crypto = subtle()

  const keyPair = (await crypto.generateKey(
    {
      name: 'RSA-OAEP',
      modulusLength: RSA_KEY_SIZE_BITS,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: 'SHA-256',
    },
    true,
    ['encrypt', 'decrypt'],
  )) as CryptoKeyPair

  const spki = await crypto.exportKey('spki', keyPair.publicKey)
  const pkcs8 = await crypto.exportKey('pkcs8', keyPair.privateKey)
  const publicKeyPem = toPem('PUBLIC KEY', spki)
  const privateKeyPem = toPem('PRIVATE KEY', pkcs8)
  const privateKeyDer = new Uint8Array(pkcs8)

  const keyId = randomUuid()
  const sealed = await sealAccountKey({
    privateKeyDer,
    passphrase,
    keyId,
    profileId: randomUuid(),
    bundleId: randomUuid(),
  })

  const keyMaterial: ClientKeyMaterial = {
    key_id: keyId,
    public_key_pem: publicKeyPem,
    key_size_bits: RSA_KEY_SIZE_BITS,
    protection: sealed.protection,
    private_key_bundle: sealed.private_key_bundle,
  }

  await assertEnvelopesUnlock(keyMaterial, passphrase, privateKeyDer)

  return { keyMaterial, privateKeyPem }
}

/**
 * Seal an existing PKCS#8 private key under a passphrase, with a fresh AMK.
 *
 * The two envelopes every account key lives in: a random AMK wrapped under an Argon2id KEK,
 * and the private key encrypted under an HKDF key derived from that AMK. Every salt, nonce,
 * and the AMK itself are drawn fresh on each call, so sealing the same key twice never
 * reuses a (key, nonce) pair under GCM.
 *
 * Enrolment and passphrase reset both go through here, so there is one construction to keep
 * in step with `unlockAccountPrivateKeyDer` and with `backend/scripts/seed_test_account.py`.
 */
export async function sealAccountKey(params: {
  privateKeyDer: Uint8Array
  passphrase: string
  keyId: string
  profileId: string
  bundleId: string
  cost?: Argon2Cost
}): Promise<Pick<SealedAccountKey, 'protection' | 'private_key_bundle'>> {
  const { privateKeyDer, passphrase, keyId, profileId, bundleId } = params
  const cost = params.cost ?? DEFAULT_ARGON2_COST

  // 1. Wrap a fresh random AMK under an Argon2id-derived KEK.
  const amk = randomBytes(AES_KEY_BYTES)
  const kdfSalt = randomBytes(KDF_SALT_BYTES)
  const kek = await deriveKek(passphrase, kdfSalt, cost)
  const amkNonce = randomBytes(AES_GCM_NONCE_BYTES)
  const wrappedAmk = await aesGcmEncryptDetached({
    key: await importAesGcmKey(kek),
    nonce: amkNonce,
    plaintext: amk,
    aad: amkWrapAad(profileId),
  })

  // 2. Encrypt the PKCS#8 private key under an AMK/HKDF-derived key.
  const hkdfSalt = randomBytes(HKDF_SALT_BYTES)
  const bundleAad = privateKeyAad(bundleId, keyId)
  const privateKeyKey = await derivePrivateKeyEncryptionKey(amk, hkdfSalt, bundleAad)
  const privateKeyNonce = randomBytes(AES_GCM_NONCE_BYTES)
  const sealedBundle = await aesGcmEncryptDetached({
    key: await importAesGcmKey(privateKeyKey),
    nonce: privateKeyNonce,
    plaintext: privateKeyDer,
    aad: bundleAad,
  })

  return {
    protection: {
      profile_id: profileId,
      kdf_salt: toBase64(kdfSalt),
      kdf_memory_kib: cost.memorySize,
      kdf_iterations: cost.iterations,
      kdf_parallelism: cost.parallelism,
      wrapped_amk: toBase64(wrappedAmk.ciphertext),
      amk_nonce: toBase64(amkNonce),
      amk_auth_tag: toBase64(wrappedAmk.authTag),
    },
    private_key_bundle: {
      bundle_id: bundleId,
      derivation_salt: toBase64(hkdfSalt),
      encrypted_private_key: toBase64(sealedBundle.ciphertext),
      nonce: toBase64(privateKeyNonce),
      auth_tag: toBase64(sealedBundle.authTag),
      ciphertext_sha256: await sha256Hex(sealedBundle.ciphertext),
    },
  }
}

/**
 * Re-derive both envelopes from the passphrase and confirm they return the same
 * private key. Registering an envelope that cannot be reopened would lock the
 * account out of every file it later encrypts.
 */
/** Everything needed to reopen an account key, as `GET /keys/me` returns it. */
export interface SealedAccountKey {
  key_id: string
  protection: KeyProtectionProfilePayload
  private_key_bundle: EncryptedPrivateKeyBundlePayload
}

export class PassphraseRejectedError extends Error {
  constructor() {
    super('That passphrase does not open your account key')
    this.name = 'PassphraseRejectedError'
  }
}

/**
 * Reopen the account private key from the passphrase.
 *
 * Two AES-GCM envelopes in sequence: the passphrase derives a KEK that unwraps the account
 * master key, and the AMK derives -- through HKDF, bound to the bundle's own AAD -- the key
 * that decrypts the PKCS8 private key. Both are authenticated, so a wrong passphrase fails
 * at the first tag rather than yielding plausible rubbish.
 *
 * The returned DER is the plaintext account private key. Callers that only need to decrypt
 * should prefer {@link unlockAccountPrivateKey}, which hands back a non-extractable
 * `CryptoKey` and never exposes the bytes.
 */
export async function unlockAccountPrivateKeyDer(
  sealed: SealedAccountKey,
  passphrase: string,
): Promise<Uint8Array> {
  const { protection, private_key_bundle: bundle } = sealed

  const kek = await deriveKek(passphrase, fromBase64(protection.kdf_salt), {
    memorySize: protection.kdf_memory_kib,
    iterations: protection.kdf_iterations,
    parallelism: protection.kdf_parallelism,
  })

  let amk: Uint8Array
  try {
    amk = await aesGcmDecryptDetached({
      key: await importAesGcmKey(kek),
      nonce: fromBase64(protection.amk_nonce),
      ciphertext: fromBase64(protection.wrapped_amk),
      authTag: fromBase64(protection.amk_auth_tag),
      aad: amkWrapAad(protection.profile_id),
    })
  } catch {
    // The only envelope the passphrase alone controls, so this is the honest place to
    // say the passphrase was wrong. A failure further in means something else is broken.
    throw new PassphraseRejectedError()
  }

  const bundleAad = privateKeyAad(bundle.bundle_id, sealed.key_id)
  const privateKeyKey = await derivePrivateKeyEncryptionKey(
    amk,
    fromBase64(bundle.derivation_salt),
    bundleAad,
  )
  return aesGcmDecryptDetached({
    key: await importAesGcmKey(privateKeyKey),
    nonce: fromBase64(bundle.nonce),
    ciphertext: fromBase64(bundle.encrypted_private_key),
    authTag: fromBase64(bundle.auth_tag),
    aad: bundleAad,
  })
}

/** Reopen the account key as a non-extractable `CryptoKey` that can only decrypt. */
export async function unlockAccountPrivateKey(
  sealed: SealedAccountKey,
  passphrase: string,
): Promise<CryptoKey> {
  return importRsaOaepPrivateKey(await unlockAccountPrivateKeyDer(sealed, passphrase))
}

export async function assertEnvelopesUnlock(
  keyMaterial: ClientKeyMaterial,
  passphrase: string,
  expectedPrivateKeyDer: Uint8Array,
): Promise<void> {
  const recoveredDer = await unlockAccountPrivateKeyDer(keyMaterial, passphrase)

  if (!bytesEqual(recoveredDer, expectedPrivateKeyDer)) {
    throw new AccountKeySelfTestError()
  }
}
