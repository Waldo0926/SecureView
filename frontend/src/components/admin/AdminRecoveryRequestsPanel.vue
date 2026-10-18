<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Download, LifeBuoy, Loader2, RefreshCw } from 'lucide-vue-next'

import { apiErrorMessage } from '@/api/http'
import {
  recoveryApi,
  type RecoveryExecutionPackage,
  type RecoveryRequestOut,
} from '@/api/recovery_api'
import { unwrapData } from '@/api/types'
import { formatSiteDateTime } from '@/utils/site-time'

defineProps<{
  /** When true, show approve / reject / execute controls. */
  canReview: boolean
}>()

const requests = ref<RecoveryRequestOut[]>([])
const total = ref(0)
const isLoading = ref(false)
const errorMessage = ref('')
const actionMessage = ref('')
const busyId = ref<string | null>(null)
const rejectReason = ref<Record<string, string>>({})
const executePackage = ref<Record<string, RecoveryExecutionPackage | null>>({})
const wrappedKeyInput = ref<Record<string, string>>({})
const page = ref(1)
const PAGE_SIZE = 50

function formatTimestamp(value: string | null): string {
  if (!value) return '—'
  return formatSiteDateTime(value)
}

function shortId(value: string): string {
  return value.slice(0, 8)
}

async function load() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const data = unwrapData(
      await recoveryApi.listRequests({ page: page.value, page_size: PAGE_SIZE }),
    )
    requests.value = data.requests
    total.value = data.total
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Failed to load recovery requests')
  } finally {
    isLoading.value = false
  }
}

async function approve(request: RecoveryRequestOut) {
  busyId.value = request.request_id
  actionMessage.value = ''
  errorMessage.value = ''
  try {
    unwrapData(await recoveryApi.approve(request.request_id))
    actionMessage.value = `Approved request ${shortId(request.request_id)}…`
    await load()
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not approve the request')
  } finally {
    busyId.value = null
  }
}

async function reject(request: RecoveryRequestOut) {
  const reason = (rejectReason.value[request.request_id] ?? '').trim()
  if (!reason) {
    errorMessage.value = 'A rejection reason is required.'
    return
  }
  busyId.value = request.request_id
  actionMessage.value = ''
  errorMessage.value = ''
  try {
    unwrapData(await recoveryApi.reject(request.request_id, reason))
    actionMessage.value = `Rejected request ${shortId(request.request_id)}…`
    await load()
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not reject the request')
  } finally {
    busyId.value = null
  }
}

async function cancel(request: RecoveryRequestOut) {
  busyId.value = request.request_id
  actionMessage.value = ''
  errorMessage.value = ''
  try {
    unwrapData(await recoveryApi.cancel(request.request_id))
    actionMessage.value = `Cancelled request ${shortId(request.request_id)}…`
    await load()
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not cancel the request')
  } finally {
    busyId.value = null
  }
}

async function loadPackage(request: RecoveryRequestOut) {
  busyId.value = request.request_id
  errorMessage.value = ''
  try {
    const pkg = unwrapData(await recoveryApi.getExecutionPackage(request.request_id))
    executePackage.value = { ...executePackage.value, [request.request_id]: pkg }
    wrappedKeyInput.value = { ...wrappedKeyInput.value, [request.request_id]: '' }
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not load the execution package')
  } finally {
    busyId.value = null
  }
}

