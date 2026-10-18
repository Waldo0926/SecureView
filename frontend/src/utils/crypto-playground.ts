/** Cipher helpers for the Education playground demos. */

export function caesarEncrypt(text: string, shift: number): string {
  const s = ((shift % 26) + 26) % 26
  return text
    .split('')
    .map((ch) => {
      const code = ch.charCodeAt(0)
      if (code >= 65 && code <= 90) {
        return String.fromCharCode(((code - 65 + s) % 26) + 65)
      }
      if (code >= 97 && code <= 122) {
        return String.fromCharCode(((code - 97 + s) % 26) + 97)
      }
      return ch
    })
    .join('')
}

export function caesarDecrypt(text: string, shift: number): string {
  return caesarEncrypt(text, -shift)
}

function vigenereTransform(text: string, key: string, encrypt: boolean): string {
  if (!key) return text
  const cleanKey = key.replace(/[^a-zA-Z]/g, '').toUpperCase()
  if (!cleanKey) return text

  let ki = 0
  return text
    .split('')
    .map((ch) => {
      const code = ch.charCodeAt(0)
      if (code >= 65 && code <= 90) {
        const shift = cleanKey.charCodeAt(ki % cleanKey.length)! - 65
        ki++
        const s = encrypt ? shift : -shift
        return String.fromCharCode(((code - 65 + s + 26) % 26) + 65)
      }
      if (code >= 97 && code <= 122) {
        const shift = cleanKey.charCodeAt(ki % cleanKey.length)! - 65
        ki++
        const s = encrypt ? shift : -shift
        return String.fromCharCode(((code - 97 + s + 26) % 26) + 97)
      }
      return ch
    })
    .join('')
}

export function vigenereEncrypt(text: string, key: string): string {
  return vigenereTransform(text, key, true)
}

export function vigenereDecrypt(text: string, key: string): string {
  return vigenereTransform(text, key, false)
}

export function railFenceEncrypt(text: string, rails: number): string {
  const n = Math.max(2, Math.min(10, rails))
  if (text.length <= 1) return text

  const rows: string[][] = Array.from({ length: n }, () => [])
  let row = 0
  let direction = 1

  for (const ch of text) {
    rows[row]!.push(ch)
    if (row === 0) direction = 1
    else if (row === n - 1) direction = -1
    row += direction
  }

  return rows.map((r) => r.join('')).join('')
}

export function railFenceDecrypt(text: string, rails: number): string {
  const n = Math.max(2, Math.min(10, rails))
  if (text.length <= 1) return text

  const pattern: number[] = []
  let row = 0
  let direction = 1
  for (let i = 0; i < text.length; i++) {
    pattern.push(row)
    if (row === 0) direction = 1
    else if (row === n - 1) direction = -1
    row += direction
  }

  const rowLens = Array.from({ length: n }, () => 0)
  for (const r of pattern) rowLens[r]!++

  const rows: string[][] = []
  let offset = 0
  for (let r = 0; r < n; r++) {
    rows[r] = text.slice(offset, offset + rowLens[r]!).split('')
    offset += rowLens[r]!
  }

  const rowIdx = Array(n).fill(0)
  let out = ''
  for (const r of pattern) {
    out += rows[r]![rowIdx[r]!]
    rowIdx[r]!++
  }
  return out
}

export interface CaesarStep {
  char: string
  shifted: string
}

export function caesarSteps(text: string, shift: number): CaesarStep[] {
  const s = ((shift % 26) + 26) % 26
  return text.split('').map((ch) => {
    const code = ch.charCodeAt(0)
    let shifted = ch
    if ((code >= 65 && code <= 90) || (code >= 97 && code <= 122)) {
      const base = code >= 97 ? 97 : 65
      shifted = String.fromCharCode(((code - base + s) % 26) + base)
    }
    return { char: ch, shifted }
  })
}

export interface VigenereStep {
  char: string
  keyChar: string
  shift: number
  output: string
}

export function vigenereSteps(text: string, key: string): VigenereStep[] {
  const cleanKey = key.replace(/[^a-zA-Z]/g, '').toUpperCase() || 'A'
  let ki = 0
  return text.split('').map((ch) => {
    const code = ch.charCodeAt(0)
    if ((code >= 65 && code <= 90) || (code >= 97 && code <= 122)) {
      const keyChar = cleanKey[ki % cleanKey.length]!
      const shift = keyChar.charCodeAt(0) - 65
      ki++
      const base = code >= 97 ? 97 : 65
      const output = String.fromCharCode(((code - base + shift) % 26) + base)
      return { char: ch, keyChar, shift, output }
    }
    return { char: ch, keyChar: '—', shift: 0, output: ch }
  })
}

