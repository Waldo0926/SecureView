<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { LifeBuoy, LogOut, Monitor, Moon, Settings, Sun, UserRound } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PASSWORD_CHANGE_REQUIRED, SETTINGS_PATH } from '@/router/guard'
import { useAuthStore } from '@/stores/auth_store'
import type { ThemePreference } from '@/composables/useTheme'

const props = defineProps<{
  themePreference: ThemePreference
}>()

const emit = defineEmits<{
  (e: 'set-theme-preference', preference: ThemePreference): void
}>()

const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()

/** What /admin is for this role: the console for staff, the request tracker for everyone else. */
const consoleLabel = computed(() => {
  if (auth.isAdmin) return t('nav.adminConsole')
  if (auth.isRecoveryReviewer) return t('nav.recoveryReview')
  return t('nav.recoveryRequests')
})

const isOpen = ref(false)
const root = ref<HTMLElement | null>(null)

/**
 * The panel hangs below the avatar with a gap between them. Closing the instant the pointer
 * leaves the button would make the menu unreachable, so a leave is a scheduled close that
 * entering either element cancels.
 */
let closeTimer = 0

const themeOptions: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: 'system', label: 'theme.system', icon: Monitor },
  { value: 'light', label: 'theme.light', icon: Sun },
  { value: 'dark', label: 'theme.dark', icon: Moon },
]

const currentTheme = computed(
  () => themeOptions.find((option) => option.value === props.themePreference) ?? themeOptions[0],
)

function cancelClose() {
  window.clearTimeout(closeTimer)
  closeTimer = 0
}

function open() {
  cancelClose()
  isOpen.value = true
}

function scheduleClose() {
  cancelClose()
  closeTimer = window.setTimeout(() => {
    isOpen.value = false
  }, 180)
}

function close() {
  cancelClose()
  isOpen.value = false
}

function goToProfile() {
  close()
  router.push('/profile')
}

function goToSettings() {
  close()
  router.push('/settings')
}

function goToOperations() {
  close()
  router.push('/admin')
}

function selectTheme(preference: ThemePreference) {
  emit('set-theme-preference', preference)
}

async function handleLogout() {
  close()
  await auth.logout()
  router.push('/login')
}

function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  if (target && root.value?.contains(target)) return
  close()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onKeydown)
  // Only mounted while signed in, so this is the natural place to learn who that is.
  void auth.loadUser().then(() => {
    // A reload lands on whatever page was open before the guard knows about the marker;
    // once `/auth/me` has answered, finish what the guard would have done. Like the guard,
    // only signed-in pages are redirected; a public page stays where it is.
    const route = router.currentRoute.value
    if (auth.mustChangePassword && route.meta.requiresAuth && route.path !== SETTINGS_PATH) {
      void router.push(PASSWORD_CHANGE_REQUIRED)
    }
  })
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onKeydown)
  cancelClose()
})
</script>

<template>
  <div
    ref="root"
    class="relative shrink-0"
    @mouseenter="open"
    @mouseleave="scheduleClose"
  >
    <button
      type="button"
      class="flex h-9 w-9 items-center justify-center overflow-hidden rounded-full border border-border bg-primary/10 text-sm font-semibold text-primary transition-colors hover:border-primary/60 hover:bg-primary/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      :aria-expanded="isOpen"
      aria-haspopup="menu"
      :aria-label="t('nav.accountMenuFor', { name: auth.displayName })"
      @click="open"
    >
      <img
        v-if="auth.avatarObjectUrl"
        :src="auth.avatarObjectUrl"
        alt=""
        class="h-full w-full object-cover"
      />
      <template v-else>{{ auth.initials }}</template>
    </button>

    <div
      v-if="isOpen"
      role="menu"
      class="absolute left-0 lg:left-auto lg:right-0 top-full z-[60] mt-2 w-60 overflow-hidden rounded-xl border border-border bg-card shadow-lg"
    >
      <button
        type="button"
        role="menuitem"
        class="flex w-full items-center gap-3 border-b border-border px-4 py-3 text-left transition-colors hover:bg-secondary"
        @click="goToProfile"
      >
        <span
          class="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/10 text-sm font-semibold text-primary"
        >
          <img
            v-if="auth.avatarObjectUrl"
            :src="auth.avatarObjectUrl"
            alt=""
            class="h-full w-full object-cover"
          />
          <template v-else>{{ auth.initials }}</template>
        </span>
        <span class="min-w-0">
          <span translate="no" class="block truncate text-sm font-medium text-foreground">{{ auth.displayName }}</span>
          <span translate="no" v-if="auth.user?.email" class="block truncate text-xs text-muted-foreground">
            {{ auth.user.email }}
          </span>
        </span>
      </button>

      <div class="py-1">
        <button
          type="button"
          role="menuitem"
          class="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-foreground transition-colors hover:bg-secondary"
          @click="goToProfile"
        >
          <UserRound class="h-4 w-4 shrink-0 text-muted-foreground" />
          {{ t('nav.profile') }}
        </button>
      </div>

      <div class="border-t border-border px-4 py-2">
        <p class="mb-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {{ t('theme.menuHeading', { current: t(currentTheme.label) }) }}
        </p>
        <div class="grid grid-cols-3 gap-1">
          <button
            v-for="option in themeOptions"
            :key="option.value"
            type="button"
            role="menuitemradio"
            :aria-checked="themePreference === option.value"
            class="flex flex-col items-center gap-1 rounded-md border px-1 py-2 text-[0.7rem] transition-colors"
            :class="
              themePreference === option.value
                ? 'border-primary bg-primary/10 text-foreground'
                : 'border-transparent text-muted-foreground hover:bg-secondary hover:text-foreground'
            "
            @click="selectTheme(option.value)"
          >
            <component :is="option.icon" class="h-4 w-4" />
            {{ t(option.label) }}
          </button>
        </div>
      </div>

      <div class="border-t border-border py-1">
        <button
          type="button"
          role="menuitem"
          class="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-foreground transition-colors hover:bg-secondary"
          @click="goToOperations"
        >
          <LifeBuoy class="h-4 w-4 shrink-0 text-muted-foreground" />
          {{ consoleLabel }}
        </button>
        <button
          type="button"
          role="menuitem"
          class="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-foreground transition-colors hover:bg-secondary"
          @click="goToSettings"
        >
          <Settings class="h-4 w-4 shrink-0 text-muted-foreground" />
          {{ t('nav.settings') }}
        </button>
        <button
          type="button"
          role="menuitem"
          class="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10"
          @click="handleLogout"
        >
          <LogOut class="h-4 w-4 shrink-0" />
          {{ t('nav.logOut') }}
        </button>
      </div>
    </div>
  </div>
</template>
