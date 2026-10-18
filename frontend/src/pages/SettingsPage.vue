<script setup lang="ts">
import { computed, ref } from 'vue'
import { LogOut, Monitor, Moon, ShieldAlert, Sun, UserRound } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/securfile/PageHeader.vue'
import ChangePasswordCard from '@/components/ChangePasswordCard.vue'
import DeleteAccountDialog from '@/components/DeleteAccountDialog.vue'
import KeyFingerprintCard from '@/components/KeyFingerprintCard.vue'
import ChangePassphraseCard from '@/components/ChangePassphraseCard.vue'
import ResetPassphraseCard from '@/components/ResetPassphraseCard.vue'
import { useTheme, type ThemePreference } from '@/composables/useTheme'
import { useAuthStore } from '@/stores/auth_store'
import { LOCALES, setLocale } from '@/i18n'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { preference, setPreference } = useTheme()
const showDelete = ref(false)
const { t, locale } = useI18n()

/**
 * An administrator reset the login password. The store knows once login or `/auth/me` has
 * answered; the query is set by the guard so the notice is there from the first paint too.
 */
const passwordChangeRequired = computed(
  () => auth.mustChangePassword || route.query.password === 'required',
)

const themeOptions: { value: ThemePreference; label: string; hint: string; icon: typeof Sun }[] = [
  { value: 'system', label: 'theme.system', hint: 'theme.systemHint', icon: Monitor },
  { value: 'light', label: 'theme.light', hint: 'theme.lightHint', icon: Sun },
  { value: 'dark', label: 'theme.dark', hint: 'theme.darkHint', icon: Moon },
]

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}

/**
 * The account is gone server-side; clear the local session so the app does not keep
 * rendering a signed-in shell against a user that no longer exists. Sessions were already
 * revoked with the account — do not call `POST /auth/logout` against a deleted user.
 */
function onDeleted() {
  showDelete.value = false
  auth.clearLocalSession()
  router.push({ path: '/register', query: { deleted: '1' } })
}
</script>

<template>
  <section class="product-page">
    <div class="page-container">
      <PageHeader :title="t('settings.title')" :subtitle="t('settings.intro', { name: auth.displayName })" />

      <div
        v-if="passwordChangeRequired"
        class="mb-6 flex items-start gap-3 rounded-xl border border-amber-500/50 bg-amber-500/10 p-4"
        role="alert"
        data-testid="password-change-required"
      >
        <ShieldAlert class="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
        <div>
          <p class="text-sm font-semibold text-foreground">{{ t('settings.passwordResetTitle') }}</p>
          <p class="mt-1 text-sm text-muted-foreground">{{ t('settings.passwordResetBody') }}</p>
        </div>
      </div>

      <div class="grid gap-6 lg:grid-cols-2">
        <div class="flex flex-col gap-6">
          <div class="rounded-xl border border-border bg-card p-6">
            <h2 class="text-lg font-semibold text-foreground">{{ t('settings.appearance') }}</h2>
            <p class="mt-1 text-sm text-muted-foreground">
              {{ t('settings.appearanceHint') }}
            </p>

            <div class="mt-4 grid gap-3 sm:grid-cols-3">
              <button
                v-for="option in themeOptions"
                :key="option.value"
                type="button"
                role="radio"
                :aria-checked="preference === option.value"
                class="rounded-lg border p-4 text-left transition-colors"
                :class="
                  preference === option.value
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:border-primary/40'
                "
                @click="setPreference(option.value)"
              >
                <component
                  :is="option.icon"
                  class="mb-2 h-5 w-5"
                  :class="preference === option.value ? 'text-primary' : 'text-muted-foreground'"
                />
                <p class="text-sm font-semibold text-foreground">{{ t(option.label) }}</p>
                <p class="mt-1 text-sm text-muted-foreground">{{ t(option.hint) }}</p>
              </button>
            </div>
          </div>

          <div class="flex-1 rounded-xl border border-border bg-card p-6">
            <h2 id="settings-language" class="text-lg font-semibold text-foreground">{{ t('settings.language') }}</h2>
            <p class="mt-1 text-sm text-muted-foreground">{{ t('settings.languageHint') }}</p>
            <div class="mt-4 grid gap-3 sm:grid-cols-2" role="radiogroup" aria-labelledby="settings-language">
              <button
                v-for="option in LOCALES"
                :key="option.code"
                type="button"
                role="radio"
                :lang="option.code"
                :aria-checked="locale === option.code"
                class="rounded-lg border p-4 text-left text-sm font-semibold text-foreground transition-colors"
                :class="locale === option.code ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/40'"
                @click="setLocale(option.code)"
              >
                {{ option.label }}
              </button>
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-6">
          <div class="rounded-xl border border-border bg-card p-6">
            <h2 class="text-lg font-semibold text-foreground">{{ t('settings.account') }}</h2>
            <div class="mt-4 flex flex-wrap gap-3">
              <RouterLink
                to="/profile"
                class="inline-flex h-10 items-center gap-2 rounded-md border border-border px-4 text-sm text-foreground transition-colors hover:bg-secondary"
              >
                <UserRound class="h-4 w-4" />
                {{ t('settings.viewProfile') }}
              </RouterLink>
              <button
                type="button"
                class="inline-flex h-10 items-center gap-2 rounded-md border border-border px-4 text-sm text-foreground transition-colors hover:bg-secondary"
                @click="handleLogout"
              >
                <LogOut class="h-4 w-4" />
                {{ t('nav.logOut') }}
              </button>
            </div>
          </div>

          <KeyFingerprintCard class="flex-1" />
        </div>
      </div>

      <div class="mt-6 flex flex-col gap-6">
        <ChangePasswordCard :required="passwordChangeRequired" />
        <ChangePassphraseCard />
        <ResetPassphraseCard />

        <div class="rounded-xl border border-destructive/40 bg-card p-6">
          <h2 class="text-lg font-semibold text-foreground">{{ t('settings.deleteTitle') }}</h2>
          <p class="mt-2 reading-measure text-sm text-muted-foreground">
            {{ t('settings.deleteBody') }}
          </p>
          <button
            type="button"
            class="mt-4 h-10 rounded-md border border-destructive/50 px-4 text-sm text-destructive transition-colors hover:bg-destructive/10"
            @click="showDelete = true"
          >
            {{ t('settings.deleteButton') }}
          </button>
        </div>
      </div>
    </div>

    <DeleteAccountDialog v-if="showDelete" @deleted="onDeleted" @close="showDelete = false" />
  </section>
</template>
