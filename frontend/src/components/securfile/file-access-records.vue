<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/securfile/PageHeader.vue'
import { Activity, AlertTriangle, ChevronDown, ChevronUp, Clock, Download, FileIcon, Filter, RefreshCw, Share2, User } from 'lucide-vue-next'
import { auditApi, type AuditLogFilters } from '@/api/audit_api'
import { apiErrorMessage } from '@/api/http'
import { formatFileSize, unwrapData, type AuditLogOut } from '@/api/types'
import { useAuthStore } from '@/stores/auth_store'
import {
  auditActionLabel,
  auditActionOptions,
  auditActorLabel,
  auditFileLabel,
  auditSubjectFileId,
  isDownloadAction,
  isShareAction,
} from '@/utils/audit-actions'
import {
  EMPTY_AUDIT_FILTERS,
  fetchAuditPage,
  hasAuditFilters,
  toAuditLogFilters,
  type AuditFilterForm,
} from '@/utils/audit-trail'
import { formatSiteDateTime } from '@/utils/site-time'

interface AccessEvent {
  id: string
  /** Who did it. The API sends the username; only an admin ever sees anyone else's. */
  actor: string
  /** `actor` is a real username (never translated), not "System (server script)". */
  actorNamed: boolean
  accessTime: string
  /** Human label, e.g. "Downloaded". */
  action: string
  isDownload: boolean
  /** Sharing or revoking -- an action that changed who can reach the file. */
  isShare: boolean
  /** SUCCESS, or the failure this row records. */
  succeeded: boolean
  /** "Shared with junyan", the size uploaded -- whatever this action has worth saying. */
  detail: string
}

interface AuditGroup {
  id: string
  name: string
  /** The file was deleted since; its name is still known (a soft delete). */
  isDeleted: boolean
  /** `name` is the person's own file name, which is never translated. */
  named: boolean
  /** Account-level rows (sign-in, key changes) belong to no file and say so. */
  isAccount: boolean
  sharedAt: string
  totalDownloads: number
  totalShares: number
  accessHistory: AccessEvent[]
}

interface StatCard {
  key: 'totalFiles' | 'totalDownloads' | 'totalShares' | 'uniqueUsers'
  label: string
  icon: typeof FileIcon
  wrapperClass: string
  iconClass: string
}

const logs = ref<AuditLogOut[]>([])
const isLoading = ref(false)
const errorMessage = ref('')
const expanded = ref<string[]>([])
const chainState = ref<'unknown' | 'valid' | 'invalid' | 'unavailable'>('unknown')
const chainCheckedEntries = ref(0)
const auth = useAuthStore()

const ACCOUNT_GROUP = 'account'

/** Same locale rendering the file list uses, so timestamps read alike across the app. */
const formatTimestamp = (value: string | null | undefined): string => {
  if (!value) return '-'
  return formatSiteDateTime(value)
}

/** Whatever this particular action has worth saying beyond its name. */
const detailOf = (log: AuditLogOut): string => {
  if (log.target_username) return `with ${log.target_username}`
  if (log.description) return log.description
  const size = log.metadata?.ciphertext_size
  return typeof size === 'number' ? formatFileSize(size) : ''
}

const mapLogToEvent = (log: AuditLogOut, index: number): AccessEvent => ({
  id: `${log.created_at}-${log.action}-${index}`,
  actor: auditActorLabel(log.actor_username).name,
  actorNamed: auditActorLabel(log.actor_username).named,
  accessTime: formatTimestamp(log.created_at),
  action: auditActionLabel(log.action),
  isDownload: isDownloadAction(log.action),
  isShare: isShareAction(log.action),
  succeeded: log.result === 'SUCCESS',
  detail: detailOf(log),
})

