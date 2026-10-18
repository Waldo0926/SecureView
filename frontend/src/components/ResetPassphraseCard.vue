<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { CheckCircle, KeyRound, Loader2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import PasswordField from '@/components/PasswordField.vue'
import { apiErrorMessage } from '@/api/http'
import { PrivateKeyMismatchError } from '@/crypto/download'
import {
  PassphraseTooShortError,
  ResetVerificationError,
  resetPassphraseWithPrivateKeyPem,
} from '@/crypto/passphrase-reset'
import {
  PASSPHRASE_MIN_LENGTH,
  passphraseLength,
  weakPassphraseMessage,
  weakPassphraseReason,
} from '@/utils/password-policy'
import { useAuthStore } from '@/stores/auth_store'

/**
 * Set a new encryption passphrase using the private key file issued at registration.
 *
 * The file is read in the page and never uploaded: it is the plaintext account private key.
 * Only the two re-sealed envelopes and a signature over them reach the server.
 */

const { t } = useI18n()
const auth = useAuthStore()
const keyPem = ref('')
const keyFileName = ref('')
const passphrase = ref('')
const confirmation = ref('')
const submitted = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const done = ref(false)
const acknowledged = ref(false)

// Leaving the page must not leave the plaintext key file sitting in component state.
onBeforeUnmount(() => {
  keyPem.value = ''
  passphrase.value = ''
  confirmation.value = ''
})

const passphraseError = computed(() => {
  if (!submitted.value) return ''
  if (passphraseLength(passphrase.value) < PASSPHRASE_MIN_LENGTH) {
    return t('register.passphraseTooShort', { min: PASSPHRASE_MIN_LENGTH })
  }
  return weakPassphraseMessage(
    weakPassphraseReason(passphrase.value, [auth.user?.username ?? '', auth.user?.email ?? '']),
  )
})

const confirmationError = computed(() => {
  if (!submitted.value) return ''
  return confirmation.value === passphrase.value ? '' : t('resetPassphrase.mismatch')
})

async function chooseKeyFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // Reset immediately so choosing the same file twice after a failure still fires a change.
  input.value = ''
  if (!file) return
  keyFileName.value = file.name
  keyPem.value = await file.text()
  errorMessage.value = ''
}

async function submit() {
  submitted.value = true
  errorMessage.value = ''
  if (!keyPem.value) {
    errorMessage.value = t('resetPassphrase.chooseFile')
    return
  }
  if (passphraseError.value || confirmationError.value) return
  if (!acknowledged.value) {
    errorMessage.value = t('resetPassphrase.needAcknowledge')
    return
  }

  busy.value = true
  try {
    await resetPassphraseWithPrivateKeyPem(keyPem.value, passphrase.value)
    done.value = true
    // Nothing sensitive should outlive the form.
    keyPem.value = ''
    passphrase.value = ''
    confirmation.value = ''
    acknowledged.value = false
  } catch (error) {
    if (error instanceof PrivateKeyMismatchError) {
      errorMessage.value = t('resetPassphrase.wrongKey')
    } else if (error instanceof TypeError) {
      errorMessage.value = error.message
    } else if (error instanceof PassphraseTooShortError || error instanceof ResetVerificationError) {
      errorMessage.value = error.message
    } else {
      errorMessage.value = apiErrorMessage(error, t('resetPassphrase.failed'))
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="rounded-xl border border-border bg-card p-6">
    <h2 class="flex items-center gap-2 text-lg font-semibold text-foreground">
      <KeyRound class="h-5 w-5 text-primary" />
      {{ t('resetPassphrase.title') }}
    </h2>
    <p class="mt-2 reading-measure text-sm text-muted-foreground">
      {{ t('resetPassphrase.intro') }}
    </p>

    <div v-if="done" class="mt-4 flex items-start gap-2 rounded-lg border border-success/40 bg-success-soft p-3">
      <CheckCircle class="mt-0.5 h-4 w-4 shrink-0 text-success" />
      <p class="text-sm text-foreground">
        {{ t('resetPassphrase.done') }}
      </p>
    </div>

    <form v-else class="mt-4 space-y-4" novalidate @submit.prevent="submit">
      <div>
        <label class="inline-flex h-10 cursor-pointer items-center rounded-md border border-border px-4 text-sm text-foreground transition-colors hover:bg-secondary">
          <span>{{ keyFileName || t('resetPassphrase.chooseButton') }}</span>
          <input
            type="file"
            accept=".pem,application/x-pem-file,text/plain"
            class="hidden"
            :disabled="busy"
            @change="chooseKeyFile"
          />
        </label>
      </div>

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

      <label class="flex items-start gap-2 text-sm text-foreground">
        <input v-model="acknowledged" type="checkbox" class="mt-1 h-5 w-5 shrink-0" :disabled="busy" />
        <span>{{ t('resetPassphrase.acknowledge') }}</span>
      </label>

      <p v-if="errorMessage" class="text-sm text-destructive">{{ errorMessage }}</p>

      <button
        type="submit"
        :disabled="busy"
        class="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
      >
        <Loader2 v-if="busy" class="h-4 w-4 animate-spin" />
        {{ busy ? t('resetPassphrase.submitting') : t('resetPassphrase.submit') }}
      </button>
      <p v-if="busy" class="text-xs text-muted-foreground">
        {{ t('resetPassphrase.slowOnPurpose') }}
      </p>
    </form>
  </div>
</template>
