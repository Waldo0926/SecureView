/**
 * The whole product, against a running backend, in one pass.
 *
 * Unit tests prove each half agrees with itself. This proves the halves agree with each
 * other and with the server: that a file uploaded by one account can be opened by another
 * using only that other account's passphrase, that the trail records who did what, and that
 * revoking really does close the door.
 *
 * Skipped unless the environment names a backend and two accounts, so `npm test` stays
 * offline and deterministic:
 *
 *   E2E_API_BASE=https://secureview.tech/api/v1 \
 *   E2E_SENDER=e2e-sender E2E_SENDER_PASSWORD='...' E2E_SENDER_PASSPHRASE='...' \
 *   E2E_RECIPIENT=e2e-recipient E2E_RECIPIENT_PASSWORD='...' E2E_RECIPIENT_PASSPHRASE='...' \
 *   npx vitest run src/crypto/mvp.integration.test.ts
 *
 * Two accounts are required because the property that matters most cannot be observed with
 * one: the recipient decrypts with their own passphrase and never the sender's.
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { auditApi } from '@/api/audit_api'
import { authApi } from '@/api/auth_api'
import { fileApi } from '@/api/file_api'
import { http } from '@/api/http'
import { shareApi } from '@/api/share_api'
import { unwrapData, type FileSummaryOut } from '@/api/types'

import { downloadAndDecrypt, forgetUnlockedKeys, isUnlocked, unlockWithPassphrase } from './download'
import { shareFileWithUsername } from './share'
import { encryptAndUpload } from './upload'

const API_BASE = process.env.E2E_API_BASE
const SENDER = process.env.E2E_SENDER
const SENDER_PASSWORD = process.env.E2E_SENDER_PASSWORD
const SENDER_PASSPHRASE = process.env.E2E_SENDER_PASSPHRASE
const RECIPIENT = process.env.E2E_RECIPIENT
const RECIPIENT_PASSWORD = process.env.E2E_RECIPIENT_PASSWORD
const RECIPIENT_PASSPHRASE = process.env.E2E_RECIPIENT_PASSPHRASE

const live = Boolean(
  API_BASE &&
    SENDER &&
    SENDER_PASSWORD &&
    SENDER_PASSPHRASE &&
    RECIPIENT &&
    RECIPIENT_PASSWORD &&
    RECIPIENT_PASSPHRASE,
)

/** The axios instance reads its token from localStorage, which node does not provide. */
const store = new Map<string, string>()

const CONTENT = `MCS21 demo file, generated ${new Date().toISOString()}\n${'x'.repeat(400)}\n`
const FILENAME = `mcs21-e2e-${Date.now()}.txt`

let uploadedFileId = ''

async function signIn(username: string, password: string): Promise<void> {
  // Switching accounts must drop the previous account's opened key, or the next download
  // would silently reuse it and the test would prove nothing.
  forgetUnlockedKeys()
  store.clear()
  const res = await authApi.login({ username, password })
  const token = res.data?.data?.access_token
  if (!token) throw new Error(`No access token for ${username}`)
  store.set('access_token', token)
  store.set('refresh_token', res.data?.data?.refresh_token ?? '')
}

async function listAll(): Promise<FileSummaryOut[]> {
  return unwrapData(await fileApi.listFiles({ page: 1, page_size: 100 })).items
}

