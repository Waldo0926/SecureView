<script setup lang="ts">
import SentenceLines from '@/components/SentenceLines.vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/securfile/PageHeader.vue'
import { Activity, AlertCircle, Check, CheckCircle, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Download, FileIcon, FileLock2, Folder, FolderPlus, LifeBuoy, Loader2, MoreHorizontal, PanelRightOpen, Pencil, RefreshCw, Search, Shield, Share2, Trash2, X } from 'lucide-vue-next'
import { fileApi } from '@/api/file_api'
import { apiErrorCode, apiErrorMessage } from '@/api/http'
import { formatFileSize, mapFileLifecycle, mapFileStatus, unwrapData } from '@/api/types'
import type { FileFolderOut, FileSummaryOut } from '@/api/types'
import ShareDialog from '@/components/ShareDialog.vue'
import RequestRecoveryDialog from '@/components/RequestRecoveryDialog.vue'
import CiphertextPreviewPanel from '@/components/CiphertextPreviewPanel.vue'
import { exactBytes } from '@/utils/ciphertext-preview'
import ConfirmActionDialog from '@/components/ConfirmActionDialog.vue'
import FileHistoryDialog from '@/components/FileHistoryDialog.vue'
import FileDetailDrawer from '@/components/FileDetailDrawer.vue'
import { markSharesSeen, unseenSharedIds } from '@/utils/seen-shares'
import { downloadEncryptedFile } from '@/utils/file-download'
import { riskyFileKind } from '@/utils/risky-file'
import UnlockDialog from '@/components/UnlockDialog.vue'
import {
  downloadAndDecrypt,
  FileIntegrityError,
  FileKeyUnwrapError,
  isUnlocked,
  KeyNotUnlockedError,
  NotUnlockedError,
  onRelock,
  saveDecryptedFile,
} from '@/crypto/download'
import { formatSiteDateTime } from '@/utils/site-time'

interface EncryptedFile {
  id: string
  name: string
  originalSize: string
  encryptedSize: string
  /** Exact counts, for the tooltips: "7.54 MB" twice hides the only thing being compared. */
  originalBytes: number
  encryptedBytes: number
  encryptedAt: string
  status: 'verified' | 'modified' | 'pending'
  /** False when someone else owns this file and shared it with the viewer. */
  owned: boolean
  /** Who uploaded it, shown when that is not the viewer. */
  ownerName: string
  folderId: string | null
  algorithm: string
  mimeType: string | null
  /** Absent from a server that predates the field, so the panel only shows it when present. */
  sha256?: string
  /** Set when a stale shared row is no longer authorized on the server. */
  accessError?: string
}

interface StatusConfig {
  label: string
  icon: typeof CheckCircle
  className: string
}

/** `GET /files` caps `page_size` at 100. Ask for the most the API will give per request. */
const PAGE_SIZE = 100

type FileScope = 'mine' | 'shared'

const scope = ref<FileScope>('mine')
const selectedFolder = ref<'all' | 'unfiled' | string>('all')
const searchQuery = ref('')
const files = ref<EncryptedFile[]>([])
const folders = ref<FileFolderOut[]>([])
const newFolderName = ref('')
const editingFolderId = ref<string | null>(null)
const editingFolderName = ref('')
const pendingFolderDelete = ref<FileFolderOut | null>(null)
const folderBusy = ref(false)
const isLoading = ref(false)
const errorMessage = ref('')
const shareFileId = ref<string | null>(null)
const recoveryFileId = ref<string | null>(null)
const historyFileId = ref<string | null>(null)
const detailFileId = ref<string | null>(null)
const detailFile = computed(() => files.value.find((file) => file.id === detailFileId.value))
/** A click on the row's blank space opens (or closes) its details; its own controls keep their jobs. */
function openDetailsFromRow(fileId: string, event: MouseEvent) {
  if ((event.target as HTMLElement).closest('button,a,select,input,label')) return
  if (window.getSelection()?.toString()) return
  detailFileId.value = detailFileId.value === fileId ? null : fileId
}
/** The one file whose encrypted preview is open beneath its row. */
const previewFileId = ref<string | null>(null)
const togglePreview = (file: EncryptedFile) => {
  previewFileId.value = previewFileId.value === file.id ? null : file.id
}

/**
 * How many table columns are on screen, so the preview row can span exactly that many. The
 * size and date columns are hidden on narrow screens, and a cell that spans more columns than
 * exist makes the browser invent extra ones.
 */
const viewportColumns = ref(7)
const updateViewportColumns = () => {
  if (typeof window === 'undefined' || !window.matchMedia) return
  const medium = window.matchMedia('(min-width: 768px)').matches
  const wide = window.matchMedia('(min-width: 1280px)').matches
  viewportColumns.value = 3 + (medium ? 2 : 0) + (wide ? 1 : 0)
}
// The Folder column is shown on both tabs: shared files can be filed too.
const columnCount = computed(() => viewportColumns.value + 1)
/** Owned file waiting for delete confirmation; null when no dialog is open. */
const pendingDelete = ref<EncryptedFile | null>(null)
const isDeleting = ref(false)
const actionMessage = ref('')
const page = ref(1)
const total = ref(0)
const downloadingId = ref<string | null>(null)
const encryptedDownloadingId = ref<string | null>(null)
const downloadBusy = computed(() => downloadingId.value !== null || encryptedDownloadingId.value !== null)
const activeDownload = computed(() => {
  const id = downloadingId.value ?? encryptedDownloadingId.value
  return id === null ? undefined : files.value.find((file) => file.id === id)
})
const downloadProgressMessage = computed(() => {
  if (!activeDownload.value) return ''
  const verb = downloadingId.value ? 'Downloading and decrypting' : 'Downloading'
  return `${verb} ${activeDownload.value.name}… Keep this page open until the download finishes.`
})
// Set while the passphrase dialog is open; holds the file to resume once unlocked.
const pendingDownloadId = ref<string | null>(null)
// The same for Share: the passphrase is asked for first, then the share dialog opens.
const pendingShareId = ref<string | null>(null)
const unlockKeyId = ref<string | null>(null)
const showUnlock = ref(false)