export interface RailFenceStep {
  row: number
  char: string
}

export function railFenceSteps(text: string, rails: number): RailFenceStep[] {
  const n = Math.max(2, Math.min(10, rails))
  const steps: RailFenceStep[] = []
  let row = 0
  let direction = 1
  for (const ch of text) {
    steps.push({ row, char: ch })
    if (row === 0) direction = 1
    else if (row === n - 1) direction = -1
    row += direction
  }
  return steps
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((b) => {
    binary += String.fromCharCode(b)
  })
  return btoa(binary)
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

async function deriveAesKey(password: string): Promise<CryptoKey> {
  const enc = new TextEncoder()
  const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: enc.encode('secureview-edu'), iterations: 100000, hash: 'SHA-256' },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    true,
    ['encrypt', 'decrypt'],
  )
}

export interface AesEncryptResult {
  ciphertext: string
  ivHex: string
  keyHex: string
}

export async function aesEncrypt(plaintext: string, password: string): Promise<AesEncryptResult> {
  const enc = new TextEncoder()
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const key = await deriveAesKey(password)
  const rawKey = new Uint8Array(await crypto.subtle.exportKey('raw', key))
  const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, enc.encode(plaintext))
  const combined = new Uint8Array(iv.length + cipher.byteLength)
  combined.set(iv)
  combined.set(new Uint8Array(cipher), iv.length)
  return {
    ciphertext: bytesToBase64(combined),
    ivHex: bytesToHex(iv),
    keyHex: bytesToHex(rawKey),
  }
}

export async function aesDecrypt(ciphertextB64: string, password: string): Promise<string> {
  const raw = base64ToBytes(ciphertextB64.trim())
  if (raw.length < 13) throw new Error('Ciphertext is too short. Encrypt first, then paste the Base64 output.')
  const iv = raw.slice(0, 12)
  const data = raw.slice(12)
  const key = await deriveAesKey(password)
  let plain: ArrayBuffer
  try {
    plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, data)
  } catch {
    // A failed tag check is an OperationError with an empty message in Chrome and Safari, so
    // the page showed nothing at all. Both causes look the same to AES-GCM, by design.
    throw new Error('Wrong password, or the ciphertext was changed.')
  }
  return new TextDecoder().decode(plain)
}

function modPow(base: bigint, exp: bigint, mod: bigint): bigint {
  let result = 1n
  let b = ((base % mod) + mod) % mod
  let e = exp
  while (e > 0n) {
    if (e & 1n) result = (result * b) % mod
    b = (b * b) % mod
    e >>= 1n
  }
  return result
}

/** Tiny RSA demo key: p=61, q=53, n=3233, e=17, d=2753. For teaching only. */
export const RSA_DEMO = {
  p: 61,
  q: 53,
  n: 3233,
  e: 17,
  d: 2753,
} as const

export interface RsaStep {
  char: string
  m: number
  c: number
}

export function rsaToyEncrypt(text: string): { ciphertext: string; steps: RsaStep[] } {
  const n = BigInt(RSA_DEMO.n)
  const e = BigInt(RSA_DEMO.e)
  const steps = text.split('').map((char) => {
    const m = char.charCodeAt(0)
    const c = Number(modPow(BigInt(m), e, n))
    return { char, m, c }
  })
  return {
    ciphertext: steps.map((s) => String(s.c)).join(' '),
    steps,
  }
}

export function rsaToyDecrypt(ciphertext: string): string {
  const n = BigInt(RSA_DEMO.n)
  const d = BigInt(RSA_DEMO.d)
  const parts = ciphertext.trim().split(/[\s,]+/).filter(Boolean)
  if (parts.length === 0) throw new Error('Paste RSA ciphertext numbers (space-separated).')
  return parts
    .map((part) => {
      const c = Number(part)
      if (!Number.isFinite(c)) throw new Error(`Invalid ciphertext value: ${part}`)
      return String.fromCharCode(Number(modPow(BigInt(c), d, n)))
    })
    .join('')
}

export function rsaToyStepsFromCiphertext(ciphertext: string): RsaStep[] {
  const n = BigInt(RSA_DEMO.n)
  const d = BigInt(RSA_DEMO.d)
  return ciphertext
    .trim()
    .split(/[\s,]+/)
    .filter(Boolean)
    .map((part) => {
      const c = Number(part)
      const m = Number(modPow(BigInt(c), d, n))
      return { char: String.fromCharCode(m), m, c }
    })
}
