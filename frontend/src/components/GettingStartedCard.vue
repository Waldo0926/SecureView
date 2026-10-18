<script setup lang="ts">
import SentenceLines from '@/components/SentenceLines.vue'
import { Check, ChevronRight, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { auditApi } from '@/api/audit_api'
import { unwrapData } from '@/api/types'
import { useAuthStore } from '@/stores/auth_store'
import {
  GETTING_STARTED_STEPS,
  gettingStartedProgress,
  hideGettingStarted,
  isGettingStartedHidden,
  type GettingStartedStep,
} from '@/utils/getting-started'

const auth = useAuthStore()
const username = computed(() => auth.user?.username ?? '')
const hidden = ref(true)
const progress = ref<Record<GettingStartedStep, boolean> | null>(null)

const STEP_TEXT: Record<GettingStartedStep, { title: string; body: string; to: string; cta: string }> = {
  upload: {
    title: 'Encrypt and upload a file',
    body: 'Your browser encrypts it first; the server only receives ciphertext.',
    to: '/upload',
    cta: 'Upload',
  },
  share: {
    title: 'Share it with someone',
    body: 'The file key is re-sealed to their public key. Check their key fingerprint before you confirm.',
    to: '/files',
    cta: 'My Files',
  },
  download: {
    title: 'Download and decrypt a file',
    body: 'Yours, or one shared with you. It is checked for tampering before it is saved.',
    to: '/files',
    cta: 'My Files',
  },
}

const doneCount = computed(() =>
  progress.value ? GETTING_STARTED_STEPS.filter((step) => progress.value![step]).length : 0,
)
const allDone = computed(() => doneCount.value === GETTING_STARTED_STEPS.length)

// The signed-in user is fetched after the page loads, so wait for the name rather than
// reading it once at mount, when it can still be empty.
let loaded = false
watch(username, load, { immediate: true })

async function load() {
  if (loaded || !username.value || isGettingStartedHidden(username.value)) return
  loaded = true
  try {
    // One page of the account's own trail is enough for someone still getting started.
    const logs = unwrapData(await auditApi.listLogs({ limit: 100 })).logs
    progress.value = gettingStartedProgress(logs.map((log) => log.action))
    hidden.value = false
  } catch {
    // Without the trail the card cannot tell what is done, so it stays out of the way.
  }
}

function hide() {
  hideGettingStarted(username.value)
  hidden.value = true
}
</script>

<template>
  <div
    v-if="!hidden && progress"
    class="mb-10 rounded-xl border border-primary/30 bg-card p-6"
    data-testid="getting-started"
  >
    <div class="mb-4 flex items-start justify-between gap-4">
      <div>
        <h3 class="text-lg font-medium text-foreground">
          {{ allDone ? 'You have seen the whole flow' : 'Getting started' }}
        </h3>
        <p class="text-sm text-muted-foreground">
          {{ doneCount }} of {{ GETTING_STARTED_STEPS.length }} done
        </p>
      </div>
      <button
        type="button"
        class="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary"
        title="Hide this checklist"
        aria-label="Hide this checklist"
        @click="hide"
      >
        <X class="h-4 w-4" />
      </button>
    </div>
    <ol class="grid gap-3 md:grid-cols-3">
      <li
        v-for="(step, index) in GETTING_STARTED_STEPS"
        :key="step"
        class="flex gap-3 rounded-lg border border-border p-3"
        :class="progress[step] ? 'bg-success-soft' : ''"
        :data-done="progress[step] ? 'true' : 'false'"
      >
        <span
          class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs"
          :class="progress[step] ? 'border-success bg-success text-success-foreground' : 'border-border text-muted-foreground'"
        >
          <Check v-if="progress[step]" class="h-3.5 w-3.5" />
          <span v-else>{{ index + 1 }}</span>
        </span>
        <div class="min-w-0">
          <p class="text-sm font-medium text-foreground">{{ STEP_TEXT[step].title }}</p>
          <p class="mt-0.5 text-sm text-muted-foreground"><SentenceLines :text="STEP_TEXT[step].body" /></p>
          <RouterLink
            v-if="!progress[step]"
            :to="STEP_TEXT[step].to"
            class="mt-1 inline-flex min-h-10 items-center gap-1 text-sm font-medium text-primary hover:underline md:min-h-0"
          >
            {{ STEP_TEXT[step].cta }}
            <ChevronRight class="h-4 w-4" />
          </RouterLink>
        </div>
      </li>
    </ol>
    <p v-if="allDone" class="mt-4 text-sm text-muted-foreground">
      <SentenceLines text="That is the whole idea: encrypted on your device, shared by key, checked on the way out. You can hide this now." />
    </p>
  </div>
</template>
