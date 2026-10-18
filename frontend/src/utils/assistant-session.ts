/**
 * What the Help assistant remembers: whether it is open and the last few questions.
 *
 * `sessionStorage` only, so it lasts while the tab is open and never outlives it, and is never
 * sent anywhere. Each question keeps the key of the answer it was shown, so a "did you mean"
 * choice comes back as the answer that was picked rather than whatever the words match first.
 *
 * Account answers (v2) are never stored, only the question: after a reload they wait behind a
 * button rather than asking the server again. Signing out forgets the lot, so the next person
 * at this tab does not see what the last one asked about their files.
 */
const KEY = 'help_assistant'

/** Enough to keep the thread across a page change; a long log is noise in a small panel. */
export const MAX_REMEMBERED = 5

export interface RememberedQuestion {
  question: string
  /** The answer shown, or null when the reply was "not sure" or empty. */
  answerKey: string | null
  /** The file a question about one file named, so "check again" asks about the same file. */
  fileName?: string | null
}

export interface AssistantSession {
  open: boolean
  questions: RememberedQuestion[]
}

const EMPTY: AssistantSession = { open: false, questions: [] }

export function readAssistantSession(): AssistantSession {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return EMPTY
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return EMPTY
    const { open, questions } = parsed as Record<string, unknown>
    return {
      open: open === true,
      questions: Array.isArray(questions)
        ? questions
            .filter(
              (q): q is RememberedQuestion =>
                Boolean(q) &&
                typeof (q as RememberedQuestion).question === 'string' &&
                ((q as RememberedQuestion).answerKey === null || typeof (q as RememberedQuestion).answerKey === 'string') &&
                ((q as RememberedQuestion).fileName == null || typeof (q as RememberedQuestion).fileName === 'string'),
            )
            .slice(-MAX_REMEMBERED)
        : [],
    }
  } catch {
    // A private window, blocked storage, or something else in this key: start fresh.
    return EMPTY
  }
}

export function writeAssistantSession(session: AssistantSession): void {
  try {
    sessionStorage.setItem(
      KEY,
      JSON.stringify({ open: session.open, questions: session.questions.slice(-MAX_REMEMBERED) }),
    )
  } catch {
    // Storage unavailable: the assistant still works, it just forgets on reload.
  }
}

/** Signing out: nothing the last person asked stays in this tab. */
export function forgetAssistantSession(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // Storage unavailable, so there is nothing stored to forget.
  }
}
