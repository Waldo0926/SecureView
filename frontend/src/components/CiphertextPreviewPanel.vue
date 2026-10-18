<script setup lang="ts">
import { AlertTriangle, CheckCircle, FileLock2, Loader2, Lock } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { fileApi } from '@/api/file_api'
import { apiErrorMessage } from '@/api/http'
import { unwrapData } from '@/api/types'
import type { CiphertextPreviewOut } from '@/api/types'
import {
  checkFileHeader,
  describeSizes,
  exactBytes,
  hexDumpRows,
} from '@/utils/ciphertext-preview'

/**
 * What the server actually holds for one file: the first bytes of the stored ciphertext, the
 * exact sizes, and its recorded SHA-256. It exists to make "your file is encrypted" something
 * a person can look at instead of take on trust, for owned and received files alike.
 */
const props = defineProps<{ fileId: string; fileName: string }>()
const emit = defineEmits<{ (event: 'download-encrypted'): void }>()

const preview = ref<CiphertextPreviewOut | null>(null)
const errorMessage = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    preview.value = unwrapData((await fileApi.ciphertextPreview(props.fileId)))
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not load the encrypted preview')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="rounded-lg border border-border bg-secondary/40 p-3 text-sm sm:p-4" data-testid="ciphertext-preview">
    <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div class="flex min-w-0 items-start gap-2">
        <Lock class="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div class="min-w-0">
          <p class="font-medium text-foreground">What the server stores for this file</p>
          <p class="text-xs text-muted-foreground">
            The start of the encrypted data, exactly as saved. It is not your file's content, and nothing here is decrypted.
          </p>
        </div>
      </div>
      <button
        type="button"
        class="inline-flex h-10 w-fit shrink-0 items-center gap-1.5 rounded-md border border-border px-3 text-xs text-foreground hover:bg-secondary sm:h-8 sm:px-2.5"
        @click="emit('download-encrypted')"
      >
        <FileLock2 class="h-3.5 w-3.5" />
        Download encrypted file
      </button>
    </div>

    <p v-if="loading" class="flex items-center gap-2 text-muted-foreground">
      <Loader2 class="h-4 w-4 animate-spin" /> Reading the stored bytes…
    </p>
    <p v-else-if="errorMessage" class="text-destructive" role="alert">{{ errorMessage }}</p>

    <template v-else-if="preview">
      <dl class="grid gap-x-6 gap-y-2 sm:grid-cols-3">
        <div>
          <dt class="text-xs text-muted-foreground">Algorithm</dt>
          <dd class="font-medium text-foreground">{{ preview.encryption_algorithm }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">Original file size</dt>
          <dd class="font-mono text-foreground" data-testid="preview-original-size">{{ exactBytes(preview.plaintext_size) }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">Stored (encrypted) size</dt>
          <dd class="font-mono text-foreground" data-testid="preview-encrypted-size">{{ exactBytes(preview.ciphertext_size) }}</dd>
        </div>
        <div class="sm:col-span-3">
          <dt class="text-xs text-muted-foreground">SHA-256 of the stored bytes, recorded at upload</dt>
          <dd translate="no" class="break-all font-mono text-xs text-foreground">{{ preview.ciphertext_sha256 }}</dd>
        </div>
      </dl>

      <p
        class="mt-3 flex items-start gap-2 rounded-md px-3 py-2 text-xs"
        :class="describeSizes(preview).sameLength ? 'bg-primary/5 text-muted-foreground' : 'bg-destructive/10 text-destructive'"
      >
        <CheckCircle v-if="describeSizes(preview).sameLength" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
        <AlertTriangle v-else class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{{ describeSizes(preview).explanation }}</span>
      </p>

      <p class="mt-4 mb-1 text-xs text-muted-foreground">
        First {{ preview.sample_length }} bytes (hexadecimal, with the printable characters on the right)
      </p>
      <div class="overflow-x-auto rounded-md border border-border bg-background p-3">
        <table class="font-mono text-xs leading-5">
          <tbody>
            <tr v-for="row in hexDumpRows(preview.sample_hex)" :key="row.offset">
              <td class="pr-4 text-muted-foreground">{{ row.offset }}</td>
              <td class="pr-4 whitespace-pre text-foreground">{{ row.hex }}</td>
              <td class="whitespace-pre text-muted-foreground">{{ row.ascii }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template v-for="check in [checkFileHeader(fileName, preview.sample_hex)]" :key="check.kind">
        <p v-if="check.kind === 'hidden'" class="mt-3 flex items-start gap-2 text-xs text-muted-foreground" data-testid="preview-header-hidden">
          <CheckCircle class="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
          <span>
            An unencrypted file of this type begins with <span class="font-mono">{{ check.expected }}</span> ({{ check.label }}).
            These bytes do not, so the original's header is not visible in storage.
          </span>
        </p>
        <p v-else-if="check.kind === 'exposed'" class="mt-3 flex items-start gap-2 text-xs text-destructive" role="alert" data-testid="preview-header-exposed">
          <AlertTriangle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            These bytes begin like {{ check.label }} (<span class="font-mono">{{ check.expected }}</span>), as an unencrypted file would. Do not trust this file's encryption and report it.
          </span>
        </p>
      </template>

      <p class="mt-3 text-xs text-muted-foreground">
        This sample is read straight from storage and is not verified here. The status badge and the integrity check say whether the stored bytes still match the recorded SHA-256.
        To look at all of it yourself, use <em>Download encrypted file</em> and open it in a hex viewer.
      </p>
    </template>
  </div>
</template>
