<script setup lang="ts">
import { Check, Cloud, ShieldCheck, X } from 'lucide-vue-next'

import { COMPARISON } from '@/data/security-story'

/** The advantages, side by side: ordinary cloud storage against SecureView. */
</script>

<template>
  <div data-testid="why-secureview">
    <!-- Wide screens: a comparison table -->
    <div class="hidden overflow-hidden rounded-xl border border-border bg-card md:block">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b border-border">
            <!-- The question column is a row header: its own eyebrow, numbered questions and a firmer
                 rule on its right, so it does not read as a third answer column. -->
            <th class="w-[28%] border-r border-border px-5 py-4 align-middle" scope="col">
              <span class="font-mono text-[0.7rem] font-medium uppercase tracking-[0.14em] text-muted-foreground">Question</span>
            </th>
            <th class="w-[34%] px-5 py-4" scope="col">
              <span class="inline-flex items-center gap-2 font-semibold text-muted-foreground">
                <Cloud class="h-4 w-4" /> Ordinary cloud storage
              </span>
            </th>
            <th class="w-[38%] bg-secondary px-5 py-4" scope="col">
              <span class="inline-flex items-center gap-2 font-semibold text-foreground">
                <ShieldCheck class="h-4 w-4" /> SecureView
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in COMPARISON" :key="row.question" class="border-b border-border last:border-0 align-top">
            <th scope="row" class="border-r border-border px-5 py-4 font-semibold text-foreground">
              <span class="flex gap-3">
                <span class="mt-px font-mono text-xs font-medium text-muted-foreground" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
                <span>{{ row.question }}</span>
              </span>
            </th>
            <td class="px-5 py-4 text-muted-foreground">
              <span class="flex gap-2"><X class="mt-0.5 h-4 w-4 shrink-0 text-destructive" />{{ row.ordinary }}</span>
            </td>
            <td class="bg-secondary px-5 py-4 text-foreground">
              <span class="flex gap-2"><Check class="mt-0.5 h-4 w-4 shrink-0 text-success" />{{ row.secureview }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Phones: one card per question -->
    <ul class="space-y-3 md:hidden">
      <li v-for="row in COMPARISON" :key="row.question" class="rounded-xl border border-border bg-card p-4">
        <p class="font-medium text-foreground">{{ row.question }}</p>
        <p class="mt-2 flex gap-2 text-sm text-muted-foreground">
          <X class="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <span><span class="font-medium">Ordinary cloud:</span> {{ row.ordinary }}</span>
        </p>
        <p class="mt-1.5 flex gap-2 text-sm text-foreground">
          <Check class="mt-0.5 h-4 w-4 shrink-0 text-success" />
          <span><span class="font-medium text-foreground">SecureView:</span> {{ row.secureview }}</span>
        </p>
      </li>
    </ul>
  </div>
</template>
