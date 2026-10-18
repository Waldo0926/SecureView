<script setup lang="ts">
import PageHeader from '@/components/securfile/PageHeader.vue'
import { AlertTriangle, Check, FileIcon, Lock, RefreshCw, Upload, X } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiErrorMessage } from '@/api/http'
import { formatFileSize } from '@/api/types'
import {
  DEFAULT_ENCRYPTION_ALGORITHM,
  type EncryptionAlgorithm,
  supportedEncryptionAlgorithms,
} from '@/crypto/primitives'
import EncryptionProgress from '@/components/EncryptionProgress.vue'
import {
  classifyUploadSize,
  encryptAndUpload,
  fetchUploadRecipients,
  filesStillToUpload,
  MAX_UPLOAD_BYTES,
  type UploadEvent,
  type UploadRecipients,
  type UploadStage,
} from '@/crypto/upload'

type UploadStatus = 'pending' | 'encrypting' | 'done' | 'failed'

interface UploadedFile {
  raw: File
  name: string
  size: number
  type: string
  status: UploadStatus
  error: string
}

const router = useRouter()
const files = ref<UploadedFile[]>([])
const isEncrypting = ref(false)
const isEncrypted = ref(false)
const errorMessage = ref('')
const dragActive = ref(false)
const recoveryFingerprint = ref('')
const algorithm = ref<EncryptionAlgorithm>(DEFAULT_ENCRYPTION_ALGORITHM)
const algorithmChoices = ref<EncryptionAlgorithm[]>([DEFAULT_ENCRYPTION_ALGORITHM])

/**
 * Every suite, on every browser.
 *
 * AES-192-GCM is specified but absent from some WebCrypto implementations (Chromium), so the
 * crypto layer probes once and performs it in the same JavaScript library as the SIV and
 * ChaCha suites where the platform refuses it. The probe also confirms AES-256-GCM, which
 * has no fallback; if that fails the list stays at the default and the upload itself
 * explains why.
 */
onMounted(async () => {
  try {
    algorithmChoices.value = await supportedEncryptionAlgorithms()
  } catch {
    // Leaving the default in place is right: if the probe cannot run, encryption itself
    // will fail with a message that explains far more than a broken dropdown would.
  }
})

/**
 * A short grade after each name, so someone who does not know the ciphers can still pick one.
 * Every suite here is safe; "Max" is a 256-bit key (or ChaCha20, which only has 256), "High" is
 * a shorter AES key that is still secure, not a weak option.
 */
const ALGORITHM_LABELS: Record<EncryptionAlgorithm, string> = {
  'AES-256-GCM': 'AES-256-GCM · Max · Recommended',
  'AES-256-GCM-SIV': 'AES-256-GCM-SIV · Max · Extra safety net',
  'XChaCha20-Poly1305': 'XChaCha20-Poly1305 · Max · Long nonce',
  'ChaCha20-Poly1305': 'ChaCha20-Poly1305 · Max · Fast on phones',
  'AES-192-GCM': 'AES-192-GCM · High',
  'AES-128-GCM': 'AES-128-GCM · High · Widely used',
}

const ALGORITHM_NOTES: Record<EncryptionAlgorithm, string> = {
  'AES-256-GCM':
    'The default and our recommendation. Most computers and phones have AES built into the processor, so it is fast, and it is the algorithm the recovery process is tested with.',
  'AES-256-GCM-SIV':
    'AES-256 with an extra safety net (RFC 8452). If a random nonce were ever repeated, an attacker would only learn that the same file was encrypted twice, never its contents. Runs in a JavaScript library, so it is slower than the default on very large files.',
  'XChaCha20-Poly1305':
    'ChaCha20-Poly1305 with a 24-byte nonce, long enough to pick at random without ever repeating. What libsodium recommends, and a good choice on devices without AES hardware.',
  'ChaCha20-Poly1305':
    'A stream cipher authenticated by Poly1305, built differently from AES rather than with a different key length. It is designed to be fast in plain software, which is why phones without AES hardware use it. Here it runs in a JavaScript library.',
  'AES-192-GCM':
    'AES with its middle key length. Rarely used in practice. Chrome and Edge do not offer it in WebCrypto, so there it runs in a JavaScript library and is slower; the encrypted file is the same either way.',
  'AES-128-GCM':
    'AES with its shortest key. Still considered secure and widely used in HTTPS. Pick it if you need to match a system that expects 128-bit keys.',
}

