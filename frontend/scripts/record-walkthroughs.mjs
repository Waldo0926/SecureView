/**
 * Record the Help page's walkthrough videos from the real product.
 *
 *   node scripts/record-walkthroughs.mjs --base http://localhost:5174 \
 *     --accounts /path/to/video-accounts.json --out public/videos
 *
 * It drives a real, running stack (frontend + API + MySQL) in Chromium, the way a person would:
 * it types visibly, outlines each control before clicking it, and shows a caption bar saying
 * what is happening and why. Nothing is mocked: the upload is really encrypted in the browser,
 * really shared by re-wrapping the key, and really decrypted by the recipient.
 *
 * `--accounts` is a JSON file `{ "sam": {username, password, passphrase}, "alex": {...} }` for
 * two existing accounts on that stack (create them with backend/scripts/seed_test_account.py,
 * using made-up names and @example.com addresses). Point it only at a disposable local stack: the
 * credentials are typed on screen and end up in the video's keystrokes (passphrases are masked
 * by the page, but use throwaway values anyway).
 *
 * Output, in `--out`: encrypt-upload.mp4, share-open.mp4 and how-it-works.mp4 (the animated
 * explainer in present mode), each with a .jpg poster. Needs ffmpeg on PATH.
 */

import { mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { chromium } from '@playwright/test'

import { OVERLAY, caption, click, encode, pause, point, signIn as signInAt, signOut, type, unlockIfAsked, unpoint } from './lib/video.mjs'

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, value, i, all) => (value.startsWith('--') ? [...pairs, [value.slice(2), all[i + 1]]] : pairs), []),
)
const BASE = args.base ?? 'http://localhost:5174'
const OUT = resolve(args.out ?? 'public/videos')
const ONLY = args.only ? args.only.split(',') : null
const accounts = JSON.parse(readFileSync(args.accounts, 'utf8'))
// 1920x1080: the page is laid out at that size and recorded at it, so full-screen on a laptop the
// video is as crisp as the site itself. Playwright only ever scales a frame down into the video,
// never up, so the viewport has to be the video size (a 1280x720 page in a 1080p video is padded,
// not enlarged, and a deviceScaleFactor does not change what the screencast delivers).
const SIZE = { width: 1920, height: 1080 }
const FILE_NAME = 'Project notes.txt'
const FILE_TEXT =
  'Project notes\n\nMilestone 3 is due on Friday. Budget review moved to Monday.\n' +
  'These notes are encrypted in the browser before upload; the server stores only ciphertext.\n'

mkdirSync(OUT, { recursive: true })
const work = mkdtempSync(join(tmpdir(), 'sv-video-'))
const signIn = (page, account, step) => signInAt(page, BASE, account, step)

async function recordFlow(name, flow) {
  if (ONLY && !ONLY.includes(name)) return
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: SIZE,
    colorScheme: 'light',
    acceptDownloads: true,
    recordVideo: { dir: work, size: SIZE },
  })
  await context.addInitScript(OVERLAY)
  const page = await context.newPage()
  page.setDefaultTimeout(60_000)
  try {
    await flow(page)
  } finally {
    const video = page.video()
    await context.close()
    await browser.close()
    const raw = await video.path()
    const webm = join(work, `${name}.webm`)
    renameSync(raw, webm)
    encode(webm, OUT, name)
  }
}