function downloadPackage(requestId: string) {
  const pkg = executePackage.value[requestId]
  if (!pkg) return
  const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `recovery-execution-${requestId.slice(0, 8)}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

async function execute(request: RecoveryRequestOut) {
  const pkg = executePackage.value[request.request_id]
  const wrapped = (wrappedKeyInput.value[request.request_id] ?? '').trim()
  if (!pkg) {
    errorMessage.value = 'Load the execution package first.'
    return
  }
  if (!wrapped) {
    errorMessage.value =
      'Paste the base64 file key rewrapped to the requester target public key (offline unwrap).'
    return
  }
  busyId.value = request.request_id
  actionMessage.value = ''
  errorMessage.value = ''
  try {
    unwrapData(
      await recoveryApi.execute(request.request_id, {
        wrapped_file_key: wrapped,
        recovery_key_id: pkg.recovery_key.key_id,
        target_key_id: pkg.target_key.key_id,
      }),
    )
    actionMessage.value = `Executed recovery for ${shortId(request.request_id)}…`
    executePackage.value = { ...executePackage.value, [request.request_id]: null }
    await load()
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not execute the recovery request')
  } finally {
    busyId.value = null
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
        <h2 class="text-lg font-semibold text-foreground">Recovery requests</h2>
        <p class="text-sm text-muted-foreground">
          <template v-if="canReview">
            Review pending requests, then take the execution package offline to rewrap with the
            recovery private key. Never paste that private key here.
          </template>
          <template v-else>
            Your recovery requests for files you can access. Cancel a pending request if it is no
            longer needed.
          </template>
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
    <p class="mb-3 text-xs text-muted-foreground">{{ total }} request(s) total</p>

    <div v-if="isLoading && !requests.length" class="py-10 text-center text-sm text-muted-foreground">
      Loading recovery requests…
    </div>
    <div
      v-else-if="!requests.length"
      class="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-card px-6 py-16 text-center"
      data-testid="recovery-empty"
    >
      <LifeBuoy class="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      <p class="text-base font-medium text-foreground">No recovery requests yet</p>
      <p class="text-sm text-muted-foreground">
        When a file needs to be recovered, the request appears here with its status.
      </p>
    </div>

    <ul v-else class="space-y-4">
      <li
        v-for="request in requests"
        :key="request.request_id"
        class="rounded-xl border border-border bg-card p-5"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="text-sm font-semibold text-foreground">
              {{ request.status }}
              <span class="font-normal text-muted-foreground">
                · file {{ shortId(request.file_id) }}…
              </span>
            </p>
            <p translate="no" class="mt-1 text-sm text-foreground">{{ request.reason }}</p>
            <p v-if="request.rejection_reason" class="mt-1 text-sm text-destructive">
              Rejection: {{ request.rejection_reason }}
            </p>
            <p class="mt-2 text-xs text-muted-foreground">
              Created {{ formatTimestamp(request.created_at) }}
              · expires {{ formatTimestamp(request.expires_at) }}
              · request {{ request.request_id }}
            </p>
          </div>
        </div>

        <div v-if="canReview && request.status === 'PENDING'" class="mt-4 space-y-3 border-t border-border pt-4">
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              :disabled="busyId === request.request_id"
              @click="approve(request)"
            >
              <Loader2 v-if="busyId === request.request_id" class="h-4 w-4 animate-spin" />
              Approve
            </button>
          </div>
          <div class="flex flex-col gap-2 sm:flex-row">
            <input
              v-model="rejectReason[request.request_id]"
              type="text"
              maxlength="2000"
              placeholder="Rejection reason"
              class="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
            />
            <button
              type="button"
              class="inline-flex h-9 items-center gap-2 rounded-md border border-destructive/40 px-3 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
              :disabled="busyId === request.request_id"
              @click="reject(request)"
            >
              Reject
            </button>
          </div>
        </div>

        <div
          v-else-if="canReview && request.status === 'APPROVED'"
          class="mt-4 space-y-3 border-t border-border pt-4"
        >
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-secondary disabled:opacity-50"
              :disabled="busyId === request.request_id"
              @click="loadPackage(request)"
            >
              <Loader2 v-if="busyId === request.request_id" class="h-4 w-4 animate-spin" />
              Load execution package
            </button>
            <button
              v-if="executePackage[request.request_id]"
              type="button"
              class="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-secondary"
              @click="downloadPackage(request.request_id)"
            >
              <Download class="h-4 w-4" />
              Download JSON
            </button>
          </div>
          <template v-if="executePackage[request.request_id]">
            <p class="text-xs text-muted-foreground">
              Offline: unwrap
              <code class="text-foreground">recovery_wrapped_file_key</code>
              with the recovery private key, rewrap to the target public key, paste the base64
              result below.
            </p>
            <textarea
              v-model="wrappedKeyInput[request.request_id]"
              rows="3"
              class="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
              placeholder="Base64 RSA-OAEP wrapped file key for the requester"
            />
            <button
              type="button"
              class="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              :disabled="busyId === request.request_id"
              @click="execute(request)"
            >
              <Loader2 v-if="busyId === request.request_id" class="h-4 w-4 animate-spin" />
              Submit rewrapped key
            </button>
          </template>
        </div>

        <div
          v-else-if="!canReview && (request.status === 'PENDING' || request.status === 'APPROVED')"
          class="mt-4 border-t border-border pt-4"
        >
          <button
            type="button"
            class="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-secondary disabled:opacity-50"
            :disabled="busyId === request.request_id"
            @click="cancel(request)"
          >
            <Loader2 v-if="busyId === request.request_id" class="h-4 w-4 animate-spin" />
            Cancel request
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>
