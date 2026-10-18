<script setup lang="ts">
import { byteRows } from '@/utils/byte-rows'

/** The dark scenes' wall of ciphertext. Decorative, so hidden from assistive technology. */
const props = withDefaults(defineProps<{ rows?: number; width?: number }>(), { rows: 16, width: 22 })
const wall = byteRows(props.rows, props.width)
</script>

<template>
  <div class="cipher-wall absolute inset-0 flex flex-col justify-center gap-3.5 overflow-hidden" aria-hidden="true">
    <div
      v-for="(row, i) in wall"
      :key="i"
      class="cipher-hex whitespace-nowrap font-mono text-[0.95rem] tracking-[0.18em] text-[#7ce0b5]"
      :style="{ animationDelay: `${(i * 0.37) % 3}s` }"
    >
      {{ row }}
    </div>
  </div>
</template>

<style scoped>
.cipher-wall {
  mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, #000 40%, transparent 85%);
}
.cipher-hex {
  animation: cipher-flicker 3.2s ease-in-out infinite;
}
@keyframes cipher-flicker {
  0%, 100% { opacity: 0.18; }
  45% { opacity: 0.55; }
  55% { opacity: 0.3; }
}
@media (prefers-reduced-motion: reduce) {
  .cipher-hex { animation: none; }
}
</style>
