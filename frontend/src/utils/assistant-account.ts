/**
 * The Help assistant's account checks (v2): answers about the signed-in visitor's own files and
 * records, such as "who has access to budget.xlsx?" or "what has been shared with me?".
 *
 * Each check is read-only and uses the requests My Files and the Activity Log already make, under
 * the visitor's own session, so it can never show more than those pages would. The question
 * itself is still not sent: at most a file name goes to `GET /files?search=`, the same search
 * the My Files box runs. Nothing here changes anything; where the answer suggests an action
 * (revoke, restore, change password) it links to the page where the visitor does it.
 *
 * The API is passed in so the checks can be tested without a server.
 */
import { auditApi } from '@/api/audit_api'
import { fileApi } from '@/api/file_api'
import { shareApi, type SharedUser } from '@/api/share_api'
import { unwrapData, type AuditLogOut, type FileFolderOut, type FileListOut, type FileSummaryOut } from '@/api/types'
import type { AccountCheckId, AssistantLink } from '@/data/assistant/intents'
import { auditActionLabel } from '@/utils/audit-actions'
import { unseenSharedIds } from '@/utils/seen-shares'
import { formatSiteDateTime, SITE_TIME_ZONE } from '@/utils/site-time'

export interface AccountApi {
  listFiles(params: { scope: 'all' | 'mine' | 'shared'; page?: number; page_size: number; search?: string }): Promise<FileListOut>
  listFolders(): Promise<FileFolderOut[]>
  sharedUsers(fileId: string): Promise<SharedUser[]>
  fileLogs(fileId: string): Promise<AuditLogOut[]>
  recentLogs(limit: number): Promise<AuditLogOut[]>
  /** Shared file ids this browser has not shown in the Shared with me tab yet. */
  unseen(sharedFileIds: string[]): string[]
}

export const liveAccountApi: AccountApi = {
  async listFiles(params) {
    return unwrapData(await fileApi.listFiles(params))
  },
  async listFolders() {
    return unwrapData(await fileApi.listFolders()).items
  },
  async sharedUsers(fileId) {
    return unwrapData(await shareApi.sharedUsers(fileId)).users
  },
  async fileLogs(fileId) {
    return unwrapData(await auditApi.listFileLogs(fileId)).logs
  },
  async recentLogs(limit) {
    return unwrapData(await auditApi.listLogs({ limit })).logs
  },
  unseen: unseenSharedIds,
}

export interface AccountRow {
  text: string
  detail?: string
  /** A page in SecureView that shows this row's file or record. */
  to?: string
  tone?: 'new' | 'warn'
}

export interface FileChoice {
  fileId: string
  name: string
  detail: string
}

export type AccountResult =
  | { kind: 'result'; headline: string; rows: AccountRow[]; note?: string; links: AssistantLink[] }
  /** A one-file check that needs the visitor to say which file. */
  | { kind: 'choose'; prompt: string; choices: FileChoice[] }

export interface AccountQuery {
  /** The file the question named, or the words that are probably its name. */
  fileName?: string | null
  /** A file picked from the choices. */
  fileId?: string
}

/** `GET /files` caps a page at 100. */
const PAGE_SIZE = 100
/** How many of the newest files "which have I shared" looks at: one request each. */
export const SHARE_SCAN_LIMIT = 50
/** How many files "any marked Modified" pages through before saying it stopped. */
export const STATUS_SCAN_LIMIT = 500
const CONCURRENCY = 4
const CHOICES = 6
const ROWS = 8

const MY_FILES: AssistantLink = { label: 'My Files', to: '/files' }
const SHARED_WITH_ME: AssistantLink = { label: 'Shared with me', to: '/files?tab=shared' }
const RECORDS: AssistantLink = { label: 'Activity Log', to: '/audit-logs' }

