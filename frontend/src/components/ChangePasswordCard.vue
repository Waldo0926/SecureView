<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { KeyRound, Loader2 } from 'lucide-vue-next'
import { useRouter } from 'vue-router'

import { authApi } from '@/api/auth_api'
import { apiErrorMessage } from '@/api/http'
import { unwrapData } from '@/api/types'
import PasswordField from '@/components/PasswordField.vue'
import { useAuthStore } from '@/stores/auth_store'
import { evaluatePassword, passwordRequirementHint } from '@/utils/password-policy'

/**
 * Change the login password while signed in.
 *
 * `POST /auth/change-password` existed but nothing in the app called it, so the only way to a new
 * login password was the emailed reset -- and after an administrator reset an account to a
 * temporary password, the holder had nowhere to choose their own. The server signs out every
 * session afterwards, this one included, so the page goes to sign-in.
 *
 * This is the login password only. Files open with the encryption passphrase, which is changed
 * in the card below with the private key file.
 */
const props = withDefaults(
  defineProps<{
    /**
     * An administrator reset the login password and the holder has been sent here to choose
     * their own. The card is the same; it only takes the cursor so the next thing they type
     * is the temporary password they were given.
     */
    required?: boolean
  }>(),
  { required: false },
)

const auth = useAuthStore()
const router = useRouter()

const current = ref('')
const next = ref('')
const repeat = ref('')
const submitted = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const currentField = ref<InstanceType<typeof PasswordField> | null>(null)

onMounted(() => {
  if (props.required) currentField.value?.focus()
})

const policy = computed(() => evaluatePassword(next.value, [auth.user?.username ?? '', auth.user?.email ?? '']))
const nextError = computed(() => (submitted.value || next.value ? (policy.value.ok ? '' : policy.value.message) : ''))
const repeatError = computed(() =>
  (submitted.value || repeat.value) && repeat.value !== next.value ? 'The two new passwords do not match.' : '',
)
const sameAsCurrent = computed(() => next.value !== '' && next.value === current.value)

async function submit() {
  submitted.value = true
  errorMessage.value = ''
  if (!current.value || !policy.value.ok || repeat.value !== next.value) return
  if (sameAsCurrent.value) {
    errorMessage.value = 'Choose a password different from the current one.'
    return
  }
  busy.value = true
  try {
    unwrapData(await authApi.changePassword({ current_password: current.value, new_password: next.value }))
    // The server has already ended every session; only the local copy is left to clear.
    auth.clearLocalSession()
    await router.push({ path: '/login', query: { passwordChanged: '1' } })
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'The password could not be changed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div
    id="login-password"
    class="rounded-xl border bg-card p-6"
    :class="required ? 'border-amber-500/60' : 'border-border'"
    data-testid="change-password"
  >
    <h2 class="flex items-center gap-2 text-lg font-semibold text-foreground">
      <KeyRound class="h-5 w-5" /> Login password
    </h2>
    <p class="mt-1 text-sm text-muted-foreground">
      The password you sign in with. Changing it signs you out everywhere, this device too. Your
      files and encryption passphrase are not affected.
    </p>

    <form class="mt-4 grid gap-4 md:grid-cols-3" novalidate @submit.prevent="submit">
      <PasswordField
        ref="currentField"
        v-model="current"
        label="Current password"
        autocomplete="current-password"
      />
      <PasswordField
        v-model="next"
        label="New password"
        :hint="passwordRequirementHint()"
        :error="nextError"
      />
      <PasswordField v-model="repeat" label="Repeat new password" :error="repeatError" />
      <div class="flex flex-wrap items-center gap-3 md:col-span-3">
        <button
          type="submit"
          class="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          :disabled="busy"
        >
          <Loader2 v-if="busy" class="h-4 w-4 animate-spin" />
          Change password
        </button>
        <p v-if="errorMessage" class="text-sm text-destructive" role="alert">{{ errorMessage }}</p>
      </div>
    </form>
  </div>
</template>
