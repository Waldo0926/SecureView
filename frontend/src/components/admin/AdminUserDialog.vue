<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, Copy, KeyRound, Loader2, ShieldAlert, UserRound, X } from 'lucide-vue-next'

import { adminApi, type AdminPasswordReset, type AdminUserDetail } from '@/api/admin_api'
import { apiErrorMessage } from '@/api/http'
import { formatFileSize, unwrapData } from '@/api/types'
import { formatSiteDateTime } from '@/utils/site-time'

/**
 * One account, for an administrator: who it is, what it holds, and a login-password reset.
 *
 * There is deliberately no "show password". The login password is stored only as a one-way
 * hash, so the server cannot show it, and the encryption passphrase never reaches the server
 * at all. A reset sets a new random login password, shows it here once, signs the account out
 * everywhere and emails the holder; the files are untouched because they open with the
 * passphrase, not the login password.
 */
const props = defineProps<{ userId: string; isSelf: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'reset', username: string): void }>()

const detail = ref<AdminUserDetail | null>(null)
const isLoading = ref(true)
const errorMessage = ref('')
const confirming = ref(false)
const resetting = ref(false)
const reset = ref<AdminPasswordReset | null>(null)
const copied = ref(false)
let copiedTimer = 0

const canReset = computed(
  () => detail.value !== null && !props.isSelf && detail.value.role !== 'ADMIN' && detail.value.status !== 'DELETED',
)

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Never'
  return formatSiteDateTime(value)
}

const roleLabel = (role: string) => (role === 'ADMIN' ? 'Admin' : role === 'RECOVERY_OFFICER' ? 'Recovery officer' : 'User')
const STATUS_LABELS: Record<string, string> = { ACTIVE: 'Active', DISABLED: 'Disabled', DELETED: 'Deleted' }
const statusLabel = (status: string) => STATUS_LABELS[status] ?? status

async function resetPassword() {
  if (!detail.value) return
  resetting.value = true
  errorMessage.value = ''
  try {
    reset.value = unwrapData(await adminApi.resetUserPassword(props.userId))
    confirming.value = false
    detail.value = { ...detail.value, active_sessions: 0, password_changed_at: new Date().toISOString() }
    emit('reset', detail.value.username)
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not reset the login password')
  } finally {
    resetting.value = false
  }
}

