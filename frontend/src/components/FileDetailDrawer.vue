<script setup lang="ts">
import { Activity, AlertCircle, Check, CheckCircle, Copy, Download, Loader2, Share2, Shield, Trash2, X } from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { shareApi } from '@/api/share_api'
import type { SharedUser } from '@/api/share_api'
import { unwrapData } from '@/api/types'
import { exactBytes } from '@/utils/ciphertext-preview'

/**
 * Everything the list knows about one file, in one place: what it is, whether it is intact, who can
 * open it, and the actions. It adds no data of its own: the facts come from the list row, the
 * people from `GET /files/{id}/shared-users`, and every button hands the work back to the page's
 * own handler, so a download, share or delete behaves exactly as it does from the row.
 */
interface DetailFile {
  id: string
  name: string
  originalSize: string
  encryptedSize: string
  originalBytes: number
  encryptedBytes: number
  encryptedAt: string
  status: 'verified' | 'modified' | 'pending'
  owned: boolean
  ownerName: string
  algorithm: string
  mimeType: string | null
  sha256?: string
}

/** `checking` is the page's own integrity-check state, so the button here and the row's badge agree. */
const props = defineProps<{ file: DetailFile; downloadBusy: boolean; downloading: boolean; checking?: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'download'): void
  (e: 'share'): void
  (e: 'check'): void
  (e: 'history'): void
  (e: 'delete'): void
}>()

const statusView = {
  verified: { label: 'Verified', icon: CheckCircle, className: 'bg-success-soft text-success' },
  modified: { label: 'Modified', icon: AlertCircle, className: 'bg-destructive-soft text-destructive' },
  pending: { label: 'Pending', icon: Shield, className: 'bg-muted text-muted-foreground' },
} as const

const people = ref<SharedUser[]>([])
const peopleState = ref<'idle' | 'loading' | 'error' | 'paused'>('idle')
const closeButton = ref<HTMLButtonElement | null>(null)
const copied = ref(false)
let copiedTimer = 0

async function copyDigest() {
  if (!props.file.sha256) return
  try {
    await navigator.clipboard.writeText(props.file.sha256)
    copied.value = true
    window.clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => (copied.value = false), 2000)
  } catch {
    // Clipboard access can be refused; the digest is on screen and can be selected by hand.
  }
}