const mapFile = (file: FileSummaryOut): EncryptedFile => ({
  id: file.file_id,
  name: file.original_filename,
  originalSize: formatFileSize(file.plaintext_size),
  // AES-GCM is a stream mode, so these match; the tag is stored apart from the object.
  encryptedSize: formatFileSize(file.ciphertext_size),
  originalBytes: file.plaintext_size,
  encryptedBytes: file.ciphertext_size,
  encryptedAt: formatSiteDateTime(file.created_at),
  // `files.status` is ACTIVE/CORRUPTED/DELETED, not the integrity vocabulary. Sending it
  // through mapFileStatus put every row on the fallback branch, so a damaged file looked
  // exactly like a healthy one.
  status: mapFileLifecycle(file.status),
  // The API has always sent this and the page has never read it, so a file someone else
  // shared with you sat in "My Encrypted Files" looking exactly like one you uploaded --
  // as though you owned and managed it, which you do not.
  owned: file.owner,
  ownerName: file.owner_username ?? 'another account',
  folderId: file.folder_id,
  algorithm: file.encryption_algorithm,
  mimeType: file.mime_type,
  sha256: file.ciphertext_sha256,
})

/**
 * Tab totals come from the server. Counting the rows of the current page made "Shared with me"
 * show only the shared files that happened to be on it, and the total mix both kinds.
 */
const ownedCount = ref(0)
const sharedCount = ref(0)
const unseenCount = ref(0)

/** Showing the shared list is what counts as having seen it. */
const showShared = () => {
  scope.value = 'shared'
  selectedFolder.value = 'all'
  unseenCount.value = 0
  page.value = 1
  void loadFiles()
}
const showMine = () => {
  scope.value = 'mine'
  selectedFolder.value = 'all'
  page.value = 1
  void loadFiles()
}

let requestId = 0

/** The "new" badge on the shared tab: shared files this browser has not shown yet. */
const refreshUnseenShares = async () => {
  try {
    const res = await fileApi.listFiles({ page: 1, page_size: PAGE_SIZE, scope: 'shared' })
    unseenCount.value = unseenSharedIds(unwrapData(res).items.map((file) => file.file_id)).length
  } catch {
    // The badge is a convenience; the shared tab itself still lists everything.
  }
}

const loadFolders = async () => {
  try {
    folders.value = unwrapData(await fileApi.listFolders()).items
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Failed to load folders')
  }
}

/**
 * Fetch the current page. A `silent` load keeps the rows, the skeleton and any message as
 * they are until the response arrives; it exists for the background refresh below, which
 * must never look like something the person did.
 */
const loadFiles = async ({ silent = false } = {}) => {
  const thisRequest = ++requestId
  lastLoadedAt = Date.now()
  if (!silent) {
    isLoading.value = true
    errorMessage.value = ''
  }
  try {
    const res = await fileApi.listFiles({
      page: page.value,
      page_size: PAGE_SIZE,
      search: searchQuery.value.trim() || undefined,
      scope: scope.value,
      folder_id: !['all', 'unfiled'].includes(selectedFolder.value) ? selectedFolder.value : undefined,
      unfiled: selectedFolder.value === 'unfiled' ? true : undefined,
    })
    // The API paginates: rows live under `items`. Reading anything else silently
    // yields an empty list, which reads as "no files" even when uploads succeeded.
    if (thisRequest !== requestId) return
    const data = unwrapData(res)
    files.value = data.items.map(mapFile)
    ownedCount.value = data.owned_total
    sharedCount.value = data.shared_total
    // Opening the shared list is what counts as seeing it; from the other tab, the badge
    // counts shared files not seen yet.
    if (scope.value === 'shared') {
      markSharesSeen(files.value.map((file) => file.id))
      unseenCount.value = 0
    } else {
      void refreshUnseenShares()
    }
    // `total` counts every file the caller can reach, not the ones on this page. Dropping
    // it is what let the list quietly stop at one page and still call that the total.
    total.value = data.total
  } catch (error) {
    if (thisRequest !== requestId) return
    // A background refresh keeps whatever is on screen: the next explicit load will say so.
    if (!silent) errorMessage.value = apiErrorMessage(error, 'Failed to load files')
  } finally {
    if (thisRequest === requestId && !silent) isLoading.value = false
  }
}

/**
 * When this list was last fetched, so a return to the tab can decide whether it is worth
 * fetching again. Set when a request starts so two returns in quick succession fetch once.
 */
let lastLoadedAt = 0
const REFRESH_ON_RETURN_AFTER_MS = 5_000

/**
 * Refresh quietly when the person comes back to this tab or window.
 *
 * A share, a revoke or a recovery happens in someone else's browser, and until now the
 * recipient's list only noticed when they pressed Refresh: a demo that revokes Bob's access
 * in one window showed Bob still holding the file in the other. The rows are replaced in
 * place, with no loading state and no error, because nothing the person did asked for a
 * reload and a flash of "Loading files..." over a list they were reading would be noise.
 */
const refreshOnReturn = () => {
  if (document.visibilityState !== 'visible') return
  if (Date.now() - lastLoadedAt < REFRESH_ON_RETURN_AFTER_MS) return
  if (isLoading.value) return
  void loadFiles({ silent: true })
}

/**
 * `/files?tab=shared&q=budget` opens the shared tab searched for "budget": the links the Help
 * assistant gives for one file. Read again when the query changes, because following such a
 * link while already on My Files does not remount the page.
 */
const route = useRoute()
const applyRouteQuery = (): boolean => {
  const tab = route.query.tab === 'shared' ? 'shared' : route.query.tab === 'mine' ? 'mine' : null
  const q = typeof route.query.q === 'string' ? route.query.q.slice(0, 200) : null
  if (tab === null && q === null) return false
  if (tab) scope.value = tab
  selectedFolder.value = 'all'
  page.value = 1
  if (q !== null) searchQuery.value = q
  return true
}
watch(
  () => [route.query.tab, route.query.q],
  () => {
    if (applyRouteQuery()) void loadFiles()
  },
)

const moreMenuFileId = ref<string | null>(null)
// The table scrolls sideways inside an overflow box, which would clip a menu positioned within
// it. The menu is teleported to <body> and placed under its button instead.
/** Matches the menu's `w-56`. */
const MORE_MENU_WIDTH = 224
const moreMenuPosition = ref<{ top?: number; bottom?: number; right: number }>({ right: 0 })
const MORE_MENU_HEIGHT = 136

const closeMoreMenu = () => {
  moreMenuFileId.value = null
}

