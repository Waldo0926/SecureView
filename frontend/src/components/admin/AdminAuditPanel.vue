<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Shield } from 'lucide-vue-next'

import { auditApi } from '@/api/audit_api'
import { apiErrorMessage } from '@/api/http'
import { unwrapData } from '@/api/types'

const chainState = ref<'unknown' | 'valid' | 'invalid' | 'error'>('unknown')
const checkedEntries = ref(0)
const firstInvalid = ref<number | null>(null)
const isVerifying = ref(false)
const errorMessage = ref('')

async function verify() {
  isVerifying.value = true
  errorMessage.value = ''
  try {
    const data = unwrapData(await auditApi.verifyChain())
    chainState.value = data.valid ? 'valid' : 'invalid'
    checkedEntries.value = data.checked_entries ?? 0
    firstInvalid.value = data.first_invalid_position ?? null
  } catch (error) {
    chainState.value = 'error'
    errorMessage.value = apiErrorMessage(error, 'Chain verification failed')
  } finally {
    isVerifying.value = false
  }
}

onMounted(() => {
  void verify()
})
</script>

<template>
  <div>
    <div class="mb-4">
      <h2 class="text-lg font-semibold text-foreground">Audit chain verification</h2>
      <p class="text-sm text-muted-foreground">
        Recomputes every hash in the audit table and checks the singleton chain head. ADMIN only —
        an ordinary user opening the Activity Log does not run this check.
      </p>
    </div>

    <div class="rounded-xl border border-border bg-card p-6">
      <div class="flex flex-wrap items-center gap-3">
        <button
          type="button"
          class="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          :disabled="isVerifying"
          @click="verify"
        >
          <Loader2 v-if="isVerifying" class="h-4 w-4 animate-spin" />
          <RefreshCw v-else class="h-4 w-4" />
          Verify hash chain
        </button>
        <span
          v-if="chainState === 'valid'"
          class="inline-flex items-center gap-1.5 text-sm text-primary"
        >
          <CheckCircle2 class="h-4 w-4" />
          Valid · {{ checkedEntries }} entries checked
        </span>
        <span
          v-else-if="chainState === 'invalid'"
          class="inline-flex items-center gap-1.5 text-sm font-medium text-destructive"
        >
          <AlertTriangle class="h-4 w-4" />
          Broken
          <template v-if="firstInvalid !== null">
            · first invalid at position {{ firstInvalid }}
          </template>
          · {{ checkedEntries }} entries checked
        </span>
        <span
          v-else-if="chainState === 'unknown'"
          class="inline-flex items-center gap-1.5 text-sm text-muted-foreground"
        >
          <Shield class="h-4 w-4" />
          Not verified yet
        </span>
      </div>
      <p v-if="errorMessage" class="mt-3 text-sm text-destructive" role="alert">{{ errorMessage }}</p>
    </div>
  </div>
</template>
