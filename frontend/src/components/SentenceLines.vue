<script setup lang="ts">
import { computed } from 'vue'
import { splitSentences } from '@/utils/sentences'

/**
 * Text of two or more sentences, where a line may only break between sentences.
 *
 * Each sentence is an inline-block: when the whole text fits it stays on one line; when it does
 * not, the next sentence moves to a new line as a unit instead of the line breaking in the middle
 * of a sentence ("...from picking a file to your / teammate downloading it."). A sentence wider
 * than the space still wraps inside itself, as on a phone.
 *
 * `data-sentence-lines` tells the Chinese layer (`i18n/dom-translate.ts`) to translate the whole
 * text as one dictionary entry and then hand one Chinese sentence to each block.
 */
const props = defineProps<{ text: string }>()
const sentences = computed(() => splitSentences(props.text))
</script>

<template>
  <span data-sentence-lines><template v-for="(sentence, index) in sentences" :key="index"><span class="inline-block max-w-full">{{ sentence }}</span>{{ index < sentences.length - 1 ? ' ' : '' }}</template></span>
</template>