const toggleMoreMenu = (id: string, event: MouseEvent) => {
  if (moreMenuFileId.value === id) {
    closeMoreMenu()
    return
  }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  // Right-aligned to the button, but never so far right that the menu's left edge leaves the screen:
  // on a narrow phone the buttons can wrap, which puts More at the left of a second row.
  const right = Math.min(window.innerWidth - rect.right, Math.max(8, window.innerWidth - MORE_MENU_WIDTH - 8))
  // Open upwards when the row sits too close to the bottom of the window for the menu to fit.
  moreMenuPosition.value =
    rect.bottom + 4 + MORE_MENU_HEIGHT > window.innerHeight
      ? { bottom: window.innerHeight - rect.top + 4, right }
      : { top: rect.bottom + 4, right }
  moreMenuFileId.value = id
}

const moreMenuFile = computed(() => files.value.find((file) => file.id === moreMenuFileId.value) ?? null)
const PX = 'px'
const moreMenuStyle = computed(() => {
  const { top, bottom, right } = moreMenuPosition.value
  return top === undefined
    ? { bottom: bottom + PX, right: right + PX }
    : { top: top + PX, right: right + PX }
})

/** A click anywhere outside the open More menu, or Escape, closes it. */
const onDocumentPointer = (event: Event) => {
  if (!(event.target as HTMLElement | null)?.closest('[data-more-actions]')) closeMoreMenu()
}
const onDocumentKey = (event: KeyboardEvent) => {
  if (event.key === 'Escape') closeMoreMenu()
}

onMounted(() => {
  applyRouteQuery()
  void Promise.all([loadFiles(), loadFolders()])
  updateViewportColumns()
  window.addEventListener('resize', updateViewportColumns)
  document.addEventListener('pointerdown', onDocumentPointer)
  document.addEventListener('keydown', onDocumentKey)
  window.addEventListener('scroll', closeMoreMenu, true)
  window.addEventListener('resize', closeMoreMenu)
  document.addEventListener('visibilitychange', refreshOnReturn)
  window.addEventListener('focus', refreshOnReturn)
})

// The account key relocks itself after a spell of disuse. Nothing on screen depends on it
// directly, but a download started afterwards must ask for the passphrase again rather
// than failing, so the message says what happened before the dialog reappears.
const stopRelockListener = onRelock(() => {
  actionMessage.value = 'Your account key was locked after a period of inactivity.'
})

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const hasPreviousPage = computed(() => page.value > 1)
const hasNextPage = computed(() => page.value < pageCount.value)
const firstOnPage = computed(() => (total.value === 0 ? 0 : (page.value - 1) * PAGE_SIZE + 1))
const lastOnPage = computed(() => (page.value - 1) * PAGE_SIZE + files.value.length)

const goToPage = async (next: number) => {
  if (next < 1 || next > pageCount.value || next === page.value) return
  page.value = next
  actionMessage.value = ''
  await loadFiles()
}

/**
 * Search runs on the server, so it sees every page rather than only the fetched one.
 *
 * Debounced because it costs a request per keystroke otherwise, and the request that
 * returns last is not necessarily the one for the current text -- `requestId` drops any
 * response that a newer search has already superseded.
 */
const SEARCH_DEBOUNCE_MS = 250
let searchTimer: ReturnType<typeof setTimeout> | undefined

watch(searchQuery, () => {
  if (searchTimer !== undefined) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    // A narrower result set rarely has the page the user was on; start from the first.
    page.value = 1
    void loadFiles()
  }, SEARCH_DEBOUNCE_MS)
})

onBeforeUnmount(() => {
  if (searchTimer !== undefined) clearTimeout(searchTimer)
  stopRelockListener()
  window.removeEventListener('resize', updateViewportColumns)
  document.removeEventListener('pointerdown', onDocumentPointer)
  document.removeEventListener('keydown', onDocumentKey)
  window.removeEventListener('scroll', closeMoreMenu, true)
  window.removeEventListener('resize', closeMoreMenu)
  document.removeEventListener('visibilitychange', refreshOnReturn)
  window.removeEventListener('focus', refreshOnReturn)
})

// The server applies the search, the tab and the folder. The ownership check stays as a guard
// so a stale response from the other tab can never be shown under this one.
const filteredFiles = computed(() =>
  files.value.filter((file) => (scope.value === 'shared' ? !file.owned : file.owned)),
)

const selectFolder = (folder: 'all' | 'unfiled' | string) => {
  selectedFolder.value = folder
  page.value = 1
  void loadFiles()
}

const createFolder = async () => {
  const name = newFolderName.value.trim()
  if (!name || folderBusy.value) return
  folderBusy.value = true
  errorMessage.value = ''
  try {
    const folder = unwrapData(await fileApi.createFolder(name))
    folders.value = [...folders.value, folder].sort((a, b) => a.name.localeCompare(b.name))
    newFolderName.value = ''
    selectedFolder.value = folder.folder_id
    page.value = 1
    await loadFiles()
    actionMessage.value = `Created folder ${folder.name}`
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not create folder')
  } finally {
    folderBusy.value = false
  }
}

const startRenameFolder = (folder: FileFolderOut) => {
  editingFolderId.value = folder.folder_id
  editingFolderName.value = folder.name
}

const renameFolder = async () => {
  const id = editingFolderId.value
  const name = editingFolderName.value.trim()
  if (!id || !name || folderBusy.value) return
  folderBusy.value = true
  try {
    const updated = unwrapData(await fileApi.renameFolder(id, name))
    folders.value = folders.value
      .map((folder) => (folder.folder_id === id ? updated : folder))
      .sort((a, b) => a.name.localeCompare(b.name))
    editingFolderId.value = null
    actionMessage.value = `Renamed folder to ${updated.name}`
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not rename folder')
  } finally {
    folderBusy.value = false
  }
}

const deleteFolder = async () => {
  const folder = pendingFolderDelete.value
  if (!folder || folderBusy.value) return
  folderBusy.value = true
  try {
    await fileApi.deleteFolder(folder.folder_id)
    files.value.forEach((file) => {
      if (file.folderId === folder.folder_id) file.folderId = null
    })
    folders.value = folders.value.filter((item) => item.folder_id !== folder.folder_id)
    if (selectedFolder.value === folder.folder_id) selectedFolder.value = 'unfiled'
    page.value = 1
    await loadFiles()
    actionMessage.value = `Deleted folder ${folder.name}; its files are now unfiled`
    pendingFolderDelete.value = null
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not delete folder')
  } finally {
    folderBusy.value = false
  }
}

