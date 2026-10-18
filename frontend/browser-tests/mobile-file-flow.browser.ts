/**
 * The primary file flow on a phone, against the real backend: register, upload, find the file in
 * My Files, look at what the server stores, open the share dialog, and download the original back.
 *
 * Why a second end-to-end test and not just the golden path at a smaller size: on a phone My Files
 * is a different layout (cards, not a table), the dialogs have to fit a 740 px tall screen, and the
 * actions must be inside the screen and big enough to tap. Those are the things a desktop run
 * cannot see.
 *
 * Every identity, password, passphrase and file byte is minted per run and obviously fake, as in
 * the golden path, and lives in a database destroyed with the stack.
 */
import { randomBytes, randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'

import { expect, test, type Page } from '@playwright/test'

import { takeVerificationCode } from './mailbox'
import { expectDialogFits, expectFitsScreen, expectReachable } from './viewport'

const run = randomUUID().slice(0, 8)
const account = {
  username: `pw-phone-${run}`,
  email: `pw-phone-${run}@example.com`,
  password: `Throwaway!${randomUUID()}`,
  passphrase: `throwaway phone passphrase ${randomUUID()}`,
}
// One long unbroken name: the case that overflowed cards and dialogs before.
const fileName = `pw-phone-${run}-a-long-unbroken-file-name-that-a-narrow-screen-has-to-wrap.bin`
const fileBytes = Buffer.concat([Buffer.from(Array.from({ length: 256 }, (_, i) => i)), randomBytes(2048)])

test.use({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true })

async function register(page: Page) {
  await page.goto('/register')
  await page.getByRole('textbox', { name: /^Username/ }).fill(account.username)
  await page.getByRole('textbox', { name: /^Password/ }).fill(account.password)
  await page.getByRole('textbox', { name: /^Confirm Password/ }).fill(account.password)
  await page.getByRole('textbox', { name: /^Email Address/ }).fill(account.email)
  await expectFitsScreen(page, 'registration form, step 1')

  await page.getByRole('button', { name: 'Send code' }).click()
  await expect(page.getByText('a code is on its way')).toBeVisible()
  let code: string | undefined
  await expect.poll(() => (code = takeVerificationCode(account.email))).toBeTruthy()
  await page.getByRole('textbox', { name: /^Verification Code/ }).fill(code!)
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('textbox', { name: /^Encryption Passphrase/ }).fill(account.passphrase)
  await expectFitsScreen(page, 'registration form, step 2')
  await page.getByRole('button', { name: 'Register' }).click()
  await expect(page.getByRole('heading', { name: 'Save Your Private Key' })).toBeVisible({ timeout: 60_000 })
  await expectFitsScreen(page, 'private key page')
  await page.getByRole('checkbox', { name: /I have saved this private key/ }).check()
  await page.getByRole('link', { name: 'Continue to your workspace' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  // Start the rest of the flow from a fresh sign-in, as before registration signed in.
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible()
}

test('a phone user can upload, inspect, share and download a file', async ({ page }) => {
  await test.step('register and sign in on a phone', async () => {
    await register(page)
    await page.getByRole('textbox', { name: 'Username' }).fill(account.username)
    await page.getByRole('textbox', { name: /^Password/ }).fill(account.password)
    await page.getByRole('button', { name: 'Login' }).click()
    await expect(page).toHaveURL(/\/dashboard$/)
    await expectFitsScreen(page, 'dashboard')
  })

  await test.step('upload a file with a long name', async () => {
    await page.goto('/upload')
    await page.getByLabel('Select Files').setInputFiles({
      name: fileName,
      mimeType: 'application/octet-stream',
      buffer: fileBytes,
    })
    await expectFitsScreen(page, 'upload page with a long file name chosen')
    await page.getByRole('button', { name: 'Start Encryption' }).click()
    await expect(page.getByTestId('encryption-complete')).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: 'View Encrypted Files' }).click()
  })

  // On a phone each file is a card; the table's row role does not apply, so select the element.
  const card = page.locator('tr', { hasText: fileName })

  // Download, Share, Delete and Access history stay on the card; the rest are under More.
  const moreItem = async (name: string) => {
    await card.getByRole('button', { name: 'More actions' }).click()
    return page.getByRole('menuitem', { name })
  }

  await test.step('My Files shows the file as a card whose actions can all be tapped', async () => {
    await expect(card).toBeVisible()
    await expectFitsScreen(page, 'My Files')
    for (const name of ['Download and decrypt', 'Share', 'Delete', 'Access history', 'More actions']) {
      await expectReachable(page, card.getByRole('button', { name, exact: true }), name)
    }
    for (const name of ['Download encrypted file', 'Request recovery']) {
      await expectReachable(page, await moreItem(name), name)
      await page.keyboard.press('Escape')
    }
  })

  await test.step('the encrypted preview fits the screen and shows real ciphertext', async () => {
    await card.getByRole('button', { name: 'Encrypted preview' }).click()
    const preview = page.getByTestId('ciphertext-preview')
    await expect(preview).toBeVisible()
    await expect(preview.getByTestId('preview-encrypted-size')).toHaveText(`${fileBytes.length.toLocaleString('en-US')} bytes`)
    await expectFitsScreen(page, 'encrypted preview')
    const firstRow = (await preview.locator('tbody tr').first().innerText()).replace(/\s+/g, ' ')
    expect(firstRow).not.toContain('00 01 02 03 04 05 06 07')
    await card.getByRole('button', { name: 'Encrypted preview' }).click()
    await expect(preview).toBeHidden()
  })

  await test.step('the dialogs stay inside the screen', async () => {
    const panel = page.locator('div.fixed.inset-0 > div').first()

    await (await moreItem('Request recovery')).click()
    await expect(page.getByRole('heading', { name: 'Request file recovery' })).toBeVisible()
    await expectDialogFits(page, panel, 'recovery dialog')
    await page.getByRole('button', { name: 'Cancel' }).click()

    await card.getByRole('button', { name: 'Access history', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Access history' })).toBeVisible()
    await expectDialogFits(page, panel, 'access history dialog')
    await page.getByRole('button', { name: 'Close', exact: true }).click()

    await card.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Delete this file?' })).toBeVisible()
    await expectDialogFits(page, panel, 'delete confirmation')
    await page.getByRole('button', { name: 'Cancel' }).click()
  })

  await test.step('download and decrypt the original bytes after unlocking', async () => {
    await card.getByRole('button', { name: 'Download and decrypt' }).click()
    const unlock = page.getByRole('heading', { name: 'Unlock your files' })
    await expect(unlock).toBeVisible()
    await expectDialogFits(page, page.locator('div.fixed.inset-0 > div').first(), 'unlock dialog')
    await page.getByRole('textbox', { name: /^Encryption passphrase/ }).fill(account.passphrase)
    const download = page.waitForEvent('download', { timeout: 60_000 })
    await page.getByRole('button', { name: 'Unlock', exact: true }).click()
    const saved = await download
    expect(saved.suggestedFilename()).toBe(fileName)
    expect((await readFile(await saved.path())).equals(fileBytes), 'the decrypted download equals the upload').toBe(true)
  })

  await test.step('the share dialog fits the screen', async () => {
    await card.getByRole('button', { name: 'Share', exact: true }).click()
    // Share asks for the passphrase first, every time.
    const unlock = page.getByRole('heading', { name: 'Unlock your files' })
    await expect(unlock).toBeVisible()
    await page.getByRole('textbox', { name: /^Encryption passphrase/ }).fill(account.passphrase)
    await page.getByRole('button', { name: 'Unlock', exact: true }).click()
    await expect(unlock).toBeHidden({ timeout: 60_000 })
    await expect(page.getByRole('heading', { name: 'Share this file' })).toBeVisible()
    await expectDialogFits(page, page.locator('div.fixed.inset-0 > div').first(), 'share dialog')
    await page.getByRole('button', { name: 'Cancel' }).click()
  })
})
