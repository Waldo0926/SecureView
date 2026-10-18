<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, KeyRound, Loader2, Share2, UserMinus } from 'lucide-vue-next'

import {
  FileKeyUnwrapError,
  forgetUnlockedKeys,
  KeyNotUnlockedError,
  NotUnlockedError,
} from '@/crypto/download'
import { formatFingerprint } from '@/crypto/fingerprint'
import {
  lookupRecipient,
  RecipientKeyMismatchError,
  RecipientNotFoundError,
  shareFileWithRecipient,
  ShareWithSelfError,
  type RecipientCandidate,
} from '@/crypto/share'
import { apiErrorMessage } from '@/api/http'
import { shareApi, type SharedUser } from '@/api/share_api'
import { unwrapData } from '@/api/types'
import ConfirmActionDialog from '@/components/ConfirmActionDialog.vue'
import UnlockDialog from '@/components/UnlockDialog.vue'
import { useAuthStore } from '@/stores/auth_store'
import { knownFingerprint, rememberFingerprint } from '@/utils/known-keys'
import { formatSiteDate } from '@/utils/site-time'

const props = defineProps<{
  fileId: string
  filename?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'shared', username: string): void
  (e: 'revoked', username: string): void
}>()

const targetUsername = ref('')
const errorMessage = ref('')
const isSubmitting = ref(false)
const field = ref<HTMLInputElement | null>(null)

const recipients = ref<SharedUser[]>([])
const isLoadingRecipients = ref(true)
const revokingUserId = ref<string | null>(null)
/** Recipient selected for revoke confirmation; null when the dialog is closed. */
const pendingRevoke = ref<SharedUser | null>(null)

/** The owner holds a canonical grant that cannot be revoked, so it is not offered. */
const others = computed(() => recipients.value.filter((user) => !user.is_owner))

/**
 * Who currently holds this file.
 *
 * `GET /files/{id}/shared-users` existed and nothing called it, so a share, once made, was
 * invisible and irreversible from the interface -- there was no list of who held the file
 * and no way to take it back.
 */
const loadRecipients = async () => {
  isLoadingRecipients.value = true
  try {
    recipients.value = unwrapData(await shareApi.sharedUsers(props.fileId)).users ?? []
  } catch {
    // Not fatal: sharing with someone new still works without the current list.
    recipients.value = []
  } finally {
    isLoadingRecipients.value = false
  }
}

function requestRevoke(user: SharedUser) {
  pendingRevoke.value = user
}

/**
 * Runs only after the confirmation dialog. Revoke used to fire on the first click of the
 * icon, which #72 requires to state the consequence first.
 */
async function confirmRevoke() {
  const user = pendingRevoke.value
  if (!user) return
  revokingUserId.value = user.user_id
  errorMessage.value = ''
  try {
    await shareApi.revokeAccess(props.fileId, { target_user_id: user.user_id })
    pendingRevoke.value = null
    await loadRecipients()
    emit('revoked', user.username)
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, `Could not revoke ${user.username}'s access`)
  } finally {
    revokingUserId.value = null
  }
}

function closePendingRevoke() {
  if (revokingUserId.value !== null) return
  pendingRevoke.value = null
}

/**
 * Step two of sharing: who it will go to and the fingerprint of the key it will be sealed to.
 * A typo now stops here instead of sharing with a stranger, and the fingerprint can be checked
 * against the one the recipient sees in their Settings.
 */
const candidate = ref<RecipientCandidate | null>(null)
const previousFingerprint = ref<string | null>(null)
const auth = useAuthStore()
/**
 * The sender's own name resolves to a perfectly good key, but the owner already holds the
 * file. Saying so under the fingerprint, with the confirm button off, beats letting them
 * confirm and then reading the same thing as an error.
 */
const sharingWithSelf = computed(
  () => candidate.value !== null && auth.user?.id !== undefined && candidate.value.userId === auth.user.id,
)
const SHARE_WITH_SELF_MESSAGE = 'You already own this file; share it with someone else.'
const keyChanged = computed(
  () =>
    candidate.value !== null &&
    previousFingerprint.value !== null &&
    previousFingerprint.value !== candidate.value.fingerprint,
)

onMounted(async () => {
  loadRecipients()
  await nextTick()
  field.value?.focus()
})

