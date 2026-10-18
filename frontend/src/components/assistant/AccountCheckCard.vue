<script setup lang="ts">
/**
 * One account check under a Help assistant answer (v2): "who has access to budget.xlsx?"
 * answered from the visitor's own files.
 *
 * A question about the account (`auto`) runs the check at once. Under a general answer it waits
 * behind a button, because "who downloaded my file?" may have meant "how would I find out?".
 * Signed out, it says that signing in is what lets it look.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { AlertTriangle, ArrowRight, Loader2, RefreshCw, Search } from 'lucide-vue-next'
import { apiErrorMessage } from '@/api/http'
import type { AccountCheckId } from '@/data/assistant/intents'
import { useAuthStore } from '@/stores/auth_store'
import { CHECK_LABELS, runAccountCheck, type AccountResult, type FileChoice } from '@/utils/assistant-account'

const props = defineProps<{
  check: AccountCheckId
  /** The file the question named, if any. */
  fileName?: string | null
  /** Run straight away rather than behind a button. */
  auto: boolean
  /** Links the answer above already shows, so the result does not repeat them. */
  shownLinks?: string[]
  /**
   * The result this check already produced. The panel unmounts when closed; without this,
   * reopening it would ask the server again for every answer on screen.
   */
  cached?: AccountResult
}>()
const emit = defineEmits<{
  (e: 'navigate'): void
  (e: 'settled', summary: string): void
  (e: 'result', result: AccountResult): void
}>()

const auth = useAuthStore()

type State =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'done'; result: AccountResult }
  | { kind: 'error'; message: string }

const state = ref<State>(props.cached ? { kind: 'done', result: props.cached } : { kind: 'idle' })

const resultLinks = computed(() =>
  state.value.kind === 'done' && state.value.result.kind === 'result'
    ? state.value.result.links.filter((l) => !props.shownLinks?.includes(l.to))
    : [],
)

async function run(fileId?: string) {
  state.value = { kind: 'loading' }
  try {
    const me = (await auth.loadUser())?.username ?? null
    const result = await runAccountCheck(props.check, { fileName: props.fileName, fileId }, me)
    state.value = { kind: 'done', result }
    emit('result', result)
    emit('settled', result.kind === 'result' ? result.headline : result.prompt)
  } catch (error) {
    const message = apiErrorMessage(error, 'Could not check your account just now.')
    state.value = { kind: 'error', message }
    emit('settled', message)
  }
}

function pick(choice: FileChoice) {
  void run(choice.fileId)
}

onMounted(() => {
  if (props.auto && !props.cached && auth.isAuthed) void run()
})
</script>

<template>
  <div class="text-sm" data-testid="assistant-account" :data-check="check">
    <template v-if="!auth.isAuthed">
      <p v-if="auto" class="rounded-lg bg-secondary/60 px-3 py-2 text-foreground/90" data-testid="assistant-account-signin">
        <RouterLink to="/login" class="font-medium text-primary hover:underline" @click="emit('navigate')">Sign in</RouterLink>
        and I can check this for your account.
      </p>
    </template>

    <button
      v-else-if="state.kind === 'idle'"
      type="button"
      class="inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/5 px-3 py-1.5 text-left text-xs font-medium text-primary hover:bg-primary/10"
      @click="run()"
    >
      <Search class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      {{ CHECK_LABELS[check] }}
    </button>

    <p v-else-if="state.kind === 'loading'" class="inline-flex items-center gap-2 text-muted-foreground" role="status">
      <Loader2 class="h-4 w-4 animate-spin" aria-hidden="true" />
      Checking your account…
    </p>

    <div v-else-if="state.kind === 'error'" class="space-y-2" role="alert">
      <p class="flex items-start gap-1.5 text-destructive">
        <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{{ state.message }}</span>
      </p>
      <button type="button" class="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline" @click="run()">
        <RefreshCw class="h-3.5 w-3.5" aria-hidden="true" /> Try again
      </button>
    </div>

    <div v-else-if="state.result.kind === 'choose'" class="space-y-2" data-testid="assistant-account-choose">
      <p class="text-foreground/90">{{ state.result.prompt }}</p>
      <div class="flex flex-col items-stretch gap-1.5">
        <button
          v-for="choice in state.result.choices"
          :key="choice.fileId"
          type="button"
          class="flex min-w-0 items-baseline justify-between gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-left hover:border-primary/50 hover:bg-primary/5"
          @click="pick(choice)"
        >
          <span translate="no" class="min-w-0 truncate font-medium text-foreground">{{ choice.name }}</span>
          <span class="shrink-0 text-xs text-muted-foreground">{{ choice.detail }}</span>
        </button>
      </div>
    </div>

    <div v-else class="space-y-2" data-testid="assistant-account-result">
      <p class="font-medium text-foreground [overflow-wrap:anywhere]">{{ state.result.headline }}</p>
      <ul v-if="state.result.rows.length" class="divide-y divide-border rounded-lg border border-border bg-background" data-testid="assistant-account-rows">
        <li v-for="(row, i) in state.result.rows" :key="i" class="flex min-w-0 items-baseline justify-between gap-2 px-3 py-1.5">
          <span class="min-w-0 [overflow-wrap:anywhere]" :class="row.tone === 'warn' ? 'text-destructive' : 'text-foreground'">
            <RouterLink v-if="row.to" :to="row.to" class="hover:underline" @click="emit('navigate')">{{ row.text }}</RouterLink>
            <template v-else>{{ row.text }}</template>
            <span v-if="row.tone === 'new'" class="ml-1.5 rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-semibold uppercase text-primary-foreground">new</span>
          </span>
          <span v-if="row.detail" class="shrink-0 text-right text-xs text-muted-foreground">{{ row.detail }}</span>
        </li>
      </ul>
      <p v-if="state.result.note" class="text-xs text-muted-foreground">{{ state.result.note }}</p>
      <ul class="flex flex-col gap-1.5">
        <li v-for="link in resultLinks" :key="link.to">
          <RouterLink :to="link.to" class="inline-flex items-center gap-1.5 font-medium text-primary hover:underline" @click="emit('navigate')">
            <ArrowRight class="h-4 w-4 shrink-0" aria-hidden="true" />
            <span class="[overflow-wrap:anywhere]">{{ link.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </div>
</template>
