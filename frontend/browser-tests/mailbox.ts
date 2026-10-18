import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Verification mail, read back from the directory `backend/tests/e2e/live_server.py`
 * writes it to -- the same mechanism the Node live suite uses. Nothing is ever sent.
 */
const MAILBOX = process.env.E2E_MAILBOX_DIR!
const consumed = new Set<string>()

/** The newest unread verification code sent to `email`, or undefined if none has arrived. */
export function takeVerificationCode(email: string): string | undefined {
  const names = readdirSync(MAILBOX)
    .filter((name) => name.endsWith('.json') && !consumed.has(name))
    .sort()
    .reverse()
  for (const name of names) {
    const message = JSON.parse(readFileSync(join(MAILBOX, name), 'utf8')) as {
      to: string
      text: string
    }
    if (message.to !== email) continue
    const match = /Verification code: (\d+)/.exec(message.text)
    if (!match) continue
    consumed.add(name)
    return match[1]
  }
  return undefined
}
