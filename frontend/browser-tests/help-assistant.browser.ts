/**
 * The Help assistant (Issue #146) in a real browser: ask a question, follow the answer's link,
 * close it from the keyboard, and check that on a phone the round button fits the screen and
 * never sits on top of the controls people came to press (Start Encryption, the My Files card
 * actions).
 *
 * The first tests need no account. The last registers one throwaway account, minted per
 * run like the other browser tests, and uploads one small file so My Files has a card. It then
 * asks about that file (v2): who has access to it, its history picked from a list, and what has
 * been shared with the account, answered from the account itself.
 */
import { randomBytes, randomUUID } from 'node:crypto'

import { expect, test, type Locator, type Page } from '@playwright/test'

import { takeVerificationCode } from './mailbox'
import { expectFitsScreen, PHONE_WIDTHS } from './viewport'

const trigger = (page: Page) => page.getByTestId('assistant-trigger')
const panel = (page: Page) => page.getByRole('dialog', { name: 'Help assistant' })
const questionBox = (page: Page) => panel(page).getByRole('textbox', { name: 'Your question' })

/** The control is the topmost thing at its own centre and does not overlap the assistant's button. */
async function expectNotCovered(page: Page, control: Locator, label: string) {
  await control.scrollIntoViewIfNeeded()
  const box = await control.boundingBox()
  const bot = await trigger(page).boundingBox()
  expect(box, `${label} has a box`).not.toBeNull()
  expect(bot, 'the assistant button has a box').not.toBeNull()
  const overlaps =
    box!.x < bot!.x + bot!.width && bot!.x < box!.x + box!.width && box!.y < bot!.y + bot!.height && bot!.y < box!.y + box!.height
  expect(overlaps, `${label} overlaps the Help assistant button`).toBe(false)
  const onTop = await control.evaluate((element) => {
    const r = element.getBoundingClientRect()
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    return hit !== null && (element === hit || element.contains(hit))
  })
  expect(onTop, `${label} is the topmost element at its centre`).toBe(true)
}

test.describe('signed out, on a desktop screen', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/help')
  })

  test('answers a question with a summary and a link that works, then closes on Escape', async ({ page }) => {
    await trigger(page).click()
    await expect(panel(page)).toBeVisible()
    await expect(questionBox(page)).toBeFocused()
    await expect(panel(page)).toContainText('your question is not sent anywhere')

    await questionBox(page).fill('why not just use Google Drive?')
    await questionBox(page).press('Enter')
    const answer = panel(page).getByTestId('assistant-answer').last()
    await expect(answer).toContainText('Why not just use Google Drive?')
    await expect(answer).toContainText('Google manages the keys')
    await expect(page.getByTestId('assistant-live')).toContainText('Why not just use Google Drive?')
    await expect(answer.getByTestId('assistant-sources').getByRole('link')).not.toHaveCount(0)

    await page.keyboard.press('Escape')
    await expect(panel(page)).toBeHidden()
    await expect(trigger(page)).toBeFocused()

    await trigger(page).click()
    await panel(page).getByRole('link', { name: 'Ordinary cloud storage vs SecureView' }).last().click()
    await expect(page).toHaveURL(/\/how-it-works#why-heading$/)
    await expect(page.getByRole('heading', { name: 'What ordinary cloud storage cannot promise' })).toBeInViewport()
  })

  test('says a page needs an account before sending someone signed out to it', async ({ page }) => {
    await trigger(page).click()
    await questionBox(page).fill('how do I shre a file')
    await questionBox(page).press('Enter')
    const answer = panel(page).getByTestId('assistant-answer').last()
    await expect(answer).toContainText('How do I share a file?')
    // Five steps plus checking the recipient's key fingerprint before confirming.
    await expect(answer.getByTestId('assistant-steps').getByRole('listitem')).toHaveCount(6)
    await expect(answer.getByTestId('assistant-links')).toContainText('(sign in first)')
  })

  test('asked about an account while signed out, it offers to look once signed in', async ({ page }) => {
    await trigger(page).click()
    await questionBox(page).fill('who has access to budget.xlsx')
    await questionBox(page).press('Enter')
    const answer = panel(page).getByTestId('assistant-answer').last()
    await expect(answer).toContainText('Who has access to one of my files?')
    await expect(answer).toContainText('Signed in, name the file')
    const signIn = panel(page).getByTestId('assistant-account-signin').last()
    await expect(signIn).toContainText('Sign in and I can check this for your account.')
    await expect(panel(page).getByTestId('assistant-account-result')).toHaveCount(0)
  })

  test('admits when it does not know, and points to Help', async ({ page }) => {
    await trigger(page).click()
    await questionBox(page).fill('what is the weather tomorrow')
    await questionBox(page).press('Enter')
    const unsure = panel(page).getByTestId('assistant-unsure')
    await expect(unsure).toContainText('not sure')
    await expect(unsure.getByRole('link', { name: 'Help and videos' })).toBeVisible()
  })

  test('works from the keyboard alone', async ({ page }) => {
    // From the top of the page, Shift+Tab wraps to the last control: the assistant's button.
    await page.locator('body').focus()
    await page.keyboard.press('Shift+Tab')
    await expect(trigger(page)).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(questionBox(page)).toBeFocused()

    await page.keyboard.type('how do I revoke access')
    await page.keyboard.press('Enter')
    await expect(panel(page).getByTestId('assistant-answer').last()).toContainText('How do I stop sharing a file?')

    // Focus stays inside the open panel however far you tab.
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press('Tab')
      expect(await panel(page).evaluate((el) => el.contains(document.activeElement))).toBe(true)
    }
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Shift+Tab')
      expect(await panel(page).evaluate((el) => el.contains(document.activeElement))).toBe(true)
    }

    await page.keyboard.press('Escape')
    await expect(panel(page)).toBeHidden()
    await expect(trigger(page)).toBeFocused()
  })
})

