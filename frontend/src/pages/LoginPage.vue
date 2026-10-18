<script setup lang="ts">
import AuthShell from '@/components/securfile/AuthShell.vue'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useRoute, useRouter } from 'vue-router'
import { Lock } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { authApi } from '@/api/auth_api'
import { apiErrorMessage } from '@/api/http'
import PasswordField from '@/components/PasswordField.vue'
import { useAuthStore } from '@/stores/auth_store'
import { HOME_AFTER_LOGIN, PASSWORD_CHANGE_REQUIRED } from '@/router/guard'

const username = ref('')
const password = ref('')
const errorMessage = ref('')
const isSubmitting = ref(false)

const auth = useAuthStore()
const { t } = useI18n()
const router = useRouter()
const route = useRoute()

// Set by the refresh interceptor when a session could not be renewed. Saying so is the
// difference between "I was signed out" and "this app is broken".
const sessionExpired = computed(() => route.query.expired === '1')
const passwordChanged = computed(() => route.query.passwordChanged === '1')

async function login() {
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    const res = await authApi.login({ username: username.value, password: password.value })
    const token = res.data?.data?.access_token
    if (!token) {
      throw new Error(t('login.noToken'))
    }
    // The refresh token is what keeps the session alive past the access token's 30 minutes.
    auth.setSession(token, res.data?.data?.refresh_token ?? '')
    const user = res.data?.data?.user
    if (user) auth.adoptUser(user)
    // A temporary password from an administrator goes straight to the Login password card;
    // the page they were reaching for can wait until they have a password of their own.
    if (user?.must_change_password) {
      router.push(PASSWORD_CHANGE_REQUIRED)
      return
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : HOME_AFTER_LOGIN
    router.push(redirect)
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, t('login.failed'))
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <AuthShell>
    <div class="w-full rounded-xl border border-border bg-card p-8">
      <div class="flex items-center gap-2 mb-6">
        <div class="p-2 rounded-lg bg-primary/10">
          <Lock class="h-5 w-5 text-primary" />
        </div>
        <h1 class="text-2xl font-bold text-foreground">{{ t('login.title') }}</h1>
      </div>

      <p
        v-if="sessionExpired"
        class="text-sm rounded-md border border-border bg-secondary/60 text-foreground px-3 py-2 mb-4"
      >
        {{ t('login.sessionExpired') }}
      </p>
      <p
        v-else-if="passwordChanged"
        class="text-sm rounded-md border border-border bg-secondary/60 text-foreground px-3 py-2 mb-4"
        role="status"
      >
        Password changed. Sign in with the new one.
      </p>

      <form @submit.prevent="login">
        <label class="text-sm text-foreground mb-2 block">
          {{ t('login.username') }} <span class="text-destructive">*</span>
        </label>
        <input
          v-model="username"
          :placeholder="t('login.username')"
          required
          class="h-10 w-full rounded-md border border-border bg-secondary px-3 mb-4"
        />

        <PasswordField
          v-model="password"
          :label="t('login.password')"
          :placeholder="t('login.password')"
          autocomplete="current-password"
        >
          <template #label-aside>
            <RouterLink to="/forgot-password" class="inline-flex min-h-10 items-center text-xs text-primary hover:underline">
              {{ t('login.forgot') }}
            </RouterLink>
          </template>
        </PasswordField>
        <div class="mb-6" />

        <button
          type="submit"
          class="w-full h-11 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          :disabled="isSubmitting"
        >
          {{ isSubmitting ? t('login.submitting') : t('login.submit') }}
        </button>
      </form>

      <p v-if="errorMessage" class="text-sm text-destructive mt-3">{{ errorMessage }}</p>

      <p class="text-sm text-muted-foreground mt-6 text-center">
        {{ t('login.noAccount') }}
        <RouterLink to="/register" class="inline-flex min-h-10 items-center text-primary hover:underline">{{ t('login.register') }}</RouterLink>
      </p>
    </div>
  </AuthShell>
</template>
