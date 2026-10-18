/**
 * Which shared files this person has already looked at.
 *
 * The point is a badge that says "two new files were shared with you" rather than a total
 * that never changes. That needs a notion of "already seen", and the smallest honest one is
 * a list of file ids this browser has shown in the shared list.
 *
 * Deliberately local. A server-side read marker would be a new table, a new endpoint and a
 * new set of consistency questions, to make a badge slightly better on a second device. If
 * that turns out to matter, the audit log already records every share with its timestamp
 * and could carry a proper marker later.
 */
const KEY = 'seen_shared_file_ids'

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? new Set(parsed.filter((id): id is string => typeof id === 'string')) : new Set()
  } catch {
    // A private window, cleared storage, or something else in this key. An empty set means
    // everything reads as new, which is a harmless way to be wrong.
    return new Set()
  }
}

/** Ids shared with the viewer that this browser has not shown in the shared list yet. */
export function unseenSharedIds(sharedFileIds: readonly string[]): string[] {
  const seen = read()
  return sharedFileIds.filter((id) => !seen.has(id))
}

export function markSharesSeen(sharedFileIds: readonly string[]): void {
  try {
    // Only ids still shared with the viewer are kept: a revoked file should not sit in this
    // list forever, and if it is ever shared again it is genuinely new.
    localStorage.setItem(KEY, JSON.stringify([...new Set(sharedFileIds)]))
  } catch {
    // Storage unavailable. The badge stays visible, which is the safe direction.
  }
}

export function forgetSeenShares(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // Nothing to do.
  }
}