for (const width of PHONE_WIDTHS) {
  test.describe(`signed out, at ${width} px`, () => {
    test.use({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true })

    test('the button and the open sheet fit the screen', async ({ page }) => {
      await page.goto('/')
      const bot = await trigger(page).boundingBox()
      expect(bot!.x + bot!.width, 'a 16 px gutter on the right').toBeLessThanOrEqual(width - 16 + 0.5)
      expect(bot!.y + bot!.height, 'a 16 px gutter at the bottom').toBeLessThanOrEqual(740 - 16 + 0.5)
      await expectFitsScreen(page, `home with the assistant closed at ${width}px`)

      await trigger(page).click()
      await questionBox(page).fill('why not WhatsApp')
      await questionBox(page).press('Enter')
      await expect(panel(page).getByTestId('assistant-answer').last()).toContainText('WhatsApp')
      const sheet = await panel(page).boundingBox()
      expect(sheet!.x).toBeGreaterThanOrEqual(0)
      expect(sheet!.x + sheet!.width).toBeLessThanOrEqual(width + 0.5)
      expect(sheet!.y + sheet!.height).toBeLessThanOrEqual(740 + 0.5)
      await expectFitsScreen(page, `home with the assistant open at ${width}px`)
      await panel(page).getByRole('button', { name: 'Close' }).click()
      await expect(panel(page)).toBeHidden()
    })
  })
}

