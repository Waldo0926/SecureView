import type { AdminIntegrityScan } from '@/api/admin_api'

/**
 * Plain-language text for the Integrity tab.
 *
 * The three findings mean different things and call for different reactions, so the tab says
 * which it is rather than showing the raw enum: MODIFIED is evidence about the bytes, while
 * MISSING and ERROR describe the storage and prove nothing about the content.
 */
export function findingText(result: string | null): string {
  switch (result) {
    case 'MODIFIED':
      return 'The stored bytes no longer match the SHA-256 recorded when the file was uploaded.'
    case 'MISSING':
      return 'The encrypted object is missing from storage.'
    case 'ERROR':
      return 'The object could not be read. This is a storage problem and is not proof of tampering.'
    default:
      return 'Marked corrupted by an earlier check.'
  }
}

/**
 * The command an operator pastes on the server, as is. Without `--backup-set` the script uses
 * the server's own nightly backup, which needs no key, and as root it loads the deployment
 * environment itself; the encrypted off-site set and the custodian's key are the fallback.
 */
export function restoreCommand(fileId: string, apply = false): string {
  return (
    'cd /opt/mcs21/current/backend && sudo .venv/bin/python scripts/restore_file.py ' +
    `--file-id ${fileId}${apply ? ' --apply' : ''}`
  )
}

export function scanSummary(scan: AdminIntegrityScan): string {
  const files = (n: number) => `${n} ${n === 1 ? 'file' : 'files'}`
  const parts = [`Checked ${files(scan.scanned)} of ${scan.candidates}.`]
  parts.push(
    scan.damaged === 0
      ? 'All of them match their recorded SHA-256.'
      : `${files(scan.damaged)} damaged, ${scan.valid} intact.`,
  )
  if (scan.scanned < scan.candidates) {
    parts.push(
      scan.stopped_early
        ? 'It stopped at the time limit; scan again to continue with the files checked longest ago.'
        : 'Scan again to continue with the files checked longest ago.',
    )
  }
  return parts.join(' ')
}