const moveFile = async (file: EncryptedFile, folderId: string) => {
  const previous = file.folderId
  const next = folderId || null
  if (previous === next) return
  file.folderId = next
  try {
    await fileApi.moveFile(file.id, next)
    await Promise.all([loadFiles(), loadFolders()])
    actionMessage.value = next
      ? `Moved ${file.name} to ${folders.value.find((folder) => folder.folder_id === next)?.name ?? 'folder'}`
      : `${file.name} is no longer in a folder`
  } catch (error) {
    file.folderId = previous
    errorMessage.value = apiErrorMessage(error, 'Could not move file')
  }
}

const revokedAccessMessage =
  'This shared file is no longer available. Its owner may have revoked access or deleted it. Contact the person who shared it with you.'

const markSharedFileUnavailable = (id: string, error: unknown): boolean => {
  const row = files.value.find((file) => file.id === id)
  if (row && !row.owned && apiErrorCode(error) === 'file_not_found') {
    row.accessError = revokedAccessMessage
    errorMessage.value = revokedAccessMessage
    return true
  }
  return false
}

const handleDelete = (id: string) => {
  const file = files.value.find((row) => row.id === id)
  if (!file || !file.owned) return
  pendingDelete.value = file
}

/**
 * Runs only after the dedicated confirmation dialog. A one-click trash icon used to delete
 * immediately, which is exactly what #72 forbids for irreversible file removal.
 */
const confirmDelete = async () => {
  const file = pendingDelete.value
  if (!file) return
  isDeleting.value = true
  actionMessage.value = ''
  errorMessage.value = ''
  try {
    await fileApi.delete(file.id)
    files.value = files.value.filter((f) => f.id !== file.id)
    total.value = Math.max(0, total.value - 1)
    // Removing the last row of the last page would otherwise strand the view on a page
    // that no longer exists, showing an empty table over a non-zero total.
    if (!files.value.length && page.value > 1) {
      await goToPage(page.value - 1)
    }
    actionMessage.value = `Deleted ${file.name}`
    pendingDelete.value = null
    await loadFolders()
  } catch (error) {
    // A failure is not a result: it goes in the red message, not the blue one.
    errorMessage.value = apiErrorMessage(error, 'Delete failed')
  } finally {
    isDeleting.value = false
  }
}

const closePendingDelete = () => {
  if (isDeleting.value) return
  pendingDelete.value = null
}

/**
 * Download, decrypt in the page, and hand the plaintext to the browser.
 *
 * The account key has to be open first, so a locked session raises the passphrase dialog
 * and remembers which file to resume. Nothing is written to disk until the AES-GCM tag has
 * authenticated: a file that fails to decrypt is never saved half-formed.
 */
const pendingRiskyDownload = ref<EncryptedFile | null>(null)
/** Files the viewer already chose to save despite the warning, so an unlock does not re-ask. */
const riskyAcknowledged = new Set<string>()

const riskyConsequence = computed(() => {
  const file = pendingRiskyDownload.value
  if (!file) return ''
  // Whole sentences, not fragments, so the Chinese dictionary can translate each one.
  return riskyFileKind(file.name) === 'macro'
    ? `${file.ownerName} shared an Office file that can carry macros. SecureView cannot scan it for malware: the server only ever holds ciphertext. Save it only if you expected it from this person, and let your antivirus check it before opening.`
    : `${file.ownerName} shared a program or script that can run on your computer. SecureView cannot scan it for malware: the server only ever holds ciphertext. Save it only if you expected it from this person, and let your antivirus check it before opening.`
})

const confirmRiskyDownload = async () => {
  const file = pendingRiskyDownload.value
  pendingRiskyDownload.value = null
  if (!file) return
  riskyAcknowledged.add(file.id)
  await handleDownload(file.id)
}

const handleDownload = async (id: string) => {
  if (downloadBusy.value) return
  actionMessage.value = ''
  errorMessage.value = ''
  const row = files.value.find((file) => file.id === id)
  if (row?.accessError) return
  if (row && !row.owned && riskyFileKind(row.name) && !riskyAcknowledged.has(id)) {
    pendingRiskyDownload.value = row
    return
  }
  // The key is forgotten after every download, so this asks for the passphrase each time.
  // It is only open here when we come back from the passphrase dialog.
  if (!isUnlocked()) {
    try {
      // A stale recipient tab can still show a row after its owner revokes access. Check
      // before asking for a passphrase, otherwise the user unlocks successfully and then
      // sees an apparently dead download button.
      await fileApi.getFile(id)
      pendingDownloadId.value = id
      unlockKeyId.value = null
      showUnlock.value = true
    } catch (error) {
      if (!markSharedFileUnavailable(id, error)) {
        errorMessage.value = apiErrorMessage(error, 'Could not check access to this file')
      }
    }
    return
  }

  downloadingId.value = id
  try {
    const file = await downloadAndDecrypt(id)
    saveDecryptedFile(file)
    actionMessage.value = `Decrypted and saved ${file.filename}`
  } catch (error) {
    if (error instanceof KeyNotUnlockedError) {
      // Ordinary after a key rotation: the file is wrapped to an older account key.
      pendingDownloadId.value = id
      unlockKeyId.value = error.keyId
      showUnlock.value = true
      return
    }
    if (error instanceof NotUnlockedError) {
      pendingDownloadId.value = id
      unlockKeyId.value = null
      showUnlock.value = true
      return
    }
    if (error instanceof FileIntegrityError) {
      // An integrity finding, not a transport or permission problem. Mark the row so the
      // state persists after the message is replaced by the next action.
      const row = files.value.find((f) => f.id === id)
      if (row) row.status = 'modified'
      errorMessage.value = error.message
      return
    }
    if (error instanceof FileKeyUnwrapError) {
      errorMessage.value = error.message
      return
    }
    if (apiErrorCode(error) === 'integrity_verification_failed') {
      // The server's own check found the stored bytes changed and refused to send them.
      const row = files.value.find((f) => f.id === id)
      if (row) row.status = 'modified'
      // The server's sentence ("could not be verified") says what happened, not what to do
      // next, and the recipient has no button for this: the fix is on the server side.
      errorMessage.value =
        'The stored copy of this file was changed, so it was not sent. The daily check alerts the administrator, who restores it from backup; or ask the owner to upload it again.'
      return
    }
    if (!markSharedFileUnavailable(id, error)) {
      errorMessage.value = apiErrorMessage(error, 'Download failed')
    }
  } finally {
    downloadingId.value = null
  }
}

