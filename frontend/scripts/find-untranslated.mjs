#!/usr/bin/env node
/**
 * List the English still showing on the public pages in Chinese (Issue #74).
 *
 * Builds nothing: serve a build first (`npm run build`), then
 *
 *   node scripts/find-untranslated.mjs [base-url]     # default http://127.0.0.1:4173
 *
 * Each page is opened with the language set to 简体中文, every button that opens something
 * on the page (an article, an algorithm, a step, a tab) is pressed once, and every text node
 * or readable attribute that still has English words and no Chinese is printed with the page
 * it was on. Text inside `translate="no"`, `<code>` and `<pre>` is left out: it is meant to
 * stay as written. Signed-in pages are not visited.
 */
import { chromium } from '@playwright/test'

const BASE = process.argv[2] ?? 'http://127.0.0.1:4173'
const PAGES = ['/', '/how-it-works', '/help', '/education', '/team', '/login', '/register', '/forgot-password', '/benchmark/argon2', '/nope']

function collect() {
  const found = new Set()
  const english = (text) => /[A-Za-z]{3,}/.test(text) && !/[一-鿿]/.test(text)
  const kept = (element) => !element || element.closest('[translate="no"], code, pre, script, style, svg, textarea')
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.nodeValue ?? '').replace(/\s+/g, ' ').trim()
      if (english(text) && !kept(node.parentElement)) found.add(text)
    } else {
      for (const name of ['placeholder', 'title', 'aria-label', 'alt']) {
        const value = node.getAttribute(name)
        if (value && english(value) && !kept(node)) found.add(`[${name}] ${value}`)
      }
    }
  }
  return [...found]
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.addInitScript(() => localStorage.setItem('locale', 'zh-CN'))
const all = new Map()

for (const path of PAGES) {
  await page.goto(BASE + path, { waitUntil: 'networkidle' })
  const seen = new Set(await page.evaluate(collect))
  const buttons = page.locator('main button[type="button"]:visible, main [role="tab"]:visible')
  const count = Math.min(await buttons.count(), 120)
  for (let i = 0; i < count; i++) {
    const button = buttons.nth(i)
    try {
      await button.click({ timeout: 1500 })
      await page.waitForTimeout(150)
      if (new URL(page.url()).pathname !== new URL(BASE + path).pathname) {
        await page.goto(BASE + path, { waitUntil: 'networkidle' })
      }
      for (const text of await page.evaluate(collect)) seen.add(text)
    } catch {
      // Covered, detached by a re-render, or gone: the next one.
    }
  }
  for (const text of seen) if (!all.has(text)) all.set(text, path)
}
await browser.close()

const byPage = new Map()
for (const [text, path] of all) byPage.set(path, [...(byPage.get(path) ?? []), text])
for (const [path, texts] of byPage) {
  console.log(`\n${path} (${texts.length})`)
  for (const text of texts.sort()) console.log(`  ${text.slice(0, 160)}`)
}
console.log(`\n${all.size} English strings still showing`)
