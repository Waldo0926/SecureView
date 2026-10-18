<script setup lang="ts">
import GettingStartedCard from '@/components/GettingStartedCard.vue'
import PageHeader from '@/components/securfile/PageHeader.vue'
import { ChevronRight, FileIcon, LifeBuoy, Shield, Upload } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { fileApi } from '@/api/file_api'
import { formatFileSize, unwrapData, type FileSummaryOut } from '@/api/types'
import DeleteAccountDialog from '@/components/DeleteAccountDialog.vue'
import { useAuthStore } from '@/stores/auth_store'

const router = useRouter()
const auth = useAuthStore()
const showDelete = ref(false)

const recent = ref<FileSummaryOut[]>([])
const total = ref<number | null>(null)
const isLoading = ref(true)

/**
 * The count and the recent rows are a hint, not a gate. Every destination below is a
 * plain link, so a failed or slow call must leave them usable rather than blocking the
 * page -- this is the screen a signed-in user lands on, and it cannot be the thing that
 * strands them.
 */
onMounted(async () => {
  try {
    await auth.loadUser()
    const data = unwrapData(await fileApi.listFiles({ page: 1, page_size: 5 }))
    recent.value = data.items
    total.value = data.total
  } catch {
    total.value = null
  } finally {
    isLoading.value = false
  }
})

/**
 * The account is gone server-side; clear the local session so the app does not keep
 * rendering a signed-in shell against a user that no longer exists, and offer the only
 * thing left to do -- register again.
 */
const onDeleted = () => {
  showDelete.value = false
  // Account deletion already revoked every session server-side.
  auth.clearLocalSession()
  router.push({ path: '/register', query: { deleted: '1' } })
}

const destinations = computed(() => {
  const items = [
    {
      to: '/upload',
      icon: Upload,
      title: 'Upload & Encrypt',
      body: 'Encrypt a file in your browser with AES-256-GCM. Only the ciphertext is uploaded.',
      cta: 'Encrypt a file',
    },
    {
      to: '/files',
      icon: FileIcon,
      title: 'My Files',
      body: 'Download, share, verify or delete the files you have already uploaded.',
      cta: 'Manage files',
    },
    {
      to: '/audit-logs',
      icon: Shield,
      title: 'Activity Log',
      body: 'Your account activity and every upload, download and share of your files, in one tamper-evident log.',
      cta: 'View activity',
    },
    {
      to: '/admin',
      icon: LifeBuoy,
      title: auth.isAdmin ? 'Admin console' : auth.isRecoveryReviewer ? 'Recovery review' : 'Recovery requests',
      body: auth.isRecoveryReviewer
        ? 'Review recovery requests, manage users and files, verify the audit hash chain, and register the recovery public key.'
        : 'Track your recovery requests, or cancel one you no longer need.',
      cta: auth.isRecoveryReviewer ? 'Open console' : 'View requests',
    },
  ]
  return items
})

/**
 * The card text as runs, every odd one a hyphenated word kept on one line: on a phone the
 * browser otherwise broke "(AES-" / "256-GCM". Wrapped in a span, which the Chinese layer
 * translates together with the sentence around it.
 */
function hyphenatedKeptWhole(text: string): string[] {
  return text.split(/(\S+-\S+)/)
}
</script>

<template>
  <section id="workspace" class="product-page">
    <div class="page-container">
      <PageHeader
        title="Your Workspace"
        subtitle="Pick up where you left off. Encrypt something new, or manage and share the files you have already uploaded."
      />

      <GettingStartedCard />

      <div class="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        <RouterLink
          v-for="item in destinations"
          :key="item.to"
          :to="item.to"
          class="group flex flex-col rounded-xl bg-card border border-border p-6 transition-colors hover:border-foreground/40"
        >
          <component :is="item.icon" class="mb-5 h-5 w-5 self-center text-muted-foreground" />
          <h3 class="text-lg font-medium text-foreground mb-2 text-center">{{ item.title }}</h3>
          <p class="text-sm text-muted-foreground flex-1"><template v-for="(part, index) in hyphenatedKeptWhole(item.body)" :key="index"><span v-if="index % 2" class="whitespace-nowrap">{{ part }}</span><template v-else>{{ part }}</template></template></p>
          <span class="mt-4 inline-flex items-center gap-1 text-sm font-medium text-foreground">
            {{ item.cta }}
            <ChevronRight class="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </span>
        </RouterLink>
      </div>

      <div v-if="!isLoading && total !== null" class="mt-12">
        <div class="rounded-xl bg-card border border-border p-6">
          <div class="flex items-center justify-between gap-4 mb-4">
            <h3 class="text-lg font-medium text-foreground">
              Recent files
              <span class="text-muted-foreground font-normal text-sm">({{ total }} total)</span>
            </h3>
            <RouterLink
              v-if="total > 0"
              to="/files"
              class="inline-flex min-h-10 items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              See all
              <ChevronRight class="h-4 w-4" />
            </RouterLink>
          </div>

          <p v-if="!recent.length" class="text-sm text-muted-foreground">
            Nothing uploaded yet. Encrypt your first file to get started.
          </p>

          <ul v-else class="divide-y divide-border">
            <li v-for="file in recent" :key="file.file_id" class="flex items-center gap-3 py-3">
              <FileIcon class="h-4 w-4 text-muted-foreground shrink-0" />
              <span translate="no" class="text-sm text-foreground truncate flex-1">{{ file.original_filename }}</span>
              <span class="shrink-0 font-mono text-xs text-muted-foreground">{{ formatFileSize(file.plaintext_size) }}</span>
            </li>
          </ul>
        </div>
      </div>

      <div class="mt-12">
        <details class="rounded-xl border border-border bg-card/50 p-4">
          <summary class="text-sm text-muted-foreground cursor-pointer select-none">
            Account options
          </summary>
          <div class="mt-4 pt-4 border-t border-border">
            <p class="text-sm text-foreground mb-1">Delete this account</p>
            <p class="text-sm text-muted-foreground mb-3 reading-measure text-pretty">
              Removes the account and every file uploaded from it. There is no way to reverse
              this and no way to recover the files afterwards. If you are locked out by a
              forgotten passphrase, unlocking with your saved private key file is the thing to
              try first — deleting is the last resort, not the first.
            </p>
            <button
              type="button"
              class="h-9 px-4 rounded-md border border-destructive/50 text-destructive hover:bg-destructive/10 transition-colors text-sm"
              @click="showDelete = true"
            >
              Delete account
            </button>
          </div>
        </details>
      </div>
    </div>

    <DeleteAccountDialog
      v-if="showDelete"
      @deleted="onDeleted"
      @close="showDelete = false"
    />
  </section>
</template>
