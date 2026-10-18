/**
 * English / 简体中文 (Issue #74): switching, remembering the choice, falling back, and the
 * Chinese pages at phone widths. Public pages only; needs no account and no backend data.
 */
import { expect, test, type Page } from '@playwright/test'

import { expectFitsScreen, PHONE_WIDTHS } from './viewport'

const PUBLIC_PAGES = ['/', '/login', '/register', '/forgot-password', '/education', '/help', '/how-it-works', '/team', '/nope']

/** The switcher is in the header on wide screens and in the menu on narrow ones. */
async function chooseLanguage(page: Page, code: 'en' | 'zh-CN') {
  const switcher = page.getByTestId('language-switcher').filter({ visible: true }).first()
  if (!(await switcher.isVisible())) {
    await page.locator('header button[aria-expanded]').filter({ visible: true }).first().click()
  }
  await page.getByTestId('language-switcher').filter({ visible: true }).first().selectOption(code)
}

test.describe('desktop', () => {
  test('switches in place, and the choice survives a reload', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible()

    await chooseLanguage(page, 'zh-CN')
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
    await expect(page.getByRole('heading', { level: 1 })).not.toHaveText('Sign In')
    const chineseHeading = await page.getByRole('heading', { level: 1 }).innerText()
    expect(chineseHeading).toMatch(/[一-鿿]/)

    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(chineseHeading)

    await chooseLanguage(page, 'en')
    await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  })

  test('a returning Chinese visitor never sees the English first', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('locale', 'zh-CN'))
    // Record every heading text the page ever shows, from the first paint on.
    await page.addInitScript(() => {
      const seen: string[] = []
      ;(window as unknown as { __seen: string[] }).__seen = seen
      new MutationObserver(() => {
        const h1 = document.querySelector('h1')
        if (h1?.textContent) seen.push(h1.textContent.trim())
      }).observe(document, { subtree: true, childList: true, characterData: true })
    })
    await page.goto('/login')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/[一-鿿]/)
    const seen = await page.evaluate(() => (window as unknown as { __seen: string[] }).__seen)
    expect(seen).not.toContain('Sign In')
  })

  test('long-form pages read as Chinese sentences, and team names are as the team writes them', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('locale', 'zh-CN'))

    // A sentence with an emphasised word is translated whole, not word by word.
    await page.goto('/how-it-works')
    const callout = page.getByText(/两个秘密/).first()
    await expect(callout).toBeVisible()
    await expect(callout).not.toContainText('password')

    // Education articles are Markdown, translated whole before rendering.
    await page.goto('/education')
    await page.goto('/education?article=what-is-encryption#article-what-is-encryption')
    await expect(page.locator('body')).toContainText('明文')
    await expect(page.locator('body')).not.toContainText('Encryption is the process of converting plaintext')

    await page.goto('/team')
    for (const name of ['温硕勋', '李俊言', '黄建幸', '陈泰', 'Asad Malik 博士', '项目导师']) {
      await expect(page.locator('body')).toContainText(name)
    }
    await expect(page.locator('body')).toContainText('马来西亚莫纳什大学信息技术学院')
  })

  test('an unknown saved value falls back to English', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('locale', 'fr'))
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible()
  })

  test('no raw translation key reaches a page', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('locale', 'zh-CN'))
    for (const path of PUBLIC_PAGES) {
      await page.goto(path)
      await page.waitForLoadState('load')
      const text = await page.locator('body').innerText()
      expect(text, path).not.toMatch(/\b(nav|login|register|forgot|settings|footer|theme|password|passphrase|common|deleteAccount|resetPassphrase)\.[a-z][A-Za-z]+\b/)
    }
  })
})

for (const width of PHONE_WIDTHS) {
  test.describe(`Chinese at ${width} px`, () => {
    test.use({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true })

    test('the switcher is reachable from the menu', async ({ page }) => {
      await page.goto('/')
      await chooseLanguage(page, 'zh-CN')
      await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
    })

    for (const path of PUBLIC_PAGES) {
      test(`${path} fits the screen in Chinese`, async ({ page }) => {
        await page.addInitScript(() => localStorage.setItem('locale', 'zh-CN'))
        await page.goto(path)
        await page.waitForLoadState('load')
        await expectFitsScreen(page, `${path} (zh-CN) at ${width}px`)
      })
    }
  })
}
