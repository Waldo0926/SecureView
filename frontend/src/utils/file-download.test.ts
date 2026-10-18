import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { http } from '@/api/http'
import { downloadAndDecrypt, forgetUnlockedKeys, isUnlocked, NotUnlockedError, saveDecryptedFile } from '@/crypto/download'
import { downloadEncryptedFile } from './file-download'

let savedBlob: Blob | undefined
const anchor = { href: '', download: '', click: vi.fn(), remove: vi.fn() }

beforeEach(() => {
  vi.useFakeTimers()
  forgetUnlockedKeys()
  savedBlob = undefined
  anchor.href = ''
  anchor.download = ''
  anchor.click.mockClear()
  anchor.remove.mockClear()
  vi.stubGlobal('document', {
    createElement: vi.fn(() => anchor),
    body: { appendChild: vi.fn() },
  })
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
    savedBlob = blob as Blob
    return 'blob:encrypted-download'
  })
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
})

afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  forgetUnlockedKeys()
})

describe('encrypted file download', () => {
  it.each([0, 6, 2 * 1024 * 1024])('saves exactly %i ciphertext bytes while the vault is locked', async (size) => {
    const bytes = Uint8Array.from({ length: size }, (_, index) => index % 256)
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: bytes.buffer })
    const get = vi.spyOn(http, 'get')
    const decrypt = vi.spyOn(crypto.subtle, 'decrypt')

    await downloadEncryptedFile('file-id', 'notes.txt')

    expect(post).toHaveBeenCalledExactlyOnceWith('/files/file-id/download', null, { responseType: 'arraybuffer' })
    expect(get).not.toHaveBeenCalled()
    expect(decrypt).not.toHaveBeenCalled()
    expect(isUnlocked()).toBe(false)
    expect(savedBlob?.type).toBe('application/octet-stream')
    expect(savedBlob?.size).toBe(size)
    const saved = new Uint8Array(await savedBlob!.arrayBuffer())
    expect(saved.every((byte, index) => byte === bytes[index])).toBe(true)
    expect(anchor.download).toBe('notes.txt.ciphertext')
    expect(anchor.href).toBe('blob:encrypted-download')
    expect(anchor.click).toHaveBeenCalledOnce()
    expect(anchor.remove).toHaveBeenCalledOnce()
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    vi.runOnlyPendingTimers()
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:encrypted-download')
  })

  it.each([
    ['report.pdf', 'report.pdf.ciphertext'],
    ['报告.txt', '报告.txt.ciphertext'],
    ['folder/notes?.txt', 'folder_notes_.txt.ciphertext'],
    ['CON.txt', '_CON.txt.ciphertext'],
    ['..', 'encrypted-file.ciphertext'],
    ['', 'encrypted-file.ciphertext'],
  ])('uses a safe encrypted filename for %s', async (name, expected) => {
    vi.spyOn(http, 'post').mockResolvedValue({ data: new ArrayBuffer(0) })
    await downloadEncryptedFile('file-id', name)
    expect(anchor.download).toBe(expected)
  })

  it.each([
    'Not authenticated',
    'File not found or access revoked',
    'File integrity verification failed',
    'Network unavailable',
  ])('never saves an error response: %s', async (message) => {
    const error = new Error(message)
    vi.spyOn(http, 'post').mockRejectedValue(error)

    await expect(downloadEncryptedFile('file-id', 'notes.txt')).rejects.toBe(error)

    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(anchor.click).not.toHaveBeenCalled()
    expect(isUnlocked()).toBe(false)
  })

  it('keeps plaintext downloads locked after downloading ciphertext', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: new ArrayBuffer(0) })
    await downloadEncryptedFile('file-id', 'notes.txt')

    await expect(downloadAndDecrypt('file-id')).rejects.toBeInstanceOf(NotUnlockedError)
    expect(post).toHaveBeenCalledOnce()
  })

  it('preserves the original filename, MIME type and contents when saving decrypted files', async () => {
    const bytes = new TextEncoder().encode('a decrypted document')
    saveDecryptedFile({ filename: 'notes.txt', mimeType: 'text/plain', bytes })

    expect(anchor.download).toBe('notes.txt')
    expect(savedBlob?.type).toBe('text/plain')
    expect(await savedBlob!.text()).toBe('a decrypted document')
    expect(anchor.click).toHaveBeenCalledOnce()
  })
})
