<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loader2, PanelRightOpen, RefreshCw, Search, UserCheck, UserX } from 'lucide-vue-next'

import { adminApi, type AdminUserOut, type AdminUserStatusFilter } from '@/api/admin_api'
import { apiErrorCode, apiErrorMessage } from '@/api/http'
import { unwrapData } from '@/api/types'
import { useAuthStore } from '@/stores/auth_store'
import { matchesSearch, statusBadgeClass } from '@/utils/admin-lists'
import AdminUserDialog from '@/components/admin/AdminUserDialog.vue'
import { formatSiteDateTime } from '@/utils/site-time'

const auth = useAuthStore()
const users = ref<AdminUserOut[]>([])
const isLoading = ref(false)
const errorMessage = ref('')
const actionMessage = ref('')
const busyUserId = ref<string | null>(null)
/** The account whose Disable was clicked once and now asks for confirmation. */
const confirmingUserId = ref<string | null>(null)
const hasMore = ref(false)
const offset = ref(0)
const LIMIT = 50

// Deleted accounts stay as tombstones and soon outnumber live ones, so the default view leaves
// them out.
const statusFilter = ref<AdminUserStatusFilter | 'ALL'>('CURRENT')
const filters: { value: AdminUserStatusFilter | 'ALL'; label: string }[] = [
  { value: 'CURRENT', label: 'Current' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'DISABLED', label: 'Disabled' },
  { value: 'DELETED', label: 'Deleted' },
  { value: 'ALL', label: 'All' },
]
const search = ref('')
/** The account whose details dialog is open. */
const openUserId = ref<string | null>(null)

const visibleUsers = computed(() =>
  users.value.filter((user) => matchesSearch(search.value, user.username, user.email, user.role)),
)

function formatTimestamp(value: string | null): string {
  if (!value) return 'Never'
  return formatSiteDateTime(value)
}

const isSelf = (user: AdminUserOut) => user.user_id === auth.user?.id

async function load(reset = true) {
  isLoading.value = true
  errorMessage.value = ''
  confirmingUserId.value = null
  if (reset) offset.value = 0
  try {
    const status = statusFilter.value === 'ALL' ? undefined : statusFilter.value
    const data = unwrapData(await adminApi.listUsers({ limit: LIMIT, offset: offset.value, status }))
    users.value = reset ? data.users : [...users.value, ...data.users]
    hasMore.value = data.has_more
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Failed to load users')
  } finally {
    isLoading.value = false
  }
}

function setFilter(value: AdminUserStatusFilter | 'ALL') {
  statusFilter.value = value
  void load()
}

async function loadMore() {
  offset.value += LIMIT
  await load(false)
}

