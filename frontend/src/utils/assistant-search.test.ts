import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ACCOUNT_SUGGESTED_INTENT_IDS, ASSISTANT_INTENTS, FALLBACK_LINKS, SUGGESTED_INTENT_IDS } from '@/data/assistant/intents'
import { algorithms } from '@/data/education/algorithms'
import { knowledgeArticles } from '@/data/education/knowledge'
import { HELP_VIDEOS } from '@/data/help-videos'

import { CHECK_LABELS } from './assistant-account'
import {
  allAnswers,
  answerQuestion,
  editDistance,
  intentAnswer,
  searchAssistant,
  splitFileName,
  stem,
  tokenize,
} from './assistant-search'

// The route table imports every page; the theme composable touches `window` at import time,
// and the test environment is node.
vi.mock('@/composables/useTheme', () => ({ useTheme: () => ({}) }))
const { routes } = await import('@/router/routes')
const router = createRouter({ history: createMemoryHistory(), routes })

function keyFor(question: string): string | undefined {
  const reply = answerQuestion(question)
  return reply.kind === 'answer' ? reply.answer.key : undefined
}

describe('normalising a question', () => {
  it('meets different forms of the same word', () => {
    for (const forms of [
      ['share', 'shared', 'sharing', 'shares'],
      ['file', 'files'],
      ['encrypt', 'encrypted', 'encrypting', 'encryption'],
      ['revoke', 'revoked', 'revoking', 'revocation', 'unshare'],
      ['forgot', 'forget', 'forgotten', 'lost'],
      ['modified', 'modify'],
    ]) {
      const tokens = forms.map((w) => tokenize(w)[0])
      expect(new Set(tokens), forms.join('/')).toHaveProperty('size', 1)
    }
  })

  it('folds multi-word spellings and synonyms together', () => {
    expect(tokenize('end-to-end')).toEqual(tokenize('E2EE'))
    expect(tokenize('Whats App')).toEqual(tokenize('WhatsApp'))
    expect(tokenize('send it')).toEqual(tokenize('share it'))
    expect(tokenize('sign in')).toEqual(tokenize('log in'))
    expect(tokenize('pass phrase')).toEqual(tokenize('passphrase'))
  })

  it('keeps the password and the passphrase apart', () => {
    expect(tokenize('password')).not.toEqual(tokenize('passphrase'))
  })

  it('drops words that carry no meaning', () => {
    expect(tokenize('How do I ... ?')).toEqual([])
  })

  it('stems short words conservatively', () => {
    expect(stem('aes')).toBe('aes')
    expect(stem('access')).toBe('access')
  })

  it('measures typos as edits, swaps included', () => {
    expect(editDistance('uplaod', 'upload')).toBe(1)
    expect(editDistance('pasword', 'password')).toBe(1)
    expect(editDistance('share', 'delete')).toBeGreaterThan(2)
  })
})

describe('curated intents', () => {
  it('have unique ids and the parts an answer needs', () => {
    const ids = ASSISTANT_INTENTS.map((i) => i.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const intent of ASSISTANT_INTENTS) {
      expect(intent.phrasings.length, intent.id).toBeGreaterThanOrEqual(3)
      const sentences = intent.summary.split(/(?<=[.!?])\s+(?=[A-Z])/).length
      expect(sentences, `${intent.id} summary sentences`).toBeGreaterThanOrEqual(2)
      expect(sentences, `${intent.id} summary sentences`).toBeLessThanOrEqual(4)
      const internal = intent.links.filter((l) => l.kind !== 'source')
      expect(internal.length, `${intent.id} product links`).toBeGreaterThanOrEqual(1)
      expect(internal.length, `${intent.id} product links`).toBeLessThanOrEqual(3)
    }
  })

  it('cover what the issue asks for', () => {
    const ids = new Set(ASSISTANT_INTENTS.map((i) => i.id))
    for (const id of [
      'upload-encrypt', 'share', 'revoke', 'download-decrypt', 'passphrase-vs-password', 'forgot-passphrase',
      'forgot-password', 'folders', 'verified-status', 'encrypted-preview', 'delete-account',
      'end-to-end', 'server-cannot-read', 'same-size', 'which-cipher', 'tamper', 'access-records',
      'vs-google-drive', 'vs-whatsapp', 'vs-email',
    ]) {
      expect(ids.has(id), id).toBe(true)
    }
  })

  it.each(ASSISTANT_INTENTS.flatMap((intent) => [intent.title, ...intent.phrasings].map((q) => [intent.id, q])))(
    '%s answers "%s"',
    (id, question) => {
      expect(keyFor(question)).toBe(`intent:${id}`)
    },
  )

  it('offer suggested questions that exist', () => {
    expect(SUGGESTED_INTENT_IDS.length).toBeGreaterThanOrEqual(4)
    expect(SUGGESTED_INTENT_IDS.length).toBeLessThanOrEqual(6)
    for (const id of SUGGESTED_INTENT_IDS) expect(intentAnswer(id), id).toBeDefined()
  })
})

