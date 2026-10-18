/**
 * The golden path in a real browser: register, verify, sign in, unlock, upload, download,
 * share, revoke, sign out -- by clicking the built pages, against the disposable stack.
 *
 * The Node live suites (`src/e2e`, `src/crypto/*.integration.test.ts`) already prove the
 * crypto and the API contract. What only a browser can prove is that the buttons are wired
 * to that logic: a Share button whose handler does nothing passes every Node suite and
 * fails here.
 *
 * Every identity, password, passphrase and file byte is minted per run and obviously fake:
 * `@example.com` addresses, "Throwaway" passwords, a generated file. The accounts live in
 * a database that is destroyed with the stack.
 */
import { randomBytes, randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'

import { expect, test, type Browser, type Page, type Request } from '@playwright/test'

import { takeVerificationCode } from './mailbox'

interface Account {
  username: string
  email: string
  password: string
  passphrase: string
}

function newAccount(role: string): Account {
  const run = randomUUID().slice(0, 8)
  return {
    username: `pw-${role}-${run}`,
    email: `pw-${role}-${run}@example.com`,
    password: `Throwaway!${randomUUID()}`,
    passphrase: `throwaway ${role} passphrase ${randomUUID()}`,
  }
}

const alice = newAccount('alice')
const bob = newAccount('bob')

// Every byte value, then random bytes: a text-only path cannot pass, and there is no
// meaningful content to leak. The test compares bytes and never prints them.
const fileName = `pw-smoke-${randomUUID().slice(0, 8)}.bin`
const fileBytes = Buffer.concat([
  Buffer.from(Array.from({ length: 256 }, (_, i) => i)),
  randomBytes(4096),
])

const pages: Page[] = []

async function openPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  pages.push(page)
  return page
}

test.afterEach(async ({}, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    // Taken here rather than by the runner so the one-time private key the register page
    // shows is masked out of anything that could be published.
    for (const [index, page] of pages.entries()) {
      if (page.isClosed()) continue
      await testInfo.attach(`page-${index + 1}-at-failure`, {
        body: await page.screenshot({ fullPage: true, mask: [page.locator('textarea')] }),
        contentType: 'image/png',
      })
    }
  }
  for (const page of pages.splice(0)) await page.context().close()
})

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
  // Key generation and Argon2id run in the page before the request is even sent.
  await expect(page.getByRole('heading', { name: 'Save Your Private Key' })).toBeVisible({
    timeout: 60_000,
  })
  await page.getByRole('checkbox', { name: /I have saved this private key/ }).check()
  // Registering signs the new account straight in.
  await page.getByRole('link', { name: 'Continue to your workspace' }).click()
  await expect(page.getByRole('heading', { name: 'Your Workspace' })).toBeVisible()
  await signOut(page)
  await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible()
}

