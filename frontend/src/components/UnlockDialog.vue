<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { nextTick, onMounted, ref } from 'vue'
import { KeyRound, Upload } from 'lucide-vue-next'

import { apiErrorMessage } from '@/api/http'
import PasswordField from '@/components/PasswordField.vue'
import {
  PrivateKeyMismatchError,
  unlockOwnedKey,
  unlockWithPassphrase,
  unlockWithPrivateKeyPem,
} from '@/crypto/download'
import { PassphraseRejectedError } from '@/utils/account-crypto'

const props = defineProps<{
  /** Set when a specific superseded key is needed, rather than the active one. */
  keyId?: string | null
}>()

const emit = defineEmits<{
  (e: 'unlocked'): void
  (e: 'close'): void
}>()

const passphrase = ref('')
const errorMessage = ref('')
const isUnlocking = ref(false)
const field = ref<InstanceType<typeof PasswordField> | null>(null)
const usingKeyFile = ref(false)
const keyFileName = ref('')

onMounted(async () => {
  await nextTick()
  field.value?.focus()
})

async function unlock() {
  if (!passphrase.value) {
    errorMessage.value = 'Enter your encryption passphrase'
    return
  }
  isUnlocking.value = true
  errorMessage.value = ''
  try {
    if (props.keyId) {
      await unlockOwnedKey(props.keyId, passphrase.value)
    } else {
      await unlockWithPassphrase(passphrase.value)
    }
    // Drop the passphrase as soon as it has done its work. The unwrapped key is a
    // non-extractable CryptoKey that is forgotten after the one download or share it was
    // opened for; keeping the string around buys nothing and loses if anything later
    // serialises this component's state.
    passphrase.value = ''
    emit('unlocked')
  } catch (error) {
    passphrase.value = ''
    errorMessage.value =
      error instanceof PassphraseRejectedError
        ? 'That passphrase does not open your account key.'
        : apiErrorMessage(error, 'Could not unlock the account key')
    await nextTick()
    field.value?.focus()
  } finally {
    isUnlocking.value = false
  }
}

/**
 * Unlock with the key file saved at registration.
 *
 * The file is read in the page and never uploaded -- it is the plaintext account private
 * key, and the whole point of the design is that the server never holds one.
 */
async function useKeyFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // Reset immediately so choosing the same file twice after a failure still fires a change.
  input.value = ''
  if (!file) return

  keyFileName.value = file.name
  isUnlocking.value = true
  errorMessage.value = ''
  try {
    await unlockWithPrivateKeyPem(await file.text(), props.keyId ?? undefined)
    emit('unlocked')
  } catch (error) {
    errorMessage.value =
      error instanceof PrivateKeyMismatchError
        ? 'That key file does not match this account key. Check you saved it from this account.'
        : apiErrorMessage(error, 'Could not read that key file')
  } finally {
    isUnlocking.value = false
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    @click.self="emit('close')"
  >
    <div class="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-xl border border-border bg-card p-6 shadow-xl">
      <div class="flex items-center gap-2 mb-2">
        <div class="p-2 rounded-lg bg-secondary"><KeyRound class="h-4 w-4 text-primary" /></div>
        <h2 class="text-lg font-semibold text-foreground">Unlock your files</h2>
      </div>
      <p class="text-sm text-muted-foreground mb-4">
        Your files are decrypted in this browser, so your encryption passphrase is needed to
        open the account key. It is never sent to the server. It is asked for on every
        decrypted download and every share, and the key locks again straight after.
      </p>
      <p v-if="props.keyId" class="text-sm text-muted-foreground mb-4">
        This file was encrypted under an earlier account key
        (<code class="text-xs">{{ props.keyId }}</code
        >), which the same passphrase opens.
      </p>

      <form @submit.prevent="unlock">
        <PasswordField
          ref="field"
          v-model="passphrase"
          label="Encryption passphrase"
          placeholder="Your encryption passphrase"
          autocomplete="current-password"
        />
        <p v-if="errorMessage" class="text-sm text-destructive mt-2">{{ errorMessage }}</p>

        <div class="mt-4 flex gap-2">
          <button
            type="submit"
            class="flex-1 h-10 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            :disabled="isUnlocking"
          >
            {{ isUnlocking ? 'Unlocking...' : 'Unlock' }}
          </button>
          <button
            type="button"
            class="h-10 px-4 rounded-md border border-border hover:bg-secondary"
            @click="emit('close')"
          >
            Cancel
          </button>
        </div>
      </form>

      <p class="text-xs text-muted-foreground mt-4">
        Deriving the key takes a moment on purpose: the same cost that slows this down slows
        an attacker guessing the passphrase offline.
      </p>

      <div class="mt-4 pt-4 border-t border-border">
        <button
          v-if="!usingKeyFile"
          type="button"
          class="min-h-10 text-sm text-primary hover:underline"
          @click="usingKeyFile = true"
        >
          Forgotten your passphrase?
        </button>

        <template v-else>
          <p class="text-sm text-foreground mb-1">Unlock with your private key file</p>
          <p class="text-xs text-muted-foreground mb-3">
            The <code class="text-xs">.pem</code> file you were given once at registration. It
            is read in this browser and never uploaded. The passphrase cannot be recovered,
            but this file opens your account key without it — and in
            <RouterLink to="/settings" class="text-primary hover:underline">Settings</RouterLink>
            it can set a new passphrase so you do not need the file next time.
          </p>

          <label
            class="inline-flex h-9 px-3 items-center gap-2 rounded-md border border-border cursor-pointer hover:bg-secondary transition-colors text-sm"
          >
            <Upload class="h-4 w-4" />
            <span>{{ keyFileName || 'Choose key file' }}</span>
            <input type="file" accept=".pem,application/x-pem-file,text/plain" class="hidden" @change="useKeyFile" />
          </label>

          <p class="text-xs text-muted-foreground mt-3">
            No key file either? Your files cannot be decrypted — neither the team nor the
            server holds anything that opens them.
          </p>
        </template>
      </div>
    </div>
  </div>
</template>
