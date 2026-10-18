<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import {
  Bot,
  FileIcon,
  KeyRound,
  LayoutDashboard,
  LifeBuoy,
  ScanSearch,
  ShieldCheck,
  Users,
} from 'lucide-vue-next'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/securfile/PageHeader.vue'
import AdminAgentPanel from '@/components/admin/AdminAgentPanel.vue'
import AdminAuditPanel from '@/components/admin/AdminAuditPanel.vue'
import AdminFilesPanel from '@/components/admin/AdminFilesPanel.vue'
import AdminIntegrityPanel from '@/components/admin/AdminIntegrityPanel.vue'
import AdminRecoveryKeyPanel from '@/components/admin/AdminRecoveryKeyPanel.vue'
import AdminStatsPanel from '@/components/admin/AdminStatsPanel.vue'
import AdminRecoveryRequestsPanel from '@/components/admin/AdminRecoveryRequestsPanel.vue'
import AdminUsersPanel from '@/components/admin/AdminUsersPanel.vue'
import { useAuthStore } from '@/stores/auth_store'
import {
  consoleTitle,
  defaultTab,
  tabFromQuery,
  tabGroupsFor,
  type AdminTabId,
} from '@/utils/admin-tabs'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const ready = ref(false)
const activeTab = ref<AdminTabId>('recovery')

const groups = computed(() => tabGroupsFor(auth.isAdmin))
const heading = computed(() => consoleTitle(auth.user?.role))

const icons: Record<AdminTabId, Component> = {
  overview: LayoutDashboard,
  agent: Bot,
  integrity: ScanSearch,
  audit: ShieldCheck,
  users: Users,
  files: FileIcon,
  recovery: LifeBuoy,
  'recovery-key': KeyRound,
}

const panelMap: Record<AdminTabId, Component> = {
  overview: AdminStatsPanel,
  agent: AdminAgentPanel,
  integrity: AdminIntegrityPanel,
  audit: AdminAuditPanel,
  users: AdminUsersPanel,
  files: AdminFilesPanel,
  recovery: AdminRecoveryRequestsPanel,
  'recovery-key': AdminRecoveryKeyPanel,
}

const activePanel = computed(() => panelMap[activeTab.value])

const roleLabel = computed(() => {
  if (auth.isAdmin) return 'Administrator'
  if (auth.user?.role === 'RECOVERY_OFFICER') return 'Recovery officer'
  return auth.user?.role ?? 'Signed-in user'
})

// On a narrow screen the section row scrolls; a fade at an edge says there is more that way.
const tabRow = ref<HTMLElement | null>(null)
const moreLeft = ref(false)
const moreRight = ref(false)
function updateTabFades() {
  const el = tabRow.value
  if (!el) return
  moreLeft.value = el.scrollLeft > 4
  moreRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 4
}
let resizeObserver: ResizeObserver | null = null
watch(tabRow, (el) => {
  resizeObserver?.disconnect()
  if (el && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(updateTabFades)
    resizeObserver.observe(el)
  }
  void nextTick(updateTabFades)
})
onBeforeUnmount(() => resizeObserver?.disconnect())

/** Switch section and record it in the URL, so refresh and back land on the same one. */
function openTab(id: AdminTabId) {
  activeTab.value = id
  const query = { ...route.query, tab: id === defaultTab(auth.isAdmin) ? undefined : id }
  void router.replace({ query })
}

watch(
  () => route.query.tab,
  (value) => {
    if (ready.value) activeTab.value = tabFromQuery(value, auth.isAdmin)
  },
)

onMounted(async () => {
  await auth.loadUser(true)
  activeTab.value = tabFromQuery(route.query.tab, auth.isAdmin)
  ready.value = true
})
</script>