// The passphrase was asked for when Share was clicked. Closing without sharing must not
// leave the key open.
onBeforeUnmount(forgetUnlockedKeys)

/**
 * Set while a passphrase dialog is open on top of this one. That happens when a second
 * share is made from the same dialog (the key was dropped after the first one), or when
 * the file is under an older key. The recipient and fingerprint stay on screen and the
 * share goes ahead as soon as the key is open.
 */
const unlockFor = ref<{ keyId: string | null } | null>(null)

async function onUnlocked() {
  unlockFor.value = null
  await share()
}

function closeUnlock() {
  unlockFor.value = null
  errorMessage.value = 'Nothing was shared. Your passphrase is needed to share a file.'
}

async function findRecipient() {
  const name = targetUsername.value.trim()
  if (!name) {
    errorMessage.value = 'Enter the username or email address to share with'
    return
  }
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    const found = await lookupRecipient(name)
    previousFingerprint.value = knownFingerprint(found.userId)
    candidate.value = found
  } catch (error) {
    errorMessage.value =
      error instanceof RecipientNotFoundError
        ? `No account matches "${name}". Check their exact SecureView username or email address.`
        : error instanceof RecipientKeyMismatchError
          ? 'The server described this person’s key inconsistently, so nothing was shared. Try again later, and tell the team if it keeps happening.'
          : apiErrorMessage(error, 'Could not look up this person')
  } finally {
    isSubmitting.value = false
  }
}

function backToRecipient() {
  candidate.value = null
  errorMessage.value = ''
  void nextTick(() => field.value?.focus())
}

