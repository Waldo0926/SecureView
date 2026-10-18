<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Activity, Loader2 } from 'lucide-vue-next'

import { auditApi } from '@/api/audit_api'
import { apiErrorMessage } from '@/api/http'
import { formatFileSize, unwrapData, type AuditLogOut } from '@/api/types'
import { auditActionLabel, auditActorLabel, isDownloadAction } from '@/utils/audit-actions'
import { formatSiteDateTime } from '@/utils/site-time'

const props = defineProps<{
  fileId: string
  filename: string
  /** The viewer owns this file, so the trail includes what other people did with it. */
  owned: boolean
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

interface HistoryEntry {
  id: string
  actor: string
  /** `actor` is a real username (never translated), not "System (server script)". */
  actorNamed: boolean
  action: string
  detail: string
  at: string
  succeeded: boolean
  isDownload: boolean
  /** " · Downloaded 137.36 KB" -- separators included, so nothing depends on markup spacing. */
  summary: string
}

const entries = ref<HistoryEntry[]>([])
const isLoading = ref(true)
const errorMessage = ref('')

const detailOf = (log: AuditLogOut): string => {
  if (log.target_username) return `with ${log.target_username}`
  if (log.description) return log.description
  const size = log.metadata?.ciphertext_size
  return typeof size === 'number' ? formatFileSize(size) : ''
}

/**
 * The whole trail for one file.
 *
 * `GET /audit-logs/file/{id}` authorizes against the live entitlement and then returns
 * every event on the file, including ones performed by other people -- which the
 * account-wide listing deliberately does not. Nothing in the app had ever called it, so
 * "who downloaded the file I shared" was recorded and unreadable.
 */
onMounted(async () => {
  try {
    const data = unwrapData(await auditApi.listFileLogs(props.fileId))
    entries.value = (data.logs ?? []).map((log, index) => ({
      id: `${log.created_at}-${log.action}-${index}`,
      actor: auditActorLabel(log.actor_username).name,
      actorNamed: auditActorLabel(log.actor_username).named,
      action: auditActionLabel(log.action),
      detail: detailOf(log),
      summary: ` · ${auditActionLabel(log.action)}${detailOf(log) ? ` ${detailOf(log)}` : ''}`,
      at: formatSiteDateTime(log.created_at),
      succeeded: log.result === 'SUCCESS',
      isDownload: isDownloadAction(log.action),
    }))
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not load this file\'s history')
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    @click.self="emit('close')"
  >
    <div class="max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-card p-6 shadow-xl">
      <div class="flex items-center gap-2 mb-1">
        <div class="p-2 rounded-lg bg-secondary"><Activity class="h-4 w-4 text-primary" /></div>
        <h2 class="text-lg font-semibold text-foreground">Access history</h2>
      </div>
      <p translate="no" class="text-sm text-muted-foreground mb-4 [overflow-wrap:anywhere]">{{ props.filename }}</p>

      <p v-if="props.owned" class="text-xs text-muted-foreground mb-4">
        Everything that has happened to this file, including what the people you shared it
        with did.
      </p>

      <div v-if="isLoading" class="py-10 text-center text-muted-foreground">
        <Loader2 class="h-5 w-5 animate-spin mx-auto" />
      </div>

      <p v-else-if="errorMessage" class="text-sm text-destructive py-4">{{ errorMessage }}</p>

      <p v-else-if="!entries.length" class="text-sm text-muted-foreground py-4">
        Nothing recorded for this file yet.
      </p>

      <ul v-else class="max-h-80 overflow-y-auto divide-y divide-border">
        <li
          v-for="entry in entries"
          :key="entry.id"
          class="flex items-start justify-between gap-3 py-3"
        >
          <div class="min-w-0">
            <p class="text-sm text-foreground">
              <span :translate="entry.actorNamed ? 'no' : undefined" class="font-medium">{{ entry.actor }}</span>
              <!-- One interpolation, so the separators are real characters. Vue trims
                   whitespace *between* elements, which silently ran the words together. -->
              <span class="text-muted-foreground">{{ entry.summary }}</span>
            </p>
            <p class="text-xs text-muted-foreground mt-0.5">{{ entry.at }}</p>
          </div>
          <span
            v-if="!entry.succeeded"
            class="shrink-0 text-xs px-2 py-0.5 rounded-md bg-destructive/10 text-destructive"
          >
            Failed
          </span>
        </li>
      </ul>

      <button
        type="button"
        class="mt-5 w-full h-10 rounded-md border border-border hover:bg-secondary"
        @click="emit('close')"
      >
        Close
      </button>
    </div>
  </div>
</template>
