/**
 * Decorative ciphertext: fixed pseudo-random bytes, so a wall of them looks the same on every visit.
 * Shared by the home hero and the sign-in pages' brand panel; there is one seed, not two copies.
 */
export function byteRows(count: number, width: number): string[] {
  let seed = 1337
  const rows: string[] = []
  for (let r = 0; r < count; r++) {
    const row: string[] = []
    for (let c = 0; c < width; c++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff
      row.push(((seed >> 16) & 255).toString(16).padStart(2, '0'))
    }
    rows.push(row.join(' '))
  }
  return rows
}