const groups = computed<AuditGroup[]>(() => {
  const grouped = new Map<string, AuditGroup>()
  for (const [index, log] of logs.value.entries()) {
    // Signing in, changing a passphrase and closing an account are about the account, not
    // about any file. They used to fall into a single group labelled with a file id they
    // never had; they get their own heading now.
    const fileId = auditSubjectFileId(log)
    const key = fileId ?? ACCOUNT_GROUP
    const event = mapLogToEvent(log, index)
    const existing = grouped.get(key)
    if (existing) {
      existing.accessHistory.push(event)
      if (event.isDownload) existing.totalDownloads += 1
      if (event.isShare) existing.totalShares += 1
    } else {
      grouped.set(key, {
        id: key,
        name: fileId ? auditFileLabel(log).name : 'Account activity',
        isDeleted: fileId ? auditFileLabel(log).deleted : false,
        named: fileId ? auditFileLabel(log).named : false,
        isAccount: fileId === null,
        sharedAt: formatTimestamp(log.created_at),
        totalDownloads: event.isDownload ? 1 : 0,
        totalShares: event.isShare ? 1 : 0,
        accessHistory: [event],
      })
    }
  }
  // Account activity first (sign-ins, passphrase and key changes), then the file records.
  // Someone checking whether their account was misused looks here before anything else.
  return Array.from(grouped.values()).sort(
    (a, b) => Number(b.isAccount) - Number(a.isAccount),
  )
})

const stats = computed(() => ({
  totalFiles: groups.value.filter((group) => !group.isAccount).length,
  totalDownloads: groups.value.reduce((sum, f) => sum + f.totalDownloads, 0),
  totalShares: groups.value.reduce((sum, f) => sum + f.totalShares, 0),
  // Was counting row ids, so it only ever restated the number of log entries.
  uniqueUsers: new Set(groups.value.flatMap((f) => f.accessHistory.map((u) => u.actor))).size,
}))

const statCards: StatCard[] = [
  { key: 'totalFiles', label: 'Tracked Files', icon: FileIcon, wrapperClass: 'bg-secondary', iconClass: 'text-foreground' },
  { key: 'totalDownloads', label: 'Downloads', icon: Download, wrapperClass: 'bg-secondary', iconClass: 'text-foreground' },
  { key: 'totalShares', label: 'Shares', icon: Share2, wrapperClass: 'bg-secondary', iconClass: 'text-foreground' },
  { key: 'uniqueUsers', label: 'Unique Users', icon: User, wrapperClass: 'bg-secondary', iconClass: 'text-foreground' },
]

/**
 * The filter bar, in two halves.
 *
 * `filterForm` is what the controls hold while the person is still choosing; `appliedFilters`
 * is what the last Apply sent. Typing in the keyword box must not refetch on every keystroke,
 * and the "no events match" message has to describe the filters that produced the page, not
 * the ones half-typed since.
 */
const filterForm = ref<AuditFilterForm>({ ...EMPTY_AUDIT_FILTERS })
const appliedFilters = ref<AuditLogFilters>({})
const filtersActive = computed(() => Object.keys(appliedFilters.value).length > 0)
const actionOptions = auditActionOptions()

/** The server has rows after the ones loaded; Load more asks for the next page of them. */
const hasMore = ref(false)
const isLoadingMore = ref(false)

/**
 * Numbers each request, so only the newest one may change the list. Pressing Apply twice, or
 * Apply while Load more was still waiting, let an older answer land last: the wrong filter's
 * rows, or an old page appended to the new results.
 */
let requestSeq = 0

/**
 * The first page for the applied filters.
 *
 * The page used to walk the whole trail before drawing anything: ten requests and a
 * thousand rows on a long-lived account, and a hard stop at a thousand with no way past it.
 * Now one page (100 rows, the server's cap) loads, and the next only when asked.
 */
