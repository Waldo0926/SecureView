/**
 * Passphrase reset with the private key file, and change with the current passphrase, against a
 * running backend.
 *
 * The unit tests use a stand-in server. This one proves the halves agree for real: that the
 * backend's digest is the one the browser signs, that python-cryptography accepts a PSS
 * signature from a key WebCrypto generated for OAEP, that both rows really change, and --
 * the promise the feature makes -- that a file uploaded before the reset still opens after.
 *
 * Skipped unless the environment names a backend, an account, and its key file:
 *
 *   E2E_API_BASE=http://127.0.0.1:8000/api/v1 \
 *   E2E_RESET_USER=... E2E_RESET_PASSWORD='...' E2E_RESET_PASSPHRASE='...' \
 *   E2E_RESET_KEY_FILE=/path/to/private-key.pem \
 *   npx vitest run src/crypto/passphrase-reset.integration.test.ts
 *
 * The account is left as it was found: the last step resets back to the original passphrase.
 */

import { readFileSync } from 'node:fs'

import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { authApi } from '@/api/auth_api'
import { fileApi } from '@/api/file_api'
import { http } from '@/api/http'
import { keyApi } from '@/api/key_api'
import { PassphraseRejectedError, unlockAccountPrivateKeyDer } from '@/utils/account-crypto'

import { downloadAndDecrypt, forgetUnlockedKeys, unlockWithPassphrase } from './download'
import { changePassphrase, resetPassphraseWithPrivateKeyPem } from './passphrase-reset'
import { encryptAndUpload } from './upload'

const API_BASE = process.env.E2E_API_BASE
const USER = process.env.E2E_RESET_USER
const PASSWORD = process.env.E2E_RESET_PASSWORD
const PASSPHRASE = process.env.E2E_RESET_PASSPHRASE
const KEY_FILE = process.env.E2E_RESET_KEY_FILE

const live = Boolean(API_BASE && USER && PASSWORD && PASSPHRASE && KEY_FILE)

const NEW_PASSPHRASE = `reset-e2e ${Date.now()} passphrase`
const CHANGED_PASSPHRASE = `change-e2e ${Date.now()} passphrase`
const CONTENT = `uploaded before the passphrase reset, ${new Date().toISOString()}`
const FILENAME = `reset-e2e-${Date.now()}.txt`

/** The axios instance reads its token from localStorage, which node does not provide. */
const store = new Map<string, string>()
let uploadedFileId = ''

async function stored() {
  const bundle = (await keyApi.myBundle()).data.data
  return {
    key_id: bundle.key.key_id,
    protection: bundle.protection,
    private_key_bundle: bundle.private_key_bundle,
  }
}

describe.skipIf(!live)('passphrase reset with the key file, end to end', () => {
  const keyPem = live ? readFileSync(KEY_FILE!, 'utf8') : ''

  beforeAll(async () => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
        clear: () => store.clear(),
      },
    })
    http.defaults.baseURL = API_BASE
    const res = await authApi.login({ username: USER!, password: PASSWORD! })
    store.set('access_token', res.data.data.access_token)
    store.set('refresh_token', res.data.data.refresh_token ?? '')
  })

  afterAll(async () => {
    forgetUnlockedKeys()
    if (uploadedFileId) {
      try {
        await fileApi.delete(uploadedFileId)
      } catch {
        // Best effort; a leftover test file is untidy, not broken.
      }
    }
  })

  it('uploads a file under the original passphrase', async () => {
    const result = await encryptAndUpload({
      name: FILENAME,
      size: CONTENT.length,
      type: 'text/plain',
      arrayBuffer: async () => new TextEncoder().encode(CONTENT).buffer as ArrayBuffer,
    })
    uploadedFileId = result.fileId
  }, 60_000)

  it('resets to a new passphrase with the key file', async () => {
    const before = (await keyApi.myBundle()).data.data

    const outcome = await resetPassphraseWithPrivateKeyPem(keyPem, NEW_PASSPHRASE)

    expect(outcome.keyId).toBe(before.key.key_id)
    expect(outcome.profileRevision).toBe(before.protection.revision + 1)
    expect(outcome.bundleRevision).toBe(before.private_key_bundle.revision + 1)
    const after = (await keyApi.myBundle()).data.data
    expect(after.key.public_key_pem).toBe(before.key.public_key_pem)
  }, 120_000)

  it('opens with the new passphrase and no longer with the old one', async () => {
    await expect(unlockAccountPrivateKeyDer(await stored(), NEW_PASSPHRASE)).resolves.toBeDefined()
    await expect(unlockAccountPrivateKeyDer(await stored(), PASSPHRASE!)).rejects.toBeInstanceOf(
      PassphraseRejectedError,
    )
  }, 60_000)

  it('still decrypts the file uploaded before the reset', async () => {
    forgetUnlockedKeys()
    await unlockWithPassphrase(NEW_PASSPHRASE)
    const file = await downloadAndDecrypt(uploadedFileId)
    expect(new TextDecoder().decode(file.bytes)).toBe(CONTENT)
  }, 60_000)

  it('changes the passphrase with the current one, no key file needed', async () => {
    const before = (await keyApi.myBundle()).data.data

    await expect(changePassphrase('not the current passphrase', CHANGED_PASSPHRASE)).rejects.toBeInstanceOf(
      PassphraseRejectedError,
    )
    expect((await keyApi.myBundle()).data.data.protection.revision).toBe(before.protection.revision)

    const outcome = await changePassphrase(NEW_PASSPHRASE, CHANGED_PASSPHRASE)
    expect(outcome.keyId).toBe(before.key.key_id)
    expect(outcome.profileRevision).toBe(before.protection.revision + 1)
    await expect(unlockAccountPrivateKeyDer(await stored(), NEW_PASSPHRASE)).rejects.toBeInstanceOf(
      PassphraseRejectedError,
    )

    forgetUnlockedKeys()
    await unlockWithPassphrase(CHANGED_PASSPHRASE)
    const file = await downloadAndDecrypt(uploadedFileId)
    expect(new TextDecoder().decode(file.bytes)).toBe(CONTENT)
  }, 180_000)

  it('resets back, leaving the account as it was found', async () => {
    await resetPassphraseWithPrivateKeyPem(keyPem, PASSPHRASE!)
    await expect(unlockAccountPrivateKeyDer(await stored(), PASSPHRASE!)).resolves.toBeDefined()
  }, 120_000)
})
