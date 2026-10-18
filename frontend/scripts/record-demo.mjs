/**
 * Record the backup video for the presentation's four-minute live demo
 * (docs/presentation/DEMO_SCRIPT.md), from the real product.
 *
 *   node scripts/record-demo.mjs --base http://localhost:5173 \
 *     --accounts /path/to/video-accounts.json --tamper /path/to/tamper.sh --out /path/to/dir
 *
 * Two people, two browsers: Alice and Bob are separate browser contexts, each recorded. The
 * script follows the demo step by step and then cuts the two recordings together in the order
 * the audience would see them, with a label saying whose screen it is. Step 4 really changes the
 * stored file: `--tamper` is a command that runs backend/scripts/demo_tamper.py against the same
 * stack, and the card in the video shows that command's real output. The file is restored at
 * the end.
 *
 * `--accounts` is `{ "alice": {username, password, passphrase}, "bob": {...} }`; the usernames
 * must start with `demo-` (the tamper tool refuses anything else). Point it only at a disposable
 * local stack. Needs ffmpeg on PATH. Output: demo-backup.mp4 and a .jpg poster.
 */

import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { chromium } from '@playwright/test'

import { OVERLAY, caption as show, click, pause, point, signIn, type, unlockIfAsked, unpoint, who } from './lib/video.mjs'

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, value, i, all) => (value.startsWith('--') ? [...pairs, [value.slice(2), all[i + 1]]] : pairs), []),
)
const BASE = args.base ?? 'http://localhost:5173'
const OUT = resolve(args.out ?? '.')
const TAMPER = args.tamper
const accounts = JSON.parse(readFileSync(args.accounts, 'utf8'))
const { alice, bob } = accounts
const SIZE = { width: 1280, height: 720 }
const LIVE_FILE = 'board-minutes.pdf'
const TAMPER_FILE = 'quarterly-results.txt'
const ALICE = ['Alice’s browser', 'rgb(0, 109, 199)']
const BOB = ['Bob’s browser', 'rgb(124, 58, 237)']

if (!TAMPER) throw new Error('Pass --tamper, a command that runs demo_tamper.py against this stack')
if (![alice, bob].every((a) => a?.username?.startsWith('demo-'))) throw new Error('Both accounts must be demo-*')
mkdirSync(OUT, { recursive: true })
const work = mkdtempSync(join(tmpdir(), 'sv-demo-'))