const loadLogs = async () => {
  const seq = ++requestSeq
  isLoading.value = true
  // Any Load more still waiting is now stale and will be dropped when it answers.
  isLoadingMore.value = false
  errorMessage.value = ''
  try {
    const page = await fetchAuditPage(appliedFilters.value, 0)
    if (seq !== requestSeq) return
    logs.value = page.logs
    hasMore.value = page.hasMore
  } catch (error) {
    if (seq !== requestSeq) return
    errorMessage.value = apiErrorMessage(error, 'Failed to load audit logs')
  } finally {
    if (seq === requestSeq) isLoading.value = false
  }
}

const loadMore = async () => {
  // Not while a first page is loading: its offset would count rows that are about to go.
  if (isLoading.value || isLoadingMore.value || !hasMore.value) return
  const seq = ++requestSeq
  isLoadingMore.value = true
  errorMessage.value = ''
  try {
    // Offset by what is on screen, so a page that came back short still lines up.
    const page = await fetchAuditPage(appliedFilters.value, logs.value.length)
    if (seq !== requestSeq) return
    logs.value = [...logs.value, ...page.logs]
    hasMore.value = page.hasMore
  } catch (error) {
    if (seq !== requestSeq) return
    errorMessage.value = apiErrorMessage(error, 'Failed to load more audit logs')
  } finally {
    if (seq === requestSeq) isLoadingMore.value = false
  }
}

/** Apply what the bar holds and start again from the first page. */
const applyFilters = () => {
  const { from, to } = filterForm.value
  if (from && to && from > to) {
    errorMessage.value = 'The start date is after the end date.'
    return
  }
  appliedFilters.value = toAuditLogFilters(filterForm.value)
  loadLogs()
}

const clearFilters = () => {
  filterForm.value = { ...EMPTY_AUDIT_FILTERS }
  appliedFilters.value = {}
  loadLogs()
}

const canClear = computed(() => filtersActive.value || hasAuditFilters(filterForm.value))

/**
 * Verify the tamper-evident chain, for administrators only.
 *
 * `POST /audit-logs/verify-chain` is ADMIN-only and recomputes every hash in the table. The page
 * used to call it for everyone and hide the refusal, but the refusal was still a 403 in the
 * console on every visit. It is now not called at all for anyone else, so an ordinary user's
 * history loads with no failed request.
 *
 * An actual INVALID result is the opposite -- it is the single most important thing this
 * page can say -- so it is kept distinct from both.
 */
const verifyChain = async () => {
  try {
    const data = unwrapData(await auditApi.verifyChain())
    chainState.value = data.valid ? 'valid' : 'invalid'
    chainCheckedEntries.value = data.checked_entries ?? 0
  } catch {
    chainState.value = 'unavailable'
  }
}

onMounted(async () => {
  loadLogs()
  // The role is known once the account has loaded; it may not be on a first visit.
  await auth.loadUser().catch(() => undefined)
  if (auth.isAdmin) verifyChain()
})

const toggle = (id: string) => {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((x) => x !== id)
    : [...expanded.value, id]
}
</script>

