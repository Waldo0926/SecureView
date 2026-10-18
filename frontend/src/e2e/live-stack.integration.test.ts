/**
 * The whole account lifecycle, against a disposable backend and MySQL, from nothing.
 *
 * `crypto/mvp.integration.test.ts` needs two accounts someone seeded by hand. This suite
 * needs only an admin: it registers its own users through the emailed-code flow, so the
 * part of the product a new user meets first -- verification, enrolment, the first unlock
 * -- is exercised for real rather than bypassed by a seeding script.
 *
 * It drives the same modules the pages call, over HTTP, with the real client-side crypto.
 * It does not click the markup; see docs/E2E_TESTING.md for why that line is drawn here.
 *
 * Skipped unless the environment names a stack. `backend/tests/e2e/run_live_stack.sh`
 * provides one (and is what CI runs); by hand:
 *
 *   E2E_API_BASE=http://127.0.0.1:8000/api/v1 E2E_MAILBOX_DIR=/tmp/mailbox \
 *   E2E_ADMIN_USERNAME=e2e-admin E2E_ADMIN_PASSWORD='...' \
 *   npx vitest run src/e2e/live-stack.integration.test.ts
 *
 * The backend must serve verification mail into E2E_MAILBOX_DIR
 * (`backend/tests/e2e/live_server.py serve`) and should run with
 * AUTH_REFRESH_MIN_INTERVAL_SECONDS=1, or the refresh tests wait the default ten seconds.
 *
 * Every identity here is minted per run under example.com and every password is random.
 * Nothing the suite prints or asserts on contains a token, key, or file content.
 */

import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import axios, { type AxiosInstance } from 'axios'
import { beforeAll, describe, expect, it } from 'vitest'

import { auditApi } from '@/api/audit_api'
import { authApi } from '@/api/auth_api'
import { fileApi } from '@/api/file_api'
import { http } from '@/api/http'
import { shareApi } from '@/api/share_api'
import { unwrapData, type FileOut } from '@/api/types'
import { enrolAccountKey, type ClientKeyMaterial } from '@/utils/account-crypto'

import {
  downloadAndDecrypt,
  forgetUnlockedKeys,
  isUnlocked,
  unlockWithPassphrase,
} from '@/crypto/download'
import { ENCRYPTION_ALGORITHMS, type EncryptionAlgorithm } from '@/crypto/primitives'
import { shareFileWithRecipient } from '@/crypto/share'
import { encryptAndUpload } from '@/crypto/upload'

const API_BASE = process.env.E2E_API_BASE
const MAILBOX = process.env.E2E_MAILBOX_DIR
const ADMIN = process.env.E2E_ADMIN_USERNAME
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD
const REFRESH_INTERVAL_SECONDS = Number(process.env.E2E_REFRESH_MIN_INTERVAL_SECONDS ?? '1')

const live = Boolean(API_BASE && MAILBOX && ADMIN && ADMIN_PASSWORD)

interface Account {
  username: string
  email: string
  password: string
  passphrase: string
}

function newAccount(role: string): Account {
  const run = crypto.randomUUID().slice(0, 8)
  return {
    username: `e2e-${role}-${run}`,
    email: `e2e-${role}-${run}@example.com`,
    // Random per run, never logged. Upper, lower, digits and a symbol satisfy the policy,
    // and a UUID cannot contain the username.
    password: `Pw!${crypto.randomUUID()}`,
    passphrase: `${role} passphrase ${crypto.randomUUID()}`,
  }
}

const alice = newAccount('alice')
const bob = newAccount('bob')

/** The axios instance reads its token from localStorage, which node does not provide. */
const store = new Map<string, string>()

/**
 * A client with no interceptors and no opinion about status codes, for the assertions
 * that are about a specific token. The shared `http` instance would quietly refresh a 401
 * and retry, which is exactly the behaviour some of these tests need to see past.
 */
let raw: AxiosInstance

function bearer(token: string) {
  return { headers: { Authorization: `Bearer ${token}` } }
}

async function signIn(account: { username: string; password: string }) {
  forgetUnlockedKeys()
  store.clear()
  const res = await authApi.login({ username: account.username, password: account.password })
  const tokens = res.data.data as { access_token: string; refresh_token: string }
  store.set('access_token', tokens.access_token)
  store.set('refresh_token', tokens.refresh_token)
  return tokens
}