const handleEncryptedDownload = async (file: EncryptedFile) => {
  if (downloadBusy.value) return
  actionMessage.value = ''
  errorMessage.value = ''
  encryptedDownloadingId.value = file.id
  try {
    await downloadEncryptedFile(file.id, file.name)
    actionMessage.value = `Encrypted download started for ${file.name}. The file remains encrypted.`
  } catch (error) {
    if (!markSharedFileUnavailable(file.id, error)) {
      errorMessage.value = apiErrorMessage(error, 'Encrypted download failed')
    }
  } finally {
    encryptedDownloadingId.value = null
  }
}

const onUnlocked = async () => {
  showUnlock.value = false
  unlockKeyId.value = null
  const resumeDownload = pendingDownloadId.value
  const resumeShare = pendingShareId.value
  pendingDownloadId.value = null
  pendingShareId.value = null
  if (resumeDownload) await handleDownload(resumeDownload)
  else if (resumeShare) shareFileId.value = resumeShare
}

const closeUnlock = () => {
  showUnlock.value = false
  unlockKeyId.value = null
  pendingDownloadId.value = null
  pendingShareId.value = null
}

/** The file whose integrity check is in flight, so its badge can say so and refuse a second click. */
const checkingFileId = ref<string | null>(null)

const handleIntegrityCheck = async (id: string) => {
  // The server hashes the whole object, which takes a moment for a large file. Without a
  // visible state the badge looked inert and got clicked again, queueing a second check.
  if (checkingFileId.value !== null) return
  checkingFileId.value = id
  actionMessage.value = ''
  errorMessage.value = ''
  try {
    const res = await fileApi.integrityCheck(id)
    const data = unwrapData(res) as { status?: string }
    const file = files.value.find((f) => f.id === id)
    if (file && data.status) {
      file.status = mapFileStatus(data.status)
    }
    actionMessage.value = `Integrity check: ${data.status ?? 'done'}`
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Integrity check failed')
  } finally {
    checkingFileId.value = null
  }
}

// Every click on Share asks for the passphrase first. The key stays open while the share
// dialog is up and is forgotten after the share, or when the dialog closes.
const openShare = (id: string) => {
  pendingShareId.value = id
  unlockKeyId.value = null
  showUnlock.value = true
}

const historyFile = computed(() => files.value.find((file) => file.id === historyFileId.value))
const recoveryFile = computed(() => files.value.find((file) => file.id === recoveryFileId.value))

const closeShare = () => {
  shareFileId.value = null
}

const onRecoveryRequested = () => {
  actionMessage.value =
    'Recovery request submitted. Track it under Recovery requests in your account menu (/admin).'
}

const onShared = (username: string) => {
  // The dialog stays open: it now lists who holds the file, and seeing the new name appear
  // is the confirmation. Closing it would hide the thing that just changed.
  actionMessage.value = `Shared with ${username}`
}

const onRevoked = (username: string) => {
  actionMessage.value = `Revoked ${username}'s access`
}

const shareFilename = computed(
  () => files.value.find((file) => file.id === shareFileId.value)?.name,
)

const statusConfig: Record<EncryptedFile['status'], StatusConfig> = {
  verified: { label: 'Verified', icon: CheckCircle, className: 'bg-success-soft text-success' },
  modified: { label: 'Modified', icon: AlertCircle, className: 'bg-destructive-soft text-destructive' },
  pending: { label: 'Pending', icon: Shield, className: 'bg-muted text-muted-foreground' },
}
</script>

