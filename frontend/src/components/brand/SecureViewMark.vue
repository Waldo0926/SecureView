<script setup lang="ts">
/**
 * Inline brand SVGs so the wordmark's `currentColor` tracks Light/Dark.
 * The shield stays white with black details in both themes.
 * A plain <img src="...svg"> cannot inherit the surrounding text colour.
 *
 * Mask / title ids are rewritten with Vue's useId so header + footer can both
 * mount the logo without one stealing the other's mask reference.
 */
import { computed, useId } from 'vue'
import iconSvg from '@/assets/brand/secure-view-icon.svg?raw'
import logoSvg from '@/assets/brand/secure-view-logo.svg?raw'

const props = withDefaults(
  defineProps<{
    /** `logo` includes the wordmark; `icon` is the shield mark alone. */
    variant?: 'logo' | 'icon'
  }>(),
  { variant: 'logo' },
)

const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, '')

const markup = computed(() => {
  const raw = props.variant === 'icon' ? iconSvg : logoSvg
  return raw
    .replace(/\bid="([^"]+)"/g, (_match, id: string) => `id="${instanceId}-${id}"`)
    .replace(/\burl\(#([^)]+)\)/g, (_match, id: string) => `url(#${instanceId}-${id})`)
    .replace(/\baria-labelledby="([^"]+)"/g, (_match, ids: string) => {
      const next = ids
        .split(/\s+/)
        .filter(Boolean)
        .map((id) => `${instanceId}-${id}`)
        .join(' ')
      return `aria-labelledby="${next}"`
    })
})
</script>

<template>
  <span
    class="inline-flex items-center [&_svg]:h-full [&_svg]:w-auto"
    aria-hidden="true"
    v-html="markup"
  />
</template>
