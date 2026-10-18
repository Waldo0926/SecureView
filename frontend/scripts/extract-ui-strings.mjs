#!/usr/bin/env node
/**
 * Collect every English interface string in `src/` into `src/locales/ui-strings.json`
 * (Issue #74). No network, no model: this is the input `translate_ui_strings.py` translates.
 *
 * Two kinds of string are collected:
 *   - template text, joined the way it renders: `Resend in {{ seconds }}s` is one DOM text
 *     node at runtime, so it is collected as the pattern `Resend in {0}s`;
 *   - string and template literals in scripts and template expressions that read like prose
 *     (a capital letter or a space between words), with `${...}` turned into `{0}`, `{1}`...
 *
 * Class lists, paths, identifiers and constants are filtered out. Anything that slips
 * through is harmless: a dictionary entry only applies to text that is shown exactly so.
 *
 *   node scripts/extract-ui-strings.mjs           # rewrite the list
 *   node scripts/extract-ui-strings.mjs --check   # exit 1 if the list is out of date (CI)
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseSfc, babelParse } from 'vue/compiler-sfc'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SRC = path.join(ROOT, 'src')
const OUT = path.join(SRC, 'locales', 'ui-strings.json')

// Keyed vue-i18n messages live in en.json already; tests and the i18n layer are not UI text.
const SKIP_DIRS = new Set(['locales', 'i18n', 'e2e'])
const SKIP_FILE = /\.(test|spec)\.ts$|\.d\.ts$/

// Attributes whose static value a person reads or hears.
const TEXT_ATTRIBUTES = new Set([
  'placeholder', 'title', 'aria-label', 'alt', 'label', 'hint', 'description', 'heading',
  'consequence', 'detail', 'confirm-label', 'busy-label', 'caption', 'text', 'summary', 'eyebrow', 'subtitle',
])

export function normalize(text) {
  return text.replace(/\s+/g, ' ').trim()
}

/** Multi-line text (Markdown articles) keeps its lines; only trailing spaces go. */
export function normalizeBlock(text) {
  return text
    .split('\n')
    .map((line) => line.trimEnd())
    .join('\n')
    .trim()
}

let allowLowerWords = false