<template>
  <section id="access-records" class="product-page">
    <div class="page-container">
      <PageHeader title="Activity Log" subtitle="What happened on your account and who accessed your files, as recorded by the audit log">
        <template #actions>
          <button class="h-10 px-4 inline-flex items-center gap-2 rounded-md border border-border bg-card hover:bg-secondary" @click="loadLogs">
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': isLoading }" />
            Refresh
          </button>
          <span v-if="chainState === 'valid'" class="inline-flex items-center gap-1.5 rounded-md bg-success-soft px-2.5 py-1 font-mono text-xs text-success">
            <span aria-hidden="true">●</span>
            Hash chain verified · {{ chainCheckedEntries }} entries
          </span>
          <span
            v-else-if="chainState === 'invalid'"
            class="text-sm font-medium text-destructive inline-flex items-center gap-1"
          >
            <AlertTriangle class="h-4 w-4" />
            Hash chain broken — this log has been altered
          </span>
        </template>
      </PageHeader>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-2">
        <div v-for="card in statCards" :key="card.key" class="bg-card border border-border rounded-xl p-4">
          <div class="flex items-center gap-3">
            <div class="p-2 rounded-lg" :class="card.wrapperClass">
              <component :is="card.icon" class="h-5 w-5" :class="card.iconClass" />
            </div>
            <div>
              <p class="text-2xl font-semibold tracking-tight text-foreground">{{ stats[card.key] }}</p>
              <p class="text-xs text-muted-foreground">{{ card.label }}</p>
            </div>
          </div>
        </div>
      </div>

      <p v-if="logs.length" class="mb-4 text-xs text-muted-foreground" data-testid="records-totals-note">
        <template v-if="filtersActive">Totals cover the {{ logs.length }} loaded events that match the filters.</template>
        <template v-else>Totals cover the {{ logs.length }} loaded events.</template>
      </p>

      <form
        class="mt-2 mb-6 rounded-xl border border-border bg-card p-4"
        aria-label="Filter events"
        data-testid="records-filters"
        @submit.prevent="applyFilters"
      >
        <div class="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><Filter class="h-4 w-4" /><span>Filter events</span></div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            Event type
            <select v-model="filterForm.action" class="h-10 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground" data-testid="records-filter-action">
              <option value="">All event types</option>
              <option v-for="option in actionOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            Result
            <select v-model="filterForm.result" class="h-10 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground" data-testid="records-filter-result">
              <option value="">All results</option>
              <option value="SUCCESS">Success</option>
              <option value="FAIL">Failed</option>
            </select>
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            From
            <input v-model="filterForm.from" type="date" :max="filterForm.to || undefined" class="h-10 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground" data-testid="records-filter-from" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            To
            <input v-model="filterForm.to" type="date" :min="filterForm.from || undefined" class="h-10 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground" data-testid="records-filter-to" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            Keyword
            <input
              v-model="filterForm.q"
              type="search"
              maxlength="100"
              placeholder="Search descriptions and file names"
              class="h-10 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground placeholder:text-muted-foreground"
              data-testid="records-filter-q"
            />
          </label>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <button type="submit" class="h-10 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90" data-testid="records-filter-apply">
            Apply
          </button>
          <button
            type="button"
            class="h-10 rounded-md border border-border bg-card px-4 text-sm hover:bg-secondary disabled:opacity-50"
            :disabled="!canClear"
            data-testid="records-filter-clear"
            @click="clearFilters"
          >
            Clear
          </button>
        </div>
      </form>

      <p v-if="errorMessage" class="text-center text-sm text-destructive mb-4">{{ errorMessage }}</p>
      <p v-if="groups.length" class="mb-4 flex items-center gap-2 text-sm text-muted-foreground" data-testid="records-hint">
        <ChevronDown class="h-4 w-4 shrink-0" />
        Select an entry below to open its full history: your account activity, or who uploaded, shared or downloaded a file, and when.
      </p>

      <div v-if="isLoading && !groups.length" class="text-center py-12 text-muted-foreground">
        Loading audit logs...
      </div>

      <div v-else-if="!groups.length && filtersActive" class="text-center py-12 text-muted-foreground max-w-xl mx-auto" data-testid="records-empty-filtered">
        No events match these filters. Clear them to see everything.
      </div>

      <div v-else-if="!groups.length" class="text-center py-12 text-muted-foreground max-w-xl mx-auto" data-testid="records-empty">
        No audit logs yet. Actions such as upload, download, and share will appear here.
      </div>

      <div v-else class="space-y-3">
        <article v-for="file in groups" :key="file.id" class="bg-card border border-border rounded-xl overflow-hidden">
          <button
            class="w-full p-4 text-left hover:bg-secondary/40 transition-colors"
            :aria-expanded="expanded.includes(file.id)"
            @click="toggle(file.id)"
          >
            <div class="flex items-center justify-between gap-4">
              <!-- min-w-0 and overflow-wrap let a long file name wrap instead of pushing a 360 px
                   phone sideways. -->
              <div class="flex min-w-0 items-center gap-4">
                <div class="shrink-0 p-3 rounded-lg bg-secondary">
                  <User v-if="file.isAccount" class="h-5 w-5 text-muted-foreground" />
                  <FileIcon v-else class="h-5 w-5 text-muted-foreground" />
                </div>
                <div class="min-w-0">
                  <h3 class="text-base text-foreground">
                    <span :translate="file.named ? 'no' : undefined" class="[overflow-wrap:anywhere]">{{ file.name }}</span>
                    <span
                      v-if="file.isDeleted && !file.isAccount"
                      class="ml-2 rounded-md bg-secondary px-2 py-0.5 text-xs font-medium text-muted-foreground"
                      data-testid="records-deleted"
                    >Deleted</span>
                  </h3>
                  <p class="text-sm text-muted-foreground flex items-center gap-2 mt-1"><Clock class="h-3 w-3" /> Last activity {{ file.sharedAt }}</p>
                </div>
              </div>
              <div class="flex shrink-0 items-center gap-4 text-sm text-muted-foreground">
                <span class="hidden items-center gap-1 md:inline-flex" title="Downloads"><Download class="h-4 w-4" /> {{ file.totalDownloads }}</span>
                <span class="hidden items-center gap-1 md:inline-flex" title="People involved"><User class="h-4 w-4" /> {{ new Set(file.accessHistory.map((e) => e.actor)).size }}</span>
                <span class="inline-flex items-center gap-1 text-xs font-medium text-foreground" data-testid="records-toggle">
                  <span class="hidden sm:inline">{{ expanded.includes(file.id) ? 'Hide history' : 'View history' }}</span>
                  <component :is="expanded.includes(file.id) ? ChevronUp : ChevronDown" class="h-4 w-4" />
                </span>
              </div>
            </div>
          </button>

          <div v-if="expanded.includes(file.id)" class="border-t border-border p-4">
            <div class="flex items-center gap-2 text-sm text-muted-foreground mb-4"><Activity class="h-4 w-4" /><span>Recent Access History</span></div>
            <div class="space-y-3">
              <div
                v-for="event in file.accessHistory"
                :key="event.id"
                class="flex items-start justify-between gap-4 p-3 rounded-lg bg-secondary/50"
              >
                <div class="min-w-0">
                  <p class="text-sm font-medium text-foreground">
                    {{ event.action }}
                    <span v-if="event.detail" class="font-normal text-muted-foreground">
                      {{ event.detail }}
                    </span>
                  </p>
                  <p class="mt-0.5 font-mono text-xs text-muted-foreground">
                    <span :translate="event.actorNamed ? 'no' : undefined">{{ event.actor }}</span>
                    <span translate="no">{{ ` · ${event.accessTime}` }}</span>
                  </p>
                </div>
                <span
                  v-if="!event.succeeded"
                  class="shrink-0 rounded-md bg-destructive-soft px-2 py-0.5 text-xs text-destructive"
                >
                  Failed
                </span>
              </div>
            </div>
          </div>
        </article>
      </div>

      <div v-if="logs.length" class="mt-6 flex flex-col items-center gap-3" data-testid="records-paging">
        <p class="text-sm text-muted-foreground">
          <template v-if="hasMore">Showing {{ logs.length }} events, more available</template>
          <template v-else>Showing all {{ logs.length }} events</template>
        </p>
        <button
          v-if="hasMore"
          type="button"
          class="h-10 inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 text-sm hover:bg-secondary disabled:opacity-50"
          :disabled="isLoadingMore || isLoading"
          data-testid="records-load-more"
          @click="loadMore"
        >
          <RefreshCw v-if="isLoadingMore" class="h-4 w-4 animate-spin" />
          <template v-if="isLoadingMore">Loading more...</template>
          <template v-else>Load more</template>
        </button>
      </div>
    </div>
  </section>
</template>
