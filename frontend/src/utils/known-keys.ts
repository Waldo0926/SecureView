/**
 * The recipient keys this browser has shared to before, so a changed key is noticed.
 *
 * The same idea as SSH's known_hosts or Signal's safety numbers: the first share trusts the key
 * the server returns, and later shares compare against it. A change is not always an attack (a
 * recipient can legitimately move to a new key), so the share dialog warns rather than refuses.
 * Kept per device in localStorage; if storage is unavailable nothing is remembered and every
 * share looks like a first one.
 */
const STORAGE_KEY = 'secureview.knownRecipientKeys'

type KnownKeys = Record<string, string>

function read(): KnownKeys {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? (parsed as KnownKeys) : {}
  } catch {
    return {}
  }
}

/** The fingerprint last shared to for this recipient account, or null if never. */
export function knownFingerprint(recipientUserId: string): string | null {
  return read()[recipientUserId] ?? null
}

export function rememberFingerprint(recipientUserId: string, fingerprint: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...read(), [recipientUserId]: fingerprint }))
  } catch {
    // Private windows and blocked storage: the warning simply cannot be offered next time.
  }
}