<template>
  <section id="manage" class="product-page">
    <div class="page-container">
      <PageHeader title="Manage Encrypted Files" subtitle="View, download, share, and verify all your encrypted files" />

      <div class="bg-card border border-border rounded-3xl p-4 sm:p-6" data-testid="files-card">
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <div class="inline-flex rounded-lg border border-border p-1 mb-2">
              <button
                type="button"
                class="h-8 px-3 rounded-md text-sm transition-colors"
                :class="scope === 'mine' ? 'bg-secondary text-foreground font-medium' : 'text-muted-foreground hover:text-foreground'"
                @click="showMine"
              >
                My Files ({{ ownedCount }})
              </button>
              <button
                type="button"
                class="h-8 px-3 rounded-md text-sm transition-colors"
                :class="scope === 'shared' ? 'bg-secondary text-foreground font-medium' : 'text-muted-foreground hover:text-foreground'"
                @click="showShared"
              >
                Shared with me ({{ sharedCount }})
                <span
                  v-if="unseenCount > 0"
                  class="ml-1 inline-flex items-center justify-center min-w-5 h-5 px-1 rounded-full bg-primary text-primary-foreground text-xs"
                >{{ unseenCount }}</span>
              </button>
            </div>
            <p class="text-muted-foreground text-sm">
              <template v-if="searchQuery.trim()">{{ total }} {{ total === 1 ? 'match' : 'matches' }} for "{{ searchQuery.trim() }}"</template>
              <template v-else-if="total === 1">Total 1 encrypted file</template><template v-else>Total {{ total }} encrypted files</template><span v-if="total > files.length">, showing {{ firstOnPage }}-{{ lastOnPage }}</span>
            </p>
          </div>
          <div class="flex items-center gap-2">
            <div class="relative">
              <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input v-model="searchQuery" placeholder="Search your files..." class="h-10 w-full md:w-64 rounded-md border border-border bg-secondary pl-9 pr-3" />
            </div>
            <button class="h-10 w-10 inline-flex items-center justify-center rounded-md border border-border hover:bg-secondary" @click="loadFiles()">
              <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': isLoading }" />
            </button>
          </div>
        </div>

        <div class="mb-6 rounded-lg border border-border bg-secondary/30 p-4">
          <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div class="flex items-center gap-2">
              <Folder class="h-4 w-4 text-primary" />
              <h3 class="font-medium text-foreground">Folders</h3>
              <span class="text-xs text-muted-foreground">
                <template v-if="scope === 'shared'">Your folders are private: filing a shared file here does not change where its owner keeps it.</template>
                <template v-else>Organize metadata only; ciphertext does not move.</template>
              </span>
            </div>
            <form class="flex gap-2" @submit.prevent="createFolder">
              <input
                v-model="newFolderName"
                aria-label="New folder name"
                maxlength="80"
                placeholder="New folder"
                class="h-9 min-w-0 rounded-md border border-border bg-card px-3 text-sm"
              />
              <button
                type="submit"
                class="h-9 inline-flex items-center gap-1 rounded-md bg-primary px-3 text-sm text-primary-foreground disabled:opacity-50"
                :disabled="!newFolderName.trim() || folderBusy"
              >
                <FolderPlus class="h-4 w-4" /> Add
              </button>
            </form>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="h-9 rounded-md border px-3 text-sm"
              :class="selectedFolder === 'all' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card'"
              @click="selectFolder('all')"
            >All files</button>
            <button
              type="button"
              class="h-9 rounded-md border px-3 text-sm"
              :class="selectedFolder === 'unfiled' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card'"
              @click="selectFolder('unfiled')"
            >No folder</button>
            <div
              v-for="folder in folders"
              :key="folder.folder_id"
              class="inline-flex h-9 items-center rounded-md border"
              :class="selectedFolder === folder.folder_id ? 'border-primary bg-primary/10' : 'border-border bg-card'"
            >
              <template v-if="editingFolderId === folder.folder_id">
                <input
                  v-model="editingFolderName"
                  :aria-label="`Rename ${folder.name}`"
                  maxlength="80"
                  class="h-8 w-32 bg-transparent px-2 text-sm outline-none"
                  @keyup.enter="renameFolder"
                  @keyup.escape="editingFolderId = null"
                />
                <button type="button" class="h-8 w-8" aria-label="Save folder name" @click="renameFolder"><Check class="mx-auto h-3.5 w-3.5" /></button>
                <button type="button" class="h-8 w-8" aria-label="Cancel rename" @click="editingFolderId = null"><X class="mx-auto h-3.5 w-3.5" /></button>
              </template>
              <template v-else>
                <button translate="no" type="button" class="h-8 px-3 text-sm" @click="selectFolder(folder.folder_id)">
                  {{ folder.name }} ({{ scope === 'shared' ? folder.shared_file_count : folder.owned_file_count }})
                </button>
                <button type="button" class="h-8 w-8 text-muted-foreground hover:text-foreground" :aria-label="`Rename ${folder.name}`" @click="startRenameFolder(folder)"><Pencil class="mx-auto h-3.5 w-3.5" /></button>
                <button type="button" class="h-8 w-8 text-muted-foreground hover:text-destructive" :aria-label="`Delete ${folder.name}`" @click="pendingFolderDelete = folder"><Trash2 class="mx-auto h-3.5 w-3.5" /></button>
              </template>
            </div>
          </div>
        </div>

        <p v-if="errorMessage" class="text-sm text-destructive mb-4" role="alert">{{ errorMessage }}</p>
        <p v-if="actionMessage" class="text-sm text-primary mb-4">{{ actionMessage }}</p>
        <div
          v-if="downloadProgressMessage"
          class="mb-4 flex items-center gap-2 rounded-md border border-border bg-secondary px-3 py-2 text-sm font-medium text-foreground"
          role="status"
          aria-live="polite"
        >
          <Loader2 class="h-4 w-4 shrink-0 animate-spin" />
          <span>{{ downloadProgressMessage }}</span>
        </div>
        <p class="text-sm text-muted-foreground mb-4">
          <SentenceLines text="Download encrypted saves a .ciphertext file without your passphrase. Use Download and decrypt to save the original file." />
        </p>

        <div v-if="isLoading && !files.length" class="text-center py-12 text-muted-foreground">
          Loading files...
        </div>

        <div v-else-if="!filteredFiles.length" class="text-center py-12 text-muted-foreground">
          <template v-if="searchQuery.trim()">No file matches "{{ searchQuery.trim() }}".</template>
          <template v-else-if="selectedFolder !== 'all'">No {{ scope === 'shared' ? 'shared ' : '' }}files {{ selectedFolder === 'unfiled' ? 'outside a folder' : 'in this folder' }}.</template>
          <template v-else-if="scope === 'shared'">No one has shared a file with you yet.</template>
          <template v-else>No encrypted files yet. Upload your first file to get started.</template>
        </div>

        <div v-else class="overflow-x-auto">
          <!--
            Fixed layout with explicit widths: the name column used to take whatever the longest
            filename asked for and squeeze every other header into a few letters. Now the name is
            a bounded column that wraps, and the rest keep room for their own headings. The
            minimum width keeps the name column usable on a tablet. Below md the table is not a
            table at all: each file becomes a card (name, folder and status, then the actions in
            a row), because seven columns on a phone either squeeze the name to a few characters
            or push the actions off the right edge, out of reach.
          -->
          <table class="block w-full text-sm md:table md:min-w-[44rem] md:table-fixed">
            <thead class="hidden md:table-header-group">
              <tr class="border-b border-border text-muted-foreground">
                <th class="w-[26%] px-2 py-3 text-center font-medium">File Name</th>
                <th class="hidden w-[10%] px-2 py-3 text-center font-medium whitespace-nowrap md:table-cell">Original</th>
                <th class="hidden w-[10%] px-2 py-3 text-center font-medium whitespace-nowrap md:table-cell">Encrypted</th>
                <th class="hidden w-[14%] px-2 py-3 text-center font-medium whitespace-nowrap xl:table-cell">Encrypted At</th>
                <th class="w-[13%] px-2 py-3 text-center font-medium whitespace-nowrap">Folder</th>
                <th class="w-[11%] px-2 py-3 text-center font-medium whitespace-nowrap">Status</th>
                <th class="w-[11.5rem] px-2 py-3 text-center font-medium whitespace-nowrap lg:w-[14rem] xl:w-[17rem] min-[87.5rem]:w-[21rem]">Actions</th>
              </tr>
            </thead>
            <tbody class="block space-y-3 md:table-row-group md:space-y-0">
              <template v-for="file in filteredFiles" :key="file.id">
              <!-- The whole row opens the details panel; clicks on its own controls (download, folder,
                   status, preview) are left to those controls. The open file's row stays highlighted
                   so the panel can be matched to it, and clicking another row switches the panel. -->
              <tr
                data-file-row
                class="grid cursor-pointer grid-cols-2 gap-x-3 gap-y-3 rounded-xl border p-4 transition-colors md:table-row md:rounded-none md:border-0 md:border-b md:border-border/60 md:p-0 md:align-middle"
                :class="detailFileId === file.id ? 'border-foreground/40 bg-secondary md:bg-secondary' : 'border-border bg-card md:bg-transparent md:hover:bg-secondary/50'"
                :aria-selected="detailFileId === file.id"
                @click="openDetailsFromRow(file.id, $event)"
              >
                <td class="col-span-2 md:table-cell md:px-2 md:py-3">
                  <div class="flex items-start gap-3 md:justify-center">
                    <div class="mt-0.5 shrink-0 rounded-lg bg-secondary p-2 md:hidden"><FileIcon class="h-4 w-4 text-primary" /></div>
                    <div class="min-w-0 md:text-center">
                      <p class="text-foreground font-medium [overflow-wrap:anywhere]">
                        <button
                          type="button"
                          translate="no"
                          class="text-left font-medium underline-offset-4 hover:underline focus-visible:underline md:text-center"
                          :title="`Details of ${file.name}`"
                          @click="detailFileId = file.id"
                        >
                          <FileIcon class="mr-1.5 hidden h-4 w-4 text-muted-foreground align-[-3px] md:inline" aria-hidden="true" />{{ file.name }}
                        </button>
                      </p>
                      <p v-if="!file.owned" class="text-xs text-muted-foreground">Shared by {{ file.ownerName }}</p>
                      <p v-if="file.accessError" class="mt-1 text-xs text-destructive">{{ file.accessError }}</p>
                      <p class="text-xs text-muted-foreground md:hidden">{{ file.originalSize }} -> {{ file.encryptedSize }}</p>
                      <button
                        type="button"
                        class="mt-1 inline-flex min-h-10 items-center gap-1 text-xs text-primary hover:underline md:min-h-0"
                        :aria-expanded="previewFileId === file.id"
                        :disabled="Boolean(file.accessError)"
                        @click="togglePreview(file)"
                      >
                        <component :is="previewFileId === file.id ? ChevronUp : ChevronDown" class="h-3 w-3" />
                        Encrypted preview
                      </button>
                    </div>
                  </div>
                </td>
                <td class="px-2 py-3 text-center text-muted-foreground hidden whitespace-nowrap md:table-cell" :title="exactBytes(file.originalBytes)">{{ file.originalSize }}</td>
                <td class="px-2 py-3 text-center text-muted-foreground hidden whitespace-nowrap md:table-cell" :title="exactBytes(file.encryptedBytes)">{{ file.encryptedSize }}</td>
                <td class="px-2 py-3 text-center text-muted-foreground hidden xl:table-cell">{{ file.encryptedAt }}</td>
                <td class="md:table-cell md:px-2 md:py-3 md:text-center">
                  <select
                    :value="file.folderId ?? ''"
                    :aria-label="`Folder for ${file.name}`"
                    class="h-10 w-full rounded-md border border-border bg-secondary px-2 text-sm text-foreground md:h-8 md:max-w-36 md:text-xs"
                    @change="moveFile(file, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="">No folder</option>
                    <option translate="no" v-for="folder in folders" :key="folder.folder_id" :value="folder.folder_id">{{ folder.name }}</option>
                  </select>
                </td>
                <td class="md:table-cell md:px-2 md:py-3 md:text-center">
                  <button
                    type="button"
                    class="inline-flex min-h-10 items-center gap-1 whitespace-nowrap rounded-md px-3 py-1 md:min-h-0 md:px-2 disabled:cursor-wait disabled:opacity-70"
                    :class="statusConfig[file.status].className"
                    :title="checkingFileId === file.id ? 'Checking integrity…' : 'Check integrity now'"
                    :aria-busy="checkingFileId === file.id"
                    :disabled="checkingFileId !== null"
                    @click="handleIntegrityCheck(file.id)"
                  >
                    <template v-if="checkingFileId === file.id">
                      <Loader2 class="h-3 w-3 animate-spin" />
                      Checking…
                    </template>
                    <template v-else>
                      <component :is="statusConfig[file.status].icon" class="h-3 w-3" />
                      {{ statusConfig[file.status].label }}
                    </template>
                  </button>
                </td>
                <td class="col-span-2 border-t border-border pt-3 md:table-cell md:border-0 md:px-2 md:py-3 md:pt-3">
                  <!-- The everyday actions stay visible (download, share, delete, access history); the rest sit under More. Sharing and
                       deleting belong to the owner: a recipient's grant carries can_share=false and
                       can_manage=false, so showing them would promise something the server refuses. -->
                  <!-- Wraps on the narrowest phones instead of squeezing a button below a tappable size. -->
                  <div class="relative flex flex-wrap items-center gap-1 md:flex-nowrap md:justify-center">
                    <button
                      class="h-10 w-10 shrink-0 md:h-8 md:w-8 inline-flex items-center justify-center rounded-md hover:bg-secondary disabled:opacity-40"
                      :title="downloadingId === file.id ? 'Decrypting...' : 'Download and decrypt'"
                      aria-label="Download and decrypt"
                      :disabled="downloadBusy || Boolean(file.accessError)"
                      @click="handleDownload(file.id)"
                    >
                      <Loader2 v-if="downloadingId === file.id" class="h-4 w-4 animate-spin" />
                      <Download v-else class="h-4 w-4" />
                    </button>
                    <button
                      v-if="file.owned"
                      type="button"
                      class="h-10 shrink-0 md:h-8 inline-flex items-center justify-center gap-1.5 rounded-md bg-primary px-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 md:w-8 md:px-0 xl:w-auto xl:px-2.5"
                      title="Share"
                      aria-label="Share"
                      @click="openShare(file.id)"
                    >
                      <Share2 class="h-4 w-4 shrink-0" />
                      <span class="md:hidden xl:inline">Share</span>
                    </button>
                    <button
                      v-if="file.owned"
                      type="button"
                      class="h-10 w-10 shrink-0 md:h-8 md:w-8 inline-flex items-center justify-center rounded-md hover:bg-secondary text-destructive"
                      title="Delete"
                      aria-label="Delete"
                      @click="handleDelete(file.id)"
                    >
                      <Trash2 class="h-4 w-4" />
                    </button>
                    <!-- On a tablet the column has room for five buttons: Access history waits in Details there. -->
                    <button
                      type="button"
                      class="h-10 w-10 shrink-0 md:hidden md:h-8 md:w-8 lg:inline-flex inline-flex items-center justify-center rounded-md hover:bg-secondary"
                      title="Access history"
                      aria-label="Access history"
                      @click="historyFileId = file.id"
                    >
                      <Activity class="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      class="order-last h-10 basis-full shrink-0 md:order-none md:basis-auto md:h-8 inline-flex items-center justify-center gap-1.5 rounded-md border border-border px-2.5 text-sm font-medium hover:bg-secondary md:w-8 md:px-0 min-[87.5rem]:w-auto min-[87.5rem]:px-2.5"
                      :class="detailFileId === file.id ? 'border-foreground/50 bg-background' : ''"
                      title="Details"
                      aria-label="Details"
                      :aria-expanded="detailFileId === file.id"
                      data-testid="file-details-button"
                      @click="detailFileId = file.id"
                    >
                      <PanelRightOpen class="h-4 w-4 shrink-0" />
                      <span class="md:hidden min-[87.5rem]:inline">Details</span>
                    </button>
                    <button
                      type="button"
                      class="h-10 w-10 shrink-0 md:h-8 md:w-8 inline-flex items-center justify-center rounded-md hover:bg-secondary"
                      title="More actions"
                      aria-label="More actions"
                      aria-haspopup="menu"
                      :aria-expanded="moreMenuFileId === file.id"
                      data-more-actions
                      @click="toggleMoreMenu(file.id, $event)"
                    >
                      <MoreHorizontal class="h-4 w-4" />
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="previewFileId === file.id" class="block md:table-row md:border-b md:border-border/60">
                <td :colspan="columnCount" class="block md:table-cell md:pb-4 md:pt-1">
                  <CiphertextPreviewPanel
                    :file-id="file.id"
                    :file-name="file.name"
                    @download-encrypted="handleEncryptedDownload(file)"
                  />
                </td>
              </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div v-if="pageCount > 1" class="flex items-center justify-between gap-4 mt-6 pt-4 border-t border-border">
          <p class="text-muted-foreground text-sm">Page {{ page }} of {{ pageCount }}</p>
          <div class="flex items-center gap-2">
            <button
              class="h-9 px-3 inline-flex items-center gap-1 rounded-md border border-border hover:bg-secondary disabled:opacity-40 disabled:cursor-not-allowed"
              :disabled="!hasPreviousPage || isLoading"
              @click="goToPage(page - 1)"
            >
              <ChevronLeft class="h-4 w-4" />
              Previous
            </button>
            <button
              class="h-9 px-3 inline-flex items-center gap-1 rounded-md border border-border hover:bg-secondary disabled:opacity-40 disabled:cursor-not-allowed"
              :disabled="!hasNextPage || isLoading"
              @click="goToPage(page + 1)"
            >
              Next
              <ChevronRight class="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <FileDetailDrawer
      v-if="detailFile"
      :file="detailFile"
      :download-busy="downloadBusy"
      :downloading="downloadingId === detailFile.id"
      :checking="checkingFileId === detailFile.id"
      @close="detailFileId = null"
      @download="handleDownload(detailFile.id); detailFileId = null"
      @share="openShare(detailFile.id); detailFileId = null"
      @check="handleIntegrityCheck(detailFile.id)"
      @history="historyFileId = detailFile.id; detailFileId = null"
      @delete="handleDelete(detailFile.id); detailFileId = null"
    />

    <FileHistoryDialog
      v-if="historyFile"
      :file-id="historyFile.id"
      :filename="historyFile.name"
      :owned="historyFile.owned"
      @close="historyFileId = null"
    />
    <ShareDialog
      v-if="shareFileId !== null"
      :file-id="shareFileId"
      :filename="shareFilename"
      @close="closeShare"
      @shared="onShared"
      @revoked="onRevoked"
    />
    <RequestRecoveryDialog
      v-if="recoveryFile"
      :file-id="recoveryFile.id"
      :filename="recoveryFile.name"
      @close="recoveryFileId = null"
      @requested="onRecoveryRequested"
    />
    <Teleport to="body">
      <div
        v-if="moreMenuFile"
        role="menu"
        :aria-label="`More actions for ${moreMenuFile.name}`"
        class="fixed z-50 w-56 rounded-lg border border-border bg-card p-1 text-left shadow-lg"
        :style="moreMenuStyle"
        data-more-actions
      >
        <button
          role="menuitem"
          type="button"
          class="flex min-h-10 w-full items-center gap-2 rounded-md px-3 py-2 text-sm md:min-h-0 text-foreground hover:bg-secondary disabled:opacity-40"
          :disabled="downloadBusy || Boolean(moreMenuFile.accessError)"
          @click="handleEncryptedDownload(moreMenuFile); closeMoreMenu()"
        >
          <FileLock2 class="h-4 w-4 shrink-0" />
          <span>Download encrypted file</span>
        </button>
        <button
          role="menuitem"
          type="button"
          class="flex min-h-10 w-full items-center gap-2 rounded-md px-3 py-2 text-sm md:min-h-0 text-foreground hover:bg-secondary disabled:opacity-40"
          :disabled="Boolean(moreMenuFile.accessError) || moreMenuFile.status === 'modified'"
          @click="recoveryFileId = moreMenuFile.id; closeMoreMenu()"
        >
          <LifeBuoy class="h-4 w-4 shrink-0" />
          <span>Request recovery</span>
        </button>
        <!-- A recovery request re-seals the file key to the account key. It cannot put changed
             bytes back, so for a file the integrity check flagged it is off, with the reason. -->
        <p
          v-if="moreMenuFile.status === 'modified'"
          class="max-w-64 px-3 pb-2 pt-1 text-xs leading-relaxed text-muted-foreground"
          data-testid="recovery-unavailable-note"
        >
          This file's stored copy was changed. An administrator restores it from backup; Request recovery only re-seals a key.
        </p>
      </div>
    </Teleport>
    <ConfirmActionDialog
      v-if="pendingFolderDelete"
      title="Delete this folder?"
      :detail="pendingFolderDelete.name"
      consequence="The encrypted files stay safe and are no longer in any folder. Only this organizational folder is removed."
      confirm-label="Delete folder"
      busy-label="Deleting…"
      :busy="folderBusy"
      @confirm="deleteFolder"
      @close="pendingFolderDelete = null"
    />
    <ConfirmActionDialog
      v-if="pendingDelete"
      title="Delete this file?"
      :detail="pendingDelete.name"
      consequence="This permanently removes the encrypted file from SecureView and revokes every share. Recipients lose access immediately. It cannot be undone from this app."
      confirm-label="Delete file"
      busy-label="Deleting…"
      :busy="isDeleting"
      @confirm="confirmDelete"
      @close="closePendingDelete"
    />
    <ConfirmActionDialog
      v-if="pendingRiskyDownload"
      title="This file could run code"
      :detail="pendingRiskyDownload.name"
      :consequence="riskyConsequence"
      confirm-label="Download anyway"
      @confirm="confirmRiskyDownload"
      @close="pendingRiskyDownload = null"
    />
    <UnlockDialog
      v-if="showUnlock"
      :key-id="unlockKeyId"
      @unlocked="onUnlocked"
      @close="closeUnlock"
    />
  </section>
</template>
