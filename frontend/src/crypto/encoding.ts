/**
 * Byte-level encoding primitives for the cryptographic envelopes.
 *
 * The layout mirrors the length-prefixed encoding the backend already uses to build its
 * authorization digests (`app/services/key_service.py`, `_frame`), so a single encoder
 * serves both the file-envelope AAD and the RSA-PSS digests. Multi-byte integers are
 * unsigned big-endian; every variable-length field is length-prefixed.
 *
 * Framing is what makes the encoding injective. Without it two adjacent fields can be
 * shifted against each other so that different field values produce identical bytes.
 */

/** Concatenate byte strings in order. */
export function concatBytes(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0)
  const out = new Uint8Array(total)
  let offset = 0
  for (const part of parts) {
    out.set(part, offset)
    offset += part.length
  }
  return out
}

/** One unsigned byte. */
export function u8(value: number): Uint8Array {
  if (!Number.isInteger(value) || value < 0 || value > 0xff) {
    throw new RangeError(`u8 out of range: ${value}`)
  }
  return new Uint8Array([value])
}

/** Four bytes, unsigned big-endian. */
export function u32(value: number): Uint8Array {
  if (!Number.isInteger(value) || value < 0 || value > 0xffff_ffff) {
    throw new RangeError(`u32 out of range: ${value}`)
  }
  const out = new Uint8Array(4)
  new DataView(out.buffer).setUint32(0, value, false)
  return out
}

/**
 * Eight bytes, unsigned big-endian.
 *
 * Accepts a number or bigint. A plain number above Number.MAX_SAFE_INTEGER cannot be
 * represented exactly, so it is rejected rather than silently rounded into the wrong bytes.
 */
export function u64(value: number | bigint): Uint8Array {
  let big: bigint
  if (typeof value === 'bigint') {
    big = value
  } else {
    if (!Number.isSafeInteger(value)) {
      throw new RangeError(`u64 needs a safe integer or bigint, received: ${value}`)
    }
    big = BigInt(value)
  }
  if (big < 0n || big > 0xffff_ffff_ffff_ffffn) {
    throw new RangeError(`u64 out of range: ${big}`)
  }
  const out = new Uint8Array(8)
  new DataView(out.buffer).setBigUint64(0, big, false)
  return out
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

/**
 * The 16 raw bytes of an RFC 4122 UUID, network order — not its hyphenated text form.
 *
 * The text form is lowercased before matching so a canonical uppercase UUID from another
 * system is accepted, but any other shape is rejected: a UUID that silently encodes to the
 * wrong bytes would produce an envelope that never authenticates.
 */
export function uuidToBytes(uuid: string): Uint8Array {
  const normalized = uuid.trim().toLowerCase()
  if (!UUID_PATTERN.test(normalized)) {
    throw new TypeError(`Not a hyphenated RFC 4122 UUID: ${uuid}`)
  }
  return hexToBytes(normalized.replace(/-/g, ''))
}

/** `u32(len(bytes)) ‖ bytes` — a length-prefixed byte string. */
export function frame(bytes: Uint8Array): Uint8Array {
  return concatBytes(u32(bytes.length), bytes)
}

/**
 * ASCII bytes, used for algorithm identifiers that the API schemas constrain to ASCII.
 *
 * Non-ASCII input is rejected instead of being encoded as UTF-8, because a caller passing a
 * non-ASCII value here has confused an identifier with user-supplied text.
 */
export function asciiBytes(text: string): Uint8Array {
  const out = new Uint8Array(text.length)
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i)
    if (code > 0x7f) {
      throw new TypeError(`Not ASCII at index ${i}: ${JSON.stringify(text)}`)
    }
    out[i] = code
  }
  return out
}

/**
 * UTF-8 bytes after Unicode NFC normalization.
 *
 * The backend normalizes filenames to NFC before storing them, so a client that hashes the
 * un-normalized string builds an AAD that will not match the one rebuilt at download.
 */
export function utf8Bytes(text: string): Uint8Array {
  return new TextEncoder().encode(text.normalize('NFC'))
}

/** Raw bytes from a lowercase hex string. */
export function hexToBytes(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) {
    throw new TypeError('Hex input must have an even length')
  }
  if (!/^[0-9a-f]*$/.test(hex)) {
    throw new TypeError('Hex input must be lowercase [0-9a-f]')
  }
  const out = new Uint8Array(hex.length / 2)
  for (let i = 0; i < out.length; i += 1) {
    out[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16)
  }
  return out
}

/** Lowercase hex from raw bytes. */
export function bytesToHex(bytes: Uint8Array): string {
  let out = ''
  for (const byte of bytes) {
    out += byte.toString(16).padStart(2, '0')
  }
  return out
}

/** The 32 raw bytes of a 64-character lowercase hex SHA-256 digest. */
export function hex32(digestHex: string): Uint8Array {
  if (!/^[0-9a-f]{64}$/.test(digestHex)) {
    throw new TypeError('Expected a 64-character lowercase hex SHA-256 digest')
  }
  return hexToBytes(digestHex)
}

/**
 * Standard Base64 with `+/` and mandatory `=` padding — never URL-safe, never unpadded.
 *
 * The API rejects any encoding that does not re-encode to the identical string
 * (`key_schema.decode_base64`, `file_schema._decode_canonical_base64`).
 */
export function toBase64(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary)
}

/** Decode canonical Base64, rejecting anything the API would also reject. */
export function fromBase64(encoded: string): Uint8Array {
  if (encoded !== encoded.trim() || /\s/.test(encoded)) {
    throw new TypeError('Base64 input must not contain whitespace')
  }
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(encoded) || encoded.length % 4 !== 0) {
    throw new TypeError('Base64 input must be canonical padded standard Base64')
  }
  const binary = atob(encoded)
  const out = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    out[i] = binary.charCodeAt(i)
  }
  // Reject non-canonical encodings whose trailing bits are not zero.
  if (toBase64(out) !== encoded) {
    throw new TypeError('Base64 input is not canonical')
  }
  return out
}

/** Whether two byte strings are equal. Only for public values such as digests. */
export function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false
  }
  return true
}