/** A file over the limit can never upload, so the batch cannot start until it is removed. */
const hasOversizeFile = computed(() =>
  files.value.some((file) => file.status === 'pending' && classifyUploadSize(file.size) === 'too-large'),
)

interface Progress {
  fileName: string
  fileSize: number
  algorithm: string
  stage: UploadStage | null
  durations: Partial<Record<UploadStage, number>>
  uploadFraction: number
  plaintextHead: Uint8Array | null
  ciphertextHead: Uint8Array | null
  done: boolean
}

const progress = ref<Progress | null>(null)

/**
 * Encrypting a few MB takes tens of milliseconds, so without a pause every step would flash
 * past and the page would look as if nothing happened. Each step stays on screen at least
 * this long; the times shown are the measured work alone. Large batches skip the pause.
 */
const MIN_STAGE_MS = 350
const PACED_BATCH_LIMIT = 5

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

const startProgress = (file: UploadedFile): Progress => ({
  fileName: file.name,
  fileSize: file.size,
  algorithm: algorithm.value,
  stage: null,
  durations: {},
  uploadFraction: 0,
  plaintextHead: null,
  ciphertextHead: null,
  done: false,
})

const progressListener = (paced: boolean) => {
  let shownAt = 0
  return async (event: UploadEvent) => {
    const current = progress.value
    if (!current) return
    if (event.type === 'stage') {
      current.stage = event.stage
      shownAt = performance.now()
    } else if (event.type === 'timed') {
      const remaining = MIN_STAGE_MS - (performance.now() - shownAt)
      if (paced && remaining > 0 && event.stage !== 'upload') await sleep(remaining)
      current.durations = { ...current.durations, [event.stage]: event.ms }
    } else if (event.type === 'sample') {
      current.plaintextHead = event.plaintextHead
      current.ciphertextHead = event.ciphertextHead
    } else {
      current.uploadFraction = event.fraction
    }
  }
}

const toUploadedFile = (file: File): UploadedFile => ({
  raw: file,
  name: file.name,
  size: file.size,
  type: file.type || 'unknown',
  status: 'pending',
  error: '',
})

/**
 * The list cannot change while a batch runs. The batch works from the files it started with,
 * so a file removed mid-run was still uploaded, and one added mid-run was left pending under
 * a green "Encryption Complete".
 */
const addFiles = (fileList: FileList) => {
  if (isEncrypting.value) return
  files.value = [...files.value, ...Array.from(fileList, toUploadedFile)]
  isEncrypted.value = false
  errorMessage.value = ''
}

const handleDrag = (e: DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  if (isEncrypting.value) return
  dragActive.value = e.type === 'dragenter' || e.type === 'dragover'
}

const handleDrop = (e: DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  dragActive.value = false
  if (!e.dataTransfer?.files?.length) return
  addFiles(e.dataTransfer.files)
}

const handleFileInput = (e: Event) => {
  const target = e.target as HTMLInputElement
  if (target.files?.length) addFiles(target.files)
  // Cleared so choosing the same file again, after removing it, still fires a change.
  target.value = ''
}

const removeFile = (index: number) => {
  if (isEncrypting.value) return
  files.value = files.value.filter((_, i) => i !== index)
  isEncrypted.value = false
}

/**
 * Encrypt each file in the browser, then upload ciphertext only.
 *
 * The recipient public keys are fetched once for the whole batch rather than per file.
 * Each file reports its own outcome, because one rejected filename should not hide the
 * files that did upload. Retrying after a failure sends only the files that failed.
 */
const handleEncrypt = async () => {
  // Only files that have not uploaded yet. Before, a second press after "Encryption Complete"
  // went round the whole list again and uploaded every file a second time.
  const queue = filesStillToUpload(files.value)
  if (!queue.length || isEncrypting.value || hasOversizeFile.value) return
  isEncrypting.value = true
  errorMessage.value = ''
  isEncrypted.value = false

  let recipients: UploadRecipients
  try {
    recipients = await fetchUploadRecipients()
    recoveryFingerprint.value = recipients.recoveryKeyFingerprint
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not load the encryption keys')
    isEncrypting.value = false
    return
  }

  let failures = 0
  const paced = queue.length <= PACED_BATCH_LIMIT
  for (const file of queue) {
    file.status = 'encrypting'
    file.error = ''
    progress.value = startProgress(file)
    try {
      await encryptAndUpload(file.raw, recipients, algorithm.value, progressListener(paced))
      progress.value.stage = null
      progress.value.done = true
      file.status = 'done'
    } catch (error) {
      failures += 1
      file.status = 'failed'
      file.error = apiErrorMessage(error, 'Encryption failed')
      // The receipt would otherwise stay on the failed step with its spinner running; the
      // file's own row says what went wrong.
      progress.value = null
    }
  }

  isEncrypting.value = false
  // Complete only when nothing is left to send, not merely when this run had no failures.
  isEncrypted.value = failures === 0 && filesStillToUpload(files.value).length === 0
  if (failures > 0) {
    errorMessage.value = `${failures} of ${queue.length} file(s) failed. See each file below.`
  }
}

