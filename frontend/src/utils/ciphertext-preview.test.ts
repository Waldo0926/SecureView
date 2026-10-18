import { describe, expect, it } from 'vitest'

import { checkFileHeader, describeSizes, exactBytes, hexDumpRows, hexToBytes } from './ciphertext-preview'

describe('hexToBytes', () => {
  it('decodes hexadecimal and refuses anything else', () => {
    expect(hexToBytes('00ff10')).toEqual([0, 255, 16])
    expect(hexToBytes('')).toEqual([])
    expect(() => hexToBytes('abc')).toThrow()
    expect(() => hexToBytes('zz')).toThrow()
  })
})

describe('hexDumpRows', () => {
  it('lays bytes out sixteen to a row with offsets and printable characters', () => {
    const bytes = Array.from({ length: 20 }, (_, index) => 0x41 + index) // A..T
    const rows = hexDumpRows(bytes.map((byte) => byte.toString(16)).join(''))

    expect(rows).toHaveLength(2)
    expect(rows[0]).toEqual({
      offset: '00000000',
      hex: '41 42 43 44 45 46 47 48 49 4a 4b 4c 4d 4e 4f 50',
      ascii: 'ABCDEFGHIJKLMNOP',
    })
    expect(rows[1].offset).toBe('00000010')
    expect(rows[1].ascii).toBe('QRST')
  })

  it('shows unprintable bytes as dots and copes with an empty sample', () => {
    expect(hexDumpRows('0007f0ff')[0].ascii).toBe('....')
    expect(hexDumpRows('')).toEqual([])
  })
})

describe('checkFileHeader', () => {
  it('reports that a plain header is NOT present, which is what encryption should give', () => {
    const result = checkFileHeader('report.PDF', '9ce17a02aabbccdd')
    expect(result).toMatchObject({ kind: 'hidden', expected: '25 50 44 46' })
  })

  it('raises the alarm when the stored bytes begin like an unencrypted file', () => {
    expect(checkFileHeader('report.pdf', '25504446deadbeef').kind).toBe('exposed')
    expect(checkFileHeader('notes.docx', '504b0304aabb').kind).toBe('exposed')
    expect(checkFileHeader('photo.jpg', 'ffd8ffe000').kind).toBe('exposed')
  })

  it('says nothing for types with no fixed header, no extension, or too short a sample', () => {
    expect(checkFileHeader('notes.txt', '41424344').kind).toBe('none')
    expect(checkFileHeader('README', '41424344').kind).toBe('none')
    expect(checkFileHeader('report.pdf', '2550').kind).toBe('none')
  })
})

describe('describeSizes', () => {
  it('explains equal sizes as the expected, padding-free result', () => {
    const relation = describeSizes({ plaintext_size: 7_903_232, ciphertext_size: 7_903_232 })
    expect(relation.sameLength).toBe(true)
    expect(relation.explanation).toMatch(/Same length is expected/)
    expect(relation.explanation).toMatch(/nonce \(12 bytes, or 24 for XChaCha20-Poly1305\).*16-byte authentication tag/)
  })

  it('treats any difference as a problem rather than overhead', () => {
    const longer = describeSizes({ plaintext_size: 100, ciphertext_size: 116 })
    expect(longer.sameLength).toBe(false)
    expect(longer.explanation).toMatch(/16 bytes longer/)
    expect(describeSizes({ plaintext_size: 100, ciphertext_size: 90 }).explanation).toMatch(/10 bytes shorter/)
  })
})

describe('exactBytes', () => {
  it('prints the whole number so near-equal sizes are not hidden by rounding', () => {
    expect(exactBytes(7_903_232)).toBe('7,903,232 bytes')
    expect(exactBytes(0)).toBe('0 bytes')
  })
})
