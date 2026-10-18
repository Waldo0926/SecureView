<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, CheckCircle2, Info, Shield } from 'lucide-vue-next'
import {
  algorithms,
  algorithmFamilyLabels,
  type AlgorithmFamily,
  type AlgorithmId,
  type AlgorithmInfo,
} from '@/data/education/algorithms'
import AlgorithmDemoPanel from '@/components/education/AlgorithmDemoPanel.vue'

type SidebarEntry =
  | { kind: 'family'; family: AlgorithmFamily; label: string; items: AlgorithmInfo[] }
  | { kind: 'item'; algo: AlgorithmInfo }

const route = useRoute()
const selectedId = ref<AlgorithmId>('aes256')
const selected = computed(() => algorithms.find((a) => a.id === selectedId.value)!)

// `/education?algorithm=<id>#algorithm-detail` opens on that algorithm, which is how the Help
// assistant links to one.
watch(
  () => route.query.algorithm,
  (id) => {
    const match = algorithms.find((a) => a.id === id)
    if (match) selectedId.value = match.id
  },
  { immediate: true },
)

const sidebar = computed<SidebarEntry[]>(() => {
  const entries: SidebarEntry[] = []
  const seenFamilies = new Set<AlgorithmFamily>()

  for (const algo of algorithms) {
    if (algo.family) {
      if (seenFamilies.has(algo.family)) continue
      seenFamilies.add(algo.family)
      entries.push({
        kind: 'family',
        family: algo.family,
        label: algorithmFamilyLabels[algo.family],
        items: algorithms.filter((a) => a.family === algo.family),
      })
      continue
    }
    entries.push({ kind: 'item', algo })
  }

  return entries
})

const typeBadge: Record<string, string> = {
  symmetric: 'Symmetric',
  asymmetric: 'Asymmetric',
  hash: 'Hash Function',
  kdf: 'Key Derivation',
}

const roundsHint = computed(() => {
  if (selected.value.id === 'aes128') return 'AES-128 · 10 rounds'
  if (selected.value.id === 'aes256') return 'AES-256 · 14 rounds'
  return selected.value.demo.posterLabel
})
</script>

<template>
  <div class="grid grid-cols-1 gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
    <aside class="min-w-0 space-y-2">
      <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide px-1 mb-3">Select Algorithm</p>

      <template v-for="entry in sidebar" :key="entry.kind === 'family' ? entry.family : entry.algo.id">
        <div v-if="entry.kind === 'family'" class="rounded-lg border border-border bg-card overflow-hidden">
          <p class="px-4 pt-3 pb-1 text-xs uppercase tracking-[0.18em] text-muted-foreground">
            {{ entry.label }}
          </p>
          <button
            v-for="algo in entry.items"
            :key="algo.id"
            type="button"
            class="w-full text-left px-4 py-2.5 transition-colors border-t border-border/70"
            :class="
              selectedId === algo.id
                ? 'bg-primary/10 text-foreground'
                : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
            "
            @click="selectedId = algo.id"
          >
            <span class="font-semibold block">{{ algo.shortLabel }}</span>
            <span class="text-xs mt-0.5 block opacity-80">{{ typeBadge[algo.type] }}</span>
          </button>
        </div>

        <button
          v-else
          type="button"
          class="w-full text-left rounded-lg border px-4 py-3 transition-colors"
          :class="
            selectedId === entry.algo.id
              ? 'border-primary bg-primary/10 text-foreground'
              : 'border-border bg-card text-muted-foreground hover:border-primary/40 hover:text-foreground'
          "
          @click="selectedId = entry.algo.id"
        >
          <span class="font-semibold block">{{ entry.algo.shortLabel }}</span>
          <span class="text-xs mt-0.5 block opacity-80">{{ typeBadge[entry.algo.type] }}</span>
        </button>
      </template>
    </aside>

    <article id="algorithm-detail" class="flex min-w-0 scroll-mt-24 flex-col rounded-xl border border-border bg-card p-4 sm:p-6 md:p-8">
      <div class="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <span class="mb-3 inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
            <Shield class="h-3.5 w-3.5" />
            {{ typeBadge[selected.type] }}
            <template v-if="selected.family"> · {{ algorithmFamilyLabels[selected.family] }}</template>
          </span>
          <h3 class="text-2xl font-bold text-foreground">{{ selected.name }}</h3>
          <p class="text-muted-foreground mt-2 max-w-2xl">{{ selected.tagline }}</p>
        </div>
      </div>

      <p class="text-sm text-foreground leading-relaxed mb-6">{{ selected.summary }}</p>

      <div class="my-4 flex min-h-[14rem] w-full min-w-0 flex-1 items-center justify-center overflow-x-auto">
        <AlgorithmDemoPanel
          :demo="selected.demo"
          :algorithm-id="selected.id"
          :rounds-hint="roundsHint"
        />
      </div>

      <div class="mb-8 mt-6">
        <h4 class="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
          <ArrowRight class="h-4 w-4 text-primary" />
          How It Works
        </h4>
        <div class="space-y-3">
          <div
            v-for="(step, i) in selected.howItWorks"
            :key="step.title"
            class="flex gap-4 rounded-lg border border-border bg-secondary/20 p-4"
          >
            <div class="flex-shrink-0 h-8 w-8 rounded-full bg-primary/15 text-primary text-sm font-bold flex items-center justify-center">
              {{ i + 1 }}
            </div>
            <div>
              <p class="font-medium text-foreground">{{ step.title.replace(/^\d+\.\s*/, '') }}</p>
              <p class="text-sm text-muted-foreground mt-1">{{ step.description }}</p>
            </div>
          </div>
        </div>
      </div>

      <div class="grid md:grid-cols-3 gap-4 mb-8">
        <div class="rounded-lg border border-border p-4">
          <p class="text-xs font-medium text-primary mb-2">Use Cases</p>
          <ul class="space-y-1.5">
            <li v-for="item in selected.useCases" :key="item" class="text-sm text-muted-foreground flex gap-2">
              <CheckCircle2 class="h-4 w-4 text-success flex-shrink-0 mt-0.5" />
              {{ item }}
            </li>
          </ul>
        </div>
        <div class="rounded-lg border border-border p-4">
          <p class="text-xs font-medium text-primary mb-2">Strengths</p>
          <ul class="space-y-1.5">
            <li v-for="item in selected.strengths" :key="item" class="text-sm text-muted-foreground">• {{ item }}</li>
          </ul>
        </div>
        <div class="rounded-lg border border-border p-4">
          <p class="text-xs font-medium text-destructive mb-2">Limitations</p>
          <ul class="space-y-1.5">
            <li v-for="item in selected.limitations" :key="item" class="text-sm text-muted-foreground">• {{ item }}</li>
          </ul>
        </div>
      </div>

      <div class="rounded-lg border border-primary/20 bg-primary/5 p-4">
        <p class="text-xs font-medium text-primary mb-2 flex items-center gap-1.5">
          <Info class="h-3.5 w-3.5" />
          Key Facts
        </p>
        <ul class="space-y-1">
          <li v-for="fact in selected.keyFacts" :key="fact" class="text-sm text-foreground">• {{ fact }}</li>
        </ul>
      </div>
    </article>
  </div>
</template>
