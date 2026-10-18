import { describe, expect, it } from 'vitest'

import { enrolAccountKey } from '@/utils/account-crypto'

import { fromBase64 } from './encoding'
import { buildUploadPayload, decryptFile, encryptFile, unwrapDek } from './file_envelope'
import {
  importRsaOaepPrivateKey,
  importRsaOaepPublicKey,
  privateKeyPemToDer,
  randomBytes,
  rsaOaepUnwrap,
  rsaOaepWrap,
} from './primitives'

/**
 * The registration page hands the user a PKCS#8 PEM once and, until now, could never read
 * it back. These cover the parsing and the key-pair proof that make it usable again; the
 * network-facing `unlockWithPrivateKeyPem` wrapper is exercised in the browser.
 *
 * Argon2id at 64 MiB is deliberately slow, so enrolments are shared.
 */
const RECOVERY_KEY_ID = '00000000-0000-4000-8000-000000000001'

let enrolment: Awaited<ReturnType<typeof enrolAccountKey>>
async function sharedEnrolment() {
  enrolment ??= await enrolAccountKey('a separate encryption passphrase')
  return enrolment
}

describe('privateKeyPemToDer', () => {
  it('reads back the PEM the registration page exports', async () => {
    const { privateKeyPem } = await sharedEnrolment()

    const der = privateKeyPemToDer(privateKeyPem)

    // Importable is the property that matters: a DER blob that WebCrypto rejects is no
    // more use to the user than no file at all.
    await expect(importRsaOaepPrivateKey(der)).resolves.toBeDefined()
  })

  it('names PKCS#1 rather than failing later inside importKey', () => {
    // `openssl genrsa` still emits this header by default, so a user who regenerated a key
    // by hand lands here. A DataError from importKey would tell them nothing.
    const pkcs1 = '-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n'

    expect(() => privateKeyPemToDer(pkcs1)).toThrow(/PKCS#1/)
  })

  it('refuses a public key handed over by mistake', async () => {
    const { keyMaterial } = await sharedEnrolment()

    expect(() => privateKeyPemToDer(keyMaterial.public_key_pem)).toThrow(TypeError)
  })

  it('refuses a file that is not a key at all', () => {
    expect(() => privateKeyPemToDer('just some notes I saved\n')).toThrow(TypeError)
  })
})

describe('the imported key', () => {
  it('is the partner of the public key the account registered', async () => {
    const { privateKeyPem, keyMaterial } = await sharedEnrolment()

    // The same round trip `assertKeyPairMatches` performs: wrap a probe to the registered
    // public key, unwrap it with the key read out of the file.
    const probe = randomBytes(32)
    const publicKey = await importRsaOaepPublicKey(keyMaterial.public_key_pem)
    const privateKey = await importRsaOaepPrivateKey(privateKeyPemToDer(privateKeyPem))

    const recovered = await rsaOaepUnwrap(privateKey, await rsaOaepWrap(publicKey, probe))

    expect(Array.from(recovered)).toEqual(Array.from(probe))
  })

  it('does not open a different account, however well-formed the file is', async () => {
    // The failure this guards against: any valid PKCS#8 key imports cleanly, so a key from
    // another account would be accepted here and only fail much later as an unwrap error on
    // a file -- which reads as "this file is damaged", not "this is the wrong key".
    const mine = await sharedEnrolment()
    const stranger = await enrolAccountKey('an unrelated account passphrase')

    const probe = randomBytes(32)
    const myPublicKey = await importRsaOaepPublicKey(mine.keyMaterial.public_key_pem)
    const strangerPrivateKey = await importRsaOaepPrivateKey(
      privateKeyPemToDer(stranger.privateKeyPem),
    )

    await expect(
      rsaOaepUnwrap(strangerPrivateKey, await rsaOaepWrap(myPublicKey, probe)),
    ).rejects.toThrow()
  })

  it('cannot be read back out of the page once imported', async () => {
    const { privateKeyPem } = await sharedEnrolment()

    const privateKey = await importRsaOaepPrivateKey(privateKeyPemToDer(privateKeyPem))

    // Non-extractable, so a later bug cannot serialise the account private key into a log
    // line or a request body -- the same property the passphrase path guarantees.
    expect(privateKey.extractable).toBe(false)
    expect(privateKey.usages).toEqual(['decrypt'])
  })

  it('recovers a real file with the key file alone, no passphrase anywhere', async () => {
    // The property this whole path exists for: someone who forgot the passphrase but kept
    // the .pem gets their bytes back, using only what the server stores plus that file.
    const { keyMaterial, privateKeyPem } = await sharedEnrolment()
    const plaintext = new TextEncoder().encode('chapter one, and everything after it')

    const envelope = await encryptFile({
      plaintext,
      originalFilename: 'dissertation.pdf',
      mimeType: 'application/pdf',
    })
    const payload = await buildUploadPayload({
      envelope,
      ownerKeyId: keyMaterial.key_id,
      ownerPublicKeyPem: keyMaterial.public_key_pem,
      recoveryKeyId: RECOVERY_KEY_ID,
      recoveryPublicKeyPem: keyMaterial.public_key_pem,
    })

    const privateKey = await importRsaOaepPrivateKey(privateKeyPemToDer(privateKeyPem))
    const dek = await unwrapDek(privateKey, fromBase64(payload.metadata.wrapped_file_key))
    const recovered = await decryptFile({
      identity: {
        fileId: payload.metadata.file_id,
        originalFilename: payload.metadata.original_filename,
        plaintextSize: payload.metadata.plaintext_size,
        mimeType: payload.metadata.mime_type,
      },
      dek,
      nonce: fromBase64(payload.metadata.nonce),
      ciphertext: payload.ciphertext,
      authTag: fromBase64(payload.metadata.auth_tag),
    })

    expect(new TextDecoder().decode(recovered)).toBe(
      'chapter one, and everything after it',
    )
  })
})
