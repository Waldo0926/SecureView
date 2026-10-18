/**
 * Helpers for the encrypted-preview panel: turn the bytes the server stores into something a
 * person can read, and say what they do and do not show.
 */

import type { CiphertextPreviewOut } from '@/api/types'

const BYTES_PER_ROW = 16

export function hexToBytes(hex: string): number[] {
  if (hex.length % 2 !== 0 || /[^0-9a-f]/i.test(hex)) {
    throw new Error('Not a hexadecimal string')
  }
  const bytes: number[] = []
  for (let index = 0; index < hex.length; index += 2) {
    bytes.push(Number.parseInt(hex.slice(index, index + 2), 16))
  }
  return bytes
}

export interface HexRow {
  offset: string
  hex: string
  ascii: string
}

/** The classic hex-dump layout: offset, sixteen bytes, and the printable characters. */
export function hexDumpRows(hex: string): HexRow[] {
  const bytes = hexToBytes(hex)
  const rows: HexRow[] = []
  for (let start = 0; start < bytes.length; start += BYTES_PER_ROW) {
    const chunk = bytes.slice(start, start + BYTES_PER_ROW)
    rows.push({
      offset: start.toString(16).padStart(8, '0'),
      hex: chunk.map((byte) => byte.toString(16).padStart(2, '0')).join(' '),
      ascii: chunk.map((byte) => (byte >= 0x20 && byte < 0x7f ? String.fromCharCode(byte) : '.')).join(''),
    })
  }
  return rows
}

interface FileSignature {
  label: string
  /** Hex, lowercase, no spaces. At least three bytes, so a random sample almost never matches. */
  magic: string
}

/**
 * How well-known formats begin. The extension only selects what to compare against; nothing
 * here is sent anywhere. A *plain* file of that type starts with these bytes, so stored bytes
 * that do start with them would mean the file is not encrypted at all.
 */
const SIGNATURES: Record<string, FileSignature> = {
  pdf: { label: 'a PDF (%PDF)', magic: '25504446' },
  png: { label: 'a PNG image', magic: '89504e47' },
  jpg: { label: 'a JPEG image', magic: 'ffd8ff' },
  jpeg: { label: 'a JPEG image', magic: 'ffd8ff' },
  gif: { label: 'a GIF image', magic: '47494638' },
  zip: { label: 'a ZIP archive (PK)', magic: '504b0304' },
  docx: { label: 'a Word document (a ZIP archive, PK)', magic: '504b0304' },
  xlsx: { label: 'an Excel workbook (a ZIP archive, PK)', magic: '504b0304' },
  pptx: { label: 'a PowerPoint deck (a ZIP archive, PK)', magic: '504b0304' },
  gz: { label: 'a gzip archive', magic: '1f8b08' },
}

export type HeaderCheck =
  | { kind: 'none' }
  | { kind: 'hidden'; expected: string; label: string }
  | { kind: 'exposed'; expected: string; label: string }

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot < 0 ? '' : filename.slice(dot + 1).toLowerCase()
}

/**
 * Compare the start of the stored bytes with how an unencrypted file of this type begins.
 *
 * `hidden` is the expected result: the plain header is not there. `exposed` is the alarming
 * one and is reported as such rather than smoothed over.
 */
export function checkFileHeader(filename: string, sampleHex: string): HeaderCheck {
  const signature = SIGNATURES[extensionOf(filename)]
  if (!signature || sampleHex.length < signature.magic.length) return { kind: 'none' }
  const expected = signature.magic.match(/../g)!.join(' ')
  return sampleHex.toLowerCase().startsWith(signature.magic)
    ? { kind: 'exposed', expected, label: signature.label }
    : { kind: 'hidden', expected, label: signature.label }
}

/** Exact byte counts, because "7.54 MB" for both sizes hides the only thing being asked about. */
export function exactBytes(bytes: number): string {
  return `${bytes.toLocaleString('en-US')} bytes`
}

export interface SizeRelation {
  sameLength: boolean
  explanation: string
}

/**
 * Why the two sizes match, or what the difference means.
 *
 * Every supported suite (AES-GCM, AES-GCM-SIV, ChaCha20 and XChaCha20-Poly1305) encrypts as a
 * stream: no padding, so the ciphertext is exactly as long as the original. The nonce (12
 * bytes, or 24 for XChaCha20-Poly1305) and the 16-byte authentication tag are stored beside
 * the file, not appended to it. A mismatch is therefore not "overhead" but a
 * sign that something is wrong, and the panel says so.
 */
export function describeSizes(preview: Pick<CiphertextPreviewOut, 'plaintext_size' | 'ciphertext_size'>): SizeRelation {
  if (preview.plaintext_size === preview.ciphertext_size) {
    return {
      sameLength: true,
      explanation:
        'Same length is expected. These algorithms encrypt without padding, so the ciphertext is exactly as long as the original. The nonce (12 bytes, or 24 for XChaCha20-Poly1305) and the 16-byte authentication tag are stored next to the file, not added to it.',
    }
  }
  const difference = preview.ciphertext_size - preview.plaintext_size
  return {
    sameLength: false,
    explanation: `The stored object is ${Math.abs(difference).toLocaleString('en-US')} bytes ${
      difference > 0 ? 'longer' : 'shorter'
    } than the original, which these algorithms never produce. Run the integrity check.`,
  }
}
