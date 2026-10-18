import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { enrolAccountKey } from '@/utils/account-crypto'

import { buildUploadPayload, encryptFile } from './file_envelope'

/**
 * The account key is opened for one decrypted download or one share and then dropped, so a
 * person who signs in with a stolen password still has to know the passphrase for every
 * file. These tests use a real key and real encryption; only the three API modules are faked.
 */
let myBundle: () => unknown = () => Promise.reject(new Error('no bundle set'))
let getFile: (id: string) => unknown = () => Promise.reject(new Error('no file set'))
let download: (id: string) => unknown = () => Promise.reject(new Error('no file set'))
let shareFile: (id: string, body: unknown) => unknown = () => Promise.reject(new Error('no share set'))

vi.mock('@/api/key_api', () => ({ keyApi: { myBundle: () => myBundle() } }))
vi.mock('@/api/file_api', () => ({
  fileApi: { getFile: (id: string) => getFile(id), download: (id: string) => download(id) },
}))
vi.mock('@/api/share_api', () => ({
  shareApi: { shareFile: (id: string, body: unknown) => shareFile(id, body) },
}))

const { downloadAndDecrypt, forgetUnlockedKeys, isUnlocked, unlockWithPrivateKeyPem } = await import('./download')
const { shareFileWithRecipient } = await import('./share')

const OTHER_KEY_ID = '00000000-0000-4000-8000-000000000002'
const TEXT = 'minutes of the board meeting'

let pem = ''
let keyId = ''
let publicKeyPem = ''
let metadata: Record<string, unknown> = {}
let ciphertext: Uint8Array = new Uint8Array()

beforeAll(async () => {
  // Argon2id at the enrolled cost is slow on purpose, so one enrolment serves every test.
  const enrolment = await enrolAccountKey('one passphrase for this whole file')
  pem = enrolment.privateKeyPem
  keyId = enrolment.keyMaterial.key_id
  publicKeyPem = enrolment.keyMaterial.public_key_pem

  const envelope = await encryptFile({
    plaintext: new TextEncoder().encode(TEXT),
    originalFilename: 'minutes.txt',
    mimeType: 'text/plain',
  })
  const payload = await buildUploadPayload({
    envelope,
    ownerKeyId: keyId,
    ownerPublicKeyPem: publicKeyPem,
    recoveryKeyId: OTHER_KEY_ID,
    recoveryPublicKeyPem: publicKeyPem,
  })
  const m = payload.metadata
  metadata = {
    file_id: m.file_id,
    original_filename: m.original_filename,
    plaintext_size: m.plaintext_size,
    mime_type: m.mime_type,
    crypto_envelope: {
      key_id: keyId,
      wrapped_file_key: m.wrapped_file_key,
      nonce: m.nonce,
      auth_tag: m.auth_tag,
      envelope_version: m.envelope_version,
      aad_version: m.aad_version,
      encryption_algorithm: m.encryption_algorithm,
    },
  }
  ciphertext = payload.ciphertext

  myBundle = () => Promise.resolve({ data: { data: { key: { key_id: keyId, public_key_pem: publicKeyPem } } } })
})

afterEach(() => {
  forgetUnlockedKeys()
  getFile = () => Promise.reject(new Error('no file set'))
  download = () => Promise.reject(new Error('no file set'))
  shareFile = () => Promise.reject(new Error('no share set'))
})

function serveTheFile() {
  getFile = () => Promise.resolve({ data: { data: metadata } })
  download = () => Promise.resolve({ data: ciphertext.slice().buffer })
}

/** A recipient on a different key, so the share is not refused as sharing with yourself. */
function recipient() {
  return { identifier: 'bob', userId: 'user-bob', keyId: OTHER_KEY_ID, publicKeyPem, fingerprint: 'ab'.repeat(32) }
}

describe('a decrypted download uses the key once', () => {
  it('locks the key again after a successful download', async () => {
    serveTheFile()
    await unlockWithPrivateKeyPem(pem)
    expect(isUnlocked()).toBe(true)

    const file = await downloadAndDecrypt(String(metadata.file_id))

    expect(new TextDecoder().decode(file.bytes)).toBe(TEXT)
    expect(isUnlocked()).toBe(false)
    // The next download asks for the passphrase again.
    await expect(downloadAndDecrypt(String(metadata.file_id))).rejects.toMatchObject({ name: 'NotUnlockedError' })
  })

  it('locks the key again when the download fails', async () => {
    getFile = () => Promise.reject(new Error('network down'))
    await unlockWithPrivateKeyPem(pem)

    await expect(downloadAndDecrypt('file-id')).rejects.toThrow('network down')
    expect(isUnlocked()).toBe(false)
  })

  it('locks the key again when the file needs an older key', async () => {
    getFile = () =>
      Promise.resolve({
        data: { data: { ...metadata, crypto_envelope: { ...(metadata.crypto_envelope as object), key_id: OTHER_KEY_ID } } },
      })
    await unlockWithPrivateKeyPem(pem)

    await expect(downloadAndDecrypt('file-id')).rejects.toMatchObject({ name: 'KeyNotUnlockedError', keyId: OTHER_KEY_ID })
    expect(isUnlocked()).toBe(false)
  })
})

describe('a share uses the key once', () => {
  it('locks the key again after a successful share', async () => {
    serveTheFile()
    const sent: unknown[] = []
    shareFile = (_id, body) => {
      sent.push(body)
      return Promise.resolve({ data: { data: { created: true } } })
    }
    await unlockWithPrivateKeyPem(pem)

    const outcome = await shareFileWithRecipient(String(metadata.file_id), recipient())

    expect(outcome).toEqual({ username: 'bob', created: true })
    expect(sent).toHaveLength(1)
    expect(isUnlocked()).toBe(false)
    await expect(shareFileWithRecipient(String(metadata.file_id), recipient())).rejects.toMatchObject({
      name: 'NotUnlockedError',
    })
  })

  it('locks the key again when the server refuses the share', async () => {
    serveTheFile()
    shareFile = () => Promise.reject(new Error('forbidden'))
    await unlockWithPrivateKeyPem(pem)

    await expect(shareFileWithRecipient(String(metadata.file_id), recipient())).rejects.toThrow('forbidden')
    expect(isUnlocked()).toBe(false)
  })

  it('locks the key again when the recipient name is empty', async () => {
    await unlockWithPrivateKeyPem(pem)

    await expect(shareFileWithRecipient('file-id', '  ')).rejects.toMatchObject({ name: 'RecipientNotFoundError' })
    expect(isUnlocked()).toBe(false)
  })
})