const dateFormat = new Intl.DateTimeFormat('en-AU', {
  timeZone: SITE_TIME_ZONE,
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

/** The day in Kuala Lumpur, like every other date on the site (`utils/site-time`). */
export function formatDay(iso: string): string {
  return dateFormat.format(new Date(iso))
}

function formatMoment(iso: string): string {
  return formatSiteDateTime(iso, { seconds: false })
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`
}

/**
 * "None of your 3 files is shared" / "2 of your 50 newest files are shared", and the one-file
 * case said the way a person would say it.
 */
function howMany(found: number, scope: { checked: number; total: number }, what: string): string {
  if (scope.total === 1) return found === 0 ? `Your one file is not ${what}.` : `Your one file is ${what}.`
  const of =
    scope.checked < scope.total
      ? `your ${scope.checked.toLocaleString('en-US')} newest files`
      : `your ${scope.total.toLocaleString('en-US')} files`
  if (found === 0) return `None of ${of} is ${what}.`
  return `${found.toLocaleString('en-US')} of ${of} ${found === 1 ? 'is' : 'are'} ${what}.`
}

function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** My Files, opened on the tab the file is in and searched for its name. */
export function fileLink(file: Pick<FileSummaryOut, 'original_filename' | 'owner'>): string {
  const query = new URLSearchParams({ q: file.original_filename })
  if (!file.owner) query.set('tab', 'shared')
  return `/files?${query.toString()}`
}

async function inBatches<T, R>(items: T[], run: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length)
  let next = 0
  const workers = Array.from({ length: Math.min(CONCURRENCY, items.length) }, async () => {
    while (next < items.length) {
      const i = next++
      results[i] = await run(items[i]!)
    }
  })
  await Promise.all(workers)
  return results
}

// ------------------------------------------------------------------------------ finding the file

/**
 * One of the visitor's own files by name: the whole name first, then each word longest first,
 * so "thesis draft" still finds "Thesis-final.docx". Several matches, or none, become a choice.
 */
async function findOwnFile(
  api: AccountApi,
  query: AccountQuery,
  prompt: string,
): Promise<FileSummaryOut | AccountResult> {
  if (query.fileId) {
    const page = await api.listFiles({ scope: 'mine', page_size: PAGE_SIZE })
    const picked = page.items.find((f) => f.file_id === query.fileId)
    if (picked) return picked
  }
  const name = query.fileName?.trim()
  if (name) {
    const attempts = [name, ...name.split(/\s+/).filter((w) => w.length >= 3).sort((a, b) => b.length - a.length)]
    for (const search of [...new Set(attempts)]) {
      const page = await api.listFiles({ scope: 'mine', page_size: CHOICES, search })
      if (page.total === 1) return page.items[0]!
      if (page.total > 1) {
        return {
          kind: 'choose',
          prompt: `${plural(page.total, 'of your files matches', 'of your files match')} “${search}”. Which one?`,
          choices: page.items.map(choiceFor),
        }
      }
    }
  }
  const newest = await api.listFiles({ scope: 'mine', page_size: CHOICES })
  if (newest.total === 0) {
    return {
      kind: 'result',
      headline: 'You have not uploaded any files yet, so there is nothing to check.',
      rows: [],
      links: [{ label: 'Upload', to: '/upload' }],
    }
  }
  return {
    kind: 'choose',
    prompt: name
      ? `None of your own files is called “${name}”. Pick one of your newest, or ask again with part of its name.`
      : `${prompt} Pick one of your newest files, or ask again with part of its name.`,
    choices: newest.items.map(choiceFor),
  }
}

function choiceFor(file: FileSummaryOut): FileChoice {
  return { fileId: file.file_id, name: file.original_filename, detail: `uploaded ${formatDay(file.created_at)}` }
}

function isResult(found: FileSummaryOut | AccountResult): found is AccountResult {
  return 'kind' in found
}

// ------------------------------------------------------------------------------ the checks

async function overview(api: AccountApi): Promise<AccountResult> {
  const [all, shared, folders] = await Promise.all([
    api.listFiles({ scope: 'all', page_size: 1 }),
    api.listFiles({ scope: 'shared', page_size: PAGE_SIZE }),
    api.listFolders(),
  ])
  const unseen = api.unseen(shared.items.map((f) => f.file_id)).length
  const rows: AccountRow[] = [
    { text: plural(all.owned_total, 'file') + ' of your own', to: '/files' },
    { text: plural(all.shared_total, 'file') + ' shared with you', to: '/files?tab=shared' },
    { text: plural(folders.length, 'folder') },
  ]
  if (unseen > 0) rows.push({ text: `${plural(unseen, 'shared file')} you have not looked at yet`, to: '/files?tab=shared', tone: 'new' })
  return {
    kind: 'result',
    headline:
      all.owned_total + all.shared_total === 0
        ? 'Your account is empty so far: no files of your own and none shared with you.'
        : `You have ${plural(all.owned_total, 'file')} of your own and ${all.shared_total.toLocaleString('en-US')} shared with you.`,
    rows,
    links: [MY_FILES, { label: 'Upload', to: '/upload' }],
  }
}

async function whoHasAccess(api: AccountApi, query: AccountQuery): Promise<AccountResult> {
  const found = await findOwnFile(api, query, 'Which file?')
  if (isResult(found)) return found
  const others = (await api.sharedUsers(found.file_id)).filter((u) => !u.is_owner)
  const name = found.original_filename
  return {
    kind: 'result',
    headline:
      others.length === 0
        ? `Only you can open ${name}. It is not shared with anyone.`
        : `Besides you, ${plural(others.length, 'person', 'people')} can open ${name}: ${listNames(others.map((u) => u.username))}.`,
    rows: others.map((u) => ({
      text: u.username,
      detail: `since ${formatDay(u.granted_at)}${u.can_share ? ' · can share it on' : ''}`,
    })),
    note:
      others.length > 0
        ? 'To remove someone, press Share on the file and then Revoke. Revoking cannot reach a copy they already downloaded.'
        : undefined,
    links: [{ label: `Open ${name} in My Files`, to: fileLink(found) }],
  }
}

/** The events on one file that say who did what with it. */
const FILE_EVENTS = new Set([
  'FILE_UPLOADED',
  'FILE_SHARED',
  'FILE_ACCESS_REVOKED',
  'FILE_DOWNLOAD_AUTHORIZED',
  'FILE_DOWNLOAD_INTEGRITY_FAILED',
])

/** A blocked download, or a scan that found the stored bytes changed. */
function isIntegrityFailure(log: AuditLogOut): boolean {
  return (
    log.action === 'FILE_DOWNLOAD_INTEGRITY_FAILED' ||
    (log.action === 'FILE_INTEGRITY_CHECKED' && log.result === 'FAIL')
  )
}

function describe(log: AuditLogOut, me: string | null): string {
  const actor = log.actor_username === me ? 'You' : (log.actor_username ?? 'Someone')
  switch (log.action) {
    case 'FILE_UPLOADED':
      return `${actor} uploaded it`
    case 'FILE_SHARED':
      return `${actor} shared it with ${log.target_username ?? 'someone'}`
    case 'FILE_ACCESS_REVOKED':
      return `${actor} revoked ${log.target_username ?? 'someone'}’s access`
    case 'FILE_DOWNLOAD_AUTHORIZED':
      return `${actor} downloaded it`
    case 'FILE_DOWNLOAD_INTEGRITY_FAILED':
      return `A download by ${actor === 'You' ? 'you' : actor} was blocked: the stored copy failed its check`
    case 'FILE_INTEGRITY_CHECKED':
      return 'An integrity check found the stored copy changed'
    default:
      return auditActionLabel(log.action)
  }
}

async function fileActivity(api: AccountApi, query: AccountQuery, me: string | null): Promise<AccountResult> {
  const found = await findOwnFile(api, query, 'Which file’s history?')
  if (isResult(found)) return found
  const logs = (await api.fileLogs(found.file_id)).filter((l) => FILE_EVENTS.has(l.action) || isIntegrityFailure(l))
  const downloads = logs.filter((l) => l.action === 'FILE_DOWNLOAD_AUTHORIZED')
  const byOthers = downloads.filter((l) => l.actor_username !== me)
  const people = [...new Set(byOthers.map((l) => l.actor_username ?? 'someone'))]
  const name = found.original_filename
  let headline: string
  if (byOthers.length === 0) {
    headline = `Nobody else has downloaded ${name}.`
    if (downloads.length > 0) headline += ` You have downloaded it ${plural(downloads.length, 'time')}.`
  } else {
    headline =
      `${name} was downloaded ${plural(byOthers.length, 'time')} by ${listNames(people)}; ` +
      `most recently ${formatMoment(byOthers[0]!.created_at)}.`
  }
  const blocked = logs.some(isIntegrityFailure)
  return {
    kind: 'result',
    headline,
    rows: logs.slice(0, ROWS).map((l) => ({
      text: describe(l, me),
      detail: formatMoment(l.created_at),
      tone: isIntegrityFailure(l) ? 'warn' : undefined,
    })),
    note: blocked
      ? 'The stored copy no longer matched its fingerprint. Ask an administrator to restore it from the encrypted backup.'
      : logs.length > ROWS
        ? `The latest ${ROWS} of ${logs.length} events. Access history in My Files lists them all.`
        : undefined,
    links: [{ label: `Open ${name} in My Files`, to: fileLink(found) }, RECORDS],
  }
}

async function myShares(api: AccountApi): Promise<AccountResult> {
  const page = await api.listFiles({ scope: 'mine', page_size: SHARE_SCAN_LIMIT })
  if (page.total === 0) {
    return { kind: 'result', headline: 'You have not uploaded any files yet.', rows: [], links: [{ label: 'Upload', to: '/upload' }] }
  }
  const holders = await inBatches(page.items, async (file) => ({
    file,
    others: (await api.sharedUsers(file.file_id)).filter((u) => !u.is_owner),
  }))
  const shared = holders.filter((h) => h.others.length > 0)
  const checked = page.items.length
  return {
    kind: 'result',
    headline: howMany(shared.length, { checked, total: page.total }, shared.length === 0 ? 'shared with anyone' : 'shared'),
    rows: shared.slice(0, ROWS).map(({ file, others }) => ({
      text: file.original_filename,
      detail: `with ${listNames(others.map((u) => u.username))}`,
      to: fileLink(file),
    })),
    note:
      [
        shared.length > ROWS ? `Showing ${ROWS} of ${shared.length}.` : '',
        page.total > checked ? `${plural(page.total - checked, 'older file')} not checked.` : '',
      ]
        .filter(Boolean)
        .join(' ') || undefined,
    links: [MY_FILES],
  }
}

async function sharedWithMe(api: AccountApi): Promise<AccountResult> {
  const page = await api.listFiles({ scope: 'shared', page_size: PAGE_SIZE })
  if (page.total === 0) {
    return { kind: 'result', headline: 'Nobody has shared a file with you yet.', rows: [], links: [SHARED_WITH_ME] }
  }
  const unseen = new Set(api.unseen(page.items.map((f) => f.file_id)))
  const headline =
    `${plural(page.total, 'file is', 'files are')} shared with you` +
    (unseen.size > 0 ? `; ${unseen.size.toLocaleString('en-US')} ${unseen.size === 1 ? 'is' : 'are'} new since you last looked.` : '.')
  return {
    kind: 'result',
    headline,
    rows: page.items.slice(0, ROWS).map((file) => ({
      text: file.original_filename,
      detail: `from ${file.owner_username ?? 'unknown'} · ${formatDay(file.created_at)}`,
      to: fileLink(file),
      tone: unseen.has(file.file_id) ? 'new' : undefined,
    })),
    note: page.total > ROWS ? `The newest ${ROWS} of ${page.total}.` : undefined,
    links: [SHARED_WITH_ME],
  }
}

async function modifiedFiles(api: AccountApi): Promise<AccountResult> {
  const flagged: FileSummaryOut[] = []
  let seen = 0
  let total = 0
  for (let page = 1; seen < STATUS_SCAN_LIMIT; page++) {
    const result = await api.listFiles({ scope: 'all', page, page_size: PAGE_SIZE })
    total = result.total
    seen += result.items.length
    flagged.push(...result.items.filter((f) => f.status.toUpperCase() === 'CORRUPTED'))
    if (result.items.length < PAGE_SIZE || seen >= total) break
  }
  if (total === 0) {
    return { kind: 'result', headline: 'You have no files to check yet.', rows: [], links: [{ label: 'Upload', to: '/upload' }] }
  }
  return {
    kind: 'result',
    headline: howMany(flagged.length, { checked: seen, total }, 'marked Modified'),
    rows: flagged.slice(0, ROWS).map((file) => ({
      text: file.original_filename,
      detail: file.owner ? 'yours' : `from ${file.owner_username ?? 'unknown'}`,
      to: fileLink(file),
      tone: 'warn',
    })),
    note:
      flagged.length > 0
        ? 'A Modified file will not decrypt. The owner can ask an administrator to restore it from the encrypted backup.'
        : 'The server checks each file again at every download and in its daily scan.',
    links: [MY_FILES],
  }
}

/** Events worth surfacing among the latest: anything a visitor would want to be told about. */
const WATCH = new Set(['AUTH_LOGIN_FAILED', 'AUTH_REFRESH_REPLAY_DETECTED', 'FILE_DOWNLOAD_INTEGRITY_FAILED'])
const QUIET = new Set(['AUTH_SESSION_REFRESHED'])

async function recentActivity(api: AccountApi, me: string | null): Promise<AccountResult> {
  // One list call names the files most events are about, as the records page does.
  const [all, files] = await Promise.all([
    api.recentLogs(50),
    api.listFiles({ scope: 'all', page_size: PAGE_SIZE }).catch(() => null),
  ])
  const names = new Map((files?.items ?? []).map((f) => [f.file_id, f.original_filename]))
  const logs = all.filter((l) => !QUIET.has(l.action))
  if (logs.length === 0) {
    return { kind: 'result', headline: 'There is nothing in your Activity Log yet.', rows: [], links: [RECORDS] }
  }
  const failed = logs.filter((l) => l.action === 'AUTH_LOGIN_FAILED').length
  const headline =
    failed > 0
      ? `${plural(failed, 'failed sign-in')} among your latest ${logs.length} events. If that was not you, change your password.`
      : `No failed sign-ins among your latest ${logs.length} events.`
  return {
    kind: 'result',
    headline,
    rows: logs.slice(0, ROWS).map((l) => {
      const who = l.actor_username && l.actor_username !== me ? ` by ${l.actor_username}` : ''
      const whom = l.target_username && l.target_username !== me ? ` → ${l.target_username}` : ''
      const name = l.resource_id ? names.get(l.resource_id) : undefined
      return {
        text: `${auditActionLabel(l.action)}${name ? ` ${name}` : ''}${who}${whom}`,
        detail: formatMoment(l.created_at),
        tone: WATCH.has(l.action) ? 'warn' : undefined,
      }
    }),
    links: failed > 0 ? [RECORDS, { label: 'Change your password', to: '/settings' }] : [RECORDS],
  }
}

/** Run one account check for the visitor called `me`. */
export function runAccountCheck(
  check: AccountCheckId,
  query: AccountQuery,
  me: string | null,
  api: AccountApi = liveAccountApi,
): Promise<AccountResult> {
  switch (check) {
    case 'overview':
      return overview(api)
    case 'who-has-access':
      return whoHasAccess(api, query)
    case 'file-activity':
      return fileActivity(api, query, me)
    case 'my-shares':
      return myShares(api)
    case 'shared-with-me':
      return sharedWithMe(api)
    case 'modified-files':
      return modifiedFiles(api)
    case 'recent-activity':
      return recentActivity(api, me)
  }
}

/** The button that offers a check under a general answer. */
export const CHECK_LABELS: Record<AccountCheckId, string> = {
  overview: 'Summarise my account',
  'who-has-access': 'Check who has access to one of my files',
  'file-activity': 'Check one of my files’ history',
  'my-shares': 'List the files I have shared',
  'shared-with-me': 'List what is shared with me',
  'modified-files': 'Check my files’ status',
  'recent-activity': 'Show my recent activity',
}
