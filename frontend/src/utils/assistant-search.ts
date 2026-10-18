/**
 * The Help assistant's matcher (Issue #146): a question in, the best answer out.
 *
 * Everything happens in the browser with no network and no language model. The question is
 * normalised (lowercase, punctuation stripped, a light stemmer, synonyms folded together, small
 * typos corrected against the words the content actually uses) and scored with BM25 against:
 *
 * - the curated intents in `data/assistant/intents.ts`, which win ties because they were
 *   written to answer exactly these questions;
 * - the Education knowledge articles and algorithm pages;
 * - the explainer's scenes and its "ordinary cloud storage versus SecureView" comparison;
 * - the picture guide's steps.
 *
 * Since v2 some intents are about the visitor's own account ("who can open my file?"). Matching
 * them works the same way and still sends nothing; `utils/assistant-account.ts` then answers
 * them with the read-only requests the product pages already make.
 *
 * Those sources are read, not copied, so an article edited on the Education page is what the
 * assistant answers with. A question that shares too little with all of them gets "not sure"
 * and the closest few, rather than a confident wrong answer.
 */
import {
  ASSISTANT_INTENTS,
  type AccountCheckId,
  type AssistantIntent,
  type AssistantLink,
} from '@/data/assistant/intents'
import { algorithms } from '@/data/education/algorithms'
import { knowledgeArticles } from '@/data/education/knowledge'
import { COMPARISON, STORY_SCENES } from '@/data/security-story'
import { workflowSlides } from '@/data/workflow-guide'

export type AnswerSource = 'intent' | 'article' | 'algorithm' | 'scene' | 'comparison' | 'guide'

export interface AssistantAnswer {
  /** `<source>:<id>`, unique across sources. */
  key: string
  source: AnswerSource
  title: string
  summary: string
  steps?: string[]
  links: AssistantLink[]
  /** A look at the visitor's own account this answer can run (v2). */
  check?: AccountCheckId
  /** True when the question is about the visitor's account, so the check runs straight away. */
  personal?: boolean
}

export interface ScoredAnswer {
  answer: AssistantAnswer
  score: number
  /** Share of the question's weight (by IDF) that this answer's text contains, 0..1. */
  coverage: number
}

export type AssistantReply =
  | {
      kind: 'answer'
      answer: AssistantAnswer
      alternatives: AssistantAnswer[]
      /** For a question about one file: the name it gave, or the words that are probably the name. */
      fileName?: string | null
    }
  | { kind: 'unsure'; closest: AssistantAnswer[] }
  | { kind: 'empty' }

// ------------------------------------------------------------------------------ normalising

/** Multi-word spellings folded into one token before splitting, so "end to end" is one idea. */
const PHRASES: [RegExp, string][] = [
  [/\bend[\s-]*to[\s-]*end(?:[\s-]*encrypt\w*)?\b/g, ' endtoend '],
  [/\be2ee?\b/g, ' endtoend '],
  [/\bwhats\s*app\b/g, ' whatsapp '],
  [/\bg\s*drive\b/g, ' google drive '],
  [/\bone\s*drive\b/g, ' onedrive '],
  [/\bdrop\s*box\b/g, ' dropbox '],
  [/\bpass\s+phrase\b/g, ' passphrase '],
  [/\bpass\s*words?\b/g, ' password '],
  [/\b(?:sign|log)\s*(?:in|on)\b/g, ' login '],
  [/\bsign\s*up\b/g, ' signup '],
  [/\bun\s*share\b/g, ' unshare '],
  [/\bkey\s*file\b/g, ' key file '],
  [/\.pem\b/g, ' pem '],
]

/** Words that say nothing about which answer is wanted. */
const STOPWORDS = new Set(
  (
    'a an the i me my mine myself we us our ours you your yours it its this that these those there here ' +
    'is are was were be been being am do does did doing done to of in on at for from with by about into onto ' +
    'as and or but if so than then can could should would will shall may might must how what why where when ' +
    'which whose whom just please hi hello hey thanks thank any some also too very really still yet ' +
    'need want like use using used tell know let make made way thing things something anything ' +
    'secureview app site platform website help im ive id dont doesnt didnt cant cannot couldnt shouldnt ' +
    'wouldnt wont isnt arent wasnt havent hasnt whats hows wheres whys not no yes one'
  ).split(' '),
)

/**
 * Different words for the same thing, folded together. A key is the raw word or its stem; the
 * value is stemmed again, so it meets the content's own spelling of that word.
 */
