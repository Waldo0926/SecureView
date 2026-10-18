<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { TriangleAlert } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

import { apiErrorCode, apiErrorMessage } from '@/api/http'
import { authApi } from '@/api/auth_api'
import PasswordField from '@/components/PasswordField.vue'

const emit = defineEmits<{
  (e: 'deleted', filesDeleted: number): void
  (e: 'close'): void
}>()

const { t } = useI18n()
const password = ref('')
const confirmation = ref('')
const errorMessage = ref('')
const isDeleting = ref(false)
const field = ref<InstanceType<typeof PasswordField> | null>(null)

/** Both, deliberately: the password proves it is them, the word proves they meant this. */
const canDelete = computed(() => password.value.length > 0 && confirmation.value === 'DELETE')

onMounted(async () => {
  await nextTick()
  field.value?.focus()
})

async function deleteAccount() {
  if (!canDelete.value) {
    errorMessage.value = t('deleteAccount.needBoth')
    return
  }
  isDeleting.value = true
  errorMessage.value = ''
  try {
    const res = await authApi.deleteAccount({
      password: password.value,
      confirmation: 'DELETE',
    })
    password.value = ''
    emit('deleted', res.data?.data?.files_deleted ?? 0)
  } catch (error) {
    password.value = ''
    // Retyping the password will not help here, so say what will.
    errorMessage.value =
      apiErrorCode(error) === 'last_admin'
        ? t('deleteAccount.lastAdmin')
        : apiErrorMessage(error, t('deleteAccount.failed'))
    await nextTick()
    field.value?.focus()
  } finally {
    isDeleting.value = false
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    @click.self="emit('close')"
  >
    <div class="w-full max-w-md rounded-xl border border-destructive/40 bg-card p-6 shadow-xl">
      <div class="flex items-center gap-2 mb-2">
        <div class="p-2 rounded-lg bg-destructive/10">
          <TriangleAlert class="h-4 w-4 text-destructive" />
        </div>
        <h2 class="text-lg font-semibold text-foreground">{{ t('deleteAccount.title') }}</h2>
      </div>

      <p class="text-sm text-muted-foreground mb-3">{{ t('deleteAccount.consequence') }}</p>

      <i18n-t keypath="deleteAccount.tryKeyFile" tag="p" class="text-sm text-muted-foreground mb-4" scope="global">
        <template #unlock><strong class="text-foreground">{{ t('deleteAccount.unlockWithKey') }}</strong></template>
        <template #pem><code class="text-xs">.pem</code></template>
      </i18n-t>

      <form @submit.prevent="deleteAccount">
        <PasswordField
          ref="field"
          v-model="password"
          :label="t('deleteAccount.loginPassword')"
          :placeholder="t('deleteAccount.loginPasswordPlaceholder')"
          autocomplete="current-password"
        />

        <label class="text-sm text-foreground mt-4 mb-2 block">
          <i18n-t keypath="deleteAccount.typeDelete" scope="global">
            <template #word><code class="text-xs font-mono">DELETE</code></template>
          </i18n-t>
        </label>
        <input
          v-model="confirmation"
          placeholder="DELETE"
          autocomplete="off"
          spellcheck="false"
          class="h-10 w-full rounded-md border border-border bg-secondary px-3 text-foreground"
        />

        <p v-if="errorMessage" class="text-sm text-destructive mt-2">{{ errorMessage }}</p>

        <div class="mt-4 flex gap-2">
          <button
            type="submit"
            class="flex-1 h-10 rounded-md bg-destructive text-white hover:bg-destructive/90 disabled:opacity-50"
            :disabled="isDeleting || !canDelete"
          >
            {{ isDeleting ? t('deleteAccount.deleting') : t('deleteAccount.submit') }}
          </button>
          <button
            type="button"
            class="h-10 px-4 rounded-md border border-border hover:bg-secondary"
            @click="emit('close')"
          >
            {{ t('common.cancel') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
