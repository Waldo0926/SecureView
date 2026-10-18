/**
 * Show the pages in Chinese from a reviewed English -> Chinese dictionary (Issue #74).
 *
 * Most of the interface is English written straight into the templates. Rather than rewrite
 * every component around translation keys, `scripts/extract-ui-strings.mjs` collects that
 * English, `scripts/translate_ui_strings.py` drafts the Chinese (glm-4-flash, at build time,
 * never from the browser), and this module swaps a text node or a readable attribute whose
 * whole text is a dictionary entry. Text with values in it (`Resend in 42s`) matches a
 * pattern entry (`Resend in {0}s`) and keeps the values as they are.
 *
 * What is never changed:
 *   - anything inside `translate="no"`: file names, usernames, user content, hashes, audit
 *     evidence are marked so where they are shown;
 *   - `<code>`, `<pre>`, `<textarea>`, form values, scripts and styles;
 *   - text that is not exactly an entry. A file that happens to be called "Upload" is still
 *     shown as "Upload" wherever it sits in a `translate="no"` cell.
 *
 * Vue only rewrites a text node when its own value changes, and then writes English again;
 * the observer sees that write and translates it, before the browser paints.
 */

import { splitSentences } from '@/utils/sentences'

type Dictionary = Record<string, string>

interface Pattern {
  prefix: string
  regex: RegExp
  zh: string
}

const ATTRIBUTES = ['placeholder', 'title', 'aria-label', 'alt'] as const
const SKIP_SELECTOR = '[translate="no"], code, pre, script, style, textarea, [contenteditable="true"]'
/** A pattern needs this many literal letters, so `{0}s` cannot rewrite every plural. */
const MIN_PATTERN_LETTERS = 4

let exact = new Map<string, string>()
let patterns: Pattern[] = []
let observer: MutationObserver | null = null

/** What a text node said in English, and what it was changed to. */
const textRecords = new WeakMap<Text, { en: string; zh: string }>()
/** Text nodes translated as part of a whole sentence, and the element holding that sentence. */
const blockMembers = new WeakMap<Text, Element>()

/** Elements that only style a few words inside a sentence. */
const INLINE_TAGS = new Set(['EM', 'STRONG', 'B', 'I', 'SPAN', 'MARK', 'SMALL', 'ABBR', 'KBD'])
/** A list marker or step number the dictionary entry does not include. */
const LEADING_MARKER = /^([•·▪◦*–—-]\s*|\d+[.)]\s+)(.+)$/s
const attributeRecords = new WeakMap<Element, Map<string, { en: string; zh: string }>>()

export function normalize(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function compileDictionary(dictionary: Dictionary): void {
  exact = new Map()
  patterns = []
  for (const [en, zh] of Object.entries(dictionary)) {
    if (!zh) continue
    if (!/\{\d+\}/.test(en)) {
      exact.set(en, zh)
      continue
    }
    const literal = en.replace(/\{\d+\}/g, '')
    if ((literal.match(/[A-Za-z]/g) ?? []).length < MIN_PATTERN_LETTERS) continue
    const parts = en.split(/(\{\d+\})/)
    const order: number[] = []
    const source = parts
      .map((part) => {
        const slot = /^\{(\d+)\}$/.exec(part)
        if (!slot) return escapeRegExp(part)
        order.push(Number(slot[1]))
        // Lazy and possibly empty: `session{2}` is "" in the singular.
        return '(.*?)'
      })
      .join('')
    // Captures are numbered by position; the Chinese refers to them by the English index.
    const zhByPosition = zh.replace(/\{(\d+)\}/g, (_, index) => `{@${order.indexOf(Number(index))}}`)
    patterns.push({ prefix: en.split('{')[0], regex: new RegExp(`^${source}$`, 's'), zh: zhByPosition })
  }
  // The most specific pattern wins.
  patterns.sort((a, b) => b.prefix.length - a.prefix.length || b.regex.source.length - a.regex.source.length)
}

/** The Chinese for one piece of English, or null when the dictionary has none. */
export function translateText(text: string): string | null {
  const key = normalize(text)
  if (!key || !/[A-Za-z]/.test(key)) return null
  const hit = exact.get(key)
  if (hit !== undefined) return hit
  for (const pattern of patterns) {
    if (!key.startsWith(pattern.prefix)) continue
    const match = pattern.regex.exec(key)
    if (match) return pattern.zh.replace(/\{@(\d+)\}/g, (_, index) => match[Number(index) + 1] ?? '')
  }
  // `• Largest AES key size in common use` is the entry with a bullet in front of it.
  const marked = LEADING_MARKER.exec(key)
  if (marked) {
    const rest = translateText(marked[2]!)
    if (rest !== null) return `${marked[1]}${rest}`
  }
  return null
}

/** What a text node says in English, even while it shows Chinese. */
function englishOf(node: Text): string {
  const record = textRecords.get(node)
  const value = node.nodeValue ?? ''
  return record && value === record.zh ? record.en : value
}

/**
 * The text nodes of a sentence with styled words in it (`Your <em>password</em> signs in`),
 * or null when the element holds anything else (a link, a button, a block).
 */
function inlineBlockNodes(element: Element): Text[] | null {
  let styled = false
  const nodes: Text[] = []
  for (const child of element.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) nodes.push(child as Text)
    else if (child.nodeType === Node.COMMENT_NODE) continue
    else if (
      child.nodeType === Node.ELEMENT_NODE &&
      INLINE_TAGS.has((child as Element).tagName) &&
      !(child as Element).matches(SKIP_SELECTOR)
    ) {
      styled = true
      for (const inner of child.childNodes) {
        if (inner.nodeType === Node.TEXT_NODE) nodes.push(inner as Text)
        else if (inner.nodeType !== Node.COMMENT_NODE) return null
      }
    } else return null
  }
  return styled && nodes.length >= 2 ? nodes : null
}

