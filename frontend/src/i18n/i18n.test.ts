import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { baseCompile as compile } from '@intlify/message-compiler'
import en from '@/locales/en.json'
import zhKeyed from '@/locales/zh-CN.json'
import zhDictionary from '@/locales/zh-CN.dict.json'
import uiStrings from '@/locales/ui-strings.json'
import { compileDictionary, translateText } from './dom-translate'
// @ts-expect-error -- a plain .mjs build script, no type declarations
import { extract } from '../../scripts/extract-ui-strings.mjs'

type Tree = { [key: string]: string | Tree }

function leaves(tree: Tree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string' ? [[prefix + key, value] as [string, string]] : leaves(value, `${prefix}${key}.`),
  )
}

const enLeaves = leaves(en as Tree)
const zhLeaves = new Map(leaves(zhKeyed as Tree))
const dictionary = zhDictionary as Record<string, string>

/** Issue #74's fixed glossary: the English term, and the Chinese every translation of it uses. */
const GLOSSARY: [RegExp, string][] = [
  [/\bencryption passphrase/i, '加密口令'],
  [/\bpassphrases?\b/i, '口令'],
  [/\bprivate keys?\b/i, '私钥'],
  [/\bpublic keys?\b/i, '公钥'],
  [/(?<!private )\bkey files?\b/i, '密钥文件'],
  [/\brecovery requests?\b/i, '恢复请求'],
  [/\brevok(e|es|ed|ing)\b/i, '撤销'],
  [/\bintegrity checks?\b/i, '完整性检查'],
  [/(?<![.])\bciphertext\b/i, '密文'],
]
const KEEP_ENGLISH = /AES-256-GCM|SHA-256|RSA-OAEP|Argon2id/g

describe('keyed messages', () => {
  it('every English message compiles, so no raw key or parse error reaches a page', () => {
    for (const [key, message] of enLeaves) {
      const errors: string[] = []
      compile(message, { onError: (error) => errors.push(error.message) })
      expect(errors, key).toEqual([])
    }
  })

  it('every Chinese message compiles and keeps the English placeholders', () => {
    for (const [key, message] of zhLeaves) {
      const errors: string[] = []
      compile(message, { onError: (error) => errors.push(error.message) })
      expect(errors, key).toEqual([])
      const english = enLeaves.find(([k]) => k === key)?.[1]
      expect(english, `${key} is not an English key`).toBeDefined()
      const names = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort()
      expect(names(message), key).toEqual(names(english!))
      expect(message.split('|').length, key).toBe(english!.split('|').length)
    }
  })

  it('Chinese has every English key (parity)', () => {
    const missing = enLeaves.map(([key]) => key).filter((key) => !zhLeaves.has(key))
    expect(missing).toEqual([])
  })

  it('every key the code asks for exists in en.json', () => {
    const keys = new Set(enLeaves.map(([key]) => key))
    const used = new Set<string>()
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) walk(full)
        else if (/\.(vue|ts)$/.test(entry.name) && !entry.name.endsWith('.test.ts')) {
          const source = fs.readFileSync(full, 'utf8')
          for (const match of source.matchAll(/\bt\(\s*'([a-zA-Z]+\.[\w.]+)'/g)) used.add(match[1])
          for (const match of source.matchAll(/keypath="([a-zA-Z]+\.[\w.]+)"/g)) used.add(match[1])
          for (const match of source.matchAll(/(?:label|hint|text): '([a-z][a-zA-Z]*\.[\w.]+)'/g)) used.add(match[1])
        }
      }
    }
    walk(path.resolve(__dirname, '..'))
    expect([...used].filter((key) => !keys.has(key))).toEqual([])
  })
})

describe('the Chinese dictionary', () => {
  it('is built from the current English (run scripts/extract-ui-strings.mjs)', () => {
    expect(extract()).toEqual(uiStrings)
  })

  it('uses the fixed security glossary', () => {
    const wrong = Object.entries(dictionary).filter(([english, chinese]) =>
      GLOSSARY.some(([pattern, term]) => pattern.test(english) && !chinese.includes(term)),
    )
    expect(wrong).toEqual([])
  })

  it('never calls a login password a passphrase', () => {
    const wrong = Object.entries(dictionary).filter(
      ([english, chinese]) => !/passphrase/i.test(english) && chinese.includes('口令'),
    )
    expect(wrong).toEqual([])
  })

  it('keeps algorithm names and placeholders exactly', () => {
    for (const [english, chinese] of Object.entries(dictionary)) {
      for (const name of english.match(KEEP_ENGLISH) ?? []) expect(chinese, english).toContain(name)
      // A slot glued to the end of a word (`session{2}`) is an English plural "s"; Chinese has
      // no plural, so it may be dropped. Every other value must be shown.
      const slots = (text: string) => (text.match(/\{\d+\}/g) ?? []).sort()
      const required = (english.match(/(?<![A-Za-z])\{\d+\}/g) ?? []).sort()
      for (const slot of required) expect(slots(chinese), english).toContain(slot)
      for (const slot of slots(chinese)) expect(slots(english), english).toContain(slot)
    }
  })
})

describe('dom-translate matching', () => {
  compileDictionary({
    'My Files': '我的文件',
    'Resend in {0}s': '{0} 秒后重新发送',
    '{0} of {1} files uploaded': '已上传 {0}/{1} 个文件',
    'Shared by {0} on {1}': '由 {0} 于 {1} 分享',
    '{0}s': '{0}秒',
  })

  it('matches whole text, ignoring the whitespace a template adds', () => {
    expect(translateText('  My Files\n  ')).toBe('我的文件')
    expect(translateText('My Files and more')).toBeNull()
  })

  it('fills patterns with the values as shown, in the order the Chinese needs', () => {
    expect(translateText('Resend in 42s')).toBe('42 秒后重新发送')
    expect(translateText('3 of 5 files uploaded')).toBe('已上传 3/5 个文件')
    expect(translateText('Shared by alice on 2 Oct 2026')).toBe('由 alice 于 2 Oct 2026 分享')
  })

  it('drops patterns too short to be safe', () => {
    // `{0}s` would otherwise rewrite every word that ends in s.
    expect(translateText('Settings')).toBeNull()
  })

  it('matches an entry behind a list marker or step number', () => {
    expect(translateText('• My Files')).toBe('• 我的文件')
    expect(translateText('2. My Files')).toBe('2. 我的文件')
  })

  it('leaves text with no letters alone', () => {
    expect(translateText('42')).toBeNull()
  })
})
