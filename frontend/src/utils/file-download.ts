import { fileApi } from '@/api/file_api'

export interface DownloadableFile {
  filename: string
  mimeType: string
  bytes: Uint8Array
}

/** Save bytes without interpreting their contents or changing their format. */
export function saveFile(file: DownloadableFile): void {
  const blob = new Blob([file.bytes as BlobPart], { type: file.mimeType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  try {
    anchor.href = url
    anchor.download = file.filename
    document.body.appendChild(anchor)
    anchor.click()
  } finally {
    anchor.remove()
    // Let the browser start the save before releasing the object URL.
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

/** Download the stored ciphertext, including when the account key is locked. */
export async function downloadEncryptedFile(fileId: string, originalFilename: string): Promise<void> {
  // Use the same authenticated endpoint as decryption so grants, revocation, integrity
  // verification, and download auditing still apply. No key bundle is needed.
  const response = await fileApi.download(fileId)
  let basename = originalFilename
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, '_')
    .replace(/^[.\s]+|[.\s]+$/g, '')
    .slice(0, 150) || 'encrypted-file'
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(basename)) basename = `_${basename}`
  saveFile({
    filename: `${basename}.ciphertext`,
    mimeType: 'application/octet-stream',
    bytes: new Uint8Array(response.data as ArrayBuffer),
  })
}
