<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowRight, ExternalLink, PlayCircle } from 'lucide-vue-next'
import type { AssistantLink } from '@/data/assistant/intents'
import { useAuthStore } from '@/stores/auth_store'
import type { AssistantAnswer } from '@/utils/assistant-search'

const props = defineProps<{
  answer: AssistantAnswer
  /** Title only: an account check below answers the question itself. */
  compact?: boolean
}>()
const emit = defineEmits<{ (e: 'navigate'): void }>()

const router = useRouter()
const auth = useAuthStore()

const productLinks = computed(() => props.answer.links.filter((l) => l.kind !== 'source'))
const sourceLinks = computed(() => props.answer.links.filter((l) => l.kind === 'source'))

/** Signed out, a page behind sign-in would bounce to the login form, so say so up front. */
function needsSignIn(link: AssistantLink): boolean {
  return !auth.isAuthed && Boolean(router.resolve(link.to).meta.requiresAuth)
}
</script>

<template>
  <div class="space-y-3 text-sm" data-testid="assistant-answer">
    <p class="font-semibold text-foreground">{{ answer.title }}</p>
    <p v-if="!compact" class="leading-relaxed text-foreground/90">{{ answer.summary }}</p>

    <ol v-if="!compact && answer.steps?.length" class="space-y-1.5" data-testid="assistant-steps">
      <li v-for="(step, i) in answer.steps" :key="step" class="flex gap-2">
        <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{{ i + 1 }}</span>
        <span class="text-foreground/90">{{ step }}</span>
      </li>
    </ol>

    <ul v-if="!compact" class="flex flex-col gap-1.5" data-testid="assistant-links">
      <li v-for="link in productLinks" :key="link.to">
        <RouterLink
          :to="link.to"
          class="inline-flex items-center gap-1.5 font-medium text-primary hover:underline"
          @click="emit('navigate')"
        >
          <PlayCircle v-if="link.kind === 'video'" class="h-4 w-4 shrink-0" aria-hidden="true" />
          <ArrowRight v-else class="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{{ link.label }}</span>
        </RouterLink>
        <span v-if="needsSignIn(link)" class="ml-1 text-xs text-muted-foreground">(sign in first)</span>
      </li>
    </ul>

    <div v-if="sourceLinks.length" class="border-t border-border pt-2">
      <p class="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Sources</p>
      <ul class="flex flex-col gap-1" data-testid="assistant-sources">
        <li v-for="link in sourceLinks" :key="link.to">
          <a
            :href="link.to"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-start gap-1.5 text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            <ExternalLink class="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
            <span>{{ link.label }}<span class="sr-only"> (opens in a new tab)</span></span>
          </a>
        </li>
      </ul>
    </div>
  </div>
</template>