async function copyPassword() {
  if (!reset.value) return
  try {
    await navigator.clipboard.writeText(reset.value.temporary_password)
    copied.value = true
    window.clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => (copied.value = false), 2000)
  } catch {
    // Clipboard access can be refused; the password is on screen and can be selected by hand.
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  try {
    detail.value = unwrapData(await adminApi.getUser(props.userId))
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'Could not load this account')
  } finally {
    isLoading.value = false
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  window.clearTimeout(copiedTimer)
})
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="emit('close')">
    <div
      class="max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-card p-6 shadow-xl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-user-title"
      data-testid="admin-user-dialog"
    >
      <div class="mb-5 flex items-start justify-between gap-4">
        <div class="flex min-w-0 items-center gap-3">
          <div class="rounded-lg bg-secondary p-2"><UserRound class="h-4 w-4 text-foreground" /></div>
          <div class="min-w-0">
            <p class="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-muted-foreground">Account</p>
            <h2 id="admin-user-title" translate="no" class="truncate text-lg font-semibold text-foreground">
              {{ detail?.username ?? '…' }}
            </h2>
          </div>
        </div>
        <button
          type="button"
          class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md hover:bg-secondary"
          aria-label="Close"
          @click="emit('close')"
        >
          <X class="h-4 w-4" />
        </button>
      </div>

      <div v-if="isLoading" class="py-10 text-center text-muted-foreground">
        <Loader2 class="mx-auto h-5 w-5 animate-spin" />
      </div>

      <template v-else-if="detail">
        <dl class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] gap-x-4 gap-y-2.5 text-sm">
          <dt class="text-muted-foreground">Email</dt>
          <dd class="[overflow-wrap:anywhere]">
            <span translate="no">{{ detail.email }}</span>
            <span class="ml-1 text-xs" :class="detail.email_verified ? 'text-success' : 'text-muted-foreground'">
              {{ detail.email_verified ? 'verified' : 'not verified' }}
            </span>
          </dd>
          <dt class="text-muted-foreground">Role</dt>
          <dd>{{ roleLabel(detail.role) }}</dd>
          <dt class="text-muted-foreground">Status</dt>
          <dd>{{ statusLabel(detail.status) }}</dd>
          <dt class="text-muted-foreground">Created</dt>
          <dd>{{ formatTimestamp(detail.created_at) }}</dd>
          <dt class="text-muted-foreground">Last sign-in</dt>
          <dd>{{ formatTimestamp(detail.last_login_at) }}</dd>
          <dt class="text-muted-foreground">Password changed</dt>
          <dd>{{ formatTimestamp(detail.password_changed_at) }}</dd>
        </dl>

        <dl class="mt-5 grid grid-cols-2 gap-3 border-t border-border pt-5 text-sm sm:grid-cols-3">
          <div class="rounded-lg bg-secondary/60 px-3 py-2.5">
            <dt class="text-xs text-muted-foreground">Files</dt>
            <dd class="mt-0.5 font-semibold">{{ detail.file_count }}</dd>
          </div>
          <div class="rounded-lg bg-secondary/60 px-3 py-2.5">
            <dt class="text-xs text-muted-foreground">Stored</dt>
            <dd class="mt-0.5 font-semibold">{{ formatFileSize(detail.stored_bytes) }}</dd>
          </div>
          <div class="rounded-lg bg-secondary/60 px-3 py-2.5">
            <dt class="text-xs text-muted-foreground">Signed in now</dt>
            <dd class="mt-0.5 font-semibold">{{ detail.active_sessions }}</dd>
          </div>
          <div class="rounded-lg bg-secondary/60 px-3 py-2.5">
            <dt class="text-xs text-muted-foreground">Shares sent</dt>
            <dd class="mt-0.5 font-semibold">{{ detail.shared_by_them }}</dd>
          </div>
          <div class="rounded-lg bg-secondary/60 px-3 py-2.5">
            <dt class="text-xs text-muted-foreground">Shared with them</dt>
            <dd class="mt-0.5 font-semibold">{{ detail.shared_with_them }}</dd>
          </div>
        </dl>

        <p class="mt-4 text-xs leading-relaxed text-muted-foreground">
          Passwords are not shown. The login password is stored only as a one-way hash, and the
          encryption passphrase never reaches the server.
        </p>

        <section class="mt-5 border-t border-border pt-5">
          <h3 class="flex items-center gap-2 text-sm font-semibold">
            <KeyRound class="h-4 w-4" /> Login password
          </h3>

          <div v-if="reset" class="mt-3 space-y-3" data-testid="admin-temporary-password">
            <p class="text-sm">
              New temporary password for <span translate="no" class="font-medium">{{ reset.username }}</span>.
              It is shown only this once.
            </p>
            <div class="flex items-center gap-2">
              <code translate="no" class="flex-1 rounded-lg bg-secondary px-3.5 py-3 font-mono text-base tracking-wide">
                {{ reset.temporary_password }}
              </code>
              <button
                type="button"
                class="inline-flex h-11 items-center gap-1.5 rounded-lg border border-border px-3 text-sm hover:bg-secondary"
                @click="copyPassword"
              >
                <component :is="copied ? Check : Copy" class="h-4 w-4" />
                {{ copied ? 'Copied' : 'Copy' }}
              </button>
            </div>
            <ul class="list-disc space-y-1 pl-5 text-xs leading-relaxed text-muted-foreground">
              <li>Give it to them in person or over a channel you trust.</li>
              <li>When they sign in with it they are taken straight to Settings to choose their own.</li>
              <li>Sessions signed out: {{ reset.revoked_sessions }}.</li>
              <li>{{ reset.notice_sent ? 'They have been emailed that it changed.' : 'The notice email could not be sent.' }}</li>
              <li>Their files and encryption passphrase are unchanged.</li>
            </ul>
          </div>

          <template v-else-if="canReset">
            <p class="mt-2 text-sm text-muted-foreground">
              Set a new random login password, sign the account out everywhere, and email the holder.
              Files are not affected.
            </p>
            <div v-if="confirming" class="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-destructive/30 bg-destructive-soft p-3">
              <ShieldAlert class="h-4 w-4 shrink-0 text-destructive" />
              <span class="flex-1 text-sm">Reset and sign <span translate="no">{{ detail.username }}</span> out?</span>
              <button
                type="button"
                class="inline-flex h-9 items-center gap-1.5 rounded-md bg-destructive px-3 text-sm font-medium text-white hover:bg-destructive/90 disabled:opacity-50"
                :disabled="resetting"
                data-testid="admin-confirm-reset"
                @click="resetPassword"
              >
                <Loader2 v-if="resetting" class="h-4 w-4 animate-spin" />
                Reset password
              </button>
              <button type="button" class="h-9 rounded-md px-3 text-sm hover:bg-secondary" @click="confirming = false">
                Cancel
              </button>
            </div>
            <button
              v-else
              type="button"
              class="mt-3 inline-flex h-10 items-center gap-2 rounded-lg border border-border px-4 text-sm font-medium hover:bg-secondary"
              data-testid="admin-reset-password"
              @click="confirming = true"
            >
              <KeyRound class="h-4 w-4" /> Reset login password
            </button>
          </template>
          <p v-else class="mt-2 text-sm text-muted-foreground">
            {{
              isSelf
                ? 'Change your own password in Settings.'
                : detail.status === 'DELETED'
                  ? 'This account has been deleted.'
                  : "Another administrator's password cannot be reset here."
            }}
          </p>
        </section>
      </template>

      <p v-if="errorMessage" class="mt-4 text-sm text-destructive" role="alert">{{ errorMessage }}</p>
    </div>
  </div>
</template>
