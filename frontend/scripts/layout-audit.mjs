/**
 * Layout audit: opens every page in five configurations (1440 light, 1440 dark, 768, 390 phone,
 * 1440 Chinese), takes a full-page screenshot, and records what a screenshot review tends to miss:
 *   wraps        headings or short text broken over several lines although the parent has room for one
 *   overflowX    pixels of horizontal overflow
 *   clipped      text cut off
 *   tiny         text smaller than 12px
 *   smallTargets clickable elements under 32px tall
 *   english      untranslated English in Chinese mode
 *   errors       console errors and 4xx/5xx responses
 *
 * Needs a local API (test database) and vite on 5173, and a local accounts file that is never
 * committed: {"alice":{"username","password","passphrase"},"admin":{…}}.
 *
 *   cd frontend && ACCOUNTS=/path/to/local-accounts.json OUT=/tmp/ui-audit node scripts/layout-audit.mjs
 *
 * Screenshots and report.json are written to OUT. Never point BASE at staging.
 */
import { chromium } from '@playwright/test'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { signIn } from './lib/video.mjs'
const O = process.env.OUT || 'ui-audit', B = process.env.BASE || 'http://localhost:5173'
mkdirSync(O, { recursive: true })
if (!process.env.ACCOUNTS) throw new Error('Set ACCOUNTS to a local accounts JSON file (see the header comment).')
const accounts = JSON.parse(readFileSync(process.env.ACCOUNTS, 'utf8'))

const guestPages = ['/', '/how-it-works', '/education', '/help', '/team', '/login', '/register', '/forgot-password', '/benchmark/argon2', '/no-such-page']
const appPages = ['/dashboard', '/upload', '/files', '/audit-logs', '/admin', '/profile', '/settings', '/help', '/education']
const configs = [
  { name: 'desk', w: 1440, h: 900, scheme: 'light', locale: 'en' },
  { name: 'dark', w: 1440, h: 900, scheme: 'dark', locale: 'en' },
  { name: 'tab', w: 768, h: 1024, scheme: 'light', locale: 'en' },
  { name: 'mob', w: 390, h: 844, scheme: 'light', locale: 'en', mobile: true },
  { name: 'zh', w: 1440, h: 900, scheme: 'light', locale: 'zh-CN' },
]
// ONLY=desk,mob limits the configurations; PAGES=/files,/admin limits the pages.
const only = process.env.ONLY ? process.env.ONLY.split(',') : null
const onlyPages = process.env.PAGES ? process.env.PAGES.split(',') : null

