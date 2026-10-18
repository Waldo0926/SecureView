/**
 * Human labels for the audit vocabulary the API actually answers with.
 *
 * The records page compared `log.action` against the literal `'download'`, which no audit
 * entry has ever been. The backend writes `FILE_DOWNLOAD_AUTHORIZED` when a download is
 * served, so the Downloads counter read zero no matter how many files had been downloaded,
 * every event fell through to being counted as a view, and the raw enum name was rendered
 * to the user. Read as "downloads are not being recorded" -- they were, all along.
 */
export type AuditCategory = 'download' | 'share' | 'other'

interface AuditActionInfo {
  label: string
  category: AuditCategory
}

const ACTIONS: Record<string, AuditActionInfo> = {
  FILE_UPLOADED: { label: 'Uploaded', category: 'other' },
  FILE_DOWNLOAD_AUTHORIZED: { label: 'Downloaded', category: 'download' },
  FILE_DOWNLOAD_INTEGRITY_FAILED: { label: 'Download blocked: integrity check failed', category: 'download' },
  FILE_INTEGRITY_CHECKED: { label: 'Integrity checked', category: 'other' },
  // Looking at the first bytes of the stored ciphertext is not a download and must never be
  // counted as one.
  FILE_RESTORED_FROM_BACKUP: { label: 'Restored from backup', category: 'other' },
  INTEGRITY_SWEEP_COMPLETED: { label: 'Integrity scan completed', category: 'other' },
  FILE_CIPHERTEXT_PREVIEWED: { label: 'Encrypted preview viewed', category: 'other' },
  FILE_SHARED: { label: 'Shared', category: 'share' },
  FILE_ACCESS_REVOKED: { label: 'Access revoked', category: 'share' },
  FILE_DELETED: { label: 'Deleted', category: 'other' },
  RECOVERY_REQUEST_CREATED: { label: 'Recovery requested', category: 'other' },
  RECOVERY_REQUEST_APPROVED: { label: 'Recovery request approved', category: 'other' },
  RECOVERY_REQUEST_REJECTED: { label: 'Recovery request rejected', category: 'other' },
  RECOVERY_REQUEST_EXECUTED: { label: 'Recovery executed', category: 'other' },
  RECOVERY_REQUEST_CANCELLED: { label: 'Recovery cancelled', category: 'other' },
  // The rest of the server's vocabulary, so the event type filter can name every action the
  // API will accept rather than leaving these to the title-case fallback.
  RECOVERY_KEY_REGISTERED: { label: 'Recovery key registered', category: 'other' },
  RECOVERY_KEY_ROTATED: { label: 'Recovery key rotated', category: 'other' },
  RECOVERY_KEY_REVOKED: { label: 'Recovery key revoked', category: 'other' },
  AVATAR_UPLOADED: { label: 'Avatar uploaded', category: 'other' },
  AVATAR_DELETED: { label: 'Avatar removed', category: 'other' },
  USER_DISABLED: { label: 'Account disabled', category: 'other' },
  USER_ENABLED: { label: 'Account enabled', category: 'other' },
  KEY_PROTECTION_REWRAPPED: { label: 'Passphrase changed', category: 'other' },
  KEY_PROTECTION_RESET_WITH_PRIVATE_KEY: { label: 'Passphrase reset with key file', category: 'other' },
  USER_KEY_ADDED: { label: 'Account key added', category: 'other' },
  ACCOUNT_DELETED: { label: 'Account deleted', category: 'other' },
  ACCOUNT_DELETION_PASSWORD_FAILED: { label: 'Account deletion refused: wrong password', category: 'other' },
  // Account-level events now have a group of their own on the records page, so they are
  // worth naming properly rather than leaving to the title-case fallback.
  AUTH_REGISTERED: { label: 'Account created', category: 'other' },
  AUTH_LOGIN_SUCCEEDED: { label: 'Signed in', category: 'other' },
  AUTH_LOGIN_FAILED: { label: 'Sign-in failed', category: 'other' },
  AUTH_LOGGED_OUT: { label: 'Signed out', category: 'other' },
  AUTH_PASSWORD_CHANGED: { label: 'Password changed', category: 'other' },
  AUTH_PASSWORD_CHANGE_FAILED: { label: 'Password change failed', category: 'other' },
  AUTH_PASSWORD_RESET: { label: 'Password reset', category: 'other' },
  ADMIN_PASSWORD_RESET: { label: 'Password reset by an administrator', category: 'other' },
  AUTH_SESSION_REVOKED: { label: 'Session revoked', category: 'other' },
  AUTH_ALL_SESSIONS_REVOKED: { label: 'All sessions signed out', category: 'other' },
  AUTH_SESSION_EXPIRED: { label: 'Session expired', category: 'other' },
  AUTH_SESSION_REFRESHED: { label: 'Session renewed', category: 'other' },
  AUTH_REFRESH_REJECTED: { label: 'Session renewal rejected', category: 'other' },
  AUTH_REFRESH_REPLAY_DETECTED: { label: 'Reused session token detected', category: 'other' },
  AUTH_VERIFICATION_CODE_SENT: { label: 'Verification code sent', category: 'other' },
}

