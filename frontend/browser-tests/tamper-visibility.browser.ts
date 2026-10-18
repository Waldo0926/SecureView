/**
 * Real-browser acceptance for the user-visible tamper path.
 *
 * This test runs only through backend/tests/e2e/run_live_stack.sh. The stack gives the
 * browser suite a throwaway mailbox under a mktemp work directory; the ciphertext object
 * root is its sibling. The guard below refuses any other layout before this test writes a
 * byte, so this can never become a staging/production mutation helper by accident.
 */
import { randomBytes, randomUUID } from 'node:crypto'
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { basename, join, resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { takeVerificationCode } from './mailbox'

interface Account {
  username: string
  email: string
  password: string
  passphrase: string
}

interface FileListEnvelope {
  data: {
    items: Array<{
      file_id: string
      original_filename: string
      owner: boolean
    }>
  }
}

interface ApiFailureEnvelope {
  data?: {
    error_code?: string
  }
}

function newAccount(): Account {
  const run = randomUUID().slice(0, 8)
  return {
    username: `pw-tamper-${run}`,
    email: `pw-tamper-${run}@example.com`,
    password: `Throwaway!${randomUUID()}`,
    passphrase: `throwaway tamper passphrase ${randomUUID()}`,
  }
}

function disposableObjectRoot(): string {
  const mailbox = process.env.E2E_MAILBOX_DIR
  if (!mailbox) throw new Error('E2E_MAILBOX_DIR is required')

  const mailboxDir = resolve(mailbox)
  const workDir = resolve(mailboxDir, '..')
  if (basename(mailboxDir) !== 'mailbox' || !basename(workDir).startsWith('mcs21-e2e.')) {
    throw new Error(
      'Refusing ciphertext mutation outside the disposable mcs21-e2e.* live-stack directory',
    )
  }
  return join(workDir, 'objects')
}

async function register(page: Page, account: Account) {
  await page.goto('/register')
  await page.getByRole('textbox', { name: /^Username/ }).fill(account.username)
  await page.getByRole('textbox', { name: /^Password/ }).fill(account.password)
  await page.getByRole('textbox', { name: /^Confirm Password/ }).fill(account.password)
  await page.getByRole('textbox', { name: /^Email Address/ }).fill(account.email)

  await page.getByRole('button', { name: 'Send code' }).click()
  await expect(page.getByText('a code is on its way')).toBeVisible()
  let code: string | undefined
  await expect
    .poll(() => (code = takeVerificationCode(account.email)), {
      message: `a verification email for ${account.email}`,
    })
    .toBeTruthy()
  await page.getByRole('textbox', { name: /^Verification Code/ }).fill(code!)

  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('textbox', { name: /^Encryption Passphrase/ }).fill(account.passphrase)
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByRole('heading', { name: 'Save Your Private Key' })).toBeVisible({
    timeout: 60_000,
  })
  await page.getByRole('checkbox', { name: /I have saved this private key/ }).check()
  await page.getByRole('link', { name: 'Continue to your workspace' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  // Start the rest of the flow from a fresh sign-in, as before registration signed in.
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible()
}

async function signIn(page: Page, account: Account) {
  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Username' }).fill(account.username)
  await page.getByRole('textbox', { name: /^Password/ }).fill(account.password)
  await page.getByRole('button', { name: 'Login' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
}

async function unlockForDownload(page: Page, account: Account) {
  const unlock = page.getByRole('heading', { name: 'Unlock your files' })
  await expect(unlock).toBeVisible()
  await page.getByRole('textbox', { name: /^Encryption passphrase/ }).fill(account.passphrase)
  await page.getByRole('button', { name: 'Unlock', exact: true }).click()
  await expect(unlock).toBeHidden({ timeout: 60_000 })
}

const account = newAccount()
const fileName = `pw-tamper-${randomUUID().slice(0, 8)}.bin`
const fileBytes = Buffer.concat([
  Buffer.from(Array.from({ length: 256 }, (_, i) => i)),
  randomBytes(4096),
])

test('ciphertext tampering is visible, blocks download, persists, and heals after restore', async ({
  page,
}) => {
  await test.step('register and sign in with a throwaway account', async () => {
    await register(page, account)
    await signIn(page, account)
  })

  let fileId = ''
  let objectPath = ''
  let originalCiphertext = Buffer.alloc(0)

  await test.step('upload a synthetic file and prove the initial UI state is Verified', async () => {
    await page.getByRole('link', { name: /^Upload & Encrypt/ }).click()
    await page.getByLabel('Select Files').setInputFiles({
      name: fileName,
      mimeType: 'application/octet-stream',
      buffer: fileBytes,
    })
    await page.getByRole('button', { name: 'Start Encryption' }).click()
    await expect(page.getByTestId('encryption-complete')).toBeVisible({
      timeout: 60_000,
    })

    const fileListResponse = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return (
        response.request().method() === 'GET' &&
        url.pathname.endsWith('/api/v1/files') &&
        response.ok()
      )
    })
    await page.getByRole('button', { name: 'View Encrypted Files' }).click()
    const envelope = (await (await fileListResponse).json()) as FileListEnvelope
    const record = envelope.data.items.find(
      (item) => item.original_filename === fileName && item.owner,
    )
    expect(record, 'the uploaded file is present in GET /files').toBeTruthy()
    fileId = record!.file_id

    const row = page.getByRole('row').filter({ hasText: fileName })
    await expect(row).toBeVisible()
    await expect(row.getByRole('button', { name: 'Verified' })).toBeVisible()

    await row.getByRole('button', { name: 'Verified' }).click()
    await expect(page.getByText('Integrity check: VALID')).toBeVisible()
    await expect(row.getByRole('button', { name: 'Verified' })).toBeVisible()
  })

  await test.step('flip one byte only in this run\'s disposable ciphertext object', async () => {
    const objectDir = join(disposableObjectRoot(), fileId)
    const objectNames = (await readdir(objectDir)).filter((name) => name.endsWith('.ciphertext'))
    expect(objectNames, 'one opaque ciphertext object exists for the uploaded file').toHaveLength(1)
    objectPath = join(objectDir, objectNames[0]!)

    originalCiphertext = await readFile(objectPath)
    expect(originalCiphertext.length).toBeGreaterThan(0)
    const tampered = Buffer.from(originalCiphertext)
    tampered[Math.floor(tampered.length / 2)]! ^= 0x01
    await writeFile(objectPath, tampered)
  })

  await test.step('the integrity control changes the row from Verified to Modified', async () => {
    const row = page.getByRole('row').filter({ hasText: fileName })
    await row.getByRole('button', { name: 'Verified' }).click()
    await expect(page.getByText('Integrity check: MODIFIED')).toBeVisible()
    await expect(row.getByRole('button', { name: 'Modified' })).toBeVisible()
  })

  await test.step('download-and-decrypt is refused and no file is handed to the browser', async () => {
    const row = page.getByRole('row').filter({ hasText: fileName })
    let downloadStarted = false
    const markDownload = () => {
      downloadStarted = true
    }
    page.on('download', markDownload)

    const refusedResponse = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return (
        response.request().method() === 'POST' &&
        url.pathname.endsWith(`/api/v1/files/${fileId}/download`)
      )
    })
    await row.getByRole('button', { name: 'Download and decrypt' }).click()
    await unlockForDownload(page, account)
    const response = await refusedResponse
    expect(response.status(), 'the server refuses a download after MODIFIED is persisted').toBe(409)
    const failure = (await response.json()) as ApiFailureEnvelope
    expect(failure.data?.error_code).toBe('integrity_verification_failed')
    await expect(row.getByRole('button', { name: 'Modified' })).toBeVisible()
    expect(downloadStarted, 'a modified ciphertext never starts a browser download').toBe(false)
    page.off('download', markDownload)
  })

  await test.step('a reload still renders the durable CORRUPTED state as Modified', async () => {
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Manage Encrypted Files' })).toBeVisible()
    const row = page.getByRole('row').filter({ hasText: fileName })
    await expect(row.getByRole('button', { name: 'Modified' })).toBeVisible()
  })

  await test.step('restoring the original ciphertext heals the row back to Verified', async () => {
    await writeFile(objectPath, originalCiphertext)
    const row = page.getByRole('row').filter({ hasText: fileName })
    await row.getByRole('button', { name: 'Modified' }).click()
    await expect(page.getByText('Integrity check: VALID')).toBeVisible()
    await expect(row.getByRole('button', { name: 'Verified' })).toBeVisible()
  })

  await test.step('the restored file decrypts to the exact original bytes', async () => {
    const row = page.getByRole('row').filter({ hasText: fileName })
    const download = page.waitForEvent('download', { timeout: 60_000 })
    await row.getByRole('button', { name: 'Download and decrypt' }).click()
    await unlockForDownload(page, account)
    const saved = await download
    expect(saved.suggestedFilename()).toBe(fileName)
    expect((await readFile(await saved.path())).equals(fileBytes)).toBe(true)
  })
})
