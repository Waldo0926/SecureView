import { describe, expect, it } from 'vitest'

import {
  asciiBytes,
  bytesEqual,
  bytesToHex,
  concatBytes,
  frame,
  fromBase64,
  hex32,
  hexToBytes,
  toBase64,
  u32,
  u64,
  u8,
  utf8Bytes,
  uuidToBytes,
} from './encoding'

describe('integers are unsigned big-endian', () => {
  it('encodes u8, u32 and u64 at their boundaries', () => {
    expect(bytesToHex(u8(0))).toBe('00')
    expect(bytesToHex(u8(255))).toBe('ff')
    expect(bytesToHex(u32(0))).toBe('00000000')
    expect(bytesToHex(u32(1))).toBe('00000001')
    expect(bytesToHex(u32(0xffffffff))).toBe('ffffffff')
    expect(bytesToHex(u64(0))).toBe('0000000000000000')
    expect(bytesToHex(u64(1))).toBe('0000000000000001')
    expect(bytesToHex(u64(0xffffffffffffffffn))).toBe('ffffffffffffffff')
  })

  it('rejects out-of-range and non-integer input', () => {
    expect(() => u8(256)).toThrow(RangeError)
    expect(() => u32(-1)).toThrow(RangeError)
    expect(() => u32(1.5)).toThrow(RangeError)
    expect(() => u64(-1n)).toThrow(RangeError)
  })

  it('refuses a number too large to represent exactly rather than rounding it', () => {
    // Silently rounding here would emit bytes for a size the server never agreed to.
    expect(() => u64(Number.MAX_SAFE_INTEGER + 2)).toThrow(RangeError)
    expect(bytesToHex(u64(BigInt(Number.MAX_SAFE_INTEGER) + 2n))).toBe('0020000000000001')
  })
})

describe('uuidToBytes', () => {
  it('encodes the 16 raw bytes in network order, not the text form', () => {
    expect(bytesToHex(uuidToBytes('00112233-4455-6677-8899-aabbccddeeff'))).toBe(
      '00112233445566778899aabbccddeeff',
    )
  })

  it('accepts uppercase and surrounding whitespace', () => {
    expect(uuidToBytes('  00112233-4455-6677-8899-AABBCCDDEEFF  ')).toEqual(
      uuidToBytes('00112233-4455-6677-8899-aabbccddeeff'),
    )
  })

  it('rejects anything that is not a hyphenated UUID', () => {
    expect(() => uuidToBytes('00112233445566778899aabbccddeeff')).toThrow(TypeError)
    expect(() => uuidToBytes('not-a-uuid')).toThrow(TypeError)
    expect(() => uuidToBytes('')).toThrow(TypeError)
  })
})

describe('framing makes the encoding injective', () => {
  it('prefixes the length as u32', () => {
    expect(bytesToHex(frame(hexToBytes('aabb')))).toBe('00000002aabb')
    expect(bytesToHex(frame(new Uint8Array()))).toBe('00000000')
  })

  it('separates field assignments that would otherwise collide', () => {
    // Unframed, "AB" + "C" and "A" + "BC" are the same bytes.
    const framed = (left: string, right: string) =>
      bytesToHex(concatBytes(frame(asciiBytes(left)), frame(asciiBytes(right))))
    expect(framed('AB', 'C')).not.toBe(framed('A', 'BC'))
  })
})

describe('text encoding', () => {
  it('rejects non-ASCII where the schema guarantees ASCII', () => {
    expect(bytesToHex(asciiBytes('AES-256-GCM'))).toBe('4145532d3235362d47434d')
    expect(() => asciiBytes('文件')).toThrow(TypeError)
  })

  it('normalizes filenames to NFC so the AAD survives the round trip', () => {
    // The backend stores NFC. A client hashing the NFD form builds an AAD that will not
    // match the one rebuilt from the filename the API returns at download.
    const nfc = 'r\u00e9sum\u00e9.pdf'
    const nfd = nfc.normalize('NFD')
    expect(nfd).not.toBe(nfc)
    expect(nfd.length).toBeGreaterThan(nfc.length)
    expect(utf8Bytes(nfd)).toEqual(utf8Bytes(nfc))
  })

  it('encodes CJK filenames as UTF-8', () => {
    expect(bytesToHex(utf8Bytes('机密.txt'))).toBe('e69cbae5af862e747874')
  })
})

describe('canonical Base64', () => {
  it('round trips with standard alphabet and padding', () => {
    const bytes = hexToBytes('00010203fffefdfc')
    expect(toBase64(bytes)).toBe('AAECA//+/fw=')
    expect(fromBase64(toBase64(bytes))).toEqual(bytes)
    expect(toBase64(new Uint8Array())).toBe('')
  })

  it('rejects the encodings the API also rejects', () => {
    expect(() => fromBase64('AAECA_7-_fw=')).toThrow(TypeError) // URL-safe alphabet
    expect(() => fromBase64('AAECA//+/fw')).toThrow(TypeError) // unpadded
    expect(() => fromBase64('AAEC A//+/fw=')).toThrow(TypeError) // whitespace
    expect(() => fromBase64(' AAECA//+/fw=')).toThrow(TypeError) // leading space
  })

  it('rejects non-canonical trailing bits', () => {
    // "AB==" decodes to the same byte as "AA==" but sets discarded padding bits.
    expect(() => fromBase64('AB==')).toThrow(TypeError)
    expect(fromBase64('AA==')).toEqual(new Uint8Array([0]))
  })
})

describe('hex helpers', () => {
  it('round trips and enforces lowercase even-length input', () => {
    expect(bytesToHex(hexToBytes('00ff10'))).toBe('00ff10')
    expect(() => hexToBytes('0')).toThrow(TypeError)
    expect(() => hexToBytes('00FF')).toThrow(TypeError)
    expect(() => hexToBytes('zz')).toThrow(TypeError)
  })

  it('hex32 accepts only a full SHA-256 digest', () => {
    expect(hex32('a'.repeat(64))).toHaveLength(32)
    expect(() => hex32('a'.repeat(63))).toThrow(TypeError)
    expect(() => hex32('A'.repeat(64))).toThrow(TypeError)
  })
})

describe('bytesEqual', () => {
  it('compares length and content', () => {
    expect(bytesEqual(hexToBytes('0102'), hexToBytes('0102'))).toBe(true)
    expect(bytesEqual(hexToBytes('0102'), hexToBytes('0103'))).toBe(false)
    expect(bytesEqual(hexToBytes('0102'), hexToBytes('010200'))).toBe(false)
  })
})
