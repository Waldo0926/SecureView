<script setup lang="ts">
import { AlertTriangle, CheckCircle, Loader2, RefreshCw, ScanSearch } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { adminApi } from '@/api/admin_api'
import type { AdminIntegrityReport } from '@/api/admin_api'
import { apiErrorMessage } from '@/api/http'
import { unwrapData } from '@/api/types'
import { findingText, restoreCommand, scanSummary } from '@/utils/integrity-report'
import { formatSiteDateTime } from '@/utils/site-time'

/**
 * Is the stored ciphertext still what was uploaded? Every stored object is compared with the
 * SHA-256 recorded for it. Nothing here reads plaintext or a key, and nothing here changes an
 * object: putting a damaged one back needs the offline backup key, so it is a deliberate step
 * on the server (docs/BACKUP_AND_RECOVERY.md, "Restoring one damaged file").
 */
const report = ref<AdminIntegrityReport | null>(null)
const loading = ref(false)
const scanning = ref(false)
const errorMessage = ref('')
const scanMessage = ref('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    report.value = unwrapData(await adminApi.integrityReport())
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not load the integrity report')
  } finally {
    loading.value = false
  }
}

async function scanNow() {
  scanning.value = true
  errorMessage.value = ''
  scanMessage.value = ''
  try {
    scanMessage.value = scanSummary(unwrapData(await adminApi.scanIntegrity()))
    await load()
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'The integrity scan failed')
  } finally {
    scanning.value = false
  }
}

onMounted(() => void load())

const asOf = (value: string | null) => (value ? formatSiteDateTime(value) : '')
const coverage = computed(() => report.value?.coverage ?? null)
</script>

<template>
  <div data-testid="admin-integrity">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-foreground">Integrity</h2>
        <p class="text-sm text-muted-foreground">
          Stored ciphertext is compared with the SHA-256 recorded at upload. Nothing here reads
          file contents.
        </p>
      </div>
      <div class="flex gap-2">
        <button
          type="button"
          class="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-secondary"
          :disabled="loading || scanning"
          @click="load()"
        >
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
          Refresh
        </button>
        <button
          type="button"
          class="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          :disabled="loading || scanning"
          data-testid="integrity-scan"
          @click="scanNow()"
        >
          <Loader2 v-if="scanning" class="h-4 w-4 animate-spin" />
          <ScanSearch v-else class="h-4 w-4" />
          {{ scanning ? 'Scanning…' : 'Scan now' }}
        </button>
      </div>
    </div>

    <p v-if="errorMessage" class="mb-3 text-sm text-destructive" role="alert">{{ errorMessage }}</p>
    <p v-if="scanMessage" class="mb-3 rounded-lg border border-border bg-secondary/50 px-3 py-2 text-sm text-foreground" role="status" data-testid="integrity-scan-result">
      {{ scanMessage }}
    </p>
    <p v-if="loading && !report" class="flex items-center gap-2 py-10 text-sm text-muted-foreground">
      <Loader2 class="h-4 w-4 animate-spin" /> Loading…
    </p>

    <template v-if="report && coverage">
      <dl class="mb-5 grid gap-3 sm:grid-cols-3" data-testid="integrity-coverage">
        <div class="rounded-lg border border-border bg-card p-3">
          <dt class="text-xs text-muted-foreground">Files that can be checked</dt>
          <dd class="text-xl font-semibold text-foreground">{{ coverage.candidates.toLocaleString('en-US') }}</dd>
        </div>
        <div class="rounded-lg border border-border bg-card p-3">
          <dt class="text-xs text-muted-foreground">Checked in the last 24 hours</dt>
          <dd class="text-xl font-semibold text-foreground">{{ coverage.checked_last_24_hours.toLocaleString('en-US') }}</dd>
        </div>
        <div class="rounded-lg border border-border bg-card p-3">
          <dt class="text-xs text-muted-foreground">Never checked</dt>
          <dd class="text-xl font-semibold" :class="coverage.never_checked ? 'text-foreground' : 'text-success'">
            {{ coverage.never_checked.toLocaleString('en-US') }}
          </dd>
        </div>
      </dl>

      <p class="mb-5 text-sm text-muted-foreground" data-testid="integrity-last-sweep">
        <template v-if="coverage.last_sweep_at">Last scan: {{ asOf(coverage.last_sweep_at) }}.</template>
        <template v-else>
          No scan has been recorded yet. Use “Scan now”. The server also scans every day and records
          each run here, so tampering with a file nobody opens is still found.
        </template>
      </p>

      <p
        v-if="!report.damaged.length"
        class="flex items-center gap-2 rounded-lg border border-border bg-secondary/50 px-3 py-3 text-sm text-foreground"
        data-testid="integrity-clean"
      >
        <CheckCircle class="h-4 w-4 text-success" /> No damaged files on record.
      </p>

      <ul v-else class="space-y-3" data-testid="integrity-damaged">
        <li
          v-for="file in report.damaged"
          :key="file.file_id"
          class="rounded-lg border border-destructive/40 bg-destructive/5 p-4"
          data-testid="integrity-damaged-file"
        >
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="flex items-center gap-2 font-medium text-foreground">
                <AlertTriangle class="h-4 w-4 shrink-0 text-destructive" />
                <span translate="no" class="[overflow-wrap:anywhere]">{{ file.original_filename }}</span>
              </p>
              <p class="mt-1 text-xs text-muted-foreground">
                Owner {{ file.owner_username }} · status {{ file.status }}
                <template v-if="file.last_checked_at"> · last checked {{ asOf(file.last_checked_at) }}</template>
              </p>
            </div>
            <span class="rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-medium text-destructive">
              {{ file.last_result ?? file.status }}
            </span>
          </div>
          <p class="mt-2 text-sm text-foreground">{{ findingText(file.last_result) }}</p>
          <details class="mt-3 text-sm">
            <summary class="cursor-pointer text-primary">How to put the original back</summary>
            <ol class="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground">
              <li>On the server, paste this as it is. It reads the newest nightly backup that still holds the original and changes nothing:</li>
            </ol>
            <code class="mt-2 block overflow-x-auto rounded-md bg-secondary px-3 py-2 text-xs text-foreground">{{ restoreCommand(file.file_id) }}</code>
            <ol class="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground" start="2">
              <li>If it reports <code>dry_run_would_restore</code>, run it again with <code>--apply</code>:</li>
            </ol>
            <code class="mt-2 block overflow-x-auto rounded-md bg-secondary px-3 py-2 text-xs text-foreground">{{ restoreCommand(file.file_id, true) }}</code>
            <p class="mt-2 text-muted-foreground">
              The damaged bytes are kept in quarantine, the original is put back, the file is
              re-verified and the restore is written to the audit chain. A file uploaded after the
              last nightly backup is not in any backup yet. If the server's own backups are gone or
              suspect, add <code>--backup-set</code> and <code>--private-key</code> for an encrypted
              off-site set; the key custodian brings the key.
            </p>
          </details>
        </li>
      </ul>
      <p v-if="report.has_more" class="mt-3 text-xs text-muted-foreground">
        More damaged files exist than are listed here; restore these first, then refresh.
      </p>
    </template>
  </div>
</template>