/**
 * Translate a styled sentence as one: the Chinese word order rarely keeps the English
 * fragments in place, so the whole translation goes into the first plain text node and the
 * other fragments are emptied. The emphasis is lost; the sentence reads correctly.
 */
function translateInlineBlock(element: Element): boolean {
  if (skipped(element)) return false
  const nodes = inlineBlockNodes(element)
  if (!nodes) return false
  const english = nodes.map(englishOf)
  const zh = translateText(english.join(''))
  if (zh === null) {
    // It was one sentence and no longer is one we know: put the English fragments back, so
    // none stays emptied.
    for (const [index, node] of nodes.entries()) {
      if (blockMembers.get(node) !== element) continue
      blockMembers.delete(node)
      textRecords.delete(node)
      if (node.nodeValue !== english[index]) node.nodeValue = english[index]!
    }
    return false
  }
  const host = nodes.find((node) => node.parentNode === element && /\S/.test(englishOf(node))) ?? nodes[0]!
  // SentenceLines: one Chinese sentence per English sentence block, when the counts agree.
  const sentenceNodes = nodes.filter((node) => /\S/.test(englishOf(node)))
  const zhSentences = element.hasAttribute('data-sentence-lines') ? splitSentences(zh) : []
  const perSentence = zhSentences.length > 1 && zhSentences.length === sentenceNodes.length
  nodes.forEach((node, index) => {
    const shown = perSentence ? (zhSentences[sentenceNodes.indexOf(node)] ?? '') : node === host ? zh : ''
    textRecords.set(node, { en: english[index]!, zh: shown })
    blockMembers.set(node, element)
    if (node.nodeValue !== shown) node.nodeValue = shown
  })
  return true
}

function skipped(element: Element | null): boolean {
  return !element || element.closest(SKIP_SELECTOR) !== null
}

function translateTextNode(node: Text) {
  const value = node.nodeValue ?? ''
  const record = textRecords.get(node)
  if (record && value === record.zh) return
  const block = blockMembers.get(node)
  if (block && translateInlineBlock(block)) return
  if (skipped(node.parentElement)) return
  const zh = translateText(value)
  if (zh === null) return
  const lead = /^\s*/.exec(value)?.[0] ?? ''
  const trail = /\s*$/.exec(value)?.[0] ?? ''
  const next = `${lead}${zh}${trail}`
  textRecords.set(node, { en: value, zh: next })
  node.nodeValue = next
}

function translateAttributes(element: Element) {
  // A text field's own value is never touched, but its placeholder and label are interface.
  if (element.closest('[translate="no"]')) return
  for (const name of ATTRIBUTES) {
    const value = element.getAttribute(name)
    if (!value) continue
    const records = attributeRecords.get(element)
    if (records?.get(name)?.zh === value) continue
    const zh = translateText(value)
    if (zh === null) continue
    const map = records ?? new Map()
    map.set(name, { en: value, zh })
    attributeRecords.set(element, map)
    element.setAttribute(name, zh)
  }
}

function translateTree(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) {
    translateTextNode(root as Text)
    return
  }
  if (root.nodeType !== Node.ELEMENT_NODE) return
  const element = root as Element
  if (skipped(element)) return
  translateAttributes(element)
  translateInlineBlock(element)
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (node) => {
      if (node.nodeType !== Node.ELEMENT_NODE || !(node as Element).matches(SKIP_SELECTOR)) return NodeFilter.FILTER_ACCEPT
      // A <textarea> keeps its text, but its placeholder is still translated.
      if ((node as Element).tagName === 'TEXTAREA') translateAttributes(node as Element)
      return NodeFilter.FILTER_REJECT
    },
  })
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) translateTextNode(node as Text)
    else {
      translateAttributes(node as Element)
      translateInlineBlock(node as Element)
    }
  }
}

function onMutations(mutations: MutationRecord[]) {
  for (const mutation of mutations) {
    if (mutation.type === 'characterData') translateTextNode(mutation.target as Text)
    else if (mutation.type === 'attributes') translateAttributes(mutation.target as Element)
    else mutation.addedNodes.forEach(translateTree)
  }
}

/** Start translating the page, now and as it changes. */
export function startDomTranslation(dictionary: Dictionary, root: Node = document.body): void {
  compileDictionary(dictionary)
  translateTree(root)
  if (observer) return
  observer = new MutationObserver(onMutations)
  observer.observe(root, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: [...ATTRIBUTES],
  })
}

/** Stop, and put back the English wherever the Chinese is still showing. */
export function stopDomTranslation(root: Node = document.body): void {
  observer?.disconnect()
  observer = null
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT)
  for (let node: Node | null = root; node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) {
      const record = textRecords.get(node as Text)
      if (record && node.nodeValue === record.zh) node.nodeValue = record.en
      textRecords.delete(node as Text)
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      const records = attributeRecords.get(node as Element)
      records?.forEach((record, name) => {
        if ((node as Element).getAttribute(name) === record.zh) (node as Element).setAttribute(name, record.en)
      })
      attributeRecords.delete(node as Element)
    }
  }
}
