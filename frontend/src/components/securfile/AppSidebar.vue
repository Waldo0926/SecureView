<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Activity, BookOpen, FolderLock, HelpCircle, LayoutDashboard, LifeBuoy, LogOut, Mail, ShieldCheck, Upload } from 'lucide-vue-next'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { keyApi } from '@/api/key_api'
import { isUnlocked, onRelock } from '@/crypto/download'
import { formatFingerprint } from '@/crypto/fingerprint'
import { publicKeyFingerprint } from '@/crypto/primitives'
import SecureViewMark from '@/components/brand/SecureViewMark.vue'
import { useAuthStore } from '@/stores/auth_store'

/**
 * The signed-in app's navigation. It carries the same links as the header's signed-in list, in the
 * same words, and adds what the header never had room for: whether this browser currently holds the
 * account key, and the fingerprint that key is known by. The header keeps the account menu, the
 * language switch and (below the lg breakpoint) the menu button.
 */
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()

const consoleLabel = computed(() => {
  if (auth.isAdmin) return t('nav.adminConsole')
  if (auth.isRecoveryReviewer) return t('nav.recoveryReview')
  return t('nav.recoveryRequests')
})

const workspace = computed(() => [
  { to: '/dashboard', label: t('nav.dashboard'), icon: LayoutDashboard },
  { to: '/upload', label: t('nav.upload'), icon: Upload },
  { to: '/files', label: t('nav.myFiles'), icon: FolderLock },
  { to: '/audit-logs', label: t('nav.activityLog'), icon: Activity },
  { to: '/admin', label: consoleLabel.value, icon: LifeBuoy },
])
const learn = computed(() => [
  { to: '/help', label: t('nav.help'), icon: HelpCircle },
  { to: '/education', label: t('nav.education'), icon: BookOpen },
  { to: '/team', label: t('nav.contact'), icon: Mail },
])

const isActive = (to: string) => route.path === to || route.path.startsWith(`${to}/`)

const unlocked = ref(isUnlocked())
const fingerprint = ref('')
let timer = 0
let stopRelock: (() => void) | undefined

onMounted(async () => {
  // Unlocking and the idle relock both change a module-level map, which Vue cannot watch.
  timer = window.setInterval(() => (unlocked.value = isUnlocked()), 1500)
  stopRelock = onRelock(() => (unlocked.value = false))
  try {
    const pem = (await keyApi.myBundle()).data.data.key.public_key_pem
    fingerprint.value = formatFingerprint(await publicKeyFingerprint(pem)).split(' ').slice(0, 4).join(' ')
  } catch {
    // The fingerprint is a convenience here; Settings shows it in full and says when it fails.
  }
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  stopRelock?.()
})

async function logout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <aside class="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-6 border-r border-border bg-card px-4 py-5 lg:flex" data-testid="app-sidebar">
    <RouterLink to="/" class="inline-flex items-center px-2 text-foreground" :aria-label="t('nav.homeAria')">
      <SecureViewMark variant="logo" class="h-9" />
    </RouterLink>

    <nav class="flex flex-1 flex-col gap-6 overflow-y-auto" aria-label="Main">
      <ul class="flex flex-col gap-0.5">
        <li v-for="item in workspace" :key="item.to">
          <RouterLink
            :to="item.to"
            class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors hover:bg-secondary"
            :class="isActive(item.to) ? 'bg-secondary font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
            :aria-current="isActive(item.to) ? 'page' : undefined"
          >
            <component :is="item.icon" class="h-4 w-4 shrink-0" aria-hidden="true" />
            {{ item.label }}
          </RouterLink>
        </li>
      </ul>
      <div class="flex flex-col gap-1">
        <p class="px-3 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-muted-foreground">Learn</p>
        <ul class="flex flex-col gap-0.5">
          <li v-for="item in learn" :key="item.to">
            <RouterLink
              :to="item.to"
              class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors hover:bg-secondary"
              :class="isActive(item.to) ? 'bg-secondary font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
              :aria-current="isActive(item.to) ? 'page' : undefined"
            >
              <component :is="item.icon" class="h-4 w-4 shrink-0" aria-hidden="true" />
              {{ item.label }}
            </RouterLink>
          </li>
        </ul>
      </div>
    </nav>

    <div class="flex flex-col gap-3 rounded-xl border border-border p-4" data-testid="key-status">
      <p class="flex items-center gap-2 text-sm font-medium" :class="unlocked ? 'text-success' : 'text-muted-foreground'">
        <ShieldCheck class="h-4 w-4 shrink-0" aria-hidden="true" />
        {{ unlocked ? 'Key unlocked in this browser' : 'Key locked' }}
      </p>
      <p v-if="fingerprint" translate="no" class="font-mono text-xs tracking-[0.06em] text-muted-foreground">{{ fingerprint }}</p>
      <p v-if="!unlocked" class="text-xs leading-relaxed text-muted-foreground">You enter your passphrase for each decrypted download or share.</p>
      <div class="flex items-center justify-between gap-2 border-t border-border pt-3">
        <span translate="no" class="truncate text-sm text-foreground">{{ auth.displayName }}</span>
        <button type="button" class="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="Log out" title="Log out" @click="logout">
          <LogOut class="h-4 w-4" />
        </button>
      </div>
    </div>
  </aside>
</template>
