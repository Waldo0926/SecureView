/**
 * Text audit: finds headings and short paragraphs that wrap badly, on every page, at 1440, 1280,
 * 1100, 1024, 768 and 390 px, in English and Chinese. Each finding names the page, width and text:
 *   capped                  text kept narrower than the space it has, so it wraps beside empty room
 *   sentence-split          in text of several sentences, one that would fit on a line of its own
 *                           starts mid-line and is broken in two (SentenceLines fixes intros)
 *   heading-multi-sentence  a heading written as two sentences
 *   widow:N                 only N (1-2) words on the last line
 *   heading-wraps           any heading over one line, to review at desktop widths
 *
 * Needs a local API (test database), vite, and a local accounts file that is never committed:
 * {"alice":{"username","password","passphrase"}}.
 *
 *   cd frontend && ACCOUNTS=/path/to/local-accounts.json OUT=/tmp/text-audit.json node scripts/text-audit.mjs
 *
 * WIDTHS=1440,390 and LOCALES=en limit the run. Never point BASE at staging.
 */
import { chromium } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import { signIn } from './lib/video.mjs'
const B = process.env.BASE || 'http://localhost:5173', OUT = process.env.OUT || 'text-audit.json'
if (!process.env.ACCOUNTS) throw new Error('Set ACCOUNTS to a local accounts JSON file (see the header comment).')
const alice = JSON.parse(readFileSync(process.env.ACCOUNTS, 'utf8')).alice
const guest = ['/', '/how-it-works', '/education', '/help', '/team', '/login', '/register', '/forgot-password', '/benchmark/argon2', '/no-such-page']
const app = ['/dashboard', '/upload', '/files', '/audit-logs', '/profile', '/settings']
const widths = (process.env.WIDTHS || '1440,1280,1100,1024,768,390').split(',').map(Number)
const locales = (process.env.LOCALES || 'en,zh-CN').split(',')

const probe = () => {
  const out = []
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0' }
  for (const el of document.querySelectorAll('h1,h2,h3,h4,p,dd,figcaption')) {
    if (!vis(el) || el.closest('[aria-hidden="true"],table,pre,code,[data-testid="encryption-progress"],svg')) continue
    const text = el.textContent.replace(/\s+/g, ' ').trim()
    if (!text || text.length > 260) continue
    const isHeading = /^H[1-4]$/.test(el.tagName)
    if (!isHeading && text.length < 25) continue
    const nodes = []; let total = 0
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    while (w.nextNode()) { const n = w.currentNode; nodes.push({ n, start: total }); total += n.textContent.length }
    const raw = nodes.map((x) => x.n.textContent).join('')
    const rangeOf = (a, b) => {
      const r = document.createRange(); let sa = false
      for (const { n, start } of nodes) {
        const end = start + n.textContent.length
        if (!sa && a <= end) { r.setStart(n, Math.max(0, a - start)); sa = true }
        if (sa && b <= end) { r.setEnd(n, Math.max(0, b - start)); return r }
      }
      r.setEnd(nodes.at(-1).n, nodes.at(-1).n.textContent.length); return r
    }
    const fs0 = parseFloat(getComputedStyle(el).fontSize)
    const tops = (r) => { const ts = [...r.getClientRects()].filter((x) => x.width > 1 && x.height > 1).map((x) => x.top + x.height / 2).sort((a, b) => a - b); const out = []; for (const t of ts) if (!out.length || t - out.at(-1) > fs0 * 0.7) out.push(t); return out.map((t) => Math.round(t)) }
    const lines = tops(rangeOf(0, raw.length)).length
    if (lines < 2) continue
    const cs = getComputedStyle(el)
    let p = el.parentElement; while (p && getComputedStyle(p).display === 'contents') p = p.parentElement
    const pcs = getComputedStyle(p)
    const avail = p.getBoundingClientRect().width - parseFloat(pcs.paddingLeft) - parseFloat(pcs.paddingRight)
    const own = el.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
    const c = document.createElement('canvas').getContext('2d'); c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
    const ls = parseFloat(cs.letterSpacing) || 0
    const width = (t) => c.measureText(t).width + ls * t.length
    const issues = []
    if (width(text) < avail - 8 && own < avail - 24) issues.push('capped')
    // sentences
    const sents = []; const re = /[^.!?。！？]+(?:[.!?。！？]+["”’)]?|$)/g; let m
    while ((m = re.exec(raw))) { const s = m[0]; if (s.trim()) sents.push({ a: m.index + (s.length - s.trimStart().length), b: m.index + s.trimEnd().length, t: s.trim() }) }
    const real = sents.filter((s) => s.t.length > 2)
    if (isHeading && real.length >= 2) issues.push('heading-multi-sentence')
    if (real.length >= 2) {
      for (const s of real) if (tops(rangeOf(s.a, s.b)).length > 1 && width(s.t) < own - 4) { issues.push('sentence-split'); break }
    }
    // last line words
    const words = []; const wr = /\S+/g; let wm
    while ((wm = wr.exec(raw))) words.push([wm.index, wm.index + wm[0].length])
    const lastTop = tops(rangeOf(raw.length - 1, raw.length))[0]
    let tail = 0; for (let i = words.length - 1; i >= 0; i--) { if (Math.abs(tops(rangeOf(words[i][0], words[i][1]))[0] - lastTop) < fs0 * 0.7) tail++; else break }
    const cjk = /[一-鿿]/.test(text)
    if (!cjk && tail <= 2 && words.length > 4) issues.push(`widow:${tail}`)
    if (cjk) { const lastLine = [...rangeOf(0, raw.length).getClientRects()].filter((x) => Math.abs((x.top + x.height / 2) - lastTop) < fs0 * 0.7).reduce((a, x) => a + x.width, 0); if (lastLine < parseFloat(cs.fontSize) * 3.2) issues.push('widow:cjk') }
    if (isHeading) issues.push('heading-wraps')
    out.push({ tag: el.tagName, text: text.slice(0, 120), lines, issues })
  }
  return out
}

const report = []
const b = await chromium.launch()
for (const locale of locales) for (const wpx of widths) for (const who of ['guest', 'user']) {
  const c = await b.newContext({ viewport: { width: wpx, height: 900 }, ...(wpx < 500 ? { isMobile: true, hasTouch: true } : {}) })
  await c.addInitScript(() => { try { if (!sessionStorage.getItem('l')) localStorage.setItem('locale', 'en') } catch {} })
  const p = await c.newPage(); p.setDefaultTimeout(20000)
  if (who === 'user') await signIn(p, B, alice, null)
  await p.goto(B + '/'); await p.evaluate((l) => { sessionStorage.setItem('l', '1'); localStorage.setItem('locale', l) }, locale)
  for (const path of who === 'guest' ? guest : app) {
    await p.goto(B + path); await p.waitForTimeout(1300)
    for (const r of await p.evaluate(probe)) report.push({ locale, w: wpx, who, path, ...r })
  }
  await c.close()
}
await b.close()
writeFileSync(OUT, JSON.stringify(report, null, 1))
console.log('rows', report.length)
