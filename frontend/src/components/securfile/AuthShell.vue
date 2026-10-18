<script setup lang="ts">
import CipherWall from '@/components/brand/CipherWall.vue'
import { proof } from '@/data/proof'

/**
 * Sign in, register and forgot-password share one split layout: from lg up a dark brand panel on
 * the left (the home hero's ciphertext wall, one line of positioning and three measured results)
 * and the form on the right, centred and about 420px wide. Below lg only the form is shown.
 * The panel is dark in both themes, like the home hero.
 */
const results = proof.slice(0, 3)
</script>

<template>
  <section class="grid min-h-[calc(100svh-4.5rem)] grid-cols-[minmax(0,1fr)] lg:grid-cols-2" data-testid="auth-shell">
    <aside class="relative hidden overflow-hidden bg-[#07090d] text-[#f2f3f5] lg:block" data-testid="auth-brand">
      <!-- Kept faint: it is texture behind the text, not content. -->
      <div class="absolute inset-0 opacity-30"><CipherWall /></div>
      <div class="relative flex h-full flex-col justify-between gap-12 p-12 xl:p-16">
        <p class="font-mono text-xs uppercase tracking-[0.16em] text-[#7ce0b5]">Zero-knowledge file sharing</p>
        <div class="flex flex-col gap-10">
          <h2 class="text-4xl font-semibold leading-[1.05] tracking-[-0.04em] text-white 2xl:text-5xl">
            Sealed in your browser,
            <span class="block text-[#8a92a3]">unreadable to others.</span>
          </h2>
          <ul class="flex flex-col gap-5 border-t border-white/10 pt-8">
            <li v-for="item in results" :key="item.value" class="flex flex-col gap-1">
              <span class="font-mono text-2xl font-medium text-white">{{ item.value }}</span>
              <span class="text-sm leading-relaxed text-[#b7bcc6]">{{ item.label }}</span>
            </li>
          </ul>
        </div>
        <p class="font-mono text-xs text-[#8a92a3]">From our own test runs on the live site.</p>
      </div>
    </aside>

    <div class="flex items-center justify-center px-4 py-12 lg:py-16">
      <div class="w-full max-w-[420px]"><slot /></div>
    </div>
  </section>
</template>