async function loadPeople() {
  people.value = []
  if (!props.file.owned) return
  // The server only lists recipients of an intact file, so for a modified one the request
  // would come back as not found. Say why instead of showing it as a failure.
  if (props.file.status === 'modified') {
    peopleState.value = 'paused'
    return
  }
  peopleState.value = 'loading'
  try {
    people.value = unwrapData(await shareApi.sharedUsers(props.file.id)).users ?? []
    peopleState.value = 'idle'
  } catch {
    peopleState.value = 'error'
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

/*
 * From the md breakpoint up the panel sits beside the list rather than over a dimmed page: the
 * rows stay readable and clickable, so another file can be opened without closing this one first.
 * A click on the page outside the panel and outside the file rows closes it, as the backdrop did.
 * On a phone it is a bottom sheet over a backdrop, and modal.
 */
const panel = ref<HTMLElement | null>(null)
const narrowQuery = window.matchMedia('(max-width: 767.98px)')
const narrow = ref(narrowQuery.matches)
const onNarrowChange = (event: MediaQueryListEvent) => (narrow.value = event.matches)

function onPointerDown(event: PointerEvent) {
  if (narrow.value) return
  const target = event.target as Element | null
  if (!target || panel.value?.contains(target)) return
  if (target.closest('[data-file-row], [role="dialog"], [role="menu"]')) return
  emit('close')
}

onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('pointerdown', onPointerDown)
  narrowQuery.addEventListener('change', onNarrowChange)
  await nextTick()
  closeButton.value?.focus()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('pointerdown', onPointerDown)
  narrowQuery.removeEventListener('change', onNarrowChange)
  window.clearTimeout(copiedTimer)
})
watch(() => [props.file.id, props.file.status], loadPeople, { immediate: true })
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-50" data-testid="file-detail">
    <div class="pointer-events-auto absolute inset-0 bg-black/30 md:hidden" @click="emit('close')" />
    <aside
      ref="panel"
      class="pointer-events-auto absolute inset-x-0 bottom-0 flex max-h-[88dvh] flex-col gap-6 overflow-y-auto rounded-t-2xl border-t border-border bg-card p-6 shadow-xl animate-in slide-in-from-bottom duration-200 motion-reduce:animate-none md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-full md:max-w-md md:rounded-none md:border-l md:border-t-0 md:slide-in-from-right md:slide-in-from-bottom-0"
      role="dialog"
      :aria-modal="narrow"
      :aria-label="`Details of ${file.name}`"
    >
      <div class="-mt-2 mx-auto h-1 w-10 shrink-0 rounded-full bg-border md:hidden" aria-hidden="true" />
      <div class="flex items-start justify-between gap-4">
        <div class="flex min-w-0 flex-col gap-2">
          <p class="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-muted-foreground">File</p>
          <h2 translate="no" class="text-xl font-semibold [overflow-wrap:anywhere]">{{ file.name }}</h2>
          <span class="inline-flex w-fit items-center gap-1.5 rounded-md px-2.5 py-1 font-mono text-xs" :class="statusView[file.status].className">
            <component :is="statusView[file.status].icon" class="h-3 w-3" aria-hidden="true" />
            {{ statusView[file.status].label }}
          </span>
        </div>
        <button
          ref="closeButton"
          type="button"
          class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md hover:bg-secondary"
          aria-label="Close details"
          @click="emit('close')"
        >
          <X class="h-4 w-4" />
        </button>
      </div>

      <dl class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-x-4 gap-y-3 text-sm">
        <dt class="text-muted-foreground">Cipher</dt>
        <dd translate="no" class="font-mono text-[0.8rem]">{{ file.algorithm }}</dd>
        <dt class="text-muted-foreground">Original size</dt>
        <!-- Under 1 KB the readable size already is the byte count, so it is not repeated. -->
        <dd>{{ file.originalSize }} <span v-if="file.originalBytes >= 1024" class="font-mono text-xs text-muted-foreground">{{ exactBytes(file.originalBytes) }}</span></dd>
        <dt class="text-muted-foreground">Stored size</dt>
        <dd>{{ file.encryptedSize }} <span v-if="file.encryptedBytes >= 1024" class="font-mono text-xs text-muted-foreground">{{ exactBytes(file.encryptedBytes) }}</span></dd>
        <dt v-if="file.mimeType" class="text-muted-foreground">Type</dt>
        <dd v-if="file.mimeType" translate="no" class="font-mono text-[0.8rem]">{{ file.mimeType }}</dd>
        <dt class="text-muted-foreground">Uploaded</dt>
        <dd>{{ file.encryptedAt }}</dd>
        <dt class="text-muted-foreground">Owner</dt>
        <dd translate="no">{{ file.owned ? 'You' : file.ownerName }}</dd>
      </dl>

      <section v-if="file.sha256" class="flex flex-col gap-2.5 border-t border-border pt-5" data-testid="file-sha256">
        <div class="flex items-center justify-between gap-3">
          <h3 class="text-sm font-semibold">Ciphertext SHA-256</h3>
          <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground" @click="copyDigest">
            <component :is="copied ? Check : Copy" class="h-3.5 w-3.5" aria-hidden="true" />
            {{ copied ? 'Copied' : 'Copy' }}
          </button>
        </div>
        <code translate="no" class="break-all rounded-lg bg-secondary px-3.5 py-3 font-mono text-xs leading-relaxed">{{ file.sha256 }}</code>
        <p class="text-xs leading-relaxed text-muted-foreground">The fingerprint of the stored ciphertext as recorded at upload. Every download and the daily scan are checked against it.</p>
      </section>

      <section class="flex flex-col gap-3 border-t border-border pt-5">
        <h3 class="text-sm font-semibold">Who can open it</h3>
        <p v-if="!file.owned" class="text-sm leading-relaxed text-muted-foreground">
          Shared with you by {{ file.ownerName }}. You open it with your own key, and the server never sees the file.
        </p>
        <template v-else>
          <p v-if="peopleState === 'loading'" class="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 class="h-4 w-4 animate-spin" /> Loading…</p>
          <p v-else-if="peopleState === 'error'" class="text-sm text-destructive">The list of people could not be loaded.</p>
          <p v-else-if="peopleState === 'paused'" class="text-sm text-muted-foreground">
            Sharing details are hidden while this file fails its integrity check. They come back once it is restored.
          </p>
          <ul v-else class="flex flex-col divide-y divide-border rounded-lg border border-border text-sm">
            <li v-for="person in people" :key="person.user_id" class="flex items-center justify-between gap-3 px-3.5 py-2.5">
              <span translate="no" class="truncate">{{ person.is_owner ? 'You' : person.username }}</span>
              <span class="shrink-0 font-mono text-xs text-muted-foreground">
                {{ person.is_owner ? 'owner' : person.can_download ? 'can open' : 'view only' }}
              </span>
            </li>
            <li v-if="people.length <= 1" class="px-3.5 py-2.5 text-muted-foreground">Nobody else yet. Only you can open it.</li>
          </ul>
          <p class="text-xs leading-relaxed text-muted-foreground">The file key is also sealed for the recovery key.</p>
        </template>
      </section>

      <div class="mt-auto flex flex-col gap-2.5 border-t border-border pt-5">
        <button
          type="button"
          class="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          :disabled="downloadBusy"
          @click="emit('download')"
        >
          <Loader2 v-if="downloading" class="h-4 w-4 animate-spin" />
          <Download v-else class="h-4 w-4" />
          Download and decrypt
        </button>
        <div class="grid grid-cols-2 gap-2.5">
          <button v-if="file.owned" type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-border px-3 text-sm hover:bg-secondary" @click="emit('share')">
            <Share2 class="h-4 w-4" /> Share
          </button>
          <!-- The panel stays open during the check so the status badge above shows the result. -->
          <button type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-border px-3 text-sm hover:bg-secondary disabled:cursor-wait disabled:opacity-70" :disabled="checking" :aria-busy="checking" @click="emit('check')">
            <Loader2 v-if="checking" class="h-4 w-4 animate-spin" />
            <Shield v-else class="h-4 w-4" />
            {{ checking ? 'Checking…' : 'Check integrity' }}
          </button>
          <button type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-border px-3 text-sm hover:bg-secondary" @click="emit('history')">
            <Activity class="h-4 w-4" /> Access history
          </button>
          <button v-if="file.owned" type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-border px-3 text-sm text-destructive hover:bg-destructive-soft" @click="emit('delete')">
            <Trash2 class="h-4 w-4" /> Delete
          </button>
        </div>
      </div>
    </aside>
  </div>
</template>