/**
 * An unknown action is titled rather than hidden.
 *
 * The vocabulary grows on the server side, and a record the browser has no label for is
 * still a record of something that happened -- dropping it would be worse than showing
 * `SOMETHING_NEW` as "Something new".
 */
export function auditActionLabel(action: string | undefined): string {
  if (!action) return 'Unknown action'
  const known = ACTIONS[action]
  if (known) return known.label
  return action
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/^./, (c) => c.toUpperCase())
}

/**
 * Every action with a label, for the event type filter, in label order.
 *
 * The values are what `GET /audit-logs?action=` accepts; the server refuses anything else
 * with a 422, so the dropdown only offers names from this table.
 */
export function auditActionOptions(): { value: string; label: string }[] {
  return Object.entries(ACTIONS)
    .map(([value, info]) => ({ value, label: info.label }))
    .sort((a, b) => a.label.localeCompare(b.label, 'en'))
}

export function auditActionCategory(action: string | undefined): AuditCategory {
  if (!action) return 'other'
  return ACTIONS[action]?.category ?? 'other'
}

/** Whether this action handed the file to somebody. */
export function isDownloadAction(action: string | undefined): boolean {
  return action === 'FILE_DOWNLOAD_AUTHORIZED'
}

/** The minimum of an audit row this module needs. */
interface AuditSubject {
  resource_type: string
  resource_id: string | null
}

/**
 * The file an audit row is about, or null when it is about the account itself.
 *
 * The API identifies the subject as `resource_type` + `resource_id`; it has never sent a
 * `file_id`, which is what the page used to read. Because the field was optional in the
 * frontend type, every row resolved to `undefined` and landed in one nameless group.
 *
 * SHARE rows count as file rows: `resource_id` is the file being shared, and a share belongs
 * in that file's history rather than off on its own.
 */
export function auditSubjectFileId(log: AuditSubject): string | null {
  if (log.resource_type !== 'FILE' && log.resource_type !== 'SHARE') return null
  return log.resource_id || null
}

/**
 * How to label the file a row is about, from what the audit response already carries.
 *
 * The page used to ask `GET /files/{id}` for every file it did not know, and each deleted file
 * answered 404. The API now sends the name (a deleted file keeps its row), so nothing is asked.
 * A row with no name at all is a file that no longer exists in any form: it is still shown, as
 * a deleted file, because what happened to a file is worth keeping once the file is gone.
 */
export function auditFileLabel(log: { file_name?: string | null; file_deleted?: boolean }): {
  name: string
  deleted: boolean
  /** The name is the person's own file name (never translated), not our fallback wording. */
  named: boolean
} {
  if (log.file_name) return { name: log.file_name, deleted: log.file_deleted === true, named: true }
  return { name: 'Deleted file', deleted: true, named: false }
}

/** Whether this action changed who can reach the file. */
export function isShareAction(action: string | undefined): boolean {
  return action === 'FILE_SHARED' || action === 'FILE_ACCESS_REVOKED'
}

/** The username a deleted account is left with (`AuthRepository.release_identifiers`). */
const DELETED_ACCOUNT_USERNAME = /^deleted-[0-9a-f]{32}$/

/**
 * Who performed an audited action, as a person should read it.
 *
 * Two different things used to show as "A deleted account". A row with no actor at all was
 * written by a server job (for example `scripts/restore_file.py` recording a restore from
 * backup), while a deleted account keeps its row under a `deleted-<hex>` username. They are
 * kept apart now, so a restore by the operator no longer reads as the work of a removed user.
 */
export function auditActorLabel(username: string | null | undefined): {
  name: string
  /** The name is a real username (never translated), not our wording. */
  named: boolean
} {
  if (!username) return { name: 'System (server script)', named: false }
  if (DELETED_ACCOUNT_USERNAME.test(username)) return { name: 'A deleted account', named: false }
  return { name: username, named: true }
}
