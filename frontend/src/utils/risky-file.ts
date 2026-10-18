/**
 * File types that can run code when opened. The server holds only ciphertext, so it cannot scan
 * a shared file for malware; the most the app can do is say so before a recipient saves one.
 */
const PROGRAM_EXTENSIONS = new Set([
  'exe', 'msi', 'scr', 'com', 'pif', 'bat', 'cmd', 'app', 'dmg', 'pkg', 'apk', 'jar', 'deb',
  'rpm', 'js', 'jse', 'vbs', 'vbe', 'wsf', 'hta', 'ps1', 'sh', 'lnk', 'reg', 'iso',
])
const MACRO_EXTENSIONS = new Set(['docm', 'dotm', 'xlsm', 'xltm', 'xlam', 'pptm', 'potm', 'ppsm'])

export type RiskyFileKind = 'program' | 'macro'

/** The kind of risk a filename signals, judged by its last extension; null when none. */
export function riskyFileKind(filename: string): RiskyFileKind | null {
  const dot = filename.lastIndexOf('.')
  if (dot < 0) return null
  const extension = filename.slice(dot + 1).trim().toLowerCase()
  if (PROGRAM_EXTENSIONS.has(extension)) return 'program'
  if (MACRO_EXTENSIONS.has(extension)) return 'macro'
  return null
}