const SYNONYMS: Record<string, string> = {
  send: 'share',
  sent: 'share',
  give: 'share',
  gave: 'share',
  unshar: 'revok',
  revoc: 'revok',
  lost: 'forgot',
  lose: 'forgot',
  forget: 'forgot',
  forgotten: 'forgot',
  remember: 'forgot',
  pwd: 'password',
  pw: 'password',
  doc: 'document',
  pdf: 'document',
  photo: 'fil',
  pictur: 'fil',
  imag: 'fil',
  attach: 'attachment',
  organiz: 'organis',
  administrator: 'admin',
  hacker: 'hack',
  alter: 'modify',
  edit: 'modify',
  chang: 'modify',
  corrupt: 'tamper',
  algorithm: 'cipher',
  encryption: 'encrypt',
  decryption: 'decrypt',
  e2e: 'endtoend',
  mail: 'email',
  gmail: 'email',
  outlook: 'email',
  directory: 'folder',
  begin: 'start',
  registr: 'regist',
  register: 'regist',
  verific: 'verify',
  join: 'signup',
  erase: 'delet',
  eras: 'delet',
  trash: 'delet',
}

/** A small suffix-stripper: enough that share/shared/sharing/shares meet, nothing clever. */
export function stem(word: string): string {
  let w = word
  if (w.length <= 3) return w
  if (w.endsWith('ies') && w.length > 4) w = `${w.slice(0, -3)}y`
  else if (w.endsWith('ied') && w.length > 4) w = `${w.slice(0, -3)}y`
  else if (w.endsWith('sses')) w = w.slice(0, -2)
  else if (w.endsWith('s') && !/(ss|us|is)$/.test(w)) w = w.slice(0, -1)

  if (w.endsWith('ing') && w.length > 5) w = w.slice(0, -3)
  else if (w.endsWith('ed') && w.length > 4) w = w.slice(0, -2)
  else if (w.endsWith('ation') && w.length > 7) w = w.slice(0, -5)
  else if (w.endsWith('tion') && w.length > 6) w = w.slice(0, -3)

  // stopp → stop, but keep -ll, -ss, -zz (install, access, buzz).
  if (/([^aeiouylsz])\1$/.test(w)) w = w.slice(0, -1)
  if (w.endsWith('e') && w.length > 3) w = w.slice(0, -1)
  return w
}

interface Word {
  /** As written, lowercased: what a typo is corrected against. */
  raw: string
  /** Stemmed and folded onto its synonym: what is compared. */
  token: string
}