async function signIn(page: Page, account: Account) {
  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Username' }).fill(account.username)
  await page.getByRole('textbox', { name: /^Password/ }).fill(account.password)
  await page.getByRole('button', { name: 'Login' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByRole('heading', { name: 'Your Workspace' })).toBeVisible()
}

async function openMyFiles(page: Page) {
  await page.getByRole('navigation').getByRole('link', { name: 'My Files', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Manage Encrypted Files' })).toBeVisible()
}

/** Download-and-decrypt a row, unlocking the account key on the way, and return the bytes. */
async function downloadDecrypted(page: Page, account: Account): Promise<Buffer> {
  const row = page.getByRole('row').filter({ hasText: fileName })
  await row.getByRole('button', { name: 'Download and decrypt' }).click()

  const unlock = page.getByRole('heading', { name: 'Unlock your files' })
  await expect(unlock).toBeVisible()
  await page.getByRole('textbox', { name: /^Encryption passphrase/ }).fill(account.passphrase)
  const download = page.waitForEvent('download', { timeout: 60_000 })
  await page.getByRole('button', { name: 'Unlock', exact: true }).click()
  await expect(unlock).toBeHidden({ timeout: 60_000 })

  const saved = await download
  expect(saved.suggestedFilename()).toBe(fileName)
  await expect(page.getByText(`Decrypted and saved ${fileName}`)).toBeVisible()
  return readFile(await saved.path())
}

/** Share asks for the passphrase before its dialog opens, every time. */
async function openShareDialog(page: Page, account: Account) {
  const row = page.getByRole('row').filter({ hasText: fileName })
  await row.getByRole('button', { name: 'Share', exact: true }).click()
  const unlock = page.getByRole('heading', { name: 'Unlock your files' })
  await expect(unlock).toBeVisible()
  await page.getByRole('textbox', { name: /^Encryption passphrase/ }).fill(account.passphrase)
  await page.getByRole('button', { name: 'Unlock', exact: true }).click()
  await expect(unlock).toBeHidden({ timeout: 60_000 })
  await expect(page.getByRole('heading', { name: 'Share this file' })).toBeVisible()
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: /^Account menu for/ }).hover()
  await page.getByRole('menuitem', { name: 'Log out' }).click()
  await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeNull()
  // The session is gone from this browser: a protected page sends it back to sign in.
  await page.goto('/files')
  await expect(page).toHaveURL(/\/login\?redirect=/)
}

test('a new user encrypts, shares and revokes a file through the pages', async ({ browser }) => {
  const owner = await openPage(browser)
  const recipient = await openPage(browser)

  await test.step('register both accounts through the emailed-code flow', async () => {
    await register(owner, alice)
    await register(recipient, bob)
  })

  await test.step('sign in', async () => {
    await signIn(owner, alice)
  })

  await test.step('encrypt and upload a file', async () => {
    await owner.getByRole('link', { name: /^Upload & Encrypt/ }).click()
    await owner.getByLabel('Select Files').setInputFiles({
      name: fileName,
      mimeType: 'application/octet-stream',
      buffer: fileBytes,
    })
    // Count every upload the page sends, so a second press cannot re-upload the file unseen.
    let uploads = 0
    const countUpload = (request: Request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/files/upload')) uploads += 1
    }
    owner.on('request', countUpload)
    await owner.getByRole('button', { name: 'Start Encryption' }).click()
    const complete = owner.getByTestId('encryption-complete')
    await expect(complete).toBeVisible({ timeout: 60_000 })
    expect(uploads).toBe(1)
    // Finished is a status, not a button: nothing to press, and pressing it sends nothing.
    await expect(complete).toHaveRole('status')
    await expect(owner.getByRole('button', { name: 'Encryption Complete' })).toHaveCount(0)
    await expect(owner.getByRole('button', { name: 'Start Encryption' })).toHaveCount(0)
    await complete.click()
    await owner.waitForTimeout(500)
    expect(uploads).toBe(1)
    owner.off('request', countUpload)
    // The seal receipt (AC7) stays until it is put away, then leaves the page.
    const receipt = owner.getByTestId('encryption-progress')
    await expect(receipt).toContainText('Sealed')
    await owner.getByRole('button', { name: 'Close the seal receipt' }).click()
    await expect(receipt).toHaveCount(0)
    await owner.getByRole('button', { name: 'View Encrypted Files' }).click()
    await expect(owner.getByRole('row').filter({ hasText: fileName })).toBeVisible()
  })

  await test.step('the encrypted preview shows what the server really stores', async () => {
    const row = owner.getByRole('row').filter({ hasText: fileName })
    await row.getByRole('button', { name: 'Encrypted preview' }).click()
    const preview = owner.getByTestId('ciphertext-preview')
    await expect(preview).toBeVisible()

    // Same length by design (AES-GCM adds no padding), printed in whole bytes so rounding
    // cannot hide a difference.
    const size = `${fileBytes.length.toLocaleString('en-US')} bytes`
    await expect(preview.getByTestId('preview-original-size')).toHaveText(size)
    await expect(preview.getByTestId('preview-encrypted-size')).toHaveText(size)
    await expect(preview).toContainText('Same length is expected')

    // The file begins 00 01 02 03 ... 0f. Stored bytes that began the same way would mean the
    // server holds plaintext.
    const firstRow = (await preview.locator('tbody tr').first().innerText()).replace(/\s+/g, ' ')
    expect(firstRow).not.toContain('00 01 02 03 04 05 06 07')
    await expect(preview.locator('tbody tr')).toHaveCount(8) // 128 bytes, sixteen to a row

    await row.getByRole('button', { name: 'Encrypted preview' }).click()
    await expect(preview).toBeHidden()
  })

  await test.step('a file can be filed into a folder and unfiled again', async () => {
    // Regression: choosing any folder answered 422 "folder_id: Input should be an instance of
    // UUID", because the request body validated strictly. Only a real click reaches that path.
    await owner.getByRole('textbox', { name: 'New folder name' }).fill('Reports')
    await owner.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(owner.getByText('Created folder Reports')).toBeVisible()
    // Creating a folder selects it, which hides every file that is not in it.
    await owner.getByRole('button', { name: 'All files' }).click()

    const row = owner.getByRole('row').filter({ hasText: fileName })
    const folderSelect = row.getByLabel(`Folder for ${fileName}`)
    await folderSelect.selectOption({ label: 'Reports' })
    await expect(owner.getByText(`Moved ${fileName} to Reports`)).toBeVisible()
    await expect(owner.getByText(/Input should be an instance of UUID/)).toHaveCount(0)

    await folderSelect.selectOption({ label: 'No folder' })
    await expect(owner.getByText(`${fileName} is no longer in a folder`)).toBeVisible()
  })

  await test.step('unlock the account key and download the original bytes', async () => {
    const bytes = await downloadDecrypted(owner, alice)
    expect(bytes.equals(fileBytes), 'the decrypted download equals the uploaded file').toBe(true)
    // The key is used for that one download and locked again straight after.
    await expect(owner.getByTestId('key-status')).toContainText('Key locked')
  })

  const recipientField = owner.getByRole('textbox', { name: /their username/i })
  const shareDialog = owner.locator('form').filter({ has: recipientField })

  await test.step('share the file with the second account', async () => {
    await openShareDialog(owner, alice)
    await recipientField.fill(bob.username)
    await shareDialog.getByRole('button', { name: 'Share', exact: true }).click()
    // A second step names the recipient and shows their key fingerprint before anything is sent.
    await expect(owner.getByTestId('recipient-fingerprint')).toHaveText(/^([0-9A-F]{4} ){7}[0-9A-F]{4}$/)
    await owner.getByRole('button', { name: 'Confirm and share' }).click()
    await expect(owner.getByText(`Shared with ${bob.username}`)).toBeVisible({ timeout: 30_000 })
    await expect(owner.getByTestId('key-status')).toContainText('Key locked')
    await expect(owner.getByRole('listitem').filter({ hasText: bob.username })).toBeVisible()
    await owner.getByRole('button', { name: 'Cancel' }).click()
  })

  const sharedTab = recipient.getByRole('button', { name: /^Shared with me/ })
  const sharedRow = recipient.getByRole('row').filter({ hasText: fileName })

  await test.step('the second account sees the file and opens it with its own passphrase', async () => {
    await signIn(recipient, bob)
    await openMyFiles(recipient)
    await sharedTab.click()
    await expect(sharedRow).toContainText(`Shared by ${alice.username}`)
    const bytes = await downloadDecrypted(recipient, bob)
    expect(bytes.equals(fileBytes), "the recipient's download equals the uploaded file").toBe(true)
  })

  await test.step('the recipient files the shared file in a folder of their own', async () => {
    // Folders used to exist for your own uploads only: a shared file had no Folder column and
    // could not be organised at all.
    await recipient.getByRole('textbox', { name: 'New folder name' }).fill('From colleagues')
    await recipient.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(recipient.getByText('Created folder From colleagues')).toBeVisible()
    await recipient.getByRole('button', { name: 'All files' }).click()
    await sharedRow.getByLabel(`Folder for ${fileName}`).selectOption({ label: 'From colleagues' })
    await expect(recipient.getByText(`Moved ${fileName} to From colleagues`)).toBeVisible()

    // Selecting the folder on the shared tab lists the file, and the count says so.
    await recipient.getByRole('button', { name: 'From colleagues (1)' }).click()
    await expect(sharedRow).toBeVisible()

    // A recipient gets Download and More; Share and Delete belong to the owner and are not offered.
    await expect(sharedRow.getByRole('button', { name: 'Download and decrypt' })).toBeVisible()
    await expect(sharedRow.getByRole('button', { name: 'More actions' })).toBeVisible()
    await expect(sharedRow.getByRole('button', { name: 'Share', exact: true })).toHaveCount(0)
    await expect(sharedRow.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0)
  })

  await test.step('revoke the share', async () => {
    await openShareDialog(owner, alice)
    const holder = owner.getByRole('listitem').filter({ hasText: bob.username })
    await holder.getByRole('button', { name: 'Revoke' }).click()
    // #72: revoke states the consequence in a dedicated dialog before it runs.
    await owner.getByRole('button', { name: 'Revoke access' }).click()
    await expect(owner.getByText(`Revoked ${bob.username}'s access`)).toBeVisible()
    await expect(owner.getByText('Nobody yet')).toBeVisible()
    await owner.getByRole('button', { name: 'Cancel' }).click()
    // Closing the dialog without sharing locks the key again.
    await expect(owner.getByTestId('key-status')).toContainText('Key locked')
  })

  await test.step('the second account no longer sees the file', async () => {
    await recipient.reload()
    await expect(recipient.getByRole('heading', { name: 'Manage Encrypted Files' })).toBeVisible()
    await sharedTab.click()
    await expect(recipient.getByText('No one has shared a file with you yet.')).toBeVisible()
    await expect(sharedRow).toHaveCount(0)
  })

  await test.step('change the encryption passphrase in Settings with the current one', async () => {
    // Two more Argon2id derivations and a round trip; give the long golden path room for them.
    test.setTimeout(test.info().timeout + 60_000)
    await owner.goto('/settings')
    const card = owner.getByTestId('change-passphrase-card')
    const changed = `${alice.passphrase} changed`
    await card.getByLabel(/^Current encryption passphrase/).fill(alice.passphrase)
    await card.getByLabel(/^New encryption passphrase/).fill(changed)
    await card.getByLabel(/^Confirm new passphrase/).fill(changed)
    await card.getByRole('button', { name: 'Change passphrase' }).click()
    await expect(card.getByText('The old one no longer works.', { exact: false })).toBeVisible({
      timeout: 60_000,
    })
  })

  await test.step('log out', async () => {
    await signOut(owner)
    await signOut(recipient)
  })
})
