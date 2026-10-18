import { http } from './http'
import type { ApiEnvelope } from './auth_api'
import type {
  CiphertextPreviewOut,
  FileFolderListOut,
  FileFolderOut,
  FileListOut,
  FileOut,
} from './types'
import type { UploadPayload } from '@/crypto/file_envelope'

export const fileApi = {
  /**
   * Paginated. The rows arrive as `data.items`; `page_size` caps at 100.
   *
   * `search` is a case-insensitive substring of the original filename, matched by the
   * server across every page. Filtering in the browser can only ever see the page it
   * already holds, which is why the box used to answer "no results" for files that
   * existed on another page.
   */
  listFiles(params?: {
    page?: number
    page_size?: number
    search?: string
    folder_id?: string
    unfiled?: boolean
    /** Split on the server, so each tab pages through its own files. */
    scope?: 'all' | 'mine' | 'shared'
  }) {
    return http.get<ApiEnvelope<FileListOut>>('/files', { params })
  },
  getFile(fileId: string) {
    return http.get<ApiEnvelope<FileOut>>(`/files/${fileId}`)
  },
  listFolders() {
    return http.get<ApiEnvelope<FileFolderListOut>>('/files/folders')
  },
  createFolder(name: string) {
    return http.post<ApiEnvelope<FileFolderOut>>('/files/folders', { name })
  },
  renameFolder(folderId: string, name: string) {
    return http.post<ApiEnvelope<FileFolderOut>>(`/files/folders/${folderId}/rename`, { name })
  },
  deleteFolder(folderId: string) {
    return http.post(`/files/folders/${folderId}/delete`)
  },
  moveFile(fileId: string, folderId: string | null) {
    return http.post(`/files/${fileId}/move`, { folder_id: folderId })
  },

  /**
   * Upload one already-encrypted file.
   *
   * The route takes two multipart parts: `file` carries the ciphertext, and `metadata`
   * carries the JSON envelope describing it. Sending only the file is what produced the
   * bare "422" the upload page used to show -- `metadata` is a required form field, and
   * the browser has no way to fill it in without encrypting first.
   *
   * `Content-Type` is deliberately not set here. The browser must generate the multipart
   * boundary itself; naming the type without a boundary produces a body the server cannot
   * parse.
   */
  uploadEncrypted(payload: UploadPayload, onProgress?: (fraction: number) => void) {
    const form = new FormData()
    const ciphertext = new Blob([payload.ciphertext as BlobPart], {
      type: 'application/octet-stream',
    })
    form.append('file', ciphertext, `${payload.metadata.file_id}.ciphertext`)
    form.append('metadata', JSON.stringify(payload.metadata))
    return http.post<ApiEnvelope<FileOut>>('/files/upload', form, {
      onUploadProgress: onProgress
        ? (event) => {
            if (event.total) onProgress(event.loaded / event.total)
          }
        : undefined,
    })
  },

  /** Verified ciphertext only. The caller can save it as-is or decrypt it locally. */
  download(fileId: string) {
    return http.post(`/files/${fileId}/download`, null, { responseType: 'arraybuffer' })
  },
  /** A bounded sample of the stored ciphertext, for showing that the server holds no plaintext. */
  ciphertextPreview(fileId: string) {
    return http.post<ApiEnvelope<CiphertextPreviewOut>>(`/files/${fileId}/ciphertext-preview`)
  },
  delete(fileId: string) {
    return http.post(`/files/${fileId}/delete`)
  },
  integrityCheck(fileId: string) {
    return http.post(`/files/${fileId}/integrity-check`)
  },
}
