import { computed } from 'vue'
import { createI18n } from 'vue-i18n'
import en from '@/locales/en.json'
import { startDomTranslation, stopDomTranslation } from './dom-translate'
import { SITE_TIME_ZONE } from '@/utils/site-time'

/**
 * Interface language: English and Simplified Chinese (Issue #74).
 *
 * English is the source and ships in the main bundle. Chinese is a separate chunk, loaded
 * before the app mounts when it is the saved choice, so a returning visitor never sees a
 * flash of English first, and an English visitor never downloads it.
 *
 * Two layers, one switch. Shared chrome (navigation, sign-in, registration, settings) uses
 * keyed vue-i18n messages (`en.json` / `zh-CN.json`). Everything else is English in the
 * templates, shown in Chinese through the dictionary in `zh-CN.dict.json` (see
 * `dom-translate.ts`). The browser never calls a translation service: both files are checked
 * in, drafted at build time by `scripts/translate_ui_strings.py` and reviewed before merge. What is never
 * translated: file names, usernames, anything a user wrote, hashes, key fingerprints,
 * algorithm identifiers, API error codes and audit-log evidence.
 */
export type LocaleCode = 'en' | 'zh-CN'

export interface LocaleOption {
  code: LocaleCode
  /** Written in its own language: a switcher labelled in a language you cannot read is no use. */
  label: string
}

export const LOCALES: readonly LocaleOption[] = [
  { code: 'en', label: 'English' },
  { code: 'zh-CN', label: '简体中文' },
]

export const DEFAULT_LOCALE: LocaleCode = 'en'

/** Stored next to `theme`: a per-device preference, like the theme. */
export const LOCALE_STORAGE_KEY = 'locale'

export function isLocaleCode(value: unknown): value is LocaleCode {
  return value === 'en' || value === 'zh-CN'
}

/**
 * The saved choice, or English. The browser's own language is deliberately not used to pick
 * Chinese unasked: the English pages are the reviewed source, and a visitor who wants Chinese
 * is one click from it.
 */
export function readStoredLocale(): LocaleCode {
  try {
    const saved = localStorage.getItem(LOCALE_STORAGE_KEY)
    return isLocaleCode(saved) ? saved : DEFAULT_LOCALE
  } catch {
    return DEFAULT_LOCALE
  }
}

export type MessageSchema = typeof en

export const i18n = createI18n<[MessageSchema], LocaleCode, false>({
  legacy: false,
  locale: DEFAULT_LOCALE,
  // A key missing from Chinese shows the English text, never the raw key.
  fallbackLocale: DEFAULT_LOCALE,
  messages: { en } as Record<LocaleCode, MessageSchema>,
  // Fallback to English is expected while a translation catches up; do not flood the console.
  fallbackWarn: false,
  missingWarn: import.meta.env.DEV,
})

const loaded = new Set<LocaleCode>(['en'])
let dictionary: Record<string, string> | null = null

async function loadMessages(code: LocaleCode): Promise<void> {
  if (loaded.has(code)) return
  const [messages, dict] = await Promise.all([
    import('@/locales/zh-CN.json'),
    import('@/locales/zh-CN.dict.json'),
  ])
  i18n.global.setLocaleMessage(code, messages.default as unknown as MessageSchema)
  dictionary = dict.default as Record<string, string>
  loaded.add(code)
}

function applyPageTranslation(code: LocaleCode) {
  if (typeof document === 'undefined') return
  if (code === 'zh-CN' && dictionary) startDomTranslation(dictionary)
  else stopDomTranslation()
}

function applyDocumentLanguage(code: LocaleCode) {
  if (typeof document === 'undefined') return
  document.documentElement.lang = code
}

/** Switch language, remembering the choice on this device. */
export async function setLocale(code: LocaleCode): Promise<void> {
  await loadMessages(code)
  i18n.global.locale.value = code
  applyDocumentLanguage(code)
  applyPageTranslation(code)
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, code)
  } catch {
    // Private mode or blocked storage: the switch still applies to this visit.
  }
}

/**
 * Restore the saved language before the first render. A failed chunk load (offline, a
 * deploy that replaced the file mid-visit) falls back to English rather than blocking the app.
 */
export async function initLocale(): Promise<void> {
  const saved = readStoredLocale()
  if (saved === DEFAULT_LOCALE) {
    applyDocumentLanguage(DEFAULT_LOCALE)
    return
  }
  try {
    await loadMessages(saved)
    i18n.global.locale.value = saved
    applyDocumentLanguage(saved)
    // Started before the app mounts, so the first render is already Chinese when it paints.
    applyPageTranslation(saved)
  } catch {
    applyDocumentLanguage(DEFAULT_LOCALE)
  }
}

/**
 * Whole Markdown articles (Education) in the interface language. They are rendered with
 * v-html into many small nodes, so they are translated as source, lines and all, before
 * rendering. Reactive: called from a template, it re-renders on a switch.
 */
export function translateSource(text: string): string {
  if (currentLocale.value === 'en' || !dictionary) return text
  const key = text
    .split('\n')
    .map((line) => line.trimEnd())
    .join('\n')
    .trim()
  return dictionary[key] ?? text
}

/** Translate outside a component: API helpers, stores, plain utilities. Reactive in templates. */
export const t = i18n.global.t

export const currentLocale = computed<LocaleCode>(() => i18n.global.locale.value)

/**
 * Dates and times in the interface language, always in Kuala Lumpur time (`utils/site-time`);
 * the value itself is never altered.
 */
export function formatDateTime(value: string | number | Date, options?: Intl.DateTimeFormatOptions) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString(currentLocale.value, { timeZone: SITE_TIME_ZONE, ...options })
}

export function formatDate(value: string | number | Date, options?: Intl.DateTimeFormatOptions) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleDateString(currentLocale.value, { timeZone: SITE_TIME_ZONE, ...options })
}
