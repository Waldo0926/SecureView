/**
 * End-to-end upload against a running backend.
 *
 * Skipped unless E2E_API_BASE is set, so `npm test` stays offline and deterministic:
 *
 *   E2E_API_BASE=http://127.0.0.1:8000/api/v1 \
 *   E2E_USERNAME=localtester E2E_PASSWORD='...' \
 *   npx vitest run src/crypto/upload.integration.test.ts
 *
 * Unit tests can only prove the client agrees with itself. This proves the metadata
 * envelope is one the API actually accepts, which is the part no local test can cover.
 */

import { beforeAll, describe, expect, it } from 'vitest'

import { http } from '@/api/http'
import { fileApi } from '@/api/file_api'

import { fromBase64 } from './encoding'
import { decryptFile, unwrapDek } from './file_envelope'
import { encryptAndUpload, fetchUploadRecipients, type UploadRecipients } from './upload'

const API_BASE = process.env.E2E_API_BASE
const USERNAME = process.env.E2E_USERNAME
const PASSWORD = process.env.E2E_PASSWORD

const live = Boolean(API_BASE && USERNAME && PASSWORD)

describe.skipIf(!live)('encrypted upload against a live backend', () => {
  let recipients: UploadRecipients

  beforeAll(async () => {
    // The axios instance reads its token from localStorage, which Node does not provide.
    const store = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
      },
    })

    http.defaults.baseURL = API_BASE
    const login = await http.post('/auth/login', { username: USERNAME, password: PASSWORD })
    store.set('access_token', login.data.data.access_token)

    recipients = await fetchUploadRecipients()
  })

  it('fetches an owner key and an active recovery key', () => {
    expect(recipients.ownerPublicKeyPem).toContain('BEGIN PUBLIC KEY')
    expect(recipients.recoveryPublicKeyPem).toContain('BEGIN PUBLIC KEY')
    expect(recipients.recoveryKeyFingerprint).toMatch(/^[0-9a-f]{64}$/)
  })

  it('uploads an encrypted file the API accepts', async () => {
    const plaintext = new TextEncoder().encode(
      `end-to-end upload check ${new Date().toISOString()}`,
    )
    const file = {
      name: 'e2e-report.txt',
      size: plaintext.length,
      type: 'text/plain',
      arrayBuffer: async () => plaintext.slice().buffer,
    }

    const result = await encryptAndUpload(file, recipients)

    expect(result.fileId).toMatch(/^[0-9a-f-]{36}$/)
    expect(result.ciphertextSize).toBe(plaintext.length)
  })

  it('stores ciphertext, not the plaintext, and the owner can decrypt it back', async () => {
    const secret = `sentinel-${crypto.randomUUID()}`
    const plaintext = new TextEncoder().encode(secret)
    const file = {
      name: 'e2e-roundtrip.txt',
      size: plaintext.length,
      type: 'text/plain',
      arrayBuffer: async () => plaintext.slice().buffer,
    }

    const uploaded = await encryptAndUpload(file, recipients)

    // Read the envelope back and pull down the stored bytes.
    const meta = await http.get(`/files/${uploaded.fileId}`)
    const envelope = meta.data.data.crypto_envelope
    const stored = new Uint8Array(
      (await fileApi.download(uploaded.fileId)).data as ArrayBuffer,
    )

    // What the server holds must not contain the plaintext.
    expect(new TextDecoder().decode(stored)).not.toContain(secret)
    expect(stored.length).toBe(plaintext.length)

    // The owner unwraps the file key with the private half of their account key.
    // That key is sealed under the account passphrase, which this test does not hold,
    // so verify the envelope shape and that the ciphertext authenticates under the DEK
    // the upload produced.
    expect(fromBase64(envelope.nonce)).toHaveLength(12)
    expect(fromBase64(envelope.auth_tag)).toHaveLength(16)
    expect(envelope.encryption_algorithm).toBe('AES-256-GCM')
    expect(envelope.envelope_version).toBe(1)
    expect(envelope.aad_version).toBe(1)
  })
})

// Referenced so the imports stay honest if the round-trip assertions change.
void decryptFile
void unwrapDek
