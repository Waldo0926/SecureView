<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Loader2, RefreshCw, KeyRound } from 'lucide-vue-next'

import { apiErrorMessage } from '@/api/http'
import { recoveryApi, type RecoveryPublicKey } from '@/api/recovery_api'
import { unwrapData } from '@/api/types'

const activeKey = ref<RecoveryPublicKey | null>(null)
const isLoading = ref(false)
const isSaving = ref(false)
const errorMessage = ref('')
const actionMessage = ref('')
const publicKeyPem = ref('')
const keyId = ref(crypto.randomUUID())

async function load() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    activeKey.value = unwrapData(await recoveryApi.getPublicKey())
  } catch (error) {
    activeKey.value = null
    // "No active key" is expected before the first registration — not a red banner case.
    const message = apiErrorMessage(error, 'Failed to load recovery public key')
    if (!/no active recovery public key/i.test(message)) {
      errorMessage.value = message
    }
  } finally {
    isLoading.value = false
  }
}

async function register() {
  const pem = publicKeyPem.value.trim()
  if (!pem) {
    errorMessage.value = 'Paste an RSA public key PEM.'
    return
  }
  isSaving.value = true
  errorMessage.value = ''
  actionMessage.value = ''
  try {
    const data = unwrapData(
      await recoveryApi.registerPublicKey({
        key_id: keyId.value.trim() || crypto.randomUUID(),
        public_key_pem: pem.endsWith('\n') ? pem : `${pem}\n`,
      }),
    )
    activeKey.value = data.key
    actionMessage.value = data.created
      ? `Registered recovery key${data.rotated_keys ? `; rotated ${data.rotated_keys} previous key(s)` : ''}.`
      : 'Recovery key already registered (idempotent).'
    publicKeyPem.value = ''
    keyId.value = crypto.randomUUID()
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not register the recovery public key')
  } finally {
    isSaving.value = false
  }
}

async function revoke() {
  if (!activeKey.value) return
  if (
    !window.confirm(
      'Revoke the active recovery public key? New uploads will fail until a replacement is registered.',
    )
  ) {
    return
  }
  isSaving.value = true
  errorMessage.value = ''
  actionMessage.value = ''
  try {
    const data = unwrapData(await recoveryApi.revokePublicKey(activeKey.value.key_id))
    actionMessage.value = data.changed
      ? 'Recovery public key revoked.'
      : 'Recovery public key was already revoked.'
    await load()
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not revoke the recovery public key')
  } finally {
    isSaving.value = false
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
        <h2 class="text-lg font-semibold text-foreground">Recovery public key</h2>
        <p class="text-sm text-muted-foreground">
          Register the offline recovery key's public half. The matching private key must never be
          pasted into this browser.
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

    <p v-if="actionMessage" class="mb-3 text-sm text-muted-foreground">{{ actionMessage }}</p>
    <p v-if="errorMessage" class="mb-3 text-sm text-destructive" role="alert">{{ errorMessage }}</p>

    <div
      v-if="activeKey"
      class="mb-6 rounded-xl border border-border bg-card p-5"
    >
      <div class="flex items-start gap-3">
        <div class="rounded-lg bg-primary/10 p-2">
          <KeyRound class="h-5 w-5 text-primary" />
        </div>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-foreground">
            Active key · {{ activeKey.status }} · {{ activeKey.key_size_bits }}-bit
          </p>
          <p class="mt-1 font-mono text-xs break-all text-muted-foreground">
            {{ activeKey.key_id }}
          </p>
          <p class="mt-2 font-mono text-xs break-all text-foreground">
            fingerprint {{ activeKey.fingerprint }}
          </p>
          <button
            type="button"
            class="mt-4 inline-flex h-9 items-center gap-2 rounded-md border border-destructive/40 px-3 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
            :disabled="isSaving || activeKey.status !== 'ACTIVE'"
            @click="revoke"
          >
            <Loader2 v-if="isSaving" class="h-4 w-4 animate-spin" />
            Revoke active key
          </button>
        </div>
      </div>
    </div>
    <p v-else-if="!isLoading" class="mb-6 text-sm text-muted-foreground">
      No active recovery public key is configured. Uploads that wrap to recovery will fail until one
      is registered.
    </p>

    <div class="rounded-xl border border-border bg-card p-5">
      <h3 class="text-sm font-semibold text-foreground">Register or rotate</h3>
      <label class="mt-4 block text-xs font-medium uppercase tracking-wide text-muted-foreground" for="recovery-key-id">
        Key id (UUID)
      </label>
      <input
        id="recovery-key-id"
        v-model="keyId"
        type="text"
        class="mt-1.5 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm"
      />
      <label class="mt-4 block text-xs font-medium uppercase tracking-wide text-muted-foreground" for="recovery-pem">
        Public key PEM
      </label>
      <textarea
        id="recovery-pem"
        v-model="publicKeyPem"
        rows="8"
        class="mt-1.5 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
        placeholder="-----BEGIN PUBLIC KEY-----&#10;...&#10;-----END PUBLIC KEY-----"
      />
      <button
        type="button"
        class="mt-4 inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        :disabled="isSaving"
        @click="register"
      >
        <Loader2 v-if="isSaving" class="h-4 w-4 animate-spin" />
        Register public key
      </button>
    </div>
  </div>
</template>
