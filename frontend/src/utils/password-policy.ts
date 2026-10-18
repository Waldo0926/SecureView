/**
 * The browser-side mirror of the server password policy.
 *
 * The server in `backend/app/core/security.py` remains the authority: it re-runs
 * every rule here and is the only thing that can reject a password for real. This
 * module exists so the form can name the exact rule that is failing while the user
 * is still typing, instead of trading a round trip for one flattened error string.
 *
 * Keep the two in step. The constants and the messages below are deliberately the
 * same wording the API returns, so a user never sees the rule described two ways.
 * One rule is intentionally not mirrored: the server's common-password deny-list
 * stays on the server, where it can grow into a real breached-password corpus
 * without shipping that corpus to every browser.
 *
 * The messages come from the locale files (`password.*`), so they follow the interface
 * language; the English wording stays the server's.
 */

import { t } from '@/i18n'

export const PASSWORD_MIN_LENGTH = 8
export const PASSWORD_MAX_LENGTH = 128
export const PASSWORD_MIN_CHARACTER_CLASSES = 2

/**
 * The encryption passphrase is not a login password. It never reaches the server,
 * it wraps the account key, and losing or guessing it costs the user every file
 * they have encrypted, so it keeps the longer minimum the login password shed.
 */
export const PASSPHRASE_MIN_LENGTH = 10

/** Measure user-visible Unicode characters consistently across every passphrase form. */
export function passphraseLength(passphrase: string): number {
  return [...passphrase].length
}

export type PasswordCharacterClass = 'uppercase' | 'lowercase' | 'number' | 'symbol'

/** The rule under the field, in the interface language. A function so it follows a switch. */
export function passwordRequirementHint(): string {
  return t('password.requirementHint', {
    min: PASSWORD_MIN_LENGTH,
    classes: PASSWORD_MIN_CHARACTER_CLASSES,
  })
}

const UPPERCASE = /\p{Lu}|\p{Lt}/u
const LOWERCASE = /\p{Ll}/u
const NUMBER = /\p{Nd}|\p{Nl}|\p{No}/u

/**
 * Bucket one character the way `unicodedata.category` does on the server: cased
 * letters by case, any numeric character as a number, and everything else -
 * punctuation, symbols, spaces, and caseless scripts - as a symbol.
 */
function classOf(character: string): PasswordCharacterClass {
  if (UPPERCASE.test(character)) return 'uppercase'
  if (LOWERCASE.test(character)) return 'lowercase'
  if (NUMBER.test(character)) return 'number'
  return 'symbol'
}

export function passwordCharacterClasses(password: string): Set<PasswordCharacterClass> {
  const found = new Set<PasswordCharacterClass>()
  for (const character of password.normalize('NFC')) {
    found.add(classOf(character))
  }
  return found
}

/** Mirrors `_MIN_CONTEXT_FRAGMENT_LENGTH`: shorter fragments match honest passwords. */
const MIN_CONTEXT_FRAGMENT_LENGTH = 3

function accountDetailFragments(contextValues: readonly string[]): string[] {
  const fragments = new Set<string>()
  for (const value of contextValues) {
    const normalized = value.normalize('NFC').trim().toLowerCase()
    if (!normalized) continue
    fragments.add(normalized)
    if (normalized.includes('@')) {
      fragments.add(normalized.slice(0, normalized.indexOf('@')))
    }
  }
  return [...fragments].filter((fragment) => fragment.length >= MIN_CONTEXT_FRAGMENT_LENGTH)
}

export interface PasswordPolicyResult {
  /** True once every rule passes, i.e. the form may send this to the server. */
  readonly ok: boolean
  readonly isEmpty: boolean
  readonly length: number
  readonly satisfiedClasses: ReadonlySet<PasswordCharacterClass>
  readonly tooShort: boolean
  readonly tooLong: boolean
  readonly tooFewClasses: boolean
  readonly usesAccountDetails: boolean
  /** The single message to show under the field, or '' when the password passes. */
  readonly message: string
}

