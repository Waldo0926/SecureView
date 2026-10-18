<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { Loader2, LifeBuoy } from 'lucide-vue-next'

import { apiErrorMessage } from '@/api/http'
import { keyApi } from '@/api/key_api'
import { recoveryApi } from '@/api/recovery_api'
import { unwrapData } from '@/api/types'

const props = defineProps<{
  fileId: string
  filename?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'requested'): void
}>()

const reason = ref('')
const errorMessage = ref('')
const isSubmitting = ref(false)
const field = ref<HTMLTextAreaElement | null>(null)

onMounted(async () => {
  await nextTick()
  field.value?.focus()
})

async function submit() {
  const trimmed = reason.value.trim()
  if (!trimmed) {
    errorMessage.value = 'Explain why recovery is needed.'
    return
  }
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    const bundle = unwrapData(await keyApi.myBundle())
    await recoveryApi.createRequest({
      file_id: props.fileId,
      reason: trimmed,
      target_key_id: bundle.key.key_id,
    })
    emit('requested')
    emit('close')
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not create the recovery request')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="emit('close')">
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="recovery-request-title"
      class="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-xl border border-border bg-card p-6 shadow-lg"
    >
      <div class="flex items-start gap-3">
        <div class="rounded-lg bg-primary/10 p-2">
          <LifeBuoy class="h-5 w-5 text-primary" />
        </div>
        <div class="min-w-0 flex-1">
          <h2 id="recovery-request-title" class="text-lg font-semibold text-foreground">
            Request file recovery
          </h2>
          <p class="mt-1 text-sm text-muted-foreground">
            Ask a recovery officer to rewrap
            <span translate="no" class="font-medium text-foreground [overflow-wrap:anywhere]">{{ filename ?? 'this file' }}</span>
            to your current account key. The recovery private key stays offline.
          </p>
        </div>
      </div>

      <label class="mt-5 block text-sm font-medium text-foreground" for="recovery-reason">
        Reason
      </label>
      <textarea
        id="recovery-reason"
        ref="field"
        v-model="reason"
        rows="4"
        maxlength="2000"
        class="mt-1.5 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        placeholder="e.g. Lost encryption passphrase; retained key file still available after reset."
      />

      <p v-if="errorMessage" class="mt-2 text-sm text-destructive" role="alert">{{ errorMessage }}</p>

      <div class="mt-5 flex justify-end gap-2">
        <button
          type="button"
          class="h-9 rounded-md px-4 text-sm text-foreground hover:bg-secondary"
          :disabled="isSubmitting"
          @click="emit('close')"
        >
          Cancel
        </button>
        <button
          type="button"
          class="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          :disabled="isSubmitting"
          @click="submit"
        >
          <Loader2 v-if="isSubmitting" class="h-4 w-4 animate-spin" />
          Submit request
        </button>
      </div>
    </div>
  </div>
</template>
