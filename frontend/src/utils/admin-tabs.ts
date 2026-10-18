/**
 * The admin console's sections, grouped by what an administrator is doing, and which ones a
 * role may see.
 *
 * Eight flat tabs wrapped onto a second line with one tab left on its own. Grouping them
 * (watch the platform, manage accounts and files, handle recovery) reads better and fits one
 * row on a laptop; on a narrow screen the row scrolls instead of wrapping.
 */

export type AdminTabId =
  | 'overview'
  | 'agent'
  | 'integrity'
  | 'audit'
  | 'users'
  | 'files'
  | 'recovery'
  | 'recovery-key'

export interface AdminTab {
  id: AdminTabId
  label: string
  /** Only administrators; a recovery officer sees the recovery queue alone. */
  adminOnly: boolean
}

export interface AdminTabGroup {
  label: string
  tabs: AdminTab[]
}

const GROUPS: AdminTabGroup[] = [
  {
    label: 'Monitor',
    tabs: [
      { id: 'overview', label: 'Overview', adminOnly: true },
      { id: 'agent', label: 'Security agent', adminOnly: true },
      { id: 'integrity', label: 'Integrity', adminOnly: true },
      { id: 'audit', label: 'Audit chain', adminOnly: true },
    ],
  },
  {
    label: 'Manage',
    tabs: [
      { id: 'users', label: 'Users', adminOnly: true },
      { id: 'files', label: 'Files', adminOnly: true },
    ],
  },
  {
    label: 'Recovery',
    tabs: [
      { id: 'recovery', label: 'Requests', adminOnly: false },
      { id: 'recovery-key', label: 'Recovery key', adminOnly: true },
    ],
  },
]

/** The groups and tabs this role may open, empty groups dropped. */
export function tabGroupsFor(isAdmin: boolean): AdminTabGroup[] {
  return GROUPS.map((group) => ({
    label: group.label,
    tabs: group.tabs.filter((tab) => isAdmin || !tab.adminOnly),
  })).filter((group) => group.tabs.length > 0)
}

/** Where a role lands: the overview for an administrator, the queue for a recovery officer. */
export function defaultTab(isAdmin: boolean): AdminTabId {
  return isAdmin ? 'overview' : 'recovery'
}

/**
 * The tab named in the URL (`?tab=agent`), if this role may open it; otherwise the default.
 * Keeping the tab in the URL means a refresh, the back button or a shared link lands on the
 * same section instead of always on the first one.
 */
export function tabFromQuery(value: unknown, isAdmin: boolean): AdminTabId {
  const allowed = tabGroupsFor(isAdmin).flatMap((group) => group.tabs.map((tab) => tab.id))
  return typeof value === 'string' && (allowed as string[]).includes(value)
    ? (value as AdminTabId)
    : defaultTab(isAdmin)
}

/** The page heading for a role, in the words that role would use. */
export function consoleTitle(role: string | undefined): { title: string; subtitle: string } {
  if (role === 'ADMIN') {
    return {
      title: 'Admin console',
      subtitle:
        'Watch the platform’s security, manage accounts and files, and handle file recovery. ' +
        'Everything here is metadata: no administrator can read a user’s files.',
    }
  }
  if (role === 'RECOVERY_OFFICER') {
    return {
      title: 'Recovery review',
      subtitle: 'Review, approve and carry out requests to regain access to a file.',
    }
  }
  return {
    title: 'Recovery requests',
    subtitle: 'Requests you have made to regain access to a file, and where each one stands.',
  }
}
