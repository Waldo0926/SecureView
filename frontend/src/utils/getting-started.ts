/**
 * The three things a new account does to see the whole product once: encrypt and upload, share,
 * and have a file decrypted on the way out. Each is read from the account's own audit trail, so
 * a step ticks itself when it really happened rather than when a button was pressed.
 */
export type GettingStartedStep = 'upload' | 'share' | 'download'

export const GETTING_STARTED_STEPS: readonly GettingStartedStep[] = ['upload', 'share', 'download']

const ACTION_FOR_STEP: Record<GettingStartedStep, string> = {
  upload: 'FILE_UPLOADED',
  share: 'FILE_SHARED',
  // The account's trail includes downloads of its files by recipients, which also count:
  // either way a file left encrypted and was opened by someone holding the key.
  download: 'FILE_DOWNLOAD_AUTHORIZED',
}

export function gettingStartedProgress(actions: Iterable<string>): Record<GettingStartedStep, boolean> {
  const seen = new Set(actions)
  return {
    upload: seen.has(ACTION_FOR_STEP.upload),
    share: seen.has(ACTION_FOR_STEP.share),
    download: seen.has(ACTION_FOR_STEP.download),
  }
}

const hiddenKey = (username: string) => `secureview.gettingStarted.hidden.${username}`

export function isGettingStartedHidden(username: string): boolean {
  try {
    return localStorage.getItem(hiddenKey(username)) === '1'
  } catch {
    return false
  }
}

export function hideGettingStarted(username: string): void {
  try {
    localStorage.setItem(hiddenKey(username), '1')
  } catch {
    // Storage blocked: the card simply shows again next visit.
  }
}
