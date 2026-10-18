/**
 * Small helpers shared by the admin Users and Files lists.
 */

/** Case-insensitive substring match across the given fields; an empty query matches all. */
export function matchesSearch(query: string, ...fields: (string | null | undefined)[]): boolean {
  const needle = query.trim().toLocaleLowerCase()
  if (!needle) return true
  return fields.some((field) => field?.toLocaleLowerCase().includes(needle))
}

/**
 * The badge colour for an account or file status. Colour is never the only signal: the status
 * word is always printed in the badge.
 */
export function statusBadgeClass(status: string): string {
  switch (status) {
    case 'ACTIVE':
      return 'bg-primary/10 text-primary'
    case 'DISABLED':
      return 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
    case 'CORRUPTED':
      return 'bg-destructive/10 text-destructive'
    default:
      return 'bg-secondary text-muted-foreground'
  }
}