// --- 1. Encrypt and upload -----------------------------------------------------------------
await recordFlow('encrypt-upload', async (page) => {
  const sam = accounts.sam
  const file = join(work, FILE_NAME)
  writeFileSync(file, FILE_TEXT)

  await signIn(page, sam, 1)
  await caption(page, 2, 'Open Upload')
  await click(page.getByRole('navigation').getByRole('link', { name: 'Upload', exact: true }))
  await page.getByRole('heading', { name: 'Encrypt Your Files' }).waitFor()

  await caption(page, 3, 'Choose the file to protect', 'Drag it in or use Select Files. Several files at once are fine.')
  const picker = page.locator('label').filter({ hasText: 'Select Files' })
  await point(picker, 1100)
  await page.getByLabel('Select Files').setInputFiles(file)
  await unpoint(picker)
  await pause(page, 1200)

  // The cipher list is a native <select>; its pop-up is drawn by the OS and never reaches the
  // recording. For a few seconds the same element is shown as a six-row list (size=6): the same
  // six options, on their own line under the label, nothing drawn by the script. It is put back
  // before encrypting.
  const cipher = page.locator('#content-algorithm')
  const detail = page.getByTestId('algorithm-detail')
  await cipher.evaluate((select) => {
    select.size = select.options.length
    Object.assign(select.style, { height: 'auto', flexBasis: '100%', width: '100%', fontSize: '12px' })
    select.parentElement.style.flexWrap = 'wrap'
  })
  await caption(page, 4, 'Six ciphers to choose from, each with a grade', 'AES-256-GCM is the default and our recommendation. All six detect tampering.')
  await point(cipher, 3200)
  await unpoint(cipher)
  await caption(page, 4, 'Pick one to read what it is good at', 'The box under the list explains the cipher you choose, in plain words.')
  for (const choice of ['ChaCha20-Poly1305', 'AES-128-GCM']) {
    await cipher.selectOption(choice)
    await point(detail, 2400)
    await unpoint(detail)
  }
  const education = page.getByRole('navigation').getByRole('link', { name: 'Education', exact: true })
  await caption(page, 4, 'Want the details? Education explains each one', 'The Education page goes through every cipher step by step.')
  await point(education, 2400)
  await unpoint(education)
  await cipher.selectOption('AES-256-GCM')
  await point(detail, 1400)
  await unpoint(detail)
  await cipher.evaluate((select) => {
    select.removeAttribute('size')
    for (const name of ['height', 'flex-basis', 'width', 'font-size']) select.style.removeProperty(name)
    select.parentElement.style.removeProperty('flex-wrap')
  })
  await pause(page, 600)

  await caption(page, 5, 'Start Encryption', 'Your browser encrypts the file with a new random key. Only the scrambled result is uploaded.')
  await click(page.getByRole('button', { name: 'Start Encryption' }), 1000)
  await page.getByTestId('encryption-complete').waitFor({ timeout: 60_000 })
  const steps = page.getByTestId('encryption-progress')
  await caption(page, 5, 'Every step is real and timed', 'Read, encrypt and self-check, wrap the key, upload. The bytes below are the file’s real first bytes and what the server received.')
  await point(steps, 4500)
  await unpoint(steps)
  const done = page.getByTestId('encryption-complete')
  await caption(page, 5, 'Encryption Complete', 'A status, not a button: the file is already uploaded, so there is nothing to press twice.')
  await point(done, 2200)
  await unpoint(done)

  await caption(page, 6, 'Your file is now stored encrypted')
  await click(page.getByRole('button', { name: 'View Encrypted Files' }))
  const row = page.getByRole('row').filter({ hasText: FILE_NAME }).first()
  await row.waitFor()
  await caption(page, 6, 'Same size before and after — that is expected', 'The authentication tag and nonce are stored separately, so the ciphertext is exactly as long as the file.')
  await point(row, 2600)
  await unpoint(row)

  await caption(page, 7, 'Encrypted preview: what the server actually holds', 'Random-looking bytes. A text file would start with readable letters; this does not.')
  await click(row.getByRole('button', { name: 'Encrypted preview' }))
  const preview = page.getByTestId('ciphertext-preview').first()
  await point(preview, 4500)
  await unpoint(preview)
  await caption(page, '✓', 'Done. Next: share it with someone, in the second video.')
  await pause(page, 2500)
})

