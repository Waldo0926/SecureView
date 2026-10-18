<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { CheckCircle, LockKeyhole, Loader2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import PasswordField from '@/components/PasswordField.vue'
import { apiErrorMessage } from '@/api/http'
import {
  PassphraseTooShortError,
  ResetVerificationError,
  SamePassphraseError,
  changePassphrase,
} from '@/crypto/passphrase-reset'
import { PassphraseRejectedError } from '@/utils/account-crypto'
import {
  PASSPHRASE_MIN_LENGTH,
  passphraseLength,
  weakPassphraseMessage,
  weakPassphraseReason,
} from '@/utils/password-policy'
import { useAuthStore } from '@/stores/auth_store'

/**
 * Change the encryption passphrase while the current one is still known.
 *
 * The current passphrase opens the stored key in this browser; the key is sealed again under
 * the new one and a fresh account master key. Neither passphrase is sent anywhere.
 */

const { t } = useI18n()
const auth = useAuthStore()
const current = ref('')
const passphrase = ref('')
const confirmation = ref('')
const submitted = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const done = ref(false)

onBeforeUnmount(() => {
  current.value = ''
  passphrase.value = ''
  confirmation.value = ''
})

const currentError = computed(() =>
  submitted.value && !current.value ? t('changePassphrase.currentRequired') : '',
)

const passphraseError = computed(() => {
  if (!submitted.value) return ''
  if (passphraseLength(passphrase.value) < PASSPHRASE_MIN_LENGTH) {
    return t('register.passphraseTooShort', { min: PASSPHRASE_MIN_LENGTH })
  }
  if (passphrase.value === current.value) return t('changePassphrase.same')
  return weakPassphraseMessage(
    weakPassphraseReason(passphrase.value, [auth.user?.username ?? '', auth.user?.email ?? '']),
  )
})

const confirmationError = computed(() => {
  if (!submitted.value) return ''
  return confirmation.value === passphrase.value ? '' : t('resetPassphrase.mismatch')
})

async function submit() {
  submitted.value = true
  errorMessage.value = ''
  if (currentError.value || passphraseError.value || confirmationError.value) return

  busy.value = true
  try {
    await changePassphrase(current.value, passphrase.value)
    done.value = true
    current.value = ''
    passphrase.value = ''
    confirmation.value = ''
  } catch (error) {
    if (error instanceof PassphraseRejectedError) {
      errorMessage.value = t('changePassphrase.wrongCurrent')
    } else if (error instanceof SamePassphraseError) {
      errorMessage.value = t('changePassphrase.same')
    } else if (error instanceof PassphraseTooShortError || error instanceof ResetVerificationError) {
      errorMessage.value = error.message
    } else {
      errorMessage.value = apiErrorMessage(error, t('changePassphrase.failed'))
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="rounded-xl border border-border bg-card p-6" data-testid="change-passphrase-card">
    <h2 class="flex items-center gap-2 text-lg font-semibold text-foreground">
      <LockKeyhole class="h-5 w-5 text-primary" />
      {{ t('changePassphrase.title') }}
    </h2>
    <p class="mt-2 reading-measure text-sm text-muted-foreground">
      {{ t('changePassphrase.intro') }}
    </p>

    <div v-if="done" class="mt-4 flex items-start gap-2 rounded-lg border border-success/40 bg-success-soft p-3">
      <CheckCircle class="mt-0.5 h-4 w-4 shrink-0 text-success" />
      <p class="text-sm text-foreground">
        {{ t('changePassphrase.done') }}
      </p>
    </div>

    <form v-else class="mt-4 space-y-4" novalidate @submit.prevent="submit">
      <PasswordField
        v-model="current"
        :label="t('changePassphrase.currentLabel')"
        :error="currentError"
      />
      <PasswordField
        v-model="passphrase"
        :label="t('resetPassphrase.newLabel')"
        :hint="t('resetPassphrase.newHint', { min: PASSPHRASE_MIN_LENGTH })"
        :error="passphraseError"
      />
      <PasswordField
        v-model="confirmation"
        :label="t('resetPassphrase.confirmLabel')"
        :error="confirmationError"
      />

      <p v-if="errorMessage" class="text-sm text-destructive">{{ errorMessage }}</p>

      <button
        type="submit"
        :disabled="busy"
        class="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
      >
        <Loader2 v-if="busy" class="h-4 w-4 animate-spin" />
        {{ busy ? t('changePassphrase.submitting') : t('changePassphrase.submit') }}
      </button>
      <p v-if="busy" class="text-xs text-muted-foreground">
        {{ t('resetPassphrase.slowOnPurpose') }}
      </p>
    </form>
  </div>
</template>