function analyze(text: string): Word[] {
  let t = text
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[’‘`]/g, "'")
    .replace(/'s\b/g, '')
    .replace(/'/g, '')
  for (const [pattern, replacement] of PHRASES) t = t.replace(pattern, replacement)
  const words: Word[] = []
  for (const raw of t.split(/[^a-z0-9]+/)) {
    if (raw.length < 2 || STOPWORDS.has(raw)) continue
    const stemmed = stem(raw)
    const synonym = SYNONYMS[raw] ?? SYNONYMS[stemmed]
    words.push({ raw, token: synonym ? stem(synonym) : stemmed })
  }
  return words
}

/** Question or content text → the tokens that are compared. */
export function tokenize(text: string): string[] {
  return analyze(text).map((w) => w.token)
}

/** Damerau–Levenshtein distance with an early exit once it passes `max`. */
export function editDistance(a: string, b: string, max = 2): number {
  if (Math.abs(a.length - b.length) > max) return max + 1
  const rows = a.length + 1
  const cols = b.length + 1
  const d: number[][] = Array.from({ length: rows }, (_, i) => {
    const row = new Array<number>(cols).fill(0)
    row[0] = i
    return row
  })
  for (let j = 0; j < cols; j++) d[0]![j] = j
  for (let i = 1; i < rows; i++) {
    let rowMin = Infinity
    for (let j = 1; j < cols; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      let v = Math.min(d[i - 1]![j]! + 1, d[i]![j - 1]! + 1, d[i - 1]![j - 1]! + cost)
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, d[i - 2]![j - 2]! + 1)
      d[i]![j] = v
      rowMin = Math.min(rowMin, v)
    }
    if (rowMin > max) return max + 1
  }
  return d[a.length]![b.length]!
}

// ------------------------------------------------------------------------------ the index

interface Field {
  text: string | readonly string[]
  weight: number
}

interface IndexedDoc {
  answer: AssistantAnswer
  boost: number
  tf: Map<string, number>
  length: number
  /** Adjacent word pairs from the questions an intent was written for. */
  bigrams: Set<string>
  /** Each of those questions as a sorted token list, to spot the question asked word for word. */
  phrasings: Set<string>
}

interface Index {
  docs: IndexedDoc[]
  df: Map<string, number>
  avgLength: number
  /** Every word the content uses, as written, and the token it becomes. */
  vocabulary: Map<string, string>
}

// Curated intents were written for exactly these questions, so they outrank an article that
// happens to share words with the question. Guide steps are the least specific source.
const INTENT_BOOST = 1.5
const GUIDE_BOOST = 0.8
const K1 = 1.2
const B = 0.6
/** Per word pair the question shares with an intent's phrasings: word order carries meaning. */
const BIGRAM_BONUS = 0.75
/** The question is, word for word, one an intent was written for. */
const PHRASING_BONUS = 4

/** Below either, the reply is "not sure" and the closest answers, not a confident guess. */
export const MIN_SCORE = 2
export const MIN_COVERAGE = 0.5

const PAGE_FOR_SLIDE: Record<string, AssistantLink> = {
  Upload: { label: 'Upload', to: '/upload' },
}

function intentDoc(intent: AssistantIntent) {
  return {
    answer: {
      key: `intent:${intent.id}`,
      source: 'intent' as const,
      title: intent.title,
      summary: intent.summary,
      steps: intent.steps,
      links: intent.links,
      check: intent.check,
      personal: intent.group === 'account',
    },
    boost: INTENT_BOOST,
    questions: [intent.title, ...intent.phrasings],
    fields: [
      { text: intent.title, weight: 3 },
      { text: intent.phrasings, weight: 2 },
      { text: intent.keywords, weight: 2 },
      { text: intent.summary, weight: 0.4 },
    ],
  }
}

interface Source {
  answer: AssistantAnswer
  boost: number
  fields: Field[]
  questions?: string[]
}

function bigramsOf(tokens: string[]): string[] {
  return tokens.slice(1).map((t, i) => `${tokens[i]} ${t}`)
}

function phrasingKey(tokens: string[]): string {
  return [...new Set(tokens)].sort().join(' ')
}

function sources(): Source[] {
  return [
    ...ASSISTANT_INTENTS.map(intentDoc),
    ...knowledgeArticles.map((article) => ({
      answer: {
        key: `article:${article.id}`,
        source: 'article' as const,
        title: article.title,
        summary: article.summary,
        links: [{ label: `Read: ${article.title}`, to: `/education?article=${article.id}#article-${article.id}` }],
      },
      boost: 1,
      fields: [
        { text: article.title, weight: 3 },
        { text: article.tags, weight: 2 },
        { text: article.summary, weight: 1 },
      ],
    })),
    ...algorithms.map((algo) => ({
      answer: {
        key: `algorithm:${algo.id}`,
        source: 'algorithm' as const,
        title: algo.name,
        summary: `${algo.tagline} ${algo.summary}`,
        links: [{ label: `${algo.shortLabel} in the Algorithm Explorer`, to: `/education?algorithm=${algo.id}#algorithm-detail` }],
      },
      boost: 1,
      fields: [
        { text: [algo.name, algo.shortLabel], weight: 3 },
        { text: algo.tagline, weight: 1 },
        { text: algo.summary, weight: 1 },
      ],
    })),
    ...STORY_SCENES.map((scene) => ({
      answer: {
        key: `scene:${scene.id}`,
        source: 'scene' as const,
        title: scene.title,
        summary: `${scene.body} ${scene.why}`,
        links: [
          { label: 'How it works, animated', to: '/how-it-works' },
          { label: 'Video: what happens to your file', to: '/help?video=how-it-works#videos', kind: 'video' as const },
        ],
      },
      boost: 1,
      fields: [
        { text: scene.title, weight: 2 },
        { text: scene.body, weight: 1 },
        { text: scene.why, weight: 0.5 },
      ],
    })),
    ...COMPARISON.map((row, i) => ({
      answer: {
        key: `comparison:${i}`,
        source: 'comparison' as const,
        title: row.question,
        summary: `Ordinary cloud storage: ${row.ordinary} SecureView: ${row.secureview}`,
        links: [{ label: 'Ordinary cloud storage vs SecureView', to: '/how-it-works#why-heading' }],
      },
      boost: 1,
      fields: [
        { text: row.question, weight: 2 },
        { text: row.secureview, weight: 1 },
        { text: row.ordinary, weight: 0.5 },
      ],
    })),
    ...workflowSlides.map((slide) => ({
      answer: {
        key: `guide:${slide.id}`,
        source: 'guide' as const,
        title: slide.title,
        summary: `${slide.action} ${slide.result} ${slide.tip}`,
        links: [
          { label: 'Picture guide', to: '/#how-it-works' },
          PAGE_FOR_SLIDE[slide.page] ?? { label: 'My Files', to: '/files' },
        ],
      },
      boost: GUIDE_BOOST,
      fields: [
        { text: [slide.short, slide.title], weight: 2 },
        { text: slide.action, weight: 1 },
        { text: slide.tip, weight: 0.5 },
      ],
    })),
  ]
}