describe('realistic questions', () => {
  it.each([
    ['how do i uplaod a file', 'intent:upload-encrypt'],
    ['where do i encrypt my pdf?', 'intent:upload-encrypt'],
    ['how can i send a document to my teamate', 'intent:share'],
    ['I shared a file with the wrong guy, how do I undo it', 'intent:revoke'],
    ['how do i unshare', 'intent:revoke'],
    ['forgot passphrase help!!', 'intent:forgot-passphrase'],
    ['i lost my pasphrase', 'intent:forgot-passphrase'],
    ['forgot my pasword', 'intent:forgot-password'],
    ["can't log in", 'intent:forgot-password'],
    ["what's the diffrence between password and passphrase", 'intent:passphrase-vs-password'],
    ['what is the .pem file for', 'intent:private-key-file'],
    ['how do I make a new folder', 'intent:folders'],
    ['what does the verified badge mean', 'intent:verified-status'],
    ['can the admin read my files?', 'intent:server-cannot-read'],
    ['is this better than google drive', 'intent:vs-google-drive'],
    ["why shouldn't I just use whatsapp", 'intent:vs-whatsapp'],
    ['why not send it by email instead', 'intent:vs-email'],
    ['why is the encrypted size the same as the original', 'intent:same-size'],
    ['which algorithm should i pick', 'intent:which-cipher'],
    ['what happens if someone tampers with my file', 'intent:tamper'],
    ['who downloaded my file', 'intent:access-records'],
    ['delete my account', 'intent:delete-account'],
    ['how do i downlaod and decrypt', 'intent:download-decrypt'],
    ['how do i see the cyphertext', 'intent:encrypted-preview'],
    ['how do i shre a file', 'intent:share'],
    ['revoke acess', 'intent:revoke'],
    ['what does verifed mean', 'intent:verified-status'],
    ['what is a digital signature', 'article:digital-signatures'],
    ['caesar cipher history', 'article:caesar-cipher-history'],
    ['what is argon2id', 'algorithm:argon2id'],
    ['hashing vs encryption', 'article:hashing-vs-encryption'],
  ])('"%s" → %s', (question, expected) => {
    expect(keyFor(question)).toBe(expected)
  })

  it('answers an algorithm question from the Education content', () => {
    expect(['algorithm:rsa', 'article:rsa-explained']).toContain(keyFor('what is RSA'))
  })

  it('offers two runners-up with an answer', () => {
    const reply = answerQuestion('how do I share a file')
    expect(reply.kind).toBe('answer')
    if (reply.kind !== 'answer') return
    expect(reply.alternatives).toHaveLength(2)
    expect(reply.alternatives.map((a) => a.key)).not.toContain(reply.answer.key)
  })
})

describe('questions about the visitor’s own account (v2)', () => {
  const account = ASSISTANT_INTENTS.filter((i) => i.group === 'account')

  it('cover each account check, and every check has a button label', () => {
    expect(new Set(account.map((i) => i.check))).toEqual(new Set(Object.keys(CHECK_LABELS)))
    for (const id of ACCOUNT_SUGGESTED_INTENT_IDS) expect(intentAnswer(id)?.personal, id).toBe(true)
  })

  it('say what signing in would show, without claiming to have looked', () => {
    for (const intent of account) expect(intent.summary, intent.id).toMatch(/^Signed in, /)
  })

  it.each([
    ['who has access to budget.xlsx', 'intent:account-who-has-access', 'budget.xlsx'],
    ['who has access to my thesis draft', 'intent:account-who-has-access', 'thesis draft'],
    ['who did I share "Holiday photos" with', 'intent:account-who-has-access', 'Holiday photos'],
    ['who else has acess to Q3-report.pdf?', 'intent:account-who-has-access', 'Q3-report.pdf'],
    ['when was budget.xlsx last downloaded', 'intent:account-file-activity', 'budget.xlsx'],
    ['history of thesis.docx', 'intent:account-file-activity', 'thesis.docx'],
    // A general question names no file: the answer explains, and offers the check as a button.
    ['who downloaded my file', 'intent:access-records', null],
    ['who downloaded report.pdf', 'intent:access-records', 'report.pdf'],
  ])('"%s" → %s about %s', (question, expected, fileName) => {
    const reply = answerQuestion(question)
    expect(reply.kind).toBe('answer')
    if (reply.kind !== 'answer') return
    expect(reply.answer.key).toBe(expected)
    expect(reply.fileName ?? null).toBe(fileName)
  })

  it.each([
    ['what have I shared', 'intent:account-my-shares'],
    ['did someone share a file with me', 'intent:account-shared-with-me'],
    ['anything new shared with me', 'intent:account-shared-with-me'],
    ['any failed logins', 'intent:account-recent-activity'],
    ['has someone tried to hack my account', 'intent:account-recent-activity'],
    ['how many files do i have', 'intent:account-overview'],
    ['scan my files for problems', 'intent:account-modified-files'],
  ])('"%s" → %s', (question, expected) => {
    expect(keyFor(question)).toBe(expected)
  })

  it('offers a check under the how-to answers it fits', () => {
    expect(intentAnswer('revoke')?.check).toBe('who-has-access')
    expect(intentAnswer('access-records')?.check).toBe('file-activity')
    expect(intentAnswer('verified-status')?.check).toBe('modified-files')
    expect(intentAnswer('revoke')?.personal).toBe(false)
  })

  it('takes a file name out of the question', () => {
    expect(splitFileName('who has access to budget.xlsx?')).toEqual({ fileName: 'budget.xlsx', rest: 'who has access to  ?' })
    expect(splitFileName('who has “Q3 report” open')).toMatchObject({ fileName: 'Q3 report' })
    expect(splitFileName('what is a .pem file').fileName).toBeNull()
    expect(splitFileName('version 1.2 notes').fileName).toBeNull()
    expect(splitFileName('open notes_v2.md please').fileName).toBe('notes_v2.md')
    expect(splitFileName('how do I share a file').fileName).toBeNull()
  })
})