test.describe('signed in, on a phone', () => {
  const run = randomUUID().slice(0, 8)
  const account = {
    username: `pw-assist-${run}`,
    email: `pw-assist-${run}@example.com`,
    password: `Throwaway!${randomUUID()}`,
    passphrase: `throwaway assistant passphrase ${randomUUID()}`,
  }
  const fileName = `pw-assist-${run}.bin`

  test.use({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true })

  test('the button never covers Start Encryption or the My Files card actions', async ({ page }) => {
    await test.step('register and sign in', async () => {
      await page.goto('/register')
      await page.getByRole('textbox', { name: /^Username/ }).fill(account.username)
      await page.getByRole('textbox', { name: /^Password/ }).fill(account.password)
      await page.getByRole('textbox', { name: /^Confirm Password/ }).fill(account.password)
      await page.getByRole('textbox', { name: /^Email Address/ }).fill(account.email)
      await page.getByRole('button', { name: 'Send code' }).click()
      let code: string | undefined
      await expect.poll(() => (code = takeVerificationCode(account.email))).toBeTruthy()
      await page.getByRole('textbox', { name: /^Verification Code/ }).fill(code!)
      await page.getByRole('button', { name: 'Next' }).click()
      await page.getByRole('textbox', { name: /^Encryption Passphrase/ }).fill(account.passphrase)
      await page.getByRole('button', { name: 'Register' }).click()
      await expect(page.getByRole('heading', { name: 'Save Your Private Key' })).toBeVisible({ timeout: 60_000 })
      await page.getByRole('checkbox', { name: /I have saved this private key/ }).check()
      await page.getByRole('link', { name: 'Continue to your workspace' }).click()
      await expect(page).toHaveURL(/\/dashboard$/)
      // Start the rest of the flow from a fresh sign-in, as before registration signed in.
      await page.evaluate(() => localStorage.clear())
      await page.goto('/login')
      await page.getByRole('textbox', { name: 'Username' }).fill(account.username)
      await page.getByRole('textbox', { name: /^Password/ }).fill(account.password)
      await page.getByRole('button', { name: 'Login' }).click()
      await expect(page).toHaveURL(/\/dashboard$/)
    })

    for (const width of PHONE_WIDTHS) {
      await test.step(`Start Encryption is clear of the button at ${width} px`, async () => {
        await page.setViewportSize({ width, height: 740 })
        await page.goto('/upload')
        await page.getByLabel('Select Files').setInputFiles({
          name: fileName,
          mimeType: 'application/octet-stream',
          buffer: randomBytes(1024),
        })
        await expectNotCovered(page, page.getByRole('button', { name: 'Start Encryption' }), 'Start Encryption')
        await expectFitsScreen(page, `upload at ${width}px`)
      })
    }

    await test.step('upload one file', async () => {
      await page.getByRole('button', { name: 'Start Encryption' }).click()
      await expect(page.getByTestId('encryption-complete')).toBeVisible({ timeout: 60_000 })
    })

    for (const width of PHONE_WIDTHS) {
      await test.step(`the My Files card actions are clear of the button at ${width} px`, async () => {
        await page.setViewportSize({ width, height: 740 })
        await page.goto('/files')
        const card = page.locator('tr', { hasText: fileName })
        await expect(card).toBeVisible()
        for (const name of ['Download and decrypt', 'Share', 'Delete', 'More actions']) {
          await expectNotCovered(page, card.getByRole('button', { name, exact: true }), name)
        }
        await expectFitsScreen(page, `My Files at ${width}px`)
      })
    }

    await test.step('signed in, the answer links need no "sign in first"', async () => {
      await trigger(page).click()
      await questionBox(page).fill('how do I share a file')
      await questionBox(page).press('Enter')
      const answer = panel(page).getByTestId('assistant-answer').last()
      await expect(answer).toContainText('How do I share a file?')
      await expect(answer.getByTestId('assistant-links')).not.toContainText('sign in first')
      // On a phone, following a link closes the sheet so the page it opened is visible.
      await answer.getByRole('link', { name: 'My Files' }).click()
      await expect(panel(page)).toBeHidden()
      await expect(page).toHaveURL(/\/files$/)
    })

    for (const width of PHONE_WIDTHS) {
      await test.step(`asked who has access to the file, it answers from the account at ${width} px`, async () => {
        await page.setViewportSize({ width, height: 740 })
        await trigger(page).click()
        await questionBox(page).fill(`who has access to ${fileName}?`)
        await questionBox(page).press('Enter')
        const result = panel(page).getByTestId('assistant-account-result').last()
        await expect(result).toContainText(`Only you can open ${fileName}. It is not shared with anyone.`)
        await expect(page.getByTestId('assistant-live')).toContainText(`Only you can open ${fileName}`)
        await expectFitsScreen(page, `an account answer at ${width}px`)
        await panel(page).getByRole('button', { name: 'Close' }).click()
      })
    }

    await test.step('the answer’s link opens My Files searched for that file', async () => {
      // Reopening the panel shows the answers already given without asking the server again.
      let lookups = 0
      const count = (request: { url(): string }) => {
        if (request.url().includes('/shared-users')) lookups++
      }
      page.on('request', count)
      await trigger(page).click()
      await expect(panel(page).getByTestId('assistant-account-result').last()).toContainText(`Only you can open ${fileName}`)
      page.off('request', count)
      expect(lookups, 'shared-users requests on reopening').toBe(0)
      await panel(page).getByRole('link', { name: `Open ${fileName} in My Files` }).last().click()
      await expect(panel(page)).toBeHidden()
      await expect(page).toHaveURL((url) => url.pathname === '/files' && url.searchParams.get('q') === fileName)
      await expect(page.getByPlaceholder('Search your files...')).toHaveValue(fileName)
      await expect(page.locator('tr', { hasText: fileName })).toBeVisible()
    })

    await test.step('a general question offers the check, and the file is picked from a list', async () => {
      await trigger(page).click()
      await questionBox(page).fill('who downloaded my file')
      await questionBox(page).press('Enter')
      const latest = panel(page).getByRole('list', { name: 'Questions and answers' }).locator(':scope > li').last()
      await expect(latest.getByTestId('assistant-answer')).toContainText('What does the Activity Log show?')
      // Nothing is read until asked to: the earlier answers keep their results, this one has none yet.
      await expect(latest.getByRole('button', { name: 'Check one of my files’ history' })).toBeVisible()
      await expect(latest.getByTestId('assistant-account-result')).toHaveCount(0)
      await latest.getByRole('button', { name: 'Check one of my files’ history' }).click()
      const choose = latest.getByTestId('assistant-account-choose')
      await expect(choose).toContainText('Pick one of your newest files')
      await choose.getByRole('button', { name: new RegExp(fileName.replace(/[.]/g, '\\.')) }).click()
      await expect(panel(page).getByTestId('assistant-account-result').last()).toContainText(
        `Nobody else has downloaded ${fileName}.`,
      )
      await expect(panel(page).getByTestId('assistant-account-rows').last()).toContainText('You uploaded it')
    })

    await test.step('what has been shared with the account', async () => {
      await panel(page).getByRole('button', { name: 'What has been shared with me?' }).click()
      await expect(panel(page).getByTestId('assistant-account-result').last()).toContainText(
        'Nobody has shared a file with you yet.',
      )
    })
  })
})
