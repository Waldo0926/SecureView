<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, Search } from 'lucide-vue-next'

import { adminApi, type AdminFileOut, type AdminFileStatusFilter } from '@/api/admin_api'
import { apiErrorMessage } from '@/api/http'
import { formatFileSize, unwrapData } from '@/api/types'
import { matchesSearch, statusBadgeClass } from '@/utils/admin-lists'
import { formatSiteDateTime } from '@/utils/site-time'

const files = ref<AdminFileOut[]>([])
const isLoading = ref(false)
const errorMessage = ref('')
const hasMore = ref(false)
const offset = ref(0)
const LIMIT = 50

// Deleted files stay as tombstones and soon outnumber live ones, so the default view leaves
// them out. "Corrupted" is the one an administrator most needs to find.
const statusFilter = ref<AdminFileStatusFilter | 'ALL'>('CURRENT')
const filters: { value: AdminFileStatusFilter | 'ALL'; label: string }[] = [
  { value: 'CURRENT', label: 'Current' },
  { value: 'ACTIVE', label: 'Healthy' },
  { value: 'CORRUPTED', label: 'Corrupted' },
  { value: 'DELETED', label: 'Deleted' },
  { value: 'ALL', label: 'All' },
]
const search = ref('')
const visibleFiles = computed(() =>
  files.value.filter((file) => matchesSearch(search.value, file.original_filename, file.owner_username)),
)

function setFilter(value: AdminFileStatusFilter | 'ALL') {
  statusFilter.value = value
  void load()
}

function formatTimestamp(value: string): string {
  return formatSiteDateTime(value)
}

async function load(reset = true) {
  isLoading.value = true
  errorMessage.value = ''
  if (reset) offset.value = 0
  try {
    const status = statusFilter.value === 'ALL' ? undefined : statusFilter.value
    const data = unwrapData(await adminApi.listFiles({ limit: LIMIT, offset: offset.value, status }))
    files.value = reset ? data.files : [...files.value, ...data.files]
    hasMore.value = data.has_more
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Failed to load files')
  } finally {
    isLoading.value = false
  }
}

async function loadMore() {
  offset.value += LIMIT
  await load(false)
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-foreground">Files</h2>
        <p class="text-sm text-muted-foreground">
          Names, owners and sizes only. Files are encrypted in the owner’s browser, so no
          administrator can open them.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-secondary"
        :disabled="isLoading"
        @click="load()"
      >
        <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': isLoading }" />
        Refresh
      </button>
    </div>

    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
        <button
          v-for="filter in filters"
          :key="filter.value"
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition-colors"
          :class="
            statusFilter === filter.value
              ? 'border-primary bg-primary/10 font-medium text-primary'
              : 'border-border text-muted-foreground hover:bg-secondary hover:text-foreground'
          "
          :aria-pressed="statusFilter === filter.value"
          :data-testid="`files-filter-${filter.value}`"
          @click="setFilter(filter.value)"
        >
          {{ filter.label }}
        </button>
      </div>
      <label class="relative block w-full sm:w-64">
        <span class="sr-only">Search files</span>
        <Search class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="search"
          type="search"
          placeholder="Search by name or owner"
          class="h-9 w-full rounded-md border border-border bg-background pl-8 pr-3 text-sm outline-none focus:border-primary"
        />
      </label>
    </div>

    <p v-if="errorMessage" class="mb-3 text-sm text-destructive" role="alert">{{ errorMessage }}</p>

    <div v-if="isLoading && !files.length" class="py-10 text-center text-sm text-muted-foreground">
      Loading files…
    </div>
    <div v-else-if="!visibleFiles.length" class="py-10 text-center text-sm text-muted-foreground">
      {{ search ? 'No loaded file matches that search.' : 'No files with this status.' }}
    </div>
    <div v-else class="overflow-x-auto rounded-xl border border-border">
      <table class="w-full min-w-[44rem] text-left text-sm">
        <thead class="border-b border-border bg-secondary/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th class="px-4 py-3 font-medium">Filename</th>
            <th class="px-4 py-3 font-medium">Owner</th>
            <th class="px-4 py-3 font-medium">Size</th>
            <th class="px-4 py-3 font-medium">Status</th>
            <th class="px-4 py-3 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="file in visibleFiles"
            :key="file.file_id"
            class="border-b border-border last:border-0"
            :class="{ 'opacity-60': file.status === 'DELETED' }"
          >
            <td translate="no" class="max-w-[16rem] truncate px-4 py-3 font-medium text-foreground" :title="file.original_filename">
              {{ file.original_filename }}
            </td>
            <td translate="no" class="px-4 py-3 text-muted-foreground">{{ file.owner_username }}</td>
            <td class="px-4 py-3 text-muted-foreground">{{ formatFileSize(file.file_size) }}</td>
            <td class="px-4 py-3">
              <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(file.status)">
                {{ file.status }}
              </span>
            </td>
            <td class="px-4 py-3 text-muted-foreground">{{ formatTimestamp(file.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="mt-4 flex items-center justify-between text-xs text-muted-foreground">
      <span>
        Showing {{ visibleFiles.length }} of {{ files.length }} loaded{{ hasMore ? '; more below' : '' }}.
        <template v-if="search">Search covers the loaded files.</template>
      </span>
      <button
        v-if="hasMore"
        type="button"
        class="h-9 rounded-md border border-border px-4 text-sm text-foreground hover:bg-secondary disabled:opacity-50"
        :disabled="isLoading"
        @click="loadMore"
      >
        Load more
      </button>
    </div>
  </div>
</template>
