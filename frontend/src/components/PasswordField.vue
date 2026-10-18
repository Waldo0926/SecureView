<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { Eye, EyeOff } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const props = withDefaults(
  defineProps<{
    label: string
    placeholder?: string
    autocomplete?: string
    /** Shown in destructive text under the field. Empty string means "no problem". */
    error?: string
    /** Static guidance under the field, always visible. */
    hint?: string
    required?: boolean
  }>(),
  {
    placeholder: '',
    autocomplete: 'new-password',
    error: '',
    hint: '',
    required: true,
  },
)

const emit = defineEmits<{
  (e: 'blur'): void
}>()

const { t } = useI18n()

const value = defineModel<string>({ required: true })

/**
 * Revealing the password is per-field and always starts hidden, so a page that was
 * left open does not put a plaintext password on screen for whoever walks past.
 */
const isRevealed = ref(false)

const inputElement = ref<HTMLInputElement | null>(null)

const fieldId = useId()
const errorId = `${fieldId}-error`
const hintId = `${fieldId}-hint`

const describedBy = computed(() =>
  [props.hint ? hintId : '', props.error ? errorId : ''].filter(Boolean).join(' '),
)

function toggleReveal() {
  isRevealed.value = !isRevealed.value
  // Toggling must not cost the user their place in the field they are typing in.
  inputElement.value?.focus()
}

defineExpose({
  focus: () => inputElement.value?.focus(),
})
</script>

<template>
  <div>
    <div class="mb-2 flex items-center justify-between gap-2">
      <label :for="fieldId" class="text-sm text-foreground">
        {{ label }} <span v-if="required" class="text-destructive">*</span>
      </label>
      <slot name="label-aside" />
    </div>

    <div class="relative">
      <input
        :id="fieldId"
        ref="inputElement"
        v-model="value"
        :type="isRevealed ? 'text' : 'password'"
        :placeholder="placeholder"
        :autocomplete="autocomplete"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="describedBy || undefined"
        class="h-10 w-full rounded-md border bg-secondary pl-3 pr-10 text-foreground [&::-ms-reveal]:hidden [&::-ms-clear]:hidden"
        :class="error ? 'border-destructive' : 'border-border'"
        @blur="emit('blur')"
      />
      <button
        type="button"
        class="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground"
        :aria-label="t(isRevealed ? 'password.hide' : 'password.show')"
        :aria-pressed="isRevealed"
        :title="t(isRevealed ? 'password.hide' : 'password.show')"
        @click="toggleReveal"
      >
        <EyeOff v-if="isRevealed" class="h-4 w-4" />
        <Eye v-else class="h-4 w-4" />
      </button>
    </div>

    <p v-if="hint" :id="hintId" class="text-xs text-muted-foreground mt-1">{{ hint }}</p>
    <slot name="hint" />
    <p v-if="error" :id="errorId" class="text-xs text-destructive mt-1" role="alert">
      {{ error }}
    </p>
  </div>
</template>