function buildIndex(): Index {
  const docs: IndexedDoc[] = []
  const df = new Map<string, number>()
  const vocabulary = new Map<string, string>()
  for (const source of sources()) {
    const tf = new Map<string, number>()
    let length = 0
    for (const field of source.fields) {
      const texts = typeof field.text === 'string' ? [field.text] : field.text
      for (const text of texts) {
        for (const { raw, token } of analyze(text)) {
          vocabulary.set(raw, token)
          tf.set(token, (tf.get(token) ?? 0) + field.weight)
          length += field.weight
        }
      }
    }
    for (const token of tf.keys()) df.set(token, (df.get(token) ?? 0) + 1)
    const questions = (source.questions ?? []).map(tokenize)
    docs.push({
      answer: source.answer,
      boost: source.boost,
      tf,
      length,
      bigrams: new Set(questions.flatMap(bigramsOf)),
      phrasings: new Set(questions.map(phrasingKey)),
    })
  }
  const avgLength = docs.reduce((sum, d) => sum + d.length, 0) / Math.max(docs.length, 1)
  return { docs, df, avgLength, vocabulary }
}

let index: Index | null = null
function getIndex(): Index {
  index ??= buildIndex()
  return index
}

/**
 * A word the content never uses, replaced by the closest word it does: one typo, two in a long
 * word. Compared as written rather than stemmed, so "shre" still finds "share".
 */
function correct(word: Word, idx: Index): string {
  if (idx.df.has(word.token) || word.raw.length < 4 || /\d/.test(word.raw)) return word.token
  const max = word.raw.length >= 7 ? 2 : 1
  let best = word.token
  let bestDistance = max + 1
  let bestDf = 0
  for (const [raw, token] of idx.vocabulary) {
    if (raw.length < 3) continue
    const distance = editDistance(word.raw, raw, max)
    const count = idx.df.get(token) ?? 0
    if (distance < bestDistance || (distance === bestDistance && count > bestDf)) {
      best = token
      bestDistance = distance
      bestDf = count
    }
  }
  return bestDistance <= max ? best : word.token
}

function idf(index: Index, token: string): number {
  const n = index.docs.length
  const df = index.df.get(token) ?? 0
  return Math.log(1 + (n - df + 0.5) / (df + 0.5))
}

/** Every answer that shares a word with the question, best first. */
export function searchAssistant(question: string): ScoredAnswer[] {
  const idx = getIndex()
  const corrected = analyze(question).map((w) => correct(w, idx))
  const terms = [...new Set(corrected)]
  if (terms.length === 0) return []
  const bigrams = bigramsOf(corrected)
  const asked = phrasingKey(corrected)
  const weights = terms.map((t) => idf(idx, t))
  const totalWeight = weights.reduce((a, b) => a + b, 0)

  const results: ScoredAnswer[] = []
  for (const doc of idx.docs) {
    let score = 0
    let matched = 0
    terms.forEach((term, i) => {
      const tf = doc.tf.get(term)
      if (!tf) return
      matched += weights[i]!
      score += (weights[i]! * tf * (K1 + 1)) / (tf + K1 * (1 - B + (B * doc.length) / idx.avgLength))
    })
    if (score > 0) {
      for (const pair of bigrams) if (doc.bigrams.has(pair)) score += BIGRAM_BONUS
      if (doc.phrasings.has(asked)) score += PHRASING_BONUS
      results.push({ answer: doc.answer, score: score * doc.boost, coverage: totalWeight ? matched / totalWeight : 0 })
    }
  }
  return results.sort((a, b) => b.score - a.score || a.answer.key.localeCompare(b.answer.key))
}