const goToFiles = () => {
  router.push('/files')
}
</script>

<template>
  <section id="encrypt" class="product-page">
    <div class="page-container">
      <PageHeader
        long
        title="Encrypt Your Files"
        subtitle="Files are encrypted in your browser with the algorithm you choose below (AES-256-GCM by default). Only ciphertext is uploaded; the server never receives your readable file or its key."
      />
      <div class="rounded-xl bg-card border border-border p-6" data-testid="encrypt-card">
        <!-- minmax(0, 1fr): a grid track otherwise never gets narrower than its widest unbreakable
             content, and the cipher dropdown's longest option pushed a phone sideways. -->
        <div class="grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-8">
          <!-- The drop zone grows to the height of the Encryption column, so its bottom edge lines
               up with the Start Encryption button instead of stopping short of it. -->
          <div class="flex flex-col">
            <h2 class="text-foreground mb-4 block text-lg font-medium">Upload Files</h2>
            <div
              :class="`flex min-h-[18rem] flex-1 flex-col items-center justify-center border-2 border-dashed rounded-xl p-8 text-center transition-colors ${dragActive ? 'border-foreground bg-secondary' : 'border-input bg-background hover:border-foreground/50'} ${isEncrypting ? 'opacity-50' : ''}`"
              :aria-disabled="isEncrypting"
              @dragenter="handleDrag"
              @dragleave="handleDrag"
              @dragover="handleDrag"
              @drop="handleDrop"
            >
              <Upload class="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <p class="text-foreground mb-2">Drag files here</p>
              <p class="text-muted-foreground text-sm mb-4">or</p>
              <label
                class="inline-flex h-9 px-4 items-center rounded-md border border-border transition-colors"
                :class="isEncrypting ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-secondary'"
              >
                <input type="file" multiple class="hidden" :disabled="isEncrypting" @change="handleFileInput" />
                <span>Select Files</span>
              </label>
            </div>
            <div v-if="files.length" class="mt-4 space-y-2">
              <div v-for="(file, index) in files" :key="`${file.name}-${index}`" class="flex items-center justify-between gap-2 p-3 rounded-lg bg-secondary/50">
                <div class="flex min-w-0 items-center gap-3">
                  <FileIcon class="h-5 w-5 shrink-0 text-muted-foreground" />
                  <div class="min-w-0">
                    <p translate="no" class="text-sm text-foreground [overflow-wrap:anywhere]">{{ file.name }}</p>
                    <p class="text-xs text-muted-foreground">{{ formatFileSize(file.size) }}</p>
                    <p v-if="file.status === 'failed'" class="text-sm text-destructive mt-1">{{ file.error }}</p>
                    <p
                      v-else-if="file.status === 'pending' && classifyUploadSize(file.size) === 'too-large'"
                      class="text-xs text-destructive mt-1"
                      data-testid="upload-too-large"
                    >
                      Over the {{ formatFileSize(MAX_UPLOAD_BYTES) }} limit. Remove it to continue.
                    </p>
                    <p
                      v-else-if="file.status === 'pending' && classifyUploadSize(file.size) === 'large'"
                      class="mt-1 flex items-start gap-1 text-xs text-amber-600 dark:text-amber-400"
                      data-testid="upload-large-warning"
                    >
                      <AlertTriangle class="mt-0.5 h-3 w-3 shrink-0" />
                      <span>Large file. Encrypting needs about four times its size in memory, so it may fail on a phone or with many tabs open.</span>
                    </p>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <RefreshCw v-if="file.status === 'encrypting'" class="h-4 w-4 animate-spin text-primary" />
                  <Check v-else-if="file.status === 'done'" class="h-4 w-4 text-success" />
                  <button
                    v-else-if="!isEncrypting"
                    type="button"
                    class="h-8 w-8 inline-flex items-center justify-center rounded-md hover:bg-secondary"
                    aria-label="Remove file"
                    title="Remove file"
                    @click="removeFile(index)"
                  >
                    <X class="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div>
            <h2 class="text-foreground mb-4 block text-lg font-medium">Encryption</h2>
            <div class="space-y-4">
              <div class="p-3 rounded-lg bg-secondary/50 border border-border space-y-2">
                <div class="flex justify-between text-sm items-center gap-3">
                  <label for="content-algorithm" class="shrink-0 text-muted-foreground">File contents</label>
                  <!-- A select is as wide as its longest option, and "XChaCha20-Poly1305" pushed a
                       360 px phone 10 px sideways. min-w-0 lets it shrink with the row instead.
                       text-align-last is what centres the closed select's text in Chrome and Firefox. -->
                  <select
                    id="content-algorithm"
                    v-model="algorithm"
                    :disabled="isEncrypting"
                    class="h-10 min-w-0 max-w-full text-center [text-align-last:center] font-mono text-sm text-foreground bg-transparent border border-input rounded-md px-2 py-1 disabled:opacity-50"
                  >
                    <option v-for="choice in algorithmChoices" :key="choice" :value="choice">
                      {{ ALGORITHM_LABELS[choice] }}
                    </option>
                  </select>
                </div>
                <!-- What the chosen algorithm is good at, so the grade in the list is not the only hint. -->
                <div class="rounded-md border border-border bg-background p-3" data-testid="algorithm-detail">
                  <p translate="no" class="font-mono text-sm text-foreground">{{ algorithm }}</p>
                  <p class="mt-1 text-sm text-muted-foreground">{{ ALGORITHM_NOTES[algorithm] }}</p>
                </div>
                <div class="flex justify-between text-sm">
                  <span class="text-muted-foreground">File key wrapping</span>
                  <span
                    class="cursor-help font-mono text-foreground underline decoration-dotted decoration-muted-foreground underline-offset-4"
                    title="RSA public-key encryption with OAEP padding. SHA-256 is the hash OAEP uses inside that padding; it is not a checksum of your file."
                  >RSA-OAEP (SHA-256)</span>
                </div>
                <div class="flex justify-between text-sm">
                  <span class="text-muted-foreground">Maximum size</span>
                  <span class="text-foreground">{{ formatFileSize(MAX_UPLOAD_BYTES) }}</span>
                </div>
              </div>
              <p class="text-sm text-muted-foreground">
                A fresh key is generated per file and wrapped, with
                RSA-OAEP, to your public key and to the recovery key. (SHA-256 appears in that name
                because OAEP uses it inside its padding; it is not a checksum of your file.) Neither
                the file key nor your readable file leaves this browser unprotected.
              </p>
              <p class="text-sm text-muted-foreground">
                The choice is recorded with the file and is covered by its authentication tag, so
                each file is always read back under the algorithm it was written with. Files
                already uploaded are unaffected.
              </p>
              <div v-if="recoveryFingerprint" class="p-3 rounded-lg bg-secondary/50 border border-border">
                <p class="text-sm text-muted-foreground mb-1">
                  Recovery key fingerprint &mdash; verify this out of band before trusting an upload.
                </p>
                <p class="text-xs font-mono break-all text-foreground">{{ recoveryFingerprint }}</p>
              </div>
            </div>

            <EncryptionProgress
              v-if="progress"
              class="mt-6"
              v-bind="progress"
              :dismissible="!isEncrypting"
              @dismiss="progress = null"
            />

            <div class="mt-8">
              <!-- Once everything has uploaded this is a status, not a button: pressing it used to
                   upload the same files again. Adding a file brings the button back. -->
              <div
                v-if="isEncrypted"
                role="status"
                class="w-full h-12 inline-flex items-center justify-center gap-2 rounded-lg bg-[#7ce0b5] font-medium text-[#07090d]"
                data-testid="encryption-complete"
              >
                <Check class="h-4 w-4" /> Encryption Complete
              </div>
              <button
                v-else
                :disabled="!files.length || isEncrypting || hasOversizeFile"
                class="w-full h-12 inline-flex items-center justify-center gap-2 rounded-lg bg-primary font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                data-testid="start-encryption"
                @click="handleEncrypt"
              >
                <template v-if="isEncrypting"><RefreshCw class="h-4 w-4 animate-spin" /> Encrypting...</template>
                <template v-else><Lock class="h-4 w-4" /> Start Encryption</template>
              </button>
              <button v-if="isEncrypted" class="w-full h-11 mt-4 inline-flex items-center justify-center gap-2 rounded-md border border-border hover:bg-secondary" @click="goToFiles">
                View Encrypted Files
              </button>
              <p v-if="errorMessage" class="text-sm text-destructive mt-3">{{ errorMessage }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