const readMessages = new Set<string>()

/** The newest unread verification code sent to `email`, polled for briefly. */
async function readVerificationCode(email: string): Promise<string> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const names = readdirSync(MAILBOX!)
      .filter((name) => name.endsWith('.json') && !readMessages.has(name))
      .sort()
      .reverse()
    for (const name of names) {
      const message = JSON.parse(readFileSync(join(MAILBOX!, name), 'utf8')) as {
        to: string
        text: string
      }
      if (message.to !== email) continue
      const match = /Verification code: (\d+)/.exec(message.text)
      if (!match) continue
      readMessages.add(name)
      return match[1]!
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`No verification email arrived for ${email}`)
}

async function register(account: Account, keyMaterial: ClientKeyMaterial) {
  await authApi.sendVerificationCode({ email: account.email, purpose: 'REGISTRATION' })
  const code = await readVerificationCode(account.email)
  return authApi.register({
    username: account.username,
    email: account.email,
    password: account.password,
    verification_code: code,
    key_material: keyMaterial,
  })
}

async function listMine() {
  return unwrapData(await fileApi.listFiles({ page: 1, page_size: 100 })).items
}

/** Only what the login route takes. The passphrase never goes to the server. */
function credentials(account: Account) {
  return { username: account.username, password: account.password }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

describe.skipIf(!live)('the product against a disposable stack', () => {
  const uploaded = new Map<EncryptionAlgorithm, { fileId: string; bytes: Uint8Array }>()

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
    http.defaults.baseURL = API_BASE
    raw = axios.create({ baseURL: API_BASE, validateStatus: () => true })
  })

  describe('registration and email verification', () => {
    let aliceKeys: ClientKeyMaterial
    let aliceCode: string

    it('refuses a registration with the wrong code', async () => {
      aliceKeys = (await enrolAccountKey(alice.passphrase)).keyMaterial
      await authApi.sendVerificationCode({ email: alice.email, purpose: 'REGISTRATION' })
      aliceCode = await readVerificationCode(alice.email)
      const wrong = aliceCode === '000000' ? '111111' : '000000'

      const res = await raw.post('/auth/register', {
        username: alice.username,
        email: alice.email,
        password: alice.password,
        verification_code: wrong,
        key_material: aliceKeys,
      })

      expect(res.status).toBeGreaterThanOrEqual(400)
      expect(res.status).toBeLessThan(500)
      // Nothing was created: the username is still free to log in as nobody.
      expect((await raw.post('/auth/login', credentials(alice))).status).toBe(401)
    })

    it('registers with the code that was emailed', async () => {
      // One wrong guess spends an attempt but does not burn the code.
      const res = await authApi.register({
        username: alice.username,
        email: alice.email,
        password: alice.password,
        verification_code: aliceCode,
        key_material: aliceKeys,
      })

      const data = unwrapData(res)
      expect(data.user.username).toBe(alice.username)
      expect(data.user.email_verified).toBe(true)
      expect(data.key_id).toBe(aliceKeys.key_id)
    })

    it('registers a second, independent account', async () => {
      const bobKeys = (await enrolAccountKey(bob.passphrase)).keyMaterial
      const data = unwrapData(await register(bob, bobKeys))

      expect(data.user.username).toBe(bob.username)
    })

    it('will not register the same username twice', async () => {
      const again = newAccount('dup')
      const keys = (await enrolAccountKey(again.passphrase)).keyMaterial
      await authApi.sendVerificationCode({ email: again.email, purpose: 'REGISTRATION' })
      const code = await readVerificationCode(again.email)

      const res = await raw.post('/auth/register', {
        username: alice.username,
        email: again.email,
        password: again.password,
        verification_code: code,
        key_material: keys,
      })

      expect(res.status).toBe(409)
    })
  })

  describe('sessions: login, refresh, replay, logout', () => {
    it('signs in with both tokens and reads the account back', async () => {
      const tokens = await signIn(alice)
      expect(tokens.access_token).toBeTruthy()
      expect(tokens.refresh_token).toBeTruthy()

      const me = unwrapData(await authApi.me())
      expect(me.user.username).toBe(alice.username)
    })

    it('refuses the wrong password without revealing whether the account exists', async () => {
      const wrongPassword = await raw.post('/auth/login', {
        username: alice.username,
        password: 'Wrong!pass1',
      })
      const noAccount = await raw.post('/auth/login', credentials(newAccount('ghost')))

      expect(wrongPassword.status).toBe(401)
      expect(noAccount.status).toBe(401)
      expect(wrongPassword.data?.data?.error_code).toBe(noAccount.data?.data?.error_code)
    })

    it('rotates on refresh, retires the old access token, and detects a replay', async () => {
      const first = await signIn(alice)
      await sleep((REFRESH_INTERVAL_SECONDS + 1) * 1000)

      const rotated = await raw.post('/auth/refresh', { refresh_token: first.refresh_token })
      expect(rotated.status).toBe(200)
      const second = rotated.data.data as { access_token: string; refresh_token: string }
      expect(second.refresh_token).not.toBe(first.refresh_token)
      expect((await raw.get('/auth/me', bearer(second.access_token))).status).toBe(200)
      expect((await raw.get('/auth/me', bearer(first.access_token))).status).toBe(401)

      // Presenting the consumed token again is what a stolen copy looks like. The server
      // cannot tell which holder is legitimate, so it ends the whole session family --
      // including the tokens the rightful holder just received.
      const replay = await raw.post('/auth/refresh', { refresh_token: first.refresh_token })
      expect(replay.status).toBe(401)
      expect((await raw.get('/auth/me', bearer(second.access_token))).status).toBe(401)
      expect(
        (await raw.post('/auth/refresh', { refresh_token: second.refresh_token })).status,
      ).toBe(401)
    })

    it('logs out: the access token and its refresh token both stop working', async () => {
      const tokens = await signIn(alice)

      expect((await raw.post('/auth/logout', null, bearer(tokens.access_token))).status).toBe(200)

      expect((await raw.get('/auth/me', bearer(tokens.access_token))).status).toBe(401)
      expect((await raw.post('/auth/refresh', { refresh_token: tokens.refresh_token })).status).toBe(
        401,
      )
    })
  })

  describe('unlocking the account key', () => {
    it('refuses the wrong passphrase and accepts the right one', async () => {
      await signIn(alice)

      await expect(unlockWithPassphrase(bob.passphrase)).rejects.toThrow()
      expect(isUnlocked()).toBe(false)

      await unlockWithPassphrase(alice.passphrase)
      expect(isUnlocked()).toBe(true)
    })
  })

  describe('every supported file algorithm', () => {
    it('offers exactly the six AEAD suites the schema accepts', () => {
      // Migration 0006 widens the CHECK constraint to exactly these names.
      expect([...ENCRYPTION_ALGORITHMS].sort()).toEqual(
        [
          'AES-128-GCM',
          'AES-192-GCM',
          'AES-256-GCM',
          'AES-256-GCM-SIV',
          'ChaCha20-Poly1305',
          'XChaCha20-Poly1305',
        ].sort(),
      )
    })

    for (const algorithm of ENCRYPTION_ALGORITHMS) {
      it(`uploads, stores only ciphertext, and round-trips under ${algorithm}`, async () => {
        // Synthetic bytes, including every byte value, so a text-only path cannot pass.
        const bytes = new Uint8Array(4096 + 17)
        crypto.getRandomValues(bytes)
        for (let i = 0; i < 256; i += 1) bytes[i] = i
        const name = `e2e-${algorithm.toLowerCase()}.bin`

        const result = await encryptAndUpload(
          {
            name,
            type: 'application/octet-stream',
            size: bytes.length,
            arrayBuffer: async () => bytes.slice().buffer as ArrayBuffer,
          },
          undefined,
          algorithm,
        )
        uploaded.set(algorithm, { fileId: result.fileId, bytes })
        expect(result.encryptionAlgorithm).toBe(algorithm)

        const stored = unwrapData(await fileApi.getFile(result.fileId)) as FileOut
        expect(stored.encryption_algorithm).toBe(algorithm)
        expect(stored.crypto_envelope.encryption_algorithm).toBe(algorithm)

        // What the server hands back is ciphertext: same length (the tag travels
        // separately) and not the plaintext.
        const served = new Uint8Array((await fileApi.download(result.fileId)).data as ArrayBuffer)
        expect(served.length).toBe(bytes.length)
        expect(Buffer.from(served).equals(Buffer.from(bytes))).toBe(false)

        // Every decrypted download needs the passphrase again, and the key is dropped after it.
        await unlockWithPassphrase(alice.passphrase)
        const opened = await downloadAndDecrypt(result.fileId)
        expect(opened.filename).toBe(name)
        expect(Buffer.from(opened.bytes).equals(Buffer.from(bytes))).toBe(true)
        expect(isUnlocked()).toBe(false)
      })
    }

    it('lists every upload as owned by the uploader', async () => {
      const mine = await listMine()
      for (const { fileId } of uploaded.values()) {
        const row = mine.find((file) => file.file_id === fileId)
        expect(row?.owner).toBe(true)
        expect(row?.owner_username).toBe(alice.username)
      }
    })
  })

  describe('sharing and revocation', () => {
    // Once per suite, not once: sharing rewraps the DEK and the recipient opens the file
    // under the suite named in the stored envelope, so a suite whose key length or library
    // path differs from the default (AES-192 on Chromium, the three library suites) has to
    // be shown to survive the whole hand-off, not only its own upload.
    for (const algorithm of ENCRYPTION_ALGORITHMS) {
      describe(`a file sealed under ${algorithm}`, () => {
        const shared = () => uploaded.get(algorithm)!

        it('is shared with another account by username', async () => {
          await signIn(alice)
          await unlockWithPassphrase(alice.passphrase)

          const outcome = await shareFileWithRecipient(shared().fileId, bob.username)
          expect(outcome.created).toBe(true)
          expect(isUnlocked()).toBe(false)
        })

        it('appears in the recipient\'s list, decrypts with their passphrase, and is intact on the server', async () => {
          await signIn(bob)
          const row = (await listMine()).find((file) => file.file_id === shared().fileId)
          expect(row?.owner).toBe(false)
          expect(row?.owner_username).toBe(alice.username)

          await expect(unlockWithPassphrase(alice.passphrase)).rejects.toThrow()
          await unlockWithPassphrase(bob.passphrase)
          const opened = await downloadAndDecrypt(shared().fileId)
          expect(Buffer.from(opened.bytes).equals(Buffer.from(shared().bytes))).toBe(true)
          const seen = unwrapData(await fileApi.getFile(shared().fileId)) as FileOut
          expect(seen.encryption_algorithm).toBe(algorithm)

          // The server's own check: the stored ciphertext still hashes to what was recorded
          // at upload. A recipient may ask, since they can read the file.
          const check = unwrapData(await fileApi.integrityCheck(shared().fileId)) as {
            status: string
            expected_hash: string
            actual_hash: string | null
          }
          expect(check.status).toBe('VALID')
          expect(check.actual_hash).toBe(check.expected_hash)
        })

        it('cannot be passed on by a download-only recipient', async () => {
          // Bob's key was dropped after his download, so he unlocks again. The server, not the
          // client, has to refuse.
          await unlockWithPassphrase(bob.passphrase)
          await expect(shareFileWithRecipient(shared().fileId, ADMIN!)).rejects.toMatchObject({
            response: { status: 404 },
          })
        })

        it('is revoked, after which the recipient cannot see, fetch, or download it', async () => {
          await signIn(alice)
          const holder = unwrapData(await shareApi.sharedUsers(shared().fileId)).users.find(
            (user) => user.username === bob.username,
          )!
          expect(
            unwrapData(await shareApi.revokeAccess(shared().fileId, { target_user_id: holder.user_id }))
              .revoked,
          ).toBe(true)

          const bobTokens = await signIn(bob)
          expect((await listMine()).some((file) => file.file_id === shared().fileId)).toBe(false)
          const fetch = await raw.get(`/files/${shared().fileId}`, bearer(bobTokens.access_token))
          const download = await raw.post(
            `/files/${shared().fileId}/download`,
            null,
            bearer(bobTokens.access_token),
          )
          const integrity = await raw.post(
            `/files/${shared().fileId}/integrity-check`,
            null,
            bearer(bobTokens.access_token),
          )
          // A uniform not-found, so no route can be used to probe for existence.
          expect(fetch.status).toBe(404)
          expect(download.status).toBe(404)
          expect(integrity.status).toBe(404)
        })
      })
    }
  })

  describe('audit visibility', () => {
    it('shows the owner the whole trail of their file, including the recipient', async () => {
      await signIn(alice)
      const logs = unwrapData(await auditApi.listFileLogs(uploaded.get('ChaCha20-Poly1305')!.fileId)).logs
      const actions = logs.map((log) => log.action)

      for (const expected of ['FILE_UPLOADED', 'FILE_SHARED', 'FILE_ACCESS_REVOKED']) {
        expect(actions).toContain(expected)
      }
      expect(
        logs.some(
          (log) => log.actor_username === bob.username && log.action === 'FILE_DOWNLOAD_AUTHORIZED',
        ),
      ).toBe(true)
    })

    it('shows the recipient only what concerns them', async () => {
      await signIn(bob)
      const logs = unwrapData(await auditApi.listLogs({ limit: 100 })).logs

      expect(logs.length).toBeGreaterThan(0)
      for (const log of logs) {
        const aboutBob = log.actor_username === bob.username || log.target_username === bob.username
        expect(aboutBob, `leaked ${log.action} by ${log.actor_username}`).toBe(true)
      }
      expect(logs.some((log) => log.action === 'FILE_UPLOADED')).toBe(false)
    })

    it('lets the recipient filter, but never past what concerns them', async () => {
      // The owner's upload is called `e2e-chacha20-poly1305.bin` in `files`, and the keyword
      // filter reaches that name.
      // Searching for it as the recipient must find nothing of the owner's: the filter is
      // applied on top of the visibility rule, not instead of it.
      await signIn(bob)
      const filtered = unwrapData(
        await auditApi.listLogs({ limit: 100, action: 'FILE_UPLOADED', q: 'e2e-chacha20' }),
      ).logs
      expect(filtered).toEqual([])

      const downloads = unwrapData(
        await auditApi.listLogs({ limit: 100, action: 'FILE_DOWNLOAD_AUTHORIZED', result: 'SUCCESS' }),
      ).logs
      expect(downloads.length).toBeGreaterThan(0)
      for (const log of downloads) {
        expect(log.action).toBe('FILE_DOWNLOAD_AUTHORIZED')
        expect(log.actor_username).toBe(bob.username)
      }

      const unknown = await raw.get('/audit-logs?action=NOT_AN_ACTION', bearer((await signIn(bob)).access_token))
      expect(unknown.status).toBe(422)
    })
  })

  describe('role denial', () => {
    it('refuses an anonymous caller', async () => {
      expect((await raw.get('/files')).status).toBe(401)
      expect((await raw.get('/admin/users')).status).toBe(401)
    })

    it('refuses an ordinary user every administrator route', async () => {
      const tokens = await signIn(bob)
      const auth = bearer(tokens.access_token)

      expect((await raw.get('/admin/users', auth)).status).toBe(403)
      expect((await raw.get('/admin/files', auth)).status).toBe(403)
      expect((await raw.post('/audit-logs/verify-chain', null, auth)).status).toBe(403)
      expect(
        (
          await raw.post(
            '/recovery/public-key/register',
            {
              key_id: crypto.randomUUID(),
              public_key_pem: '-----BEGIN PUBLIC KEY-----\n-----END PUBLIC KEY-----\n',
              algorithm: 'RSA-OAEP-SHA256',
            },
            auth,
          )
        ).status,
      ).toBe(403)
    })

    it('lets the administrator in, and the audit chain verifies end to end', async () => {
      const tokens = await signIn({ username: ADMIN!, password: ADMIN_PASSWORD! })
      const auth = bearer(tokens.access_token)

      expect((await raw.get('/admin/users', auth)).status).toBe(200)
      const verified = await raw.post('/audit-logs/verify-chain', null, auth)
      expect(verified.status).toBe(200)
      expect(verified.data.data.valid).toBe(true)
    })
  })

  describe('security agent', () => {
    it('refuses an ordinary user', async () => {
      const tokens = await signIn(bob)
      expect((await raw.get('/admin/agent/report', bearer(tokens.access_token))).status).toBe(403)
    })

    it('turns real failed sign-ins into one ranked finding with evidence and an action', async () => {
      // A name that has no account: the attempts are recorded against the address only, and
      // the throttle that answers 429 after ten blocks nothing the rest of this suite uses.
      const nobody = `e2e-nobody-${crypto.randomUUID().slice(0, 8)}`
      for (let attempt = 0; attempt < 10; attempt += 1) {
        const res = await raw.post('/auth/login', { username: nobody, password: `wrong-${attempt}` })
        expect(res.status).toBe(401)
      }

      const tokens = await signIn({ username: ADMIN!, password: ADMIN_PASSWORD! })
      const res = await raw.get('/admin/agent/report?window_hours=24', bearer(tokens.access_token))
      expect(res.status).toBe(200)
      const report = res.data.data

      expect(report.rules).toHaveLength(13)
      expect(report.boundaries.length).toBeGreaterThan(0)
      expect(report.inputs.audit_events_read).toBeGreaterThanOrEqual(10)
      const guessing = report.findings.find(
        (f: { rule_id: string }) => f.rule_id === 'LOGIN_GUESSING_SOURCE',
      )
      expect(guessing).toBeDefined()
      expect(['MEDIUM', 'HIGH']).toContain(guessing.priority)
      expect(guessing.evidence.join(' ')).toMatch(/attempts? at names with no account/)
      expect(guessing.recommended_action).toMatch(/fail2ban/)
      // Ranked: nothing after a finding is more urgent than it.
      const order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
      const ranks = report.findings.map((f: { priority: string }) => order.indexOf(f.priority))
      expect(ranks).toEqual([...ranks].sort((a: number, b: number) => a - b))
    })

    it('reports a real sign-in that succeeded right after five wrong passwords', async () => {
      // A fresh throwaway account. Five failures stay well under the account throttle's ten,
      // and add only five to this address's fifty for the whole suite.
      const target = newAccount('takeover')
      const keys = (await enrolAccountKey(target.passphrase)).keyMaterial
      unwrapData(await register(target, keys))
      for (let attempt = 0; attempt < 5; attempt += 1) {
        const res = await raw.post('/auth/login', {
          username: target.username,
          password: `Wrong!${attempt}-${crypto.randomUUID()}`,
        })
        expect(res.status).toBe(401)
      }
      expect((await raw.post('/auth/login', credentials(target))).status).toBe(200)

      const tokens = await signIn({ username: ADMIN!, password: ADMIN_PASSWORD! })
      const res = await raw.get('/admin/agent/report?window_hours=24', bearer(tokens.access_token))
      expect(res.status).toBe(200)
      const takeovers = res.data.data.findings.filter(
        (f: { rule_id: string; title: string }) =>
          f.rule_id === 'SIGN_IN_AFTER_GUESSING' && f.title.startsWith(`${target.username} `),
      )

      expect(takeovers).toHaveLength(1)
      const [finding] = takeovers
      expect(finding.priority).toBe('HIGH')
      expect(finding.evidence.join(' ')).toMatch(/5 against this account/)
      expect(finding.recommended_action).toMatch(/disable the account on the Users tab/)
    })
  })

  describe('account deletion', () => {
    it('refuses a deletion without the right password, and the account survives', async () => {
      const tokens = await signIn(bob)
      const res = await raw.post(
        '/auth/delete-account',
        { password: 'Not-the-password1', confirmation: 'DELETE' },
        bearer(tokens.access_token),
      )

      expect(res.status).toBeGreaterThanOrEqual(400)
      expect((await raw.get('/auth/me', bearer(tokens.access_token))).status).toBe(200)
    })

    it('closes the recipient\'s account: its sessions end and it cannot sign in', async () => {
      const tokens = await signIn(bob)
      const res = await raw.post(
        '/auth/delete-account',
        { password: bob.password, confirmation: 'DELETE' },
        bearer(tokens.access_token),
      )

      expect(res.status).toBe(200)
      expect((await raw.get('/auth/me', bearer(tokens.access_token))).status).toBe(401)
      expect((await raw.post('/auth/login', credentials(bob))).status).toBe(401)
    })

    it('closes the owner\'s account and destroys every file it owned', async () => {
      const tokens = await signIn(alice)
      const res = await raw.post(
        '/auth/delete-account',
        { password: alice.password, confirmation: 'DELETE' },
        bearer(tokens.access_token),
      )

      expect(res.status).toBe(200)
      expect(res.data.data.files_deleted).toBe(ENCRYPTION_ALGORITHMS.length)
    })

    it('leaves an audit chain that still verifies after both deletions', async () => {
      const tokens = await signIn({ username: ADMIN!, password: ADMIN_PASSWORD! })
      const verified = await raw.post('/audit-logs/verify-chain', null, bearer(tokens.access_token))

      expect(verified.data.data.valid).toBe(true)
    })
  })
})