/** A one-page PDF, so the byte comparison shows the real `%PDF` header turning into noise. */
function minimalPdf(text) {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    null,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  const stream = `BT /F1 18 Tf 72 760 Td (${text}) Tj ET`
  objects[3] = `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`
  let pdf = '%PDF-1.7\n'
  const offsets = objects.map((body, i) => {
    const at = pdf.length
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`
    return at
  })
  const xref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return pdf
}

function tamper(...rest) {
  return execFileSync('bash', [TAMPER, ...rest, '--owner', alice.username], { encoding: 'utf8' }).trim()
}
function tamperFileId() {
  const line = tamper('list').split('\n').find((l) => l.trim().endsWith(TAMPER_FILE))
  if (!line) throw new Error(`${alice.username} has no ${TAMPER_FILE}; the setup should have uploaded it`)
  return { id: line.trim().split(/\s+/)[0], tampered: line.includes('TAMPERED') }
}

const myFiles = (page) => page.getByRole('navigation').getByRole('link', { name: 'My Files', exact: true })
const rowFor = (page, name) => page.getByRole('row').filter({ hasText: name }).first()

/**
 * Not recorded: put both accounts in the state the demo starts from. Alice owns the pre-shared
 * TAMPER_FILE (shared with Bob) and has no earlier copy of LIVE_FILE; nothing is left tampered.
 */
async function prepare(browser) {
  const existing = (() => { try { return tamperFileId() } catch { return null } })()
  if (existing?.tampered) tamper('restore', '--file-id', existing.id)

  const context = await browser.newContext({ viewport: SIZE })
  const page = await context.newPage()
  page.setDefaultTimeout(60_000)
  await signIn(page, BASE, alice, null)
  await myFiles(page).click()
  await page.getByRole('heading', { name: 'Manage Encrypted Files' }).waitFor()
  await pause(page, 1500)

  while (await rowFor(page, LIVE_FILE).isVisible().catch(() => false)) {
    await rowFor(page, LIVE_FILE).getByRole('button', { name: 'Delete', exact: true }).click()
    await page.getByRole('button', { name: 'Delete file' }).click()
    await page.getByText(`Deleted ${LIVE_FILE}`).first().waitFor()
    await pause(page, 800)
  }

  if (!(await rowFor(page, TAMPER_FILE).isVisible().catch(() => false))) {
    const file = join(work, TAMPER_FILE)
    writeFileSync(file, 'Quarterly results: confidential.\n'.repeat(200))
    await page.getByRole('navigation').getByRole('link', { name: 'Upload', exact: true }).click()
    await page.getByLabel('Select Files').setInputFiles(file)
    await page.getByRole('button', { name: 'Start Encryption' }).click()
    await page.getByTestId('encryption-complete').waitFor({ timeout: 60_000 })
    await myFiles(page).click()
    await rowFor(page, TAMPER_FILE).waitFor()
  }

  // Share it with Bob unless that is already done.
  await rowFor(page, TAMPER_FILE).getByRole('button', { name: 'Share', exact: true }).click()
  const unlockHeading = page.getByRole('heading', { name: 'Unlock your files' })
  const shareHeading = page.getByRole('heading', { name: 'Share this file' })
  await Promise.race([unlockHeading.waitFor(), shareHeading.waitFor()])
  if (await unlockHeading.isVisible()) {
    await page.getByRole('textbox', { name: /^Encryption passphrase/ }).fill(alice.passphrase)
    await page.getByRole('button', { name: 'Unlock', exact: true }).click()
  }
  await shareHeading.waitFor()
  await pause(page, 1500)
  const dialog = page.locator('.fixed.inset-0').filter({ has: shareHeading })
  if (!(await dialog.getByText(bob.username, { exact: true }).isVisible().catch(() => false))) {
    await page.getByRole('textbox', { name: /their username/i }).fill(bob.username)
    await dialog.getByRole('button', { name: 'Share', exact: true }).click()
    await page.getByRole('button', { name: 'Confirm and share', exact: true }).click()
    await page.getByText(`Shared with ${bob.username}`).first().waitFor()
  } else {
    await dialog.getByRole('button', { name: 'Cancel' }).click().catch(() => page.keyboard.press('Escape'))
  }
  await context.close()
}

/** A recorded browser for one person, with the cut points the final video is assembled from. */
async function person(browser, account, label) {
  const context = await browser.newContext({ viewport: SIZE, colorScheme: 'light', acceptDownloads: true, recordVideo: { dir: work, size: SIZE } })
  await context.addInitScript(OVERLAY)
  const page = await context.newPage()
  const started = Date.now()
  page.setDefaultTimeout(60_000)
  const cuts = []
  let open = null
  let openAt = 0
  return {
    page,
    account,
    async signInQuietly() {
      await signIn(page, BASE, account, null)
      await who(page, ...label)
    },
    /** Start a piece of this person's screen that goes into the video. */
    async show() {
      await pause(page, 300)
      open = Date.now() - started
      openAt = Date.now()
    },
    async hide() {
      await pause(page, 400)
      cuts.push({ from: open / 1000, to: (Date.now() - started) / 1000, at: openAt })
      open = null
    },
    cuts,
    async finish() {
      const video = page.video()
      await context.close()
      return video.path()
    },
  }
}

/** A full-screen card (title, the attacker's terminal, the closing line), recorded as its own clip. */
async function card(browser, html, seconds) {
  const context = await browser.newContext({ viewport: SIZE, recordVideo: { dir: work, size: SIZE } })
  const page = await context.newPage()
  const started = Date.now()
  const at = started
  // The bar keeps the page repainting: a still page produces almost no frames in the recording,
  // and a clip cut from it comes out blank.
  await page.setContent(`<!doctype html><html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0f172a;color:#f8fafc;font:500 24px/1.5 system-ui,-apple-system,Segoe UI,sans-serif">${html}
    <div style="position:fixed;left:0;bottom:0;height:4px;background:rgb(0,109,199);animation:grow ${seconds}s linear forwards"></div>
    <style>@keyframes grow{from{width:0}to{width:100%}}</style></body></html>`)
  const from = (Date.now() - started) / 1000 + 0.3
  await page.waitForTimeout(seconds * 1000)
  const to = (Date.now() - started) / 1000
  const video = page.video()
  await context.close()
  return { path: await video.path(), cuts: [{ from, to, at }] }
}

/** Captions stay up longer than in the Help videos: an audience is reading while someone talks. */
async function caption(page, ...rest) {
  await show(page, ...rest)
  await pause(page, 1500)
}

const escapeHtml = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c])

const browser = await chromium.launch()
const clips = []
try {
  await prepare(browser)
  const { id: tamperId } = tamperFileId()

  clips.push(await card(browser, `<div style="max-width:900px;text-align:center">
      <div style="font-size:18px;color:#94a3b8;letter-spacing:.12em;text-transform:uppercase">SecureView · live demo, recorded</div>
      <div style="font-size:40px;font-weight:700;margin:18px 0">Alice sends Bob a confidential report</div>
      <div style="color:#cbd5e1">Neither of them trusts the server. Watch what it can and cannot do.</div></div>`, 6))

  const a = await person(browser, alice, ALICE)
  const b = await person(browser, bob, BOB)
  await a.signInQuietly()
  await b.signInQuietly()
  await a.page.getByRole('navigation').getByRole('link', { name: 'Upload', exact: true }).click()
  await a.page.getByRole('heading', { name: 'Encrypt Your Files' }).waitFor()
  const pdf = join(work, LIVE_FILE)
  writeFileSync(pdf, minimalPdf('Board minutes - confidential'))

  // 1. Upload
  await a.show()
  await caption(a.page, 1, 'Alice encrypts the report in her own browser', 'The file is encrypted here, before anything is uploaded.')
  const picker = a.page.locator('label').filter({ hasText: 'Select Files' })
  await point(picker, 900)
  await a.page.getByLabel('Select Files').setInputFiles(pdf)
  await unpoint(picker)
  await pause(a.page, 800)
  await caption(a.page, 1, 'Start Encryption', 'A fresh random key for this file, then that key is sealed with Alice’s public key.')
  await click(a.page.getByRole('button', { name: 'Start Encryption' }), 900)
  await a.page.getByTestId('encryption-complete').waitFor({ timeout: 60_000 })
  const steps = a.page.getByTestId('encryption-progress')
  await caption(a.page, 1, 'Every step is real and timed', 'Read, encrypt and self-check, wrap the key, upload the ciphertext.')
  await point(steps, 2500)
  const bytes = a.page.getByTestId('byte-comparison')
  await unpoint(steps)
  await caption(a.page, 1, 'The file starts %PDF. What the server received is noise.', 'These are the real first bytes of this upload, before and after encryption.')
  await point(bytes, 3500)
  await unpoint(bytes)
  await a.hide()

  // 2. Share, checking the fingerprint
  await a.page.getByRole('button', { name: 'View Encrypted Files' }).click()
  const liveRow = rowFor(a.page, LIVE_FILE)
  await liveRow.waitFor()
  await a.show()
  await caption(a.page, 2, 'Alice shares it with Bob', 'Sharing is to a named account, never a public link.')
  await click(liveRow.getByRole('button', { name: 'Share', exact: true }))
  await unlockIfAsked(a.page, alice, 2, 'Alice unlocks her key with her passphrase')
  await a.page.getByRole('heading', { name: 'Share this file' }).waitFor()
  await type(a.page.getByRole('textbox', { name: /their username/i }), bob.username)
  const shareDialog = a.page.locator('form').filter({ has: a.page.getByRole('textbox', { name: /their username/i }) })
  await click(shareDialog.getByRole('button', { name: 'Share', exact: true }), 700)
  const theirFingerprint = a.page.getByTestId('recipient-fingerprint')
  await theirFingerprint.waitFor()
  await caption(a.page, 2, 'Before anything is sent: which key will this be locked to?', 'This is the fingerprint of Bob’s public key, computed here in Alice’s browser.')
  await point(theirFingerprint, 3000)
  await unpoint(theirFingerprint)
  await a.hide()

  await b.page.goto(`${BASE}/settings`)
  const own = b.page.getByTestId('own-key-fingerprint')
  await own.waitFor()
  await b.show()
  await caption(b.page, 2, 'Bob reads his fingerprint from his own Settings', 'It matches what Alice sees, so only Bob can open the file.')
  await point(own, 3500)
  await unpoint(own)
  await b.hide()

  await a.show()
  await caption(a.page, 2, 'They match. Confirm and share.', 'The browser re-seals the file key for exactly that key. The server never had it.')
  await click(a.page.getByRole('button', { name: 'Confirm and share', exact: true }), 800)
  await a.page.getByText(`Shared with ${bob.username}`).first().waitFor()
  await pause(a.page, 1500)
  await a.hide()

  // 3. Bob opens it
  await myFiles(b.page).click()
  await b.page.getByRole('button', { name: /^Shared with me/ }).click()
  const bobRow = rowFor(b.page, LIVE_FILE)
  await bobRow.waitFor()
  await b.show()
  await caption(b.page, 3, 'Bob finds it under Shared with me')
  await point(bobRow, 1500)
  await unpoint(bobRow)
  await caption(b.page, 3, 'Download and decrypt', 'Checked on the way out, then decrypted on Bob’s device.')
  await click(bobRow.getByRole('button', { name: 'Download and decrypt' }))
  await unlockIfAsked(b.page, bob, 3, 'Bob uses his own passphrase, never Alice’s')
  await b.page.getByText(`Decrypted and saved ${LIVE_FILE}`).first().waitFor({ timeout: 60_000 })
  await caption(b.page, 3, 'Decrypted and verified', 'Exactly the file Alice uploaded. Nobody sent anyone a password.')
  await pause(b.page, 1500)
  await b.hide()

  // 4. Tamper: really change the stored file, then show the command and its output.
  const command = `demo_tamper.py flip --owner ${alice.username} --file-id ${tamperId}`
  const output = tamper('flip', '--file-id', tamperId)
  clips.push(await card(browser, `<div style="width:980px">
      <div style="font-size:18px;color:#94a3b8;margin-bottom:14px">4 · Now someone with access to the server changes a stored file</div>
      <pre style="margin:0;padding:24px 28px;border-radius:14px;background:#020617;border:1px solid #334155;font:500 19px/1.6 ui-monospace,Menlo,monospace;white-space:pre-wrap;color:#e2e8f0"><span style="color:#22c55e">root@server</span>:~# ${escapeHtml(command)}
${escapeHtml(output)}</pre>
      <div style="color:#cbd5e1;margin-top:16px">One byte of <b>${TAMPER_FILE}</b>, which Alice shared with Bob earlier.</div></div>`, 8))

  // Re-list without reloading: a reload would forget Bob's unlocked key.
  await b.page.getByRole('button', { name: /^My Files/ }).click()
  await pause(b.page, 800)
  await b.page.getByRole('button', { name: /^Shared with me/ }).click()
  const changed = rowFor(b.page, TAMPER_FILE)
  await changed.waitFor()
  await b.show()
  await caption(b.page, 4, `Bob downloads ${TAMPER_FILE}`)
  await click(changed.getByRole('button', { name: 'Download and decrypt' }))
  await unlockIfAsked(b.page, bob, 4)
  await b.page.getByText('The encrypted file could not be verified').first().waitFor({ timeout: 60_000 })
  const status = changed.getByRole('button', { name: 'Modified' })
  await caption(b.page, 4, 'Refused: the stored copy has been changed', 'The server checks every file before sending it. Changed means refused; nobody had to trust us.')
  await point(status, 3500)
  await unpoint(status)
  await b.hide()

  clips.push(await card(browser, `<div style="max-width:960px;text-align:center">
      <div style="font-size:34px;font-weight:700;line-height:1.35">Encrypted before it leaves the device.<br>Opened only by the named person.<br>Refused if changed.</div>
      <div style="color:#94a3b8;margin-top:22px;font-size:18px">SecureView · MCS21</div></div>`, 6))

  const aPath = await a.finish()
  const bPath = await b.finish()

  // Assemble in the order things happened: every piece carries the wall-clock time it started.
  const ordered = [
    ...clips.map((c) => ({ path: c.path, ...c.cuts[0] })),
    ...a.cuts.map((c) => ({ path: aPath, ...c })),
    ...b.cuts.map((c) => ({ path: bPath, ...c })),
  ].sort((x, y) => x.at - y.at)

  const inputs = ordered.flatMap((p) => ['-ss', p.from.toFixed(2), '-to', p.to.toFixed(2), '-i', p.path])
  const filter = ordered.map((_, i) => `[${i}:v]setpts=PTS-STARTPTS,fps=25,format=yuv420p[v${i}]`).join(';') +
    ';' + ordered.map((_, i) => `[v${i}]`).join('') + `concat=n=${ordered.length}:v=1:a=0[out]`
  const mp4 = join(OUT, 'demo-backup.mp4')
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', ...inputs, '-filter_complex', filter, '-map', '[out]',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '28', '-movflags', '+faststart', mp4])
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-ss', '2', '-i', mp4, '-frames:v', '1', '-q:v', '4', join(OUT, 'demo-backup.jpg')])
  const seconds = Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', mp4], { encoding: 'utf8' }))
  console.log(`wrote ${mp4} (${seconds.toFixed(0)} s, ${ordered.length} pieces)`)
} finally {
  // Never leave the demo file tampered with.
  try {
    const now = tamperFileId()
    if (now.tampered) console.log(tamper('restore', '--file-id', now.id))
  } catch (error) {
    console.error('restore check failed:', error.message)
  }
  await browser.close()
  rmSync(work, { recursive: true, force: true })
}
