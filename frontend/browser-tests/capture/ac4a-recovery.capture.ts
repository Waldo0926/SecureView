/**
 * Screenshots for the AC4a slide: a tampered file before and after recovery.
 *
 * Not a test of anything new (tamper-visibility.browser.ts already asserts every step) and not
 * part of CI. It runs only through `E2E_BROWSER=capture bash backend/tests/e2e/run_live_stack.sh`
 * with E2E_CAPTURE_DIR set, uses its own config (playwright.capture.config.ts), and writes PNGs
 * for docs/presentation/screenshots/. The byte flip uses the same disposable-directory guard as
 * the tamper test, so it can never touch staging.
 *
 * The restore here writes the original bytes back, which is exactly what
 * `demo_tamper.py restore` does from its backup copy on the VPS.
 */
import { randomUUID } from 'node:crypto'
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { basename, join, resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { takeVerificationCode } from '../mailbox'

const OUT = process.env.E2E_CAPTURE_DIR
const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? '',
  password: process.env.E2E_ADMIN_PASSWORD ?? '',
}
if (!OUT || !ADMIN.username || !ADMIN.password) {
  throw new Error('Run through run_live_stack.sh with E2E_BROWSER=capture and E2E_CAPTURE_DIR')
}

const run = randomUUID().slice(0, 4)
const alice = {
  username: `demo-alice-${run}`,
  email: `demo-alice-${run}@example.com`,
  password: `Throwaway!${randomUUID()}`,
  passphrase: `capture passphrase ${randomUUID()}`,
}
const fileName = 'quarterly-results.txt'
const fileBytes = Buffer.from(
  'Quarterly results (demo)\n\nRevenue: 1.2M\nCosts: 0.9M\nNot for circulation.\n'.repeat(20),
)

function disposableObjectRoot(): string {
  const mailboxDir = resolve(process.env.E2E_MAILBOX_DIR ?? '')
  const workDir = resolve(mailboxDir, '..')
  if (basename(mailboxDir) !== 'mailbox' || !basename(workDir).startsWith('mcs21-e2e.')) {
    throw new Error('Refusing ciphertext mutation outside the disposable mcs21-e2e.* directory')
  }
  return join(workDir, 'objects')
}

async function shot(page: Page, name: string) {
  // Let drawers and badges finish their transitions so the picture is the settled screen.
  await page.waitForTimeout(800)
  // Nothing on these pages is secret (throwaway account, no key material shown), but the
  // password fields are masked anyway in case a dialog is still open.
  await page.screenshot({ path: join(OUT!, name), mask: [page.locator('input[type="password"]')] })
}

