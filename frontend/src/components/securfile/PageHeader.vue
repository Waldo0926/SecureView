<script setup lang="ts">
import { computed } from 'vue'
import SentenceLines from '@/components/SentenceLines.vue'

/**
 * The one page header every page uses: centred, on the same centre line as the content below it.
 *
 * - `eyebrow`: an optional small mono label above the title. Plain text, never a pill.
 * - `title`: the h1 (`as="h2"` where the page already has an h1 elsewhere). About 48px on a
 *   desktop, 32px on a phone, tight tracking, balanced wrapping.
 * - `subtitle`: one sentence takes all the width it needs and stays on one line when it fits.
 *   Two sentences that do not fit together break between the sentences (SentenceLines).
 *   A paragraph (over about 120 characters, or `long`) keeps a readable measure of about 70ch, still centred.
 * - `actions` slot: centred under the subtitle (a refresh button, a status badge).
 *
 * Do not cap the title or a one-line subtitle with `max-w-*`: that forces two lines with empty
 * space beside them, which is exactly what this component exists to stop.
 */
const props = withDefaults(
  defineProps<{
    title?: string
    eyebrow?: string
    subtitle?: string
    long?: boolean
    as?: 'h1' | 'h2'
    /** id for the heading, for `aria-labelledby` on the section. */
    titleId?: string
  }>(),
  { as: 'h1', long: undefined },
)

/** A subtitle that runs past one sentence is a paragraph: it gets a reading measure. */
const isLong = computed(() => props.long ?? (props.subtitle?.length ?? 0) > 120)
</script>

<template>
  <header class="page-header" data-testid="page-header">
    <p v-if="eyebrow" class="page-header-eyebrow">{{ eyebrow }}</p>
    <component :is="as" :id="titleId" class="page-header-title"><slot name="title">{{ title }}</slot></component>
    <p v-if="subtitle || $slots.subtitle" class="page-header-subtitle" :class="isLong ? 'page-header-long' : ''">
      <slot name="subtitle"><SentenceLines v-if="subtitle" :text="subtitle" /></slot>
    </p>
    <div v-if="$slots.actions" class="page-header-actions"><slot name="actions" /></div>
  </header>
</template>