describe.skipIf(!live)('the MVP, end to end', () => {
  beforeAll(() => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
        clear: () => store.clear(),
      },
    })
    if (API_BASE) http.defaults.baseURL = API_BASE
  })

  afterAll(async () => {
    // Leave the demo data as it was found.
    if (!uploadedFileId || !live) return
    try {
      await signIn(SENDER!, SENDER_PASSWORD!)
      await fileApi.delete(uploadedFileId)
    } catch {
      // Best effort; a leftover test file is untidy, not broken.
    }
  })

  it('signs the sender in', async () => {
    await signIn(SENDER!, SENDER_PASSWORD!)

    expect(store.get('access_token')).toBeTruthy()
    // The refresh token is what keeps a session alive past the access token's 30 minutes.
    expect(store.get('refresh_token')).toBeTruthy()
  })

  it('encrypts and uploads a file', async () => {
    const bytes = new TextEncoder().encode(CONTENT)
    const result = await encryptAndUpload({
      name: FILENAME,
      type: 'text/plain',
      size: bytes.length,
      arrayBuffer: async () => bytes.buffer.slice(0) as ArrayBuffer,
    })

    uploadedFileId = result.fileId
    expect(result.originalFilename).toBe(FILENAME)
    expect(result.plaintextSize).toBe(bytes.length)
    // Every upload is wrapped to the recovery key as well as the owner's.
    expect(result.recoveryKeyFingerprint).toMatch(/^[0-9a-f]{64}$/)
  })

  it('lists the file as owned by the sender', async () => {
    const mine = (await listAll()).find((file) => file.file_id === uploadedFileId)

    expect(mine).toBeDefined()
    expect(mine!.original_filename).toBe(FILENAME)
    expect(mine!.owner).toBe(true)
    expect(mine!.owner_username).toBe(SENDER)
  })

  it('gives the sender their own bytes back', async () => {
    await unlockWithPassphrase(SENDER_PASSPHRASE!)
    const file = await downloadAndDecrypt(uploadedFileId)

    expect(file.filename).toBe(FILENAME)
    expect(new TextDecoder().decode(file.bytes)).toBe(CONTENT)
    // The key is used for one download only.
    expect(isUnlocked()).toBe(false)
  })

  it('shares it with the recipient by username', async () => {
    await unlockWithPassphrase(SENDER_PASSPHRASE!)
    const outcome = await shareFileWithUsername(uploadedFileId, RECIPIENT!)

    expect(outcome.username).toBe(RECIPIENT)
  })

  it('lists the recipient as holding it', async () => {
    const users = unwrapData(await shareApi.sharedUsers(uploadedFileId)).users

    const holder = users.find((user) => user.username === RECIPIENT)
    expect(holder).toBeDefined()
    expect(holder!.can_download).toBe(true)
    // A recipient must not be able to pass it on or manage it.
    expect(holder!.can_share).toBe(false)
    expect(holder!.is_owner).toBe(false)
  })

  it('shows the recipient the file as shared, not owned', async () => {
    await signIn(RECIPIENT!, RECIPIENT_PASSWORD!)
    const theirs = (await listAll()).find((file) => file.file_id === uploadedFileId)

    expect(theirs).toBeDefined()
    expect(theirs!.owner).toBe(false)
    expect(theirs!.owner_username).toBe(SENDER)
  })

  it('lets the recipient decrypt it with their own passphrase, never the sender\'s', async () => {
    // The property the proposal promises in as many words, and the whole point of rewrapping
    // the file key rather than handing over a link.
    await unlockWithPassphrase(RECIPIENT_PASSPHRASE!)
    const file = await downloadAndDecrypt(uploadedFileId)

    expect(new TextDecoder().decode(file.bytes)).toBe(CONTENT)
  })

  it('refuses the sender\'s passphrase for the recipient\'s account key', async () => {
    forgetUnlockedKeys()

    await expect(unlockWithPassphrase(SENDER_PASSPHRASE!)).rejects.toThrow()
  })

  it('records who did what, both parties, on the file trail', async () => {
    await signIn(SENDER!, SENDER_PASSWORD!)
    const logs = unwrapData(await auditApi.listFileLogs(uploadedFileId)).logs

    const actions = logs.map((log) => log.action)
    expect(actions).toContain('FILE_UPLOADED')
    expect(actions).toContain('FILE_SHARED')
    expect(actions).toContain('FILE_DOWNLOAD_AUTHORIZED')

    // The owner sees the recipient's download, not only their own.
    const byRecipient = logs.filter((log) => log.actor_username === RECIPIENT)
    expect(byRecipient.length).toBeGreaterThan(0)
    expect(byRecipient.some((log) => log.action === 'FILE_DOWNLOAD_AUTHORIZED')).toBe(true)
    // Every row carries a name and a time; a trail that cannot say who is not a trail.
    for (const log of logs) {
      expect(log.actor_username).toBeTruthy()
      expect(log.created_at).toBeTruthy()
    }
  })

  it('does not let a recipient see what other people did with the file', async () => {
    // The privacy rule. A recipient holds an ACTIVE grant, which used to be enough to read
    // the whole trail -- so one recipient could learn that other recipients existed and
    // when each of them downloaded. Entitlement is not ownership.
    await signIn(RECIPIENT!, RECIPIENT_PASSWORD!)
    const logs = unwrapData(await auditApi.listFileLogs(uploadedFileId)).logs

    expect(logs.length).toBeGreaterThan(0)
    // Every row must be something they did or something done to them. "waldo shared this
    // with you" names the sender as the actor and is theirs to read -- it is about them.
    // What must not appear is a third party's activity: another recipient's download, or
    // the owner's own upload.
    for (const log of logs) {
      const aboutThem =
        log.actor_username === RECIPIENT || log.target_username === RECIPIENT
      expect(aboutThem, `leaked: ${log.actor_username} ${log.action}`).toBe(true)
    }
    // Specifically, the owner's upload is not.
    expect(logs.some((log) => log.action === 'FILE_UPLOADED')).toBe(false)
  })

  it('shows the owner the downloads their recipients made', async () => {
    // The reported symptom on the account-wide page: zero downloads, because the filter
    // matched only rows where the caller was the actor or the target -- and a recipient's
    // download is neither.
    await signIn(SENDER!, SENDER_PASSWORD!)
    const logs = unwrapData(await auditApi.listLogs()).logs

    const recipientDownloads = logs.filter(
      (log) => log.actor_username === RECIPIENT && log.action === 'FILE_DOWNLOAD_AUTHORIZED',
    )
    expect(recipientDownloads.length).toBeGreaterThan(0)
  })

  it('revokes the recipient', async () => {
    const res = await shareApi.revokeAccess(uploadedFileId, {
      target_user_id: unwrapData(await shareApi.sharedUsers(uploadedFileId)).users.find(
        (user) => user.username === RECIPIENT,
      )!.user_id,
    })

    expect(unwrapData(res).revoked).toBe(true)
  })

  it('takes the file off the recipient entirely', async () => {
    await signIn(RECIPIENT!, RECIPIENT_PASSWORD!)

    const theirs = (await listAll()).find((file) => file.file_id === uploadedFileId)
    expect(theirs).toBeUndefined()

    // And a direct request is refused -- as a uniform not-found, deliberately, so it cannot
    // be used to probe whether a file exists.
    await expect(fileApi.getFile(uploadedFileId)).rejects.toMatchObject({
      response: { status: 404 },
    })
  })

  it('leaves the owner\'s own access untouched', async () => {
    await signIn(SENDER!, SENDER_PASSWORD!)
    forgetUnlockedKeys()
    await unlockWithPassphrase(SENDER_PASSPHRASE!)

    const file = await downloadAndDecrypt(uploadedFileId)
    expect(new TextDecoder().decode(file.bytes)).toBe(CONTENT)
  })
})