async function register(page: Page) {
  await page.goto('/register')
  await page.getByRole('textbox', { name: /^Username/ }).fill(alice.username)
  await page.getByRole('textbox', { name: /^Password/ }).fill(alice.password)
  await page.getByRole('textbox', { name: /^Confirm Password/ }).fill(alice.password)
  await page.getByRole('textbox', { name: /^Email Address/ }).fill(alice.email)
  await page.getByRole('button', { name: 'Send code' }).click()
  let code: string | undefined
  await expect.poll(() => (code = takeVerificationCode(alice.email))).toBeTruthy()
  await page.getByRole('textbox', { name: /^Verification Code/ }).fill(code!)
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('textbox', { name: /^Encryption Passphrase/ }).fill(alice.passphrase)
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByRole('heading', { name: 'Save Your Private Key' })).toBeVisible({
    timeout: 60_000,
  })
  await page.getByRole('checkbox', { name: /I have saved this private key/ }).check()
  await page.getByRole('link', { name: 'Continue to your workspace' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
}

async function signIn(page: Page, who: { username: string; password: string }) {
  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Username' }).fill(who.username)
  await page.getByRole('textbox', { name: /^Password/ }).fill(who.password)
  await page.getByRole('button', { name: 'Login' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
}

async function openAdminTab(page: Page, tab: 'integrity' | 'agent') {
  await page.goto('/admin')
  await page.getByTestId(`admin-tab-${tab}`).click()
  await expect(page.getByTestId(`admin-tab-${tab}`)).toHaveAttribute('aria-selected', 'true')
}

test.use({ viewport: { width: 1440, height: 900 } })

test('AC4a screenshots: Modified, refused, admin view, restored', async ({ page, browser }) => {
  await register(page)

  await page.getByRole('link', { name: /^Upload & Encrypt/ }).click()
  await page.getByLabel('Select Files').setInputFiles({
    name: fileName,
    mimeType: 'text/plain',
    buffer: fileBytes,
  })
  await page.getByRole('button', { name: 'Start Encryption' }).click()
  await expect(page.getByTestId('encryption-complete')).toBeVisible({
    timeout: 60_000,
  })
  const listed = page.waitForResponse(
    (r) => r.request().method() === 'GET' && new URL(r.url()).pathname.endsWith('/api/v1/files'),
  )
  await page.getByRole('button', { name: 'View Encrypted Files' }).click()
  const items = ((await (await listed).json()) as { data: { items: Array<{ file_id: string; original_filename: string }> } }).data.items
  const fileId = items.find((item) => item.original_filename === fileName)!.file_id
  const row = page.getByRole('row').filter({ hasText: fileName })
  await expect(row.getByRole('button', { name: 'Verified' })).toBeVisible()
  await shot(page, 'ac4a-0-before-verified.png')

  // What `demo_tamper.py flip` does on the VPS: one byte of the stored ciphertext changes.
  const objectDir = join(disposableObjectRoot(), fileId)
  const objectPath = join(objectDir, (await readdir(objectDir)).find((n) => n.endsWith('.ciphertext'))!)
  const original = await readFile(objectPath)
  const tampered = Buffer.from(original)
  tampered[Math.floor(tampered.length / 2)]! ^= 0x01
  await writeFile(objectPath, tampered)

  await row.getByRole('button', { name: 'Verified' }).click()
  await expect(page.getByText('Integrity check: MODIFIED')).toBeVisible()
  await expect(row.getByRole('button', { name: 'Modified' })).toBeVisible()
  await shot(page, 'ac4a-1-modified.png')

  await row.getByRole('button', { name: 'Download and decrypt' }).click()
  // Every decrypted download asks for the passphrase first; the server's refusal comes after it.
  const unlock = page.getByRole('heading', { name: 'Unlock your files' })
  const refused = page.getByText('was changed, so it was not sent')
  await expect(unlock.or(refused).first()).toBeVisible({ timeout: 60_000 })
  if (await unlock.isVisible()) {
    await page.getByRole('textbox', { name: /^Encryption passphrase/ }).fill(alice.passphrase)
    await page.getByRole('button', { name: 'Unlock', exact: true }).click()
  }
  await expect(refused).toBeVisible({ timeout: 60_000 })
  await shot(page, 'ac4a-2-download-refused.png')

  // The administrator's side, in a separate browser context.
  const adminContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const admin = await adminContext.newPage()
  await signIn(admin, ADMIN)
  await openAdminTab(admin, 'integrity')
  await expect(admin.getByTestId('integrity-damaged-file').filter({ hasText: fileName })).toBeVisible()
  await shot(admin, 'ac4a-3-admin-integrity-damaged.png')
  await openAdminTab(admin, 'agent')
  await admin.getByTestId('agent-run').click()
  const finding = admin.getByTestId('agent-finding').filter({ hasText: fileName })
  await expect(finding).toBeVisible({ timeout: 60_000 })
  await finding.evaluate((el) => el.scrollIntoView({ block: 'center' }))
  await shot(admin, 'ac4a-4-agent-integrity-damage.png')

  // Recovery: the original bytes go back, then one re-check turns the row Verified again.
  await writeFile(objectPath, original)
  await page.reload()
  const healed = page.getByRole('row').filter({ hasText: fileName })
  await healed.getByRole('button', { name: 'Modified' }).click()
  await expect(page.getByText('Integrity check: VALID')).toBeVisible()
  await expect(healed.getByRole('button', { name: 'Verified' })).toBeVisible()
  await shot(page, 'ac4a-5-restored-verified.png')

  await openAdminTab(admin, 'integrity')
  await expect(admin.getByTestId('integrity-clean')).toBeVisible()
  await shot(admin, 'ac4a-6-admin-integrity-clean.png')
  await adminContext.close()
})
