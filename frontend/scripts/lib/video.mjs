/**
 * Shared pieces for the scripts that record videos from the real product
 * (record-walkthroughs.mjs for the Help page, record-demo.mjs for the presentation backup).
 *
 * Everything here acts on a real page the way a person would: it outlines a control before using
 * it, types visibly, and shows a caption bar saying what is happening and why.
 */

import { execFileSync } from 'node:child_process'
import { join } from 'node:path'

/**
 * Injected into every page: a caption bar along the bottom, an optional "whose screen is this"
 * badge in the top-left corner, and an outline for the control about to be used.
 */
export const OVERLAY = `
(() => {
  const css = \`
    #sv-cap { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 2147483647;
      max-width: 1100px; width: calc(100% - 64px); display: flex; gap: 14px; align-items: center;
      padding: 14px 20px; border-radius: 16px; background: rgba(255, 255, 255, 0.96); color: #0f172a;
      border: 1px solid rgba(15, 23, 42, 0.14);
      font: 500 20px/1.4 system-ui, -apple-system, Segoe UI, sans-serif; box-shadow: 0 8px 24px rgba(15, 23, 42, .16);
      transition: opacity .3s; }
    #sv-cap[hidden], #sv-who[hidden] { display: none; }
    #sv-cap b { flex: none; display: inline-flex; align-items: center; justify-content: center;
      min-width: 38px; height: 38px; border-radius: 999px; background: rgb(0, 109, 199); color: #fff; font-size: 17px; }
    #sv-cap small { display: block; font-weight: 400; color: #475569; font-size: 16px; margin-top: 2px; }
    #sv-who { position: fixed; left: 16px; top: 84px; z-index: 2147483647; padding: 6px 14px;
      border-radius: 999px; color: #fff; font: 600 18px/1.4 system-ui, -apple-system, Segoe UI, sans-serif;
      box-shadow: 0 6px 18px rgba(0,0,0,.2); }
    .sv-focus { outline: 3px solid rgb(0, 109, 199) !important; outline-offset: 4px !important;
      border-radius: 8px; box-shadow: 0 0 0 9px rgba(0, 109, 199, .18) !important; transition: outline-color .2s; }
  \`;
  const install = () => {
    if (document.getElementById('sv-cap')) return;
    const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
    const cap = document.createElement('div'); cap.id = 'sv-cap'; cap.hidden = true; document.body.appendChild(cap);
    const who = document.createElement('div'); who.id = 'sv-who'; who.hidden = true; document.body.appendChild(who);
    const saved = sessionStorage.getItem('sv-cap');
    if (saved) window.__svCaption(...JSON.parse(saved));
    const savedWho = sessionStorage.getItem('sv-who');
    if (savedWho) window.__svWho(...JSON.parse(savedWho));
  };
  window.__svCaption = (step, text, sub) => {
    sessionStorage.setItem('sv-cap', JSON.stringify([step, text, sub]));
    const cap = document.getElementById('sv-cap'); if (!cap) return;
    cap.hidden = !text;
    cap.innerHTML = (step ? '<b>' + step + '</b>' : '') + '<div>' + (text || '') + (sub ? '<small>' + sub + '</small>' : '') + '</div>';
  };
  window.__svWho = (label, colour) => {
    sessionStorage.setItem('sv-who', JSON.stringify([label, colour]));
    const who = document.getElementById('sv-who'); if (!who) return;
    who.hidden = !label; who.textContent = label || ''; who.style.background = colour || 'rgb(0, 109, 199)';
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
`

export const pause = (page, ms) => page.waitForTimeout(ms)

/** Show a caption and hold it long enough to be read: about 45 ms a character, 1.8–5 s. */
export async function caption(page, step, text, sub = '') {
  await page.evaluate(([s, t, u]) => window.__svCaption?.(s, t, u), [step, text, sub])
  await page.waitForTimeout(Math.min(5000, Math.max(1800, (text.length + sub.length) * 45)))
}

/** Label whose screen this is, for videos that cut between two people. */
export async function who(page, label, colour) {
  await page.evaluate(([l, c]) => window.__svWho?.(l, c), [label, colour])
}

/** Outline a control, give the viewer a moment to see it, then act on it. */
export async function point(locator, ms = 900) {
  // Centre it, so the caption bar along the bottom never covers what it is talking about.
  await locator.evaluate((el) => {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    el.classList.add('sv-focus')
  })
  await locator.page().waitForTimeout(ms)
}
export async function unpoint(locator) {
  // The control is often gone by now (a click that navigates), so do not wait for it.
  await locator.evaluate((el) => el.classList.remove('sv-focus'), null, { timeout: 500 }).catch(() => {})
}
export async function click(locator, ms) {
  await point(locator, ms)
  await locator.click()
  await unpoint(locator)
}
export async function type(locator, text, { secret = false } = {}) {
  await point(locator, 500)
  await locator.click()
  await locator.pressSequentially(text, { delay: secret ? 25 : 55 })
  await unpoint(locator)
}

export async function signIn(page, base, account, step) {
  await page.goto(`${base}/login`)
  if (step !== null) {
    await caption(page, step, `Sign in as ${account.username} with the account password`, 'The password only signs you in. It does not open your files.')
  }
  await type(page.getByRole('textbox', { name: 'Username' }), account.username)
  await type(page.getByRole('textbox', { name: /^Password/ }), account.password, { secret: true })
  await click(page.getByRole('button', { name: 'Login' }), 500)
  await page.getByRole('heading', { name: 'Your Workspace' }).waitFor()
  await pause(page, 900)
}

export async function signOut(page) {
  await page.getByRole('button', { name: /^Account menu for/ }).hover()
  await pause(page, 500)
  await page.getByRole('menuitem', { name: 'Log out' }).click()
  await page.getByRole('heading', { name: 'Sign In' }).waitFor()
}

export async function unlockIfAsked(page, account, step, text = 'Unlock your key with the encryption passphrase') {
  const heading = page.getByRole('heading', { name: 'Unlock your files' })
  if (!(await heading.isVisible().catch(() => false))) {
    await heading.waitFor({ timeout: 4000 }).catch(() => {})
  }
  if (!(await heading.isVisible().catch(() => false))) return
  await caption(page, step, text, 'It opens the private key here in the browser. It is never sent to the server.')
  await type(page.getByRole('textbox', { name: /^Encryption passphrase/ }), account.passphrase, { secret: true })
  await click(page.getByRole('button', { name: 'Unlock', exact: true }), 500)
}

/** H.264 MP4 that plays everywhere, with the first blank half-second trimmed, plus a poster. */
export function encode(webm, outDir, name, posterAt = 4) {
  const mp4 = join(outDir, `${name}.mp4`)
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-ss', '0.6', '-i', webm, '-an', '-c:v', 'libx264',
    '-preset', 'slow', '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', mp4])
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-ss', String(posterAt), '-i', mp4, '-frames:v', '1',
    '-q:v', '4', join(outDir, `${name}.jpg`)])
  console.log(`wrote ${mp4}`)
  return mp4
}