describe('questions it cannot answer', () => {
  it.each([
    'what is the weather tomorrow',
    'recipe for banana bread',
    'who won the football last night',
    'book me a flight to Sydney',
    'asdfghjkl qwerty',
    'tell me a joke',
  ])('"%s" gets the not-sure fallback', (question) => {
    const reply = answerQuestion(question)
    expect(reply.kind).toBe('unsure')
    if (reply.kind === 'unsure') expect(reply.closest.length).toBeLessThanOrEqual(3)
  })

  it('treats an empty question as nothing asked', () => {
    expect(answerQuestion('   ').kind).toBe('empty')
    expect(answerQuestion('how do I?').kind).toBe('empty')
  })

  it('returns no matches for words nobody wrote', () => {
    expect(searchAssistant('zzzz qqqq')).toEqual([])
  })
})

/** Every `id="…"` in the app's source, so an anchor link can be checked against a real element. */
function sourceIds(): Set<string> {
  const ids = new Set<string>()
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) walk(path)
      else if (name.endsWith('.vue')) {
        for (const m of readFileSync(path, 'utf8').matchAll(/\sid="([a-z0-9-]+)"/g)) ids.add(m[1]!)
      }
    }
  }
  walk(join(__dirname, '..'))
  return ids
}

const SOURCE_HOSTS = [
  'support.google.com',
  'docs.cloud.google.com',
  'knowledge.workspace.google.com',
  'blog.whatsapp.com',
  'signal.org',
]

describe('every link in every answer', () => {
  const ids = sourceIds()
  const links = [...allAnswers().flatMap((a) => a.links.map((link) => ({ key: a.key, link }))), ...FALLBACK_LINKS.map((link) => ({ key: 'fallback', link }))]

  it.each(links.filter(({ link }) => !link.to.startsWith('https://')).map(({ key, link }) => [key, link.to]))(
    '%s → %s is a real page',
    (_key, to) => {
      const resolved = router.resolve(to)
      expect(resolved.name, 'not the not-found page').not.toBe('not-found')
      const { article, algorithm, video } = resolved.query
      if (article !== undefined) {
        expect(knowledgeArticles.map((a) => a.id)).toContain(article)
        // KnowledgeSearch renders each article with this id.
        expect(resolved.hash).toBe(`#article-${article}`)
      } else if (resolved.hash) {
        expect(ids.has(resolved.hash.slice(1)), `an element with ${resolved.hash}`).toBe(true)
      }
      if (algorithm !== undefined) expect(algorithms.map((a) => a.id)).toContain(algorithm)
      if (video !== undefined) {
        expect(HELP_VIDEOS.map((v) => v.id)).toContain(video)
        expect(resolved.path).toBe('/help')
      }
    },
  )

  it('cites only the sources the comparisons were checked against', () => {
    for (const { link } of links.filter(({ link }) => link.to.startsWith('http'))) {
      expect(link.to.startsWith('https://')).toBe(true)
      expect(SOURCE_HOSTS).toContain(new URL(link.to).host)
      expect(link.kind).toBe('source')
    }
  })
})

describe('comparisons', () => {
  const comparisons = ASSISTANT_INTENTS.filter((i) => i.group === 'compare')

  it('cite a source and never claim to be "more secure"', () => {
    for (const intent of comparisons) {
      expect(intent.links.some((l) => l.kind === 'source'), intent.id).toBe(true)
      expect(intent.summary.toLowerCase()).not.toMatch(/more secure|safer than|most secure|unbreakable/)
    }
  })

  it('state the limits honestly', () => {
    const drive = comparisons.find((i) => i.id === 'vs-google-drive')!.summary
    expect(drive).toMatch(/encrypts files in transit and at rest/)
    expect(drive).toMatch(/some paid Workspace editions/)
    expect(drive).toMatch(/keeps any copy they downloaded/)
    const whatsapp = comparisons.find((i) => i.id === 'vs-whatsapp')!.summary
    expect(whatsapp).toMatch(/end-to-end encrypted with the Signal protocol/)
    expect(whatsapp).toMatch(/only if you turn that on/)
  })
})
