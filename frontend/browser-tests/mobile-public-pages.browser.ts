/**
 * The pages anyone can open, at phone widths: none scrolls sideways, none has a control past
 * the screen edge, and the controls a first-time visitor needs are big enough to tap.
 * Needs no account and no backend data.
 */
import { expect, test } from '@playwright/test'

import { elementsOffScreen, expectFitsScreen, expectReachable, PHONE_WIDTHS } from './viewport'

const PUBLIC_PAGES = ['/', '/login', '/register', '/forgot-password', '/education', '/help', '/team', '/nope']

for (const width of PHONE_WIDTHS) {
  test.describe(`at ${width} px`, () => {
    test.use({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true })

    for (const path of PUBLIC_PAGES) {
      test(`${path} fits the screen`, async ({ page }) => {
        await page.goto(path)
        await page.waitForLoadState('load')
        await expectFitsScreen(page, `${path} at ${width}px`)
      })
    }

    test('the sign-in and registration controls can be reached and tapped', async ({ page }) => {
      await page.goto('/login')
      await expectReachable(page, page.getByRole('button', { name: 'Login' }), 'Login button')
      await expectReachable(page, page.getByRole('link', { name: 'Forgot password?' }), 'Forgot password link')
      await expectReachable(page, page.getByRole('link', { name: 'Register' }), 'Register link')

      await page.goto('/register')
      await expectReachable(page, page.getByRole('button', { name: 'Send code' }), 'Send code button')
      expect(await elementsOffScreen(page)).toEqual([])
    })
  })
}
