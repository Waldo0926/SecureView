<script setup lang="ts">
/**
 * The Help assistant (Issue #146): a round button on every page that opens a small panel where
 * a visitor can ask "how do I…", "how does it work…" or "why not Google Drive…".
 *
 * Answers come from `utils/assistant-search.ts`, which runs entirely in this browser over
 * SecureView's own help content. No question is sent anywhere or logged, and the panel says so.
 * It is called the Help assistant, never an agent: the security agent is a different feature.
 *
 * Since v2 it also answers questions about the signed-in visitor's own account ("who has access
 * to budget.xlsx?", "what has been shared with me?") with `AccountCheckCard`, which reads the
 * same API My Files and the Activity Log use and changes nothing.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Bot, MessageCircleQuestion, Send, X } from 'lucide-vue-next'
import AccountCheckCard from '@/components/assistant/AccountCheckCard.vue'
import type { AccountResult } from '@/utils/assistant-account'
import AssistantAnswerCard from '@/components/assistant/AssistantAnswerCard.vue'
import { ACCOUNT_SUGGESTED_INTENT_IDS, FALLBACK_LINKS, SUGGESTED_INTENT_IDS } from '@/data/assistant/intents'
import { useAuthStore } from '@/stores/auth_store'
import {
  FILE_CHECKS,
  answerByKey,
  answerQuestion,
  intentAnswer,
  searchAssistant,
  type AssistantAnswer,
  type AssistantReply,
} from '@/utils/assistant-search'
import {
  MAX_REMEMBERED,
  readAssistantSession,
  writeAssistantSession,
  type RememberedQuestion,
} from '@/utils/assistant-session'

interface Exchange {
  id: number
  question: string
  reply: AssistantReply
  /** "Was this not it?" pressed: the runners-up are on show. */
  expanded: boolean
  /** Asked in this page view, so an account check may run without a click. */
  fresh: boolean
  /** The account check's result, kept in memory only so reopening the panel does not re-ask. */
  account?: AccountResult
}

const auth = useAuthStore()

const open = ref(false)
const draft = ref('')
const exchanges = ref<Exchange[]>([])
const announcement = ref('')
let nextId = 1

const trigger = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const log = ref<HTMLElement | null>(null)
const scroller = ref<HTMLElement | null>(null)

const suggestions = computed(() =>
  [...(auth.isAuthed ? ACCOUNT_SUGGESTED_INTENT_IDS : []), ...SUGGESTED_INTENT_IDS]
    .map((id) => intentAnswer(id))
    .filter((a): a is AssistantAnswer => Boolean(a)),
)

/**
 * Whether an answer's account check runs as soon as it is shown: the question was about the
 * account, or named one of the visitor's files. A restored answer waits for a click instead.
 */
function autoCheck(exchange: Exchange): boolean {
  if (exchange.reply.kind !== 'answer' || !exchange.fresh) return false
  const { answer, fileName } = exchange.reply
  return Boolean(answer.personal || (fileName && answer.check && FILE_CHECKS.has(answer.check)))
}

/** Signed in, an account answer is the check's result; the "signed in, I can…" text is for visitors. */
function compact(exchange: Exchange): boolean {
  return exchange.reply.kind === 'answer' && Boolean(exchange.reply.answer.personal) && auth.isAuthed
}

function onSettled(summary: string) {
  announcement.value = summary
}

/** Kept on the exchange (and not in storage), and the check will not run by itself again. */
function onResult(id: number, result: AccountResult) {
  exchanges.value = exchanges.value.map((e) => (e.id === id ? { ...e, account: result, fresh: false } : e))
}

function persist() {
  writeAssistantSession({
    open: open.value,
    questions: exchanges.value.map((e) => ({
      question: e.question,
      answerKey: e.reply.kind === 'answer' ? e.reply.answer.key : null,
      fileName: e.reply.kind === 'answer' ? (e.reply.fileName ?? null) : null,
    })),
  })
}