<template>
  <section class="product-page">
    <div class="page-container">
      <PageHeader v-if="ready" :title="heading.title" :subtitle="heading.subtitle" />
      <!-- Holds the header's place while the account loads, so the page does not jump. -->
      <div v-else class="mb-10 h-28 md:mb-14" aria-hidden="true" />

      <div v-if="!ready" class="py-16 text-center text-sm text-muted-foreground">
        Loading account…
      </div>

      <div
        v-else-if="!auth.isRecoveryReviewer && auth.user"
      >
        <div class="rounded-xl border border-border bg-card p-6">
          <h2 class="text-lg font-semibold text-foreground">Your recovery requests</h2>
          <p class="mt-2 text-sm text-muted-foreground">
            You can open a recovery request for a file you can access from
            <RouterLink to="/files" class="text-primary underline-offset-2 hover:underline">My Files</RouterLink>,
            and track or cancel it here. Reviewing requests and managing the platform need the
            <span class="font-medium text-foreground">ADMIN</span> or
            <span class="font-medium text-foreground">RECOVERY_OFFICER</span> role.
          </p>
        </div>
        <div class="mt-8">
          <AdminRecoveryRequestsPanel :can-review="false" />
        </div>
      </div>

      <div v-else-if="auth.isRecoveryReviewer">
        <p class="mb-6 text-center text-sm text-muted-foreground">
          Signed in as <span class="font-medium text-foreground">{{ roleLabel }}</span>
          ({{ auth.displayName }})
        </p>

        <!--
          One row, grouped. On a laptop it fits; on a narrow screen it scrolls sideways instead of
          wrapping, so no tab is ever left alone on a second line.
        -->
        <div v-if="groups.flatMap((g) => g.tabs).length > 1" class="relative -mx-4 mb-8">
          <nav
            ref="tabRow"
            class="overflow-x-auto border-b border-border px-4 pb-3 [scrollbar-width:thin]"
            aria-label="Console sections"
            @scroll.passive="updateTabFades"
          >
            <div class="mx-auto flex w-max items-end gap-2" role="tablist">
              <template v-for="(group, groupIndex) in groups" :key="group.label">
                <span
                  v-if="groupIndex > 0"
                  class="mx-1 mb-1.5 h-6 w-px shrink-0 self-end bg-border"
                  aria-hidden="true"
                />
                <div class="flex flex-col gap-1" role="presentation">
                  <span
                    class="px-3 text-[0.68rem] font-semibold uppercase tracking-wider text-muted-foreground"
                  >
                    {{ group.label }}
                  </span>
                  <div class="flex gap-1">
                    <button
                      v-for="tab in group.tabs"
                      :key="tab.id"
                      type="button"
                      role="tab"
                      :aria-selected="activeTab === tab.id"
                      :data-testid="`admin-tab-${tab.id}`"
                      class="inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors"
                      :class="
                        activeTab === tab.id
                          ? 'bg-primary/10 font-medium text-primary'
                          : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                      "
                      @click="openTab(tab.id)"
                    >
                      <component :is="icons[tab.id]" class="hidden h-4 w-4 lg:inline" />
                      {{ tab.label }}
                    </button>
                  </div>
                </div>
              </template>
            </div>
          </nav>
          <div
            v-show="moreLeft"
            class="pointer-events-none absolute inset-y-0 left-0 w-10 bg-gradient-to-r from-background to-transparent"
            aria-hidden="true"
          />
          <div
            v-show="moreRight"
            class="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-background to-transparent"
            aria-hidden="true"
          />
        </div>

        <div role="tabpanel">
          <AdminRecoveryRequestsPanel
            v-if="activeTab === 'recovery'"
            :can-review="true"
          />
          <component :is="activePanel" v-else @navigate="openTab" />
        </div>
      </div>

      <div v-else class="py-16 text-center text-sm text-muted-foreground">
        Could not load your account role. Try refreshing, or
        <RouterLink to="/login" class="text-primary underline-offset-2 hover:underline">sign in</RouterLink>
        again.
      </div>
    </div>
  </section>
</template>