const CLASS_TOKEN = /^[a-z0-9!:\-[\]/.%()#_&>~*=+,'"@]+$/

function looksLikeProse(raw) {
  const text = normalize(raw.replace(/\{\d+\}/g, 'X'))
  if (text.length < 2 || !/[A-Za-z]/.test(text)) return false
  if (/^(\/|@\/|\.\/|\.\.\/|https?:|mailto:|data:|#|application\/|image\/|text\/)/.test(text)) return false
  if (/^[\w.-]+\.(vue|ts|js|json|svg|png|webm|mp4|vtt|pem|css)$/.test(text)) return false
  const tokens = text.split(' ')
  const literal = normalize(raw.replace(/\{\d+\}/g, ' ')).split(' ').filter(Boolean)
  if (literal.length === 0) return false
  // Tailwind and other class lists: every token lowercase-ish, at least one with - or :.
  if (literal.every((t) => CLASS_TOKEN.test(t)) && literal.some((t) => /[-:[]/.test(t))) return false
  if (tokens.length === 1) {
    // Data files show lowercase tags ("encryption", "basics").
    if (allowLowerWords && /^[a-z]{3,}$/.test(text)) return true
    // One word: shown only if it is capitalised ("Upload", "Cancel"); not CONSTANTS or ids.
    if (!/^[A-Z][a-z]/.test(text)) return false
    if (/[_/]/.test(text) || /[a-z][A-Z]/.test(text)) return false
    return true
  }
  // Several words: at least two real words, and not an identifier list like "GET POST".
  const words = tokens.filter((t) => /^[A-Za-z][a-z']+[.,:;!?)]?$/.test(t) || /^[a-z]+$/i.test(t))
  if (words.length < 2) return /[A-Z][a-z]+/.test(text) && /\s/.test(text)
  return true
}

function addString(set, raw) {
  const text = normalize(raw)
  if (!looksLikeProse(text)) return
  set.add(text)
  // Markdown is translated whole, lines and all, so its structure survives (translateSource).
  if (raw.trim().includes('\n')) set.add(normalizeBlock(raw))
}

/** `'a ' + b + ' c'` is one sentence on screen: collect it as `a {0} c`. */
function concatenation(node) {
  const parts = []
  const flatten = (n) => {
    if (n.type === 'BinaryExpression' && n.operator === '+') {
      flatten(n.left)
      flatten(n.right)
    } else parts.push(n)
  }
  flatten(node)
  if (!parts.some((p) => p.type === 'StringLiteral' || p.type === 'TemplateLiteral')) return null
  let out = ''
  let index = 0
  for (const part of parts) {
    if (part.type === 'StringLiteral') out += part.value
    else if (part.type === 'TemplateLiteral' && part.expressions.length === 0) out += part.quasis[0].value.cooked ?? ''
    else out += `{${index++}}`
  }
  return { text: out, others: parts.filter((p) => p.type !== 'StringLiteral' && !(p.type === 'TemplateLiteral' && p.expressions.length === 0)) }
}

function templateLiteralPattern(node, source) {
  let out = ''
  node.quasis.forEach((quasi, i) => {
    out += quasi.value.cooked ?? quasi.value.raw
    if (i < node.expressions.length) out += `{${i}}`
  })
  return out
}

function walkJs(node, set, source) {
  if (!node || typeof node.type !== 'string') return
  if (node.type === 'ImportDeclaration' || node.type === 'ExportAllDeclaration') return
  if (node.type === 'BinaryExpression' && node.operator === '+') {
    const joined = concatenation(node)
    if (joined) {
      addString(set, joined.text)
      joined.others.forEach((child) => walkJs(child, set, source))
      return
    }
  }
  if (node.type === 'StringLiteral') addString(set, node.value)
  else if (node.type === 'TemplateLiteral') {
    // A tagged class list or a CSS string is filtered by looksLikeProse like anything else.
    addString(set, templateLiteralPattern(node, source))
  }
  if (node.type === 'ExportNamedDeclaration' && node.source) return
  for (const key of Object.keys(node)) {
    if (key === 'loc' || key === 'start' || key === 'end' || key === 'leadingComments' || key === 'trailingComments') continue
    const value = node[key]
    if (Array.isArray(value)) value.forEach((child) => walkJs(child, set, source))
    else if (value && typeof value === 'object' && typeof value.type === 'string') walkJs(value, set, source)
  }
}

function collectJs(code, set, { expression = false } = {}) {
  try {
    const ast = expression
      ? babelParse(`(${code})`, { plugins: ['typescript'], errorRecovery: true })
      : babelParse(code, { sourceType: 'module', plugins: ['typescript'], errorRecovery: true })
    walkJs(ast.program ?? ast, set, code)
  } catch {
    // An expression the parser cannot read (v-for aliases, slot props) has no prose in it.
  }
}

// Vue compiler node types.
const ELEMENT = 1
const TEXT = 2
const INTERPOLATION = 5
const ATTRIBUTE = 6
const DIRECTIVE = 7
const COMPOUND = 8

// Elements that only style a few words inside a sentence.
const INLINE = new Set(['em', 'strong', 'b', 'i', 'span', 'mark', 'small', 'abbr', 'kbd'])

/**
 * A sentence with a bold or italic word in it renders as several text nodes. Collect the whole
 * sentence too, so dom-translate can translate it as one (see translateInlineBlock).
 */
function inlineSentence(node) {
  const children = node.children.filter((c) => c.type !== 3 /* comment */)
  if (!children.some((c) => c.type === ELEMENT)) return null
  let out = ''
  let index = 0
  const add = (child) => {
    if (child.type === TEXT) out += child.content
    else if (child.type === INTERPOLATION || child.type === COMPOUND) out += `{${index++}}`
    else return false
    return true
  }
  for (const child of children) {
    if (child.type === ELEMENT) {
      if (!INLINE.has(child.tag) || child.props.some((p) => p.type === DIRECTIVE && ['if', 'else', 'else-if', 'for', 'html', 'show'].includes(p.name))) return null
      for (const grandchild of child.children) if (!add(grandchild)) return null
    } else if (!add(child)) return null
  }
  return /[A-Za-z]/.test(out) ? out : null
}

function collectTemplate(node, set) {
  if (!node) return
  if (node.type === ELEMENT && node.children?.length) {
    const sentence = inlineSentence(node)
    if (sentence) addString(set, sentence)
  }
  if (node.props) {
    for (const prop of node.props) {
      if (prop.type === ATTRIBUTE && prop.value && TEXT_ATTRIBUTES.has(prop.name)) {
        addString(set, prop.value.content)
      } else if (prop.type === DIRECTIVE) {
        if (prop.exp?.content) collectJs(prop.exp.content, set, { expression: true })
        if (prop.name === 'for' || prop.name === 'slot') continue
      }
    }
  }
  if (!node.children) return
  // Runs of text and {{ }} render as one text node; collect them as one pattern.
  let run = []
  const flush = () => {
    if (run.length === 0) return
    let pattern = ''
    let index = 0
    for (const part of run) {
      if (part.type === TEXT) pattern += part.content
      else pattern += `{${index++}}`
    }
    if (run.some((p) => p.type === TEXT && /[A-Za-z]/.test(p.content))) addString(set, pattern)
    run = []
  }
  for (const child of node.children) {
    if (child.type === TEXT || child.type === INTERPOLATION || child.type === COMPOUND) {
      if (child.type === INTERPOLATION) collectJs(child.content.content ?? '', set, { expression: true })
      run.push(child)
      continue
    }
    flush()
    if (child.type === ELEMENT || child.children) collectTemplate(child, set)
  }
  flush()
}

function files(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) out.push(...files(full))
    } else if (/\.(vue|ts)$/.test(entry.name) && !SKIP_FILE.test(entry.name)) {
      out.push(full)
    }
  }
  return out.sort()
}

export function extract() {
  const set = new Set()
  for (const file of files(SRC)) {
    const source = fs.readFileSync(file, 'utf8')
    // Only the Education data shows lowercase tags; the assistant data has keyword lists.
    allowLowerWords = file.includes(`${path.sep}data${path.sep}education${path.sep}`)
    if (file.endsWith('.vue')) {
      const { descriptor } = parseSfc(source, { filename: file })
      if (descriptor.template?.ast) collectTemplate(descriptor.template.ast, set)
      for (const block of [descriptor.script, descriptor.scriptSetup]) {
        if (block?.content) collectJs(block.content, set)
      }
    } else {
      collectJs(source, set)
    }
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'en'))
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const strings = extract()
  const json = JSON.stringify(strings, null, 2) + '\n'
  if (process.argv.includes('--check')) {
    const current = fs.existsSync(OUT) ? fs.readFileSync(OUT, 'utf8') : ''
    if (current !== json) {
      console.error('src/locales/ui-strings.json is out of date: run node scripts/extract-ui-strings.mjs')
      process.exit(1)
    }
    console.log(`ui-strings.json is current (${strings.length} strings)`)
  } else {
    fs.writeFileSync(OUT, json)
    console.log(`wrote ${strings.length} strings to ${path.relative(ROOT, OUT)}`)
  }
}