async function setEnabled(user: AdminUserOut, enabled: boolean) {
  busyUserId.value = user.user_id
  confirmingUserId.value = null
  actionMessage.value = ''
  errorMessage.value = ''
  try {
    const data = unwrapData(
      await (enabled ? adminApi.enableUser(user.user_id) : adminApi.disableUser(user.user_id)),
    )
    user.status = data.status
    actionMessage.value = enabled
      ? `Enabled ${user.username}.`
      : `Disabled ${user.username}; signed out of ${data.revoked_sessions} session${data.revoked_sessions === 1 ? '' : 's'}.`
  } catch (error) {
    // Only reachable when this administrator was disabled a moment ago by the one they are
    // now disabling: the server will not leave the platform with no active administrator.
    errorMessage.value =
      apiErrorCode(error) === 'last_admin'
        ? `Disabling ${user.username} would leave no active administrator, so it was not disabled.`
        : apiErrorMessage(error, `Could not update ${user.username}`)
  } finally {
    busyUserId.value = null
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-foreground">Users</h2>
        <p class="text-sm text-muted-foreground">
          Open an account to see what it holds or reset its login password. Disable stops it signing in
          and ends every session it has open.
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
          :data-testid="`users-filter-${filter.value}`"
          @click="setFilter(filter.value)"
        >
          {{ filter.label }}
        </button>
      </div>
      <label class="relative block w-full sm:w-64">
        <span class="sr-only">Search users</span>
        <Search class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="search"
          type="search"
          placeholder="Search by username or email"
          class="h-9 w-full rounded-md border border-border bg-background pl-8 pr-3 text-sm outline-none focus:border-primary"
        />
      </label>
    </div>

    <p v-if="actionMessage" class="mb-3 text-sm text-muted-foreground" role="status">{{ actionMessage }}</p>
    <p v-if="errorMessage" class="mb-3 text-sm text-destructive" role="alert">{{ errorMessage }}</p>

    <div v-if="isLoading && !users.length" class="py-10 text-center text-sm text-muted-foreground">
      Loading users…
    </div>
    <div v-else-if="!visibleUsers.length" class="py-10 text-center text-sm text-muted-foreground">
      {{ search ? 'No loaded account matches that search.' : 'No accounts with this status.' }}
    </div>
    <div v-else class="overflow-x-auto rounded-xl border border-border">
      <table class="w-full min-w-[56rem] text-left text-sm">
        <thead class="border-b border-border bg-secondary/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th class="px-4 py-3 font-medium">Username</th>
            <th class="px-4 py-3 font-medium">Email</th>
            <th class="px-4 py-3 font-medium">Role</th>
            <th class="px-4 py-3 font-medium">Status</th>
            <th class="px-4 py-3 font-medium">Created</th>
            <th class="px-4 py-3 font-medium">Last sign-in</th>
            <th class="px-4 py-3 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="user in visibleUsers"
            :key="user.user_id"
            class="border-b border-border last:border-0"
            :class="{ 'opacity-60': user.status === 'DELETED' }"
          >
            <td class="px-4 py-3 font-medium text-foreground">
              <button
                type="button"
                translate="no"
                class="text-left underline-offset-4 hover:underline"
                @click="openUserId = user.user_id"
              >
                {{ user.username }}
              </button>
              <span v-if="isSelf(user)" class="ml-1 text-xs font-normal text-muted-foreground">(you)</span>
            </td>
            <td translate="no" class="max-w-[16rem] truncate px-4 py-3 text-muted-foreground" :title="user.email ?? ''">
              {{ user.email ?? '—' }}
            </td>
            <td class="px-4 py-3">
              <span
                v-if="user.role !== 'USER'"
                class="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-foreground"
              >
                {{ user.role === 'RECOVERY_OFFICER' ? 'Recovery officer' : 'Admin' }}
              </span>
              <span v-else class="text-muted-foreground">User</span>
            </td>
            <td class="px-4 py-3">
              <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(user.status)">
                {{ user.status }}
              </span>
            </td>
            <td class="px-4 py-3 text-muted-foreground">{{ formatTimestamp(user.created_at) }}</td>
            <td class="px-4 py-3 text-muted-foreground">{{ formatTimestamp(user.last_login_at) }}</td>
            <td class="whitespace-nowrap px-4 py-3 text-right">
              <button
                type="button"
                class="mr-1 inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-secondary"
                :data-testid="`users-details-${user.username}`"
                @click="openUserId = user.user_id"
              >
                <PanelRightOpen class="h-3.5 w-3.5" />
                Details
              </button>
              <span v-if="isSelf(user) || user.status === 'DELETED'" class="text-xs text-muted-foreground">—</span>
              <template v-else-if="confirmingUserId === user.user_id">
                <span class="mr-2 text-xs text-foreground">Disable and sign out?</span>
                <button
                  type="button"
                  class="rounded-md bg-destructive px-2.5 py-1.5 text-xs font-medium text-white hover:bg-destructive/90"
                  :data-testid="`users-confirm-disable-${user.username}`"
                  @click="setEnabled(user, false)"
                >
                  Disable
                </button>
                <button
                  type="button"
                  class="ml-1 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-secondary"
                  @click="confirmingUserId = null"
                >
                  Cancel
                </button>
              </template>
              <button
                v-else-if="user.status === 'ACTIVE'"
                type="button"
                class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50"
                :disabled="busyUserId === user.user_id"
                @click="confirmingUserId = user.user_id"
              >
                <Loader2 v-if="busyUserId === user.user_id" class="h-3.5 w-3.5 animate-spin" />
                <UserX v-else class="h-3.5 w-3.5" />
                Disable
              </button>
              <button
                v-else
                type="button"
                class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-primary hover:bg-primary/10 disabled:opacity-50"
                :disabled="busyUserId === user.user_id"
                @click="setEnabled(user, true)"
              >
                <Loader2 v-if="busyUserId === user.user_id" class="h-3.5 w-3.5 animate-spin" />
                <UserCheck v-else class="h-3.5 w-3.5" />
                Enable
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="mt-4 flex items-center justify-between text-xs text-muted-foreground">
      <span>
        Showing {{ visibleUsers.length }} of {{ users.length }} loaded{{ hasMore ? '; more below' : '' }}.
        <template v-if="search">Search covers the loaded accounts.</template>
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

    <AdminUserDialog
      v-if="openUserId"
      :user-id="openUserId"
      :is-self="openUserId === auth.user?.id"
      @close="openUserId = null"
      @reset="(username) => (actionMessage = `Reset the login password of ${username}.`)"
    />
  </div>
</template>