export function evaluatePassword(
  password: string,
  contextValues: readonly string[] = [],
): PasswordPolicyResult {
  const normalized = password.normalize('NFC')
  const length = [...normalized].length
  const satisfiedClasses = passwordCharacterClasses(normalized)
  const candidate = normalized.toLowerCase()

  const isEmpty = normalized.length === 0
  const tooShort = !isEmpty && length < PASSWORD_MIN_LENGTH
  const tooLong = length > PASSWORD_MAX_LENGTH
  const tooFewClasses = !isEmpty && satisfiedClasses.size < PASSWORD_MIN_CHARACTER_CLASSES
  const usesAccountDetails =
    !isEmpty &&
    accountDetailFragments(contextValues).some((fragment) => candidate.includes(fragment))

  let message = ''
  if (isEmpty) {
    message = t('password.enter')
  } else if (tooShort) {
    message = t('password.tooShort', { min: PASSWORD_MIN_LENGTH, length })
  } else if (tooLong) {
    message = t('password.tooLong', { max: PASSWORD_MAX_LENGTH, length })
  } else if (usesAccountDetails) {
    message = t('password.usesAccountDetails')
  } else if (tooFewClasses) {
    message = t('password.tooFewClasses', { classes: PASSWORD_MIN_CHARACTER_CLASSES })
  }

  return {
    ok: !isEmpty && !tooShort && !tooLong && !tooFewClasses && !usesAccountDetails,
    isEmpty,
    length,
    satisfiedClasses,
    tooShort,
    tooLong,
    tooFewClasses,
    usesAccountDetails,
    message,
  }
}

/**
 * Passphrases that a guessing attacker tries first (threat model F-04, recommendation R-1).
 *
 * The passphrase never reaches the server, so this check can only run here. Each guess costs an
 * attacker one 64 MiB Argon2id derivation, so a passphrase in the first few thousand entries of
 * any list falls in minutes; one of four random words does not fall in years. Compared with
 * spaces and case removed. Entries mirror the server's login deny-list at 10 characters and up,
 * plus common passphrase defaults.
 */
const COMMON_PASSPHRASES = new Set(
  [
    '1234567890',
    '123456789012345',
    '1234567890123456',
    '111111111111111',
    'adminadmin',
    'adminadminadmin',
    'administrator123',
    'changemechangeme',
    'correcthorsebatterystaple',
    'iloveyouiloveyou',
    'letmein123',
    'letmeinletmeinletmein',
    'password123',
    'password1234',
    'password123456',
    'passwordpassword',
    'qwertyqwertyqwerty',
    'securefile',
    'securefileplatform',
    'secureview',
    'secureview123',
    'welcome123',
    'welcome123456789',
    'passphrase',
    'passphrase123',
    'mypassphrase',
    'encryption',
    'encryptionpassphrase',
    'iloveyou123',
    'qwerty12345',
    'abc1234567',
    'monash2026',
    'monashuniversity',
  ].map((entry) => entry.replace(/\s+/g, '')),
)

const SEQUENCES = ['abcdefghijklmnopqrstuvwxyz', '01234567890123456789', 'qwertyuiopasdfghjklzxcvbnm']

/** True for "aaaaaaaaaa", "abcabcabcabc", "1212121212": one short unit repeated. */
function isRepeatedUnit(value: string): boolean {
  for (let unit = 1; unit <= 4 && unit < value.length; unit += 1) {
    const piece = value.slice(0, unit)
    if (piece.repeat(Math.ceil(value.length / unit)).slice(0, value.length) === value) return true
  }
  return false
}

/** True for a run along the alphabet, the digits or a keyboard row, either direction. */
function isSequence(value: string): boolean {
  return SEQUENCES.some(
    (sequence) => sequence.includes(value) || [...sequence].reverse().join('').includes(value),
  )
}

export type WeakPassphraseReason = '' | 'common' | 'pattern' | 'account'

/**
 * Why a passphrase is too easy to guess, or '' when it is not.
 *
 * `contextValues` are the account's own identifiers (username, email): a passphrase that is
 * mostly one of them is guessed by anyone who knows whose account it is. A fragment counts
 * only when it is at least four characters and what is left after removing it is shorter than
 * eight, so a genuine phrase that happens to contain a name still passes.
 */
export function weakPassphraseReason(
  passphrase: string,
  contextValues: readonly string[] = [],
): WeakPassphraseReason {
  const compact = passphrase.normalize('NFC').toLowerCase().replace(/\s+/g, '')
  if (!compact) return ''
  if (COMMON_PASSPHRASES.has(compact)) return 'common'
  if (isRepeatedUnit(compact) || isSequence(compact) || new Set(compact).size <= 3) return 'pattern'

  for (const fragment of accountDetailFragments(contextValues)) {
    const token = fragment.replace(/\s+/g, '')
    if (token.length >= 4 && compact.includes(token) && [...compact.replace(token, '')].length < 8) {
      return 'account'
    }
  }
  return ''
}

/** The message under the field for a weak passphrase, in the interface language. */
export function weakPassphraseMessage(reason: WeakPassphraseReason): string {
  return reason ? t(`passphrase.weak.${reason}`) : ''
}