// --- 2. Share, and the recipient opens it ----------------------------------------------------
await recordFlow('share-open', async (page) => {
  const sam = accounts.sam
  const alex = accounts.alex

  await signIn(page, sam, 1)
  await caption(page, 2, 'In My Files, press Share on the file')
  await click(page.getByRole('navigation').getByRole('link', { name: 'My Files', exact: true }))
  const row = page.getByRole('row').filter({ hasText: FILE_NAME }).first()
  await row.waitFor()
  await click(row.getByRole('button', { name: 'Share', exact: true }))
  // Sharing needs Sam's key, so every share asks for the passphrase first.
  await unlockIfAsked(page, sam, 3)
  await page.getByRole('heading', { name: 'Share this file' }).waitFor()

  const recipientField = page.getByRole('textbox', { name: /their username/i })
  await caption(page, 4, `Enter the other person’s username: ${alex.username}`, 'They need a SecureView account. There is no public link that could leak.')
  await type(recipientField, alex.username)
  const dialog = page.locator('form').filter({ has: recipientField })
  await click(dialog.getByRole('button', { name: 'Share', exact: true }), 900)
  const fingerprint = page.getByTestId('recipient-fingerprint')
  await fingerprint.waitFor()
  await caption(page, 5, `Check who it goes to: ${alex.username}’s key fingerprint`, 'For a sensitive file, Alex reads out the fingerprint from Settings. If it matches, only Alex can open it.')
  await point(fingerprint, 2600)
  await unpoint(fingerprint)
  await caption(page, 5, 'Confirm and share', 'Your browser re-seals the file key for that exact key. The file itself is not copied.')
  await click(page.getByRole('button', { name: 'Confirm and share', exact: true }), 900)
  await page.getByText(`Shared with ${alex.username}`).first().waitFor({ timeout: 60_000 })
  await caption(page, 6, `Shared with ${alex.username}`, 'You can revoke this at any time from the same dialog.')
  await pause(page, 2600)
  await page.getByRole('button', { name: 'Cancel' }).click().catch(() => {})
  await signOut(page)

  await signIn(page, alex, 7)
  await caption(page, 8, 'Alex finds it under Shared with me')
  await click(page.getByRole('navigation').getByRole('link', { name: 'My Files', exact: true }))
  await click(page.getByRole('button', { name: /^Shared with me/ }))
  const shared = page.getByRole('row').filter({ hasText: FILE_NAME }).first()
  await shared.waitFor()
  await point(shared, 1600)
  await unpoint(shared)

  await caption(page, 9, 'Download and decrypt', 'Alex uses Alex’s own passphrase. Nobody had to send anyone a password.')
  await click(shared.getByRole('button', { name: 'Download and decrypt' }))
  await unlockIfAsked(page, alex, 10)
  await page.getByText(`Decrypted and saved ${FILE_NAME}`).first().waitFor({ timeout: 60_000 })
  await caption(page, 11, 'Decrypted and checked', 'The authentication tag and SHA-256 matched, so this is exactly the file Sam uploaded.')
  await pause(page, 2800)

  await caption(page, 12, 'Keep shared files in folders of your own', 'Folders are private: filing it here does not change where Sam keeps it.')
  const folderName = page.getByRole('textbox', { name: 'New folder name' })
  await type(folderName, 'From Sam')
  await click(page.getByRole('button', { name: 'Add', exact: true }))
  await page.getByText('Created folder From Sam').first().waitFor()
  await click(page.getByRole('button', { name: 'All files' }))
  const folderSelect = shared.getByLabel(`Folder for ${FILE_NAME}`)
  await point(folderSelect, 900)
  await folderSelect.selectOption({ label: 'From Sam' })
  await unpoint(folderSelect)
  await page.getByText(`Moved ${FILE_NAME} to From Sam`).first().waitFor()
  await click(page.getByRole('button', { name: 'From Sam (1)' }))
  await point(shared, 1800)
  await unpoint(shared)
  await caption(page, '✓', 'Shared, opened and filed', 'Sam can revoke access at any time; Alex’s folder simply becomes empty.')
  await pause(page, 3000)
})

// --- 3. The animated explainer, in present mode --------------------------------------------------
await recordFlow('how-it-works', async (page) => {
  await page.goto(`${BASE}/how-it-works?present`)
  await page.getByTestId('story-present').waitFor()
  // Seven scenes at eight seconds each, and a moment on the last one.
  await pause(page, 7 * 8000 + 2500)
})

rmSync(work, { recursive: true, force: true })
