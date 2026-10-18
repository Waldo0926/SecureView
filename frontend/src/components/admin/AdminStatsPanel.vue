<script setup lang="ts">
import { AlertTriangle, ArrowRight, CheckCircle, Info, Loader2, RefreshCw } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { adminApi } from '@/api/admin_api'
import type { AdminStats } from '@/api/admin_api'
import { apiErrorMessage } from '@/api/http'
import { formatFileSize, unwrapData } from '@/api/types'
import { auditActionLabel } from '@/utils/audit-actions'
import { algorithmMix, attentionItems } from '@/utils/admin-stats'
import type { AdminTabId } from '@/utils/admin-tabs'
import { formatSiteDateTime } from '@/utils/site-time'

const emit = defineEmits<{ (e: 'navigate', tab: AdminTabId): void }>()

/**
 * The platform at a glance: how many people and files, how much is stored, how much is
 * shared, and whether anything needs attention. Counts only; names, keys and addresses stay in
 * the Users, Files and Audit tabs where the administrator already has to ask for them.
 */
const stats = ref<AdminStats | null>(null)
const loading = ref(false)
const errorMessage = ref('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    stats.value = unwrapData(await adminApi.stats())
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not load the platform statistics')
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())

const attention = computed(() => (stats.value ? attentionItems(stats.value) : []))
const mix = computed(() => (stats.value ? algorithmMix(stats.value.files.by_algorithm) : []))
const asOf = computed(() => (stats.value ? formatSiteDateTime(stats.value.generated_at) : ''))
const number = (value: number) => value.toLocaleString('en-US')
</script>