function announce(reply: AssistantReply) {
  announcement.value =
    reply.kind === 'answer'
      ? `${reply.answer.title}. ${reply.answer.summary}`
      : reply.kind === 'unsure'
        ? 'Not sure about that one. Some close matches and a link to Help are shown.'
        : 'Ask a question about SecureView.'
}

/**
 * Bring the newest exchange to the top of the scrolling area. Not `scrollIntoView`: that also
 * scrolls the panel itself (overflow: hidden still scrolls from script) and pushes its header out.
 */
async function scrollToLatest() {
  await nextTick()
  const area = scroller.value
  const last = log.value?.lastElementChild
  if (!area || !(last instanceof HTMLElement)) return
  area.scrollTop += last.getBoundingClientRect().top - area.getBoundingClientRect().top - 8
}

function push(question: string, reply: AssistantReply) {
  exchanges.value = [...exchanges.value, { id: nextId++, question, reply, expanded: false, fresh: true }].slice(-MAX_REMEMBERED)
  announce(reply)
  persist()
  void scrollToLatest()
}

function ask(text: string) {
  const question = text.trim()
  if (!question) return
  push(question, answerQuestion(question))
  draft.value = ''
}

/** A suggested question or a "did you mean" choice: show exactly that answer. */
function choose(answer: AssistantAnswer) {
  push(answer.title, { kind: 'answer', answer, alternatives: alternativesFor(answer.title, answer) })
}

async function openPanel() {
  open.value = true
  persist()
  await nextTick()
  input.value?.focus()
}

async function closePanel() {
  open.value = false
  persist()
  await nextTick()
  trigger.value?.focus()
}

function toggle() {
  if (open.value) void closePanel()
  else void openPanel()
}

/** Following a link on a phone leaves the sheet covering the page it opened, so close it there. */
function onNavigate() {
  if (window.matchMedia('(max-width: 639px)').matches) {
    open.value = false
    persist()
  }
}

/** Escape closes the panel wherever focus is, as long as no dialog of the page is on top of it. */
function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !open.value || event.defaultPrevented) return
  const focus = document.activeElement
  if (focus && focus !== document.body && !panel.value?.contains(focus) && focus.closest('[role="dialog"]')) return
  event.preventDefault()
  void closePanel()
}

/** Keep Tab inside the open panel, so keyboard focus cannot wander behind it. */
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !panel.value) return
  const focusable = [
    ...panel.value.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled])'),
  ].filter((el) => el.offsetParent !== null)
  if (focusable.length === 0) return
  const first = focusable[0]!
  const last = focusable[focusable.length - 1]!
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

/** The two answers ranked next for this question, leaving out the one on show. */
function alternativesFor(question: string, shown: AssistantAnswer): AssistantAnswer[] {
  return searchAssistant(question)
    .map((r) => r.answer)
    .filter((a) => a.key !== shown.key)
    .slice(0, 2)
}

function restore(saved: RememberedQuestion): AssistantReply {
  const shown = saved.answerKey ? answerByKey(saved.answerKey) : undefined
  if (!shown) return answerQuestion(saved.question)
  return { kind: 'answer', answer: shown, alternatives: alternativesFor(saved.question, shown), fileName: saved.fileName ?? null }
}

