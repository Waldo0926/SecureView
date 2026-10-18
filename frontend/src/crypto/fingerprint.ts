/**
 * Public-key fingerprints for people to compare, e.g. read aloud or side by side on two screens.
 *
 * The first 128 bits of the SHA-256 fingerprint, as eight groups of four hex digits. Forging a
 * different key with the same 128-bit prefix is far out of reach, and 32 characters is about
 * as much as two people will reliably compare.
 */
export function formatFingerprint(hex: string): string {
  const digits = hex.replace(/[^0-9a-f]/gi, '').toUpperCase().slice(0, 32)
  return digits.match(/.{1,4}/g)?.join(' ') ?? ''
}