// ------------------------------------------------------------------------------ file names

/** `"quarterly report"` or “budget” in quotes, or one word with an extension such as report.pdf. */
const QUOTED = /["“”'‘’]([^"“”'‘’]{2,80})["“”'‘’]/
const WITH_EXTENSION = /(?:^|\s)([^\s"“”'‘’]*[^\s.?!,;:"“”'‘’]\.[a-z0-9]{1,5})(?=[\s?!,;:]|$)/i

/**
 * The file a question names, if it names one, and the question without it. A file name says
 * which file, not what is being asked, so it is matched separately: "who has access to
 * budget.xlsx" is the who-has-access question about budget.xlsx. A name with spaces needs
 * quotes; without them only the word carrying the extension is taken.
 */
export function splitFileName(question: string): { fileName: string | null; rest: string } {
  const quoted = QUOTED.exec(question)
  if (quoted) return { fileName: quoted[1]!.trim(), rest: question.replace(quoted[0], ' ') }
  const named = WITH_EXTENSION.exec(question)
  // "version 1.2" is a number, not a file: a name and its extension both carry a letter.
  if (named && /[a-z].*\.[a-z0-9]*[a-z]/i.test(named[1]!)) return { fileName: named[1]!, rest: question.replace(named[1]!, ' ') }
  return { fileName: null, rest: question }
}

/** Checks that are about one file: a question to them usually carries that file's name. */
export const FILE_CHECKS: ReadonlySet<string> = new Set(['who-has-access', 'file-activity'])
/** Only a question that is plainly about the visitor's own file gets the name allowance. */
const OWN_FILE = /\b(?:my|mine|file|files|document|documents)\b|["“'‘]|\.[a-z0-9]{1,5}\b/i

/**
 * Words the content never uses, after typo correction. For a question about one file these are
 * most likely its name ("who has access to my thesis draft"), so they do not count against
 * the match.
 */
function unknownWeight(question: string): number {
  const idx = getIndex()
  let unknown = 0
  let total = 0
  for (const word of analyze(question)) {
    const token = correct(word, idx)
    const weight = idf(idx, token)
    total += weight
    if (!idx.df.has(token)) unknown += weight
  }
  return total ? unknown / total : 0
}

/** The words of a question that the content never uses, as written: probably a file's name. */
function unknownWords(question: string): string[] {
  const idx = getIndex()
  return analyze(question)
    .filter((w) => !idx.vocabulary.has(w.raw) && !idx.df.has(w.token))
    .map((w) => w.raw)
}

/** The reply the panel shows: one answer and two runners-up, or "not sure" and the closest three. */
export function answerQuestion(question: string): AssistantReply {
  const { fileName, rest } = splitFileName(question)
  if (tokenize(rest).length === 0) return { kind: 'empty' }
  const ranked = searchAssistant(rest)
  const best = ranked[0]
  // Coverage of what is left once the words nobody wrote are taken to be the file's name.
  const fileQuestion =
    Boolean(best?.answer.check && FILE_CHECKS.has(best.answer.check)) && OWN_FILE.test(question)
  const unknown = fileQuestion ? unknownWeight(rest) : 0
  const coverage = best ? (unknown < 1 ? best.coverage / (1 - unknown) : 0) : 0
  if (!best || best.score < MIN_SCORE || coverage < MIN_COVERAGE) {
    return { kind: 'unsure', closest: ranked.slice(0, 3).map((r) => r.answer) }
  }
  const reply: AssistantReply = { kind: 'answer', answer: best.answer, alternatives: ranked.slice(1, 3).map((r) => r.answer) }
  if (best.answer.check && FILE_CHECKS.has(best.answer.check)) {
    reply.fileName = fileName ?? (fileQuestion ? unknownWords(rest).join(' ') || null : null)
  }
  return reply
}

/** An intent's answer by id, for the suggested-question chips. */
export function intentAnswer(id: string): AssistantAnswer | undefined {
  const intent = ASSISTANT_INTENTS.find((i) => i.id === id)
  return intent ? intentDoc(intent).answer : undefined
}

/** Every answer the assistant can give, for tests that check all of their links. */
export function allAnswers(): AssistantAnswer[] {
  return getIndex().docs.map((d) => d.answer)
}

/** One answer by its key, to bring back a remembered or chosen answer exactly. */
export function answerByKey(key: string): AssistantAnswer | undefined {
  return getIndex().docs.find((d) => d.answer.key === key)?.answer
}
