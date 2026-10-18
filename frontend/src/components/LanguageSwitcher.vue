<script setup lang="ts">
/**
 * English / 简体中文.
 *
 * A native <select>: keyboard and screen-reader correct with no extra work, and on a phone it
 * opens the platform's own picker rather than a custom menu that has to be re-tested on every
 * device. Each language is written in itself.
 *
 * Switching is in place, not a reload: a reload would forget an unlocked private key and any
 * half-filled form.
 */
import { Languages } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { LOCALES, isLocaleCode, setLocale } from '@/i18n'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const { t, locale } = useI18n()

function onChange(event: Event) {
  const next = (event.target as HTMLSelectElement).value
  if (isLocaleCode(next) && next !== locale.value) void setLocale(next)
}
</script>

<template>
  <label
    class="relative inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md text-black transition-colors hover:bg-secondary dark:text-white"
    :class="compact ? 'px-2' : 'px-3'"
  >
    <Languages class="pointer-events-none h-4 w-4 shrink-0" aria-hidden="true" />
    <span class="sr-only">{{ t('language.label') }}</span>
    <select
      data-testid="language-switcher"
      translate="no"
      class="cursor-pointer appearance-none bg-transparent pr-1 text-sm outline-none focus-visible:underline"
      :value="locale"
      @change="onChange"
    >
      <option
        v-for="option in LOCALES"
        :key="option.code"
        :value="option.code"
        :lang="option.code"
        class="bg-card text-foreground"
      >
        {{ option.label }}
      </option>
    </select>
  </label>
</template>