async function share() {
  const chosen = candidate.value
  if (!chosen) return
  const name = chosen.identifier
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    await shareFileWithRecipient(props.fileId, chosen)
    rememberFingerprint(chosen.userId, chosen.fingerprint)
    candidate.value = null
    targetUsername.value = ''
    await loadRecipients()
    emit('shared', name)
  } catch (error) {
    // Not a failure: ask for the passphrase and carry on with the same recipient.
    if (error instanceof NotUnlockedError) {
      unlockFor.value = { keyId: null }
      return
    }
    if (error instanceof KeyNotUnlockedError) {
      unlockFor.value = { keyId: error.keyId }
      return
    }
    errorMessage.value =
      error instanceof RecipientNotFoundError
        ? `No account matches "${name}". Check their exact SecureView username or email address.`
        : error instanceof ShareWithSelfError
          ? SHARE_WITH_SELF_MESSAGE
          : error instanceof FileKeyUnwrapError
            ? 'Your account key does not open this file, so it cannot be shared from here.'
            : apiErrorMessage(error, 'Could not share this file')
  } finally {
    isSubmitting.value = false
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
        <div class="p-2 rounded-lg bg-secondary"><Share2 class="h-4 w-4 text-primary" /></div>
        <h2 class="text-lg font-semibold text-foreground">Share this file</h2>
      </div>

      <p class="text-sm text-muted-foreground mb-4">
        <span translate="no" v-if="props.filename" class="text-foreground [overflow-wrap:anywhere]">{{ props.filename }}</span>
        <span v-else>This file</span>
        is re-encrypted to the recipient's own key in this browser. They open it with their
        own passphrase — never yours — and the server never sees the file's key.
      </p>

      <div class="mb-5 pb-5 border-b border-border">
        <p class="text-sm text-foreground mb-2">Currently shared with</p>

        <div v-if="isLoadingRecipients" class="py-2 text-sm text-muted-foreground">
          <Loader2 class="h-4 w-4 animate-spin" />
        </div>

        <p v-else-if="!others.length" class="text-sm text-muted-foreground">
          Nobody yet — only you can open this file.
        </p>

        <ul v-else class="divide-y divide-border">
          <li
            v-for="user in others"
            :key="user.user_id"
            class="flex items-center justify-between gap-3 py-2"
          >
            <div class="min-w-0">
              <p translate="no" class="text-sm text-foreground truncate">{{ user.username }}</p>
              <p class="text-xs text-muted-foreground">
                Since {{ formatSiteDate(user.granted_at) }}
                <span v-if="!user.can_download"> · view only</span>
              </p>
            </div>
            <button
              type="button"
              class="h-8 px-2 inline-flex items-center gap-1 rounded-md border border-destructive/40 text-destructive text-xs hover:bg-destructive/10 disabled:opacity-50"
              :disabled="revokingUserId !== null"
              @click="requestRevoke(user)"
            >
              <Loader2 v-if="revokingUserId === user.user_id" class="h-3 w-3 animate-spin" />
              <UserMinus v-else class="h-3 w-3" />
              Revoke
            </button>
          </li>
        </ul>

        <p v-if="others.length" class="text-xs text-muted-foreground mt-3">
          Revoking stops further access and removes the file from their list. It cannot
          recover a copy they have already downloaded and decrypted.
        </p>
      </div>

      <div v-if="candidate" data-testid="share-confirm">
        <p class="text-sm text-foreground mb-3">
          Share with <span translate="no" class="font-semibold [overflow-wrap:anywhere]">{{ candidate.identifier }}</span>?
        </p>
        <div class="rounded-lg border border-border bg-secondary/50 p-3">
          <p class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <KeyRound class="h-3.5 w-3.5" />
            Their key fingerprint
          </p>
          <p translate="no" class="mt-1 font-mono text-base tracking-wide text-foreground" data-testid="recipient-fingerprint">
            {{ formatFingerprint(candidate.fingerprint) }}
          </p>
          <p class="mt-2 text-xs text-muted-foreground">
            For a sensitive file, ask them to read out the fingerprint shown in their Settings. If
            it matches, the file can only be opened by them. If it does not, do not share: the key
            may not be theirs.
          </p>
        </div>
        <p
          v-if="keyChanged"
          class="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300"
          data-testid="recipient-key-changed"
        >
          <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Their key has changed since you last shared with them from this browser. That happens
            when someone sets up a new key, but it is also what a swapped key looks like. Check the
            fingerprint with them before sharing.
          </span>
        </p>

        <p v-if="sharingWithSelf" class="text-sm text-destructive mt-2" role="alert" data-testid="share-with-self">{{ SHARE_WITH_SELF_MESSAGE }}</p>
        <p v-else-if="errorMessage" class="text-sm text-destructive mt-2">{{ errorMessage }}</p>

        <div class="mt-4 flex gap-2">
          <button
            type="button"
            class="flex-1 h-10 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            :disabled="isSubmitting || sharingWithSelf"
            @click="share"
          >
            {{ isSubmitting ? 'Sharing...' : 'Confirm and share' }}
          </button>
          <button
            type="button"
            class="h-10 px-4 rounded-md border border-border hover:bg-secondary"
            :disabled="isSubmitting"
            @click="backToRecipient"
          >
            Back
          </button>
        </div>
      </div>

      <form v-else @submit.prevent="findRecipient">
        <label class="text-sm text-foreground mb-2 block">
          Share with someone else <span class="text-destructive">*</span>
        </label>
        <input
          ref="field"
          v-model="targetUsername"
          placeholder="Their username/ Email address on Secureview."
          autocomplete="off"
          class="h-10 w-full rounded-md border border-border bg-secondary px-3 text-foreground"
        />
        <p class="text-xs text-muted-foreground mt-2">
          They need a SecureView account. Sharing is per account, not by link — a file can
          only be re-encrypted to a key that already exists. Enter their exact username or
          email address.
        </p>

        <p v-if="errorMessage" class="text-sm text-destructive mt-2">{{ errorMessage }}</p>

        <div class="mt-4 flex gap-2">
          <button
            type="submit"
            class="flex-1 h-10 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            :disabled="isSubmitting || !targetUsername.trim()"
          >
            {{ isSubmitting ? 'Looking up...' : 'Share' }}
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
    </div>
  </div>

  <ConfirmActionDialog
    v-if="pendingRevoke"
    title="Revoke access?"
    :detail="`Remove ${pendingRevoke.username}'s access${filename ? ` to ${filename}` : ''}?`"
    consequence="They lose further access and the file leaves their Shared with me list. A copy they have already downloaded and decrypted cannot be recovered."
    confirm-label="Revoke access"
    busy-label="Revoking…"
    :busy="revokingUserId === pendingRevoke.user_id"
    @confirm="confirmRevoke"
    @close="closePendingRevoke"
  />

  <UnlockDialog
    v-if="unlockFor"
    :key-id="unlockFor.keyId"
    @unlocked="onUnlocked"
    @close="closeUnlock"
  />
</template>