<template>
  <div data-testid="admin-stats">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-foreground">Overview</h2>
        <p class="text-sm text-muted-foreground">
          Counts only — no file names, keys or addresses.
          <span v-if="asOf">As of {{ asOf }}.</span>
        </p>
      </div>
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-secondary"
        :disabled="loading"
        @click="load()"
      >
        <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
        Refresh
      </button>
    </div>

    <p v-if="errorMessage" class="mb-3 text-sm text-destructive" role="alert">{{ errorMessage }}</p>
    <p v-if="loading && !stats" class="flex items-center gap-2 py-10 text-sm text-muted-foreground">
      <Loader2 class="h-4 w-4 animate-spin" /> Loading…
    </p>

    <template v-if="stats">
      <ul v-if="attention.length" class="mb-4 space-y-2" data-testid="admin-attention">
        <li
          v-for="item in attention"
          :key="item.id"
          class="flex flex-wrap items-start gap-x-2 gap-y-1 rounded-lg border px-3 py-2 text-sm"
          :class="item.severity === 'critical' ? 'border-destructive/40 bg-destructive/10 text-destructive' : 'border-border bg-secondary/50 text-foreground'"
        >
          <AlertTriangle v-if="item.severity === 'critical'" class="mt-0.5 h-4 w-4 shrink-0" />
          <Info v-else class="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <span class="min-w-[12rem] flex-1">{{ item.message }}</span>
          <button
            type="button"
            class="inline-flex shrink-0 items-center gap-1 whitespace-nowrap font-medium underline-offset-2 hover:underline"
            :class="item.severity === 'critical' ? 'text-destructive' : 'text-primary'"
            :data-testid="`attention-open-${item.id}`"
            @click="emit('navigate', item.tab)"
          >
            {{ item.action }}
            <ArrowRight class="h-3.5 w-3.5" />
          </button>
        </li>
      </ul>
      <p v-else class="mb-4 flex items-center gap-2 rounded-lg border border-border bg-secondary/50 px-3 py-2 text-sm text-foreground" data-testid="admin-all-clear">
        <CheckCircle class="h-4 w-4 text-success" /> Nothing needs attention: no damaged files, no failed integrity checks, no pending recovery requests.
      </p>

      <div class="grid gap-4 md:grid-cols-2">
        <section class="rounded-xl border border-border bg-card p-4" aria-labelledby="stats-users">
          <h3 id="stats-users" class="mb-3 text-sm font-semibold text-foreground">Users</h3>
          <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div><dt class="text-xs text-muted-foreground">Total accounts</dt><dd class="text-2xl font-semibold text-foreground" data-testid="stat-users-total">{{ number(stats.users.total) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Active</dt><dd class="text-2xl font-semibold text-foreground">{{ number(stats.users.active) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Disabled</dt><dd class="font-medium text-foreground">{{ number(stats.users.disabled) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Deleted</dt><dd class="font-medium text-foreground">{{ number(stats.users.deleted) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Administrators</dt><dd class="font-medium text-foreground">{{ number(stats.users.administrators) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">New in 7 days</dt><dd class="font-medium text-foreground">{{ number(stats.users.created_last_7_days) }}</dd></div>
            <div class="col-span-2"><dt class="text-xs text-muted-foreground">Signed in during the last 24 hours</dt><dd class="font-medium text-foreground">{{ number(stats.users.signed_in_last_24_hours) }}</dd></div>
          </dl>
        </section>

        <section class="rounded-xl border border-border bg-card p-4" aria-labelledby="stats-files">
          <h3 id="stats-files" class="mb-3 text-sm font-semibold text-foreground">Files</h3>
          <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div><dt class="text-xs text-muted-foreground">Encrypted files</dt><dd class="text-2xl font-semibold text-foreground" data-testid="stat-files-total">{{ number(stats.files.total) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Total stored</dt><dd class="text-2xl font-semibold text-foreground">{{ formatFileSize(stats.files.stored_bytes) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Healthy</dt><dd class="font-medium text-foreground">{{ number(stats.files.active) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Corrupted</dt><dd class="font-medium" :class="stats.files.corrupted ? 'text-destructive' : 'text-foreground'">{{ number(stats.files.corrupted) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Deleted</dt><dd class="font-medium text-foreground">{{ number(stats.files.deleted) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Uploaded in 24 hours</dt><dd class="font-medium text-foreground">{{ number(stats.files.uploaded_last_24_hours) }}</dd></div>
            <div class="col-span-2">
              <dt class="text-xs text-muted-foreground">Algorithms in use</dt>
              <dd v-if="mix.length" class="flex flex-wrap gap-x-4 text-foreground">
                <span v-for="entry in mix" :key="entry.name"><span class="font-medium">{{ entry.name }}</span> {{ number(entry.count) }}</span>
              </dd>
              <dd v-else class="text-muted-foreground">No files yet</dd>
            </div>
          </dl>
        </section>

        <section class="rounded-xl border border-border bg-card p-4" aria-labelledby="stats-sharing">
          <h3 id="stats-sharing" class="mb-3 text-sm font-semibold text-foreground">Sharing, integrity and recovery</h3>
          <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div><dt class="text-xs text-muted-foreground">Active shares</dt><dd class="text-2xl font-semibold text-foreground">{{ number(stats.shares.active_shares) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Files shared</dt><dd class="text-2xl font-semibold text-foreground">{{ number(stats.shares.files_shared) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Integrity checks, 24 hours</dt><dd class="font-medium text-foreground">{{ number(stats.integrity.checks_last_24_hours) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Failed, 24 hours</dt><dd class="font-medium" :class="stats.integrity.failed_checks_last_24_hours ? 'text-destructive' : 'text-foreground'">{{ number(stats.integrity.failed_checks_last_24_hours) }}</dd></div>
            <div class="col-span-2"><dt class="text-xs text-muted-foreground">Recovery requests awaiting review</dt><dd class="font-medium text-foreground">{{ number(stats.recovery.pending_requests) }}</dd></div>
          </dl>
        </section>

        <section class="rounded-xl border border-border bg-card p-4" aria-labelledby="stats-audit">
          <h3 id="stats-audit" class="mb-3 text-sm font-semibold text-foreground">Activity</h3>
          <dl class="grid grid-cols-3 gap-x-4 gap-y-2 text-sm">
            <div><dt class="text-xs text-muted-foreground">Events recorded</dt><dd class="text-2xl font-semibold text-foreground">{{ number(stats.audit.events_total) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Last 24 hours</dt><dd class="text-2xl font-semibold text-foreground">{{ number(stats.audit.events_last_24_hours) }}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Failed, 24 hours</dt><dd class="text-2xl font-semibold" :class="stats.audit.failures_last_24_hours ? 'text-destructive' : 'text-foreground'">{{ number(stats.audit.failures_last_24_hours) }}</dd></div>
          </dl>
          <p class="mt-3 text-xs font-medium text-muted-foreground">Most recent failed or blocked events</p>
          <ul v-if="stats.audit.recent_failures.length" class="mt-1 divide-y divide-border text-sm" data-testid="admin-recent-failures">
            <li v-for="(event, index) in stats.audit.recent_failures" :key="index" class="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5">
              <span class="text-foreground">{{ auditActionLabel(event.action) }}<span v-if="event.actor_username" translate="no" class="text-muted-foreground"> · {{ event.actor_username }}</span></span>
              <span class="text-xs text-muted-foreground">{{ formatSiteDateTime(event.created_at) }}</span>
            </li>
          </ul>
          <p v-else class="mt-1 text-sm text-muted-foreground">None recorded.</p>
        </section>
      </div>
    </template>
  </div>
</template>