onMounted(() => {
  const saved = readAssistantSession()
  exchanges.value = saved.questions.map((q) => ({ id: nextId++, question: q.question, reply: restore(q), expanded: false, fresh: false }))
  open.value = saved.open
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => document.removeEventListener('keydown', onDocumentKeydown))

watch(open, (isOpen) => {
  if (isOpen) void scrollToLatest()
})

// Signing out (here or in another tab's refresh failure) forgets what was asked, so an answer
// about the last person's files is not left on screen for the next one.
watch(
  () => auth.isAuthed,
  (isAuthed, was) => {
    if (was && !isAuthed) {
      exchanges.value = []
      announcement.value = ''
    }
  },
)
</script>

<template>
  <div class="help-assistant">
    <button
      ref="trigger"
      type="button"
      class="assistant-trigger fixed z-40 inline-flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      :class="{ 'max-sm:hidden': open }"
      :aria-expanded="open"
      aria-controls="help-assistant-panel"
      :aria-label="open ? 'Close the Help assistant' : 'Open the Help assistant'"
      data-testid="assistant-trigger"
      @click="toggle"
    >
      <X v-if="open" class="h-5 w-5" aria-hidden="true" />
      <Bot v-else class="h-6 w-6" aria-hidden="true" />
    </button>

    <section
      v-if="open"
      id="help-assistant-panel"
      ref="panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="help-assistant-title"
      class="assistant-panel fixed z-40 flex flex-col overflow-hidden border border-border bg-card text-foreground shadow-2xl"
      data-testid="assistant-panel"
      @keydown="onKeydown"
    >
      <header class="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div class="flex min-w-0 items-center gap-2">
          <span class="rounded-lg bg-primary/10 p-1.5 text-primary"><MessageCircleQuestion class="h-4 w-4" aria-hidden="true" /></span>
          <h2 id="help-assistant-title" class="truncate font-semibold">Help assistant</h2>
        </div>
        <button
          type="button"
          class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          aria-label="Close"
          @click="closePanel"
        >
          <X class="h-4 w-4" aria-hidden="true" />
        </button>
      </header>

      <div ref="scroller" class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">
        <p class="text-sm text-muted-foreground">
          Hi! Ask how to do something in SecureView, how it keeps your files private, or how it compares with
          tools you already use.<template v-if="auth.isAuthed">
            You can also ask about your own files, such as who has access to one of them.</template>
        </p>
        <div class="mt-3 flex flex-wrap gap-2" data-testid="assistant-suggestions">
          <button
            v-for="s in suggestions"
            :key="s.key"
            type="button"
            class="rounded-full border border-border bg-secondary/40 px-3 py-1.5 text-left text-xs text-foreground hover:border-primary/50 hover:bg-primary/10"
            @click="choose(s)"
          >
            {{ s.title }}
          </button>
        </div>

        <ol ref="log" class="mt-4 space-y-4" aria-label="Questions and answers">
          <li v-for="exchange in exchanges" :key="exchange.id" class="scroll-mt-2 space-y-2">
            <p translate="no" class="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground [overflow-wrap:anywhere]">
              {{ exchange.question }}
            </p>

            <div class="rounded-2xl rounded-bl-sm border border-border bg-background/60 p-3">
              <template v-if="exchange.reply.kind === 'answer'">
                <AssistantAnswerCard :answer="exchange.reply.answer" :compact="compact(exchange)" @navigate="onNavigate" />
                <AccountCheckCard
                  v-if="exchange.reply.answer.check && (auth.isAuthed || exchange.reply.answer.personal)"
                  :key="`${exchange.id}:${auth.isAuthed}`"
                  class="mt-3"
                  :check="exchange.reply.answer.check"
                  :file-name="exchange.reply.fileName"
                  :auto="autoCheck(exchange)"
                  :shown-links="compact(exchange) ? [] : exchange.reply.answer.links.map((l) => l.to)"
                  :cached="exchange.account"
                  @navigate="onNavigate"
                  @settled="onSettled"
                  @result="(result) => onResult(exchange.id, result)"
                />
                <div v-if="!exchange.expanded" class="mt-3 border-t border-border pt-2">
                  <button
                    type="button"
                    class="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    @click="exchange.expanded = true"
                  >
                    Was this not it?
                  </button>
                </div>
                <div v-else class="mt-3 space-y-2 border-t border-border pt-2 text-xs" data-testid="assistant-more">
                  <p class="text-muted-foreground">Maybe one of these:</p>
                  <div class="flex flex-col items-start gap-1.5">
                    <button
                      v-for="alt in exchange.reply.alternatives"
                      :key="alt.key"
                      type="button"
                      class="text-left font-medium text-primary hover:underline"
                      @click="choose(alt)"
                    >
                      {{ alt.title }}
                    </button>
                  </div>
                  <p class="text-muted-foreground">
                    Or try
                    <RouterLink :to="FALLBACK_LINKS[0]!.to" class="text-primary hover:underline" @click="onNavigate">{{ FALLBACK_LINKS[0]!.label }}</RouterLink>
                    or
                    <RouterLink :to="FALLBACK_LINKS[1]!.to" class="text-primary hover:underline" @click="onNavigate">{{ FALLBACK_LINKS[1]!.label }}</RouterLink>.
                  </p>
                </div>
              </template>

              <div v-else-if="exchange.reply.kind === 'unsure'" class="space-y-2 text-sm" data-testid="assistant-unsure">
                <p>I’m not sure about that one. The closest things I know about:</p>
                <div class="flex flex-col items-start gap-1.5">
                  <button
                    v-for="alt in exchange.reply.closest"
                    :key="alt.key"
                    type="button"
                    class="text-left font-medium text-primary hover:underline"
                    @click="choose(alt)"
                  >
                    {{ alt.title }}
                  </button>
                </div>
                <p class="text-muted-foreground">
                  Or browse
                  <RouterLink :to="FALLBACK_LINKS[0]!.to" class="text-primary hover:underline" @click="onNavigate">{{ FALLBACK_LINKS[0]!.label }}</RouterLink>
                  or
                  <RouterLink :to="FALLBACK_LINKS[1]!.to" class="text-primary hover:underline" @click="onNavigate">{{ FALLBACK_LINKS[1]!.label }}</RouterLink>.
                </p>
              </div>

              <p v-else class="text-sm text-muted-foreground">
                Ask me something about SecureView, for example “how do I share a file?”
              </p>
            </div>
          </li>
        </ol>
      </div>

      <form class="shrink-0 border-t border-border px-3 pb-2 pt-3" @submit.prevent="ask(draft)">
        <div class="flex gap-2">
          <label for="help-assistant-input" class="sr-only">Your question</label>
          <input
            id="help-assistant-input"
            ref="input"
            v-model="draft"
            type="text"
            maxlength="200"
            autocomplete="off"
            enterkeyhint="send"
            placeholder="Ask a question…"
            class="h-10 min-w-0 flex-1 rounded-md border border-border bg-background px-3 text-base sm:text-sm"
          />
          <button
            type="submit"
            class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground disabled:opacity-50"
            :disabled="!draft.trim()"
            aria-label="Ask"
          >
            <Send class="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <p class="mt-2 text-[11px] leading-snug text-muted-foreground">
          Answers come from SecureView's own help content; your question is not sent anywhere. Answers about your
          account only read what My Files and the Activity Log already show you.
        </p>
      </form>
    </section>

    <div class="sr-only" aria-live="polite" aria-atomic="true" data-testid="assistant-live">{{ announcement }}</div>
  </div>
</template>

<style scoped>
/* The 16 px gutter, or more where a phone's rounded corners or home bar need it. */
.assistant-trigger {
  right: max(1rem, env(safe-area-inset-right));
  bottom: max(1rem, env(safe-area-inset-bottom));
}

/* A bottom sheet on a phone… */
.assistant-panel {
  left: 0;
  right: 0;
  bottom: 0;
  max-height: 85dvh;
  border-radius: 1rem 1rem 0 0;
  padding-bottom: env(safe-area-inset-bottom);
}

/* …and a card above the button on anything wider. */
@media (min-width: 640px) {
  .assistant-panel {
    left: auto;
    right: max(1rem, env(safe-area-inset-right));
    bottom: calc(max(1rem, env(safe-area-inset-bottom)) + 3.75rem);
    width: 380px;
    max-height: min(640px, calc(100dvh - 7rem));
    border-radius: 1rem;
    padding-bottom: 0;
  }
}
</style>