/** Runs in the page: layout findings that a screenshot review tends to miss. */
const probe = (locale) => {
  const out = { overflowX: document.documentElement.scrollWidth - window.innerWidth, wraps: [], clipped: [], tiny: 0, smallTargets: 0, english: [] }
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' }
  for (const el of document.querySelectorAll('h1,h2,h3,p,li')) {
    if (!vis(el) || el.closest('[aria-hidden="true"]')) continue
    const text = el.innerText.trim(); if (!text || text.length > 180) continue
    // A grid cell, card or step button that holds blocks or controls of its own is layout, not a heading squeezed by a cap.
    if (el.querySelector('button,a')) continue
    if ([...el.children].some((c) => !/^inline/.test(getComputedStyle(c).display) && getComputedStyle(c).display !== 'contents')) continue
    const cs = getComputedStyle(el), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.3
    // Content height only: padding and borders (chips, pills) must not read as extra lines.
    const box = el.getBoundingClientRect().height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - parseFloat(cs.borderTopWidth) - parseFloat(cs.borderBottomWidth)
    const lines = Math.round(box / lh)
    if (lines < 2) continue
    // How wide the text would be on one line, against the space the parent actually offers.
    const c = document.createElement('canvas').getContext('2d'); c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
    const oneLine = c.measureText(text.replace(/\s+/g, ' ')).width
    let p = el.parentElement; while (p && getComputedStyle(p).display === 'contents') p = p.parentElement
    const pcs = getComputedStyle(p), avail = p.getBoundingClientRect().width - parseFloat(pcs.paddingLeft) - parseFloat(pcs.paddingRight)
    const own = el.getBoundingClientRect().width
    if (oneLine < avail - 8 && own < avail - 40) out.wraps.push({ tag: el.tagName, text: text.slice(0, 90), lines, own: Math.round(own), avail: Math.round(avail), oneLine: Math.round(oneLine) })
  }
  for (const el of document.querySelectorAll('button,a,td,th,span,label')) {
    if (!vis(el)) continue
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow !== 'visible' && el.innerText.trim()) out.clipped.push(el.innerText.trim().slice(0, 50))
  }
  for (const el of document.querySelectorAll('body *')) {
    if (!el.childElementCount && vis(el) && el.innerText?.trim() && parseFloat(getComputedStyle(el).fontSize) < 12) out.tiny++
  }
  for (const el of document.querySelectorAll('a,button,input,select,[role=button]')) {
    if (!vis(el)) continue; const r = el.getBoundingClientRect(); if (r.height < 32 && r.width < 200) out.smallTargets++
  }
  if (locale !== 'en') {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    const seen = new Set()
    while (walker.nextNode()) {
      const n = walker.currentNode, t = n.textContent.trim(), el = n.parentElement
      if (!t || !el || !vis(el) || el.closest('[translate="no"],code,pre,svg,[aria-hidden="true"]')) continue
      if (/[A-Za-z]{3,}(\s+[A-Za-z]{2,}){2,}/.test(t) && !/[一-鿿]/.test(t)) seen.add(t.slice(0, 70))
    }
    out.english = [...seen].slice(0, 25)
  }
  return out
}

const report = {}
const b = await chromium.launch()
for (const cfg of configs) {
  if (only && !only.includes(cfg.name)) continue
  for (const who of ['guest', 'user', 'admin']) {
    const pages = (who === 'guest' ? guestPages : who === 'user' ? appPages : ['/admin']).filter((p) => !onlyPages || onlyPages.includes(p))
    if (!pages.length) continue
    const c = await b.newContext({ viewport: { width: cfg.w, height: cfg.h }, colorScheme: cfg.scheme, ...(cfg.mobile ? { isMobile: true, hasTouch: true, deviceScaleFactor: 1 } : {}) })
    // Signing in uses the English labels, so the language is switched after that (below).
    await c.addInitScript(([s, l]) => { try { localStorage.setItem('theme', s); if (l) localStorage.setItem('locale', l) } catch {} }, [cfg.scheme, who === 'guest' ? cfg.locale : cfg.locale === 'en' ? 'en' : ''])
    const p = await c.newPage(); p.setDefaultTimeout(30000)
    const errors = []
    p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)) })
    p.on('pageerror', (e) => errors.push('PAGEERROR ' + String(e).slice(0, 160)))
    p.on('response', (r) => { if (r.status() >= 400 && !(r.status() === 401 && who === 'guest')) errors.push(`HTTP ${r.status()} ${new URL(r.url()).pathname}`) })
    if (who !== 'guest') {
      try { await signIn(p, B, who === 'user' ? accounts.alice : accounts.admin, null) } catch (e) { report[`${cfg.name}:${who}:signin`] = String(e).slice(0, 200); await c.close(); continue }
    }
    if (who !== 'guest' && cfg.locale !== 'en') await p.evaluate((l) => localStorage.setItem('locale', l), cfg.locale)
    for (const path of pages) {
      errors.length = 0
      await p.goto(B + path); await p.waitForTimeout(1800)
      const key = `${cfg.name}:${who}:${path}`
      const r = await p.evaluate(probe, cfg.locale)
      r.errors = [...new Set(errors)]
      report[key] = r
      await p.screenshot({ path: `${O}/${cfg.name}-${who}-${path.replace(/\W+/g, '_') || 'home'}.png`, fullPage: true, timeout: 30000 }).catch(() => {})
    }
    await c.close()
  }
}
await b.close()
writeFileSync(O + '/report.json', JSON.stringify(report, null, 1))
console.log('pages audited', Object.keys(report).length)
