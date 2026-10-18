export interface ApiEnvelope<T> {
  success: boolean
  status: string
  message: string
  data: T
  code: number
}

/** One row of `GET /files`. Mirrors the backend `FileSummaryOut`. */
export interface FileSummaryOut {
  file_id: string
  original_filename: string
  /** Size of the original file. Equal to the ciphertext size under AES-GCM. */
  plaintext_size: number
  /** Size of the stored ciphertext, excluding the detached authentication tag. */
  ciphertext_size: number
  /** SHA-256 of the stored ciphertext, as recorded at upload. */
  ciphertext_sha256: string
  mime_type: string | null
  encryption_algorithm: string
  status: string
  owner: boolean
  /** Who uploaded it. Null only for a row whose owner row could not be loaded. */
  owner_username: string | null
  /** Owner-only organization. Null means the file is in no folder (and is always null on shared rows). */
  folder_id: string | null
  created_at: string
  updated_at: string
}

/** `GET /files/{id}` adds the envelope needed to decrypt. */
export interface FileOut extends FileSummaryOut {
  crypto_envelope: FileCryptoEnvelopeOut
}

/** The envelope fields a client needs to unwrap the file key and decrypt. */
export interface FileCryptoEnvelopeOut {
  encryption_algorithm: 'AES-256-GCM'
  envelope_version: number
  aad_version: number
  nonce: string
  auth_tag: string
  key_id: string
  key_wrapping_algorithm: 'RSA-OAEP-SHA256'
  wrapped_file_key: string
  encrypted_manifest: string | null
}

/** `GET /files` is paginated: the rows live under `items`, not `files`. */
export interface FileListOut {
  items: FileSummaryOut[]
  page: number
  page_size: number
  /** Files matching every filter, the tab included: what this page is a page of. */
  total: number
  /** Your own files and files shared with you that match the search, for the tab labels. */
  owned_total: number
  shared_total: number
}

export interface FileFolderOut {
  folder_id: string
  name: string
  file_count: number
  /** The same total split by tab: your own files, and shared files you filed here. */
  owned_file_count: number
  shared_file_count: number
  created_at: string
  updated_at: string
}

export interface FileFolderListOut {
  items: FileFolderOut[]
}

/**
 * One row of `GET /audit-logs`. Mirrors the backend `AuditLogOut` exactly.
 *
 * It previously declared `log_id`, `file_id`, `actor_username`, `device` and `location` --
 * none of which the API has ever sent. Because every field was optional, TypeScript was
 * happy and the page silently read `undefined` for all of them: every row grouped under one
 * "unknown" file, every actor rendered as "Unknown user", and the device and location
 * columns were permanently "Unknown". The audit trail was on screen and told you nothing.
 *
 * The server identifies the subject as `resource_type` + `resource_id`, not as a file id:
 * a row can be about a FILE, a SHARE, or a USER.
 */
export interface AuditLogOut {
  action: string
  resource_type: string
  resource_id: string | null
  actor_user_id: string | null
  actor_username: string | null
  target_user_id: string | null
  target_username: string | null
  result: string
  description: string | null
  metadata: Record<string, unknown>
  created_at: string
  /** For a row about a file: its original name. Deleted files keep theirs (a soft delete). */
  file_name?: string | null
  /** The file has since been deleted. */
  file_deleted?: boolean
}

/**
 * `POST /files/{id}/ciphertext-preview`: a fixed-size look at what the server stores.
 *
 * `sample_hex` is the start of the stored *ciphertext*, never of the original file, and it is
 * not integrity-checked by this call (that is what the status badge and the integrity check
 * are for).
 */
export interface CiphertextPreviewOut {
  file_id: string
  encryption_algorithm: string
  plaintext_size: number
  ciphertext_size: number
  ciphertext_sha256: string
  status: string
  sample_offset: number
  sample_length: number
  sample_hex: string
}

export function unwrapData<T>(response: { data: ApiEnvelope<T> }): T {
  return response.data.data
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
}

export type FileBadge = 'verified' | 'modified' | 'pending'

/**
 * Map an *integrity check* result onto a badge.
 *
 * The vocabulary here is the one `POST /files/{id}/integrity-check` answers with:
 * `VALID`, `MODIFIED`, `MISSING`, `ERROR`. It is not the vocabulary of `files.status`.
 */
export function mapFileStatus(status: string): FileBadge {
  const normalized = status.toUpperCase()
  if (normalized === 'VALID' || normalized === 'VERIFIED') return 'verified'
  if (normalized === 'MODIFIED' || normalized === 'INVALID') return 'modified'
  return 'pending'
}

/**
 * Map a *file lifecycle* status onto a badge.
 *
 * `GET /files` reports `files.status` — `ACTIVE`, `CORRUPTED`, `DELETED` — which shares no
 * word with the integrity vocabulary above. Running it through `mapFileStatus` sent every
 * value down the fallback branch, so a healthy file and a file the server had positively
 * marked as damaged both rendered as an identical grey "Pending". The two lookups are kept
 * apart because they answer different questions about different fields.
 */
export function mapFileLifecycle(status: string): FileBadge {
  const normalized = status.toUpperCase()
  if (normalized === 'ACTIVE') return 'verified'
  if (normalized === 'CORRUPTED') return 'modified'
  return 'pending'
}
