<script setup lang="ts">
import { computed, ref } from 'vue'
import PageHeader from '@/components/securfile/PageHeader.vue'
import { Clipboard, Loader2, Play } from 'lucide-vue-next'
import { DEFAULT_ARGON2_COST, deriveKek, type Argon2Cost } from '@/utils/account-crypto'

/**
 * Measure the Argon2id KEK derivation on this device, using the production code path.
 *
 * Evidence for the threat model (Issue #60): how long an unlock takes on real clients at the
 * enrolled cost, and how much headroom there is to raise it. It calls the same `deriveKek`
 * the unlock dialog calls, so the number is the user's wait, not a lookalike's.
 *
 * Nothing here touches an account. The passphrase is a fixed dummy and the salt is random.
 */

interface Config {
  label: string
  cost: Argon2Cost
  production?: boolean
}

interface Result {
  label: string
  memoryKib: number
  iterations: number
  parallelism: number
  runsMs: number[]
  medianMs: number | null
  minMs: number | null
  maxMs: number | null
  error: string | null
}

const RUNS = 5

const CONFIGS: Config[] = [
  { label: 'Production (64 MiB, t=3)', cost: DEFAULT_ARGON2_COST, production: true },
  { label: '64 MiB, t=6', cost: { memorySize: 65536, iterations: 6, parallelism: 1 } },
  { label: '128 MiB, t=3', cost: { memorySize: 131072, iterations: 3, parallelism: 1 } },
  { label: '256 MiB, t=3', cost: { memorySize: 262144, iterations: 3, parallelism: 1 } },
]

const running = ref(false)
const progress = ref('')
const results = ref<Result[]>([])
const copied = ref(false)

const device = computed(() => {
  const nav = navigator as Navigator & { deviceMemory?: number }
  return {
    userAgent: nav.userAgent,
    hardwareConcurrency: nav.hardwareConcurrency ?? null,
    // Chromium only; other engines leave it undefined.
    deviceMemoryGiB: nav.deviceMemory ?? null,
  }
})

const report = computed(() =>
  JSON.stringify(
    {
      benchmark: 'secureview-argon2id-kek',
      version: 1,
      measuredAt: new Date().toISOString(),
      runsPerConfig: RUNS,
      device: device.value,
      results: results.value,
    },
    null,
    2,
  ),
)

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2
}

/** Yield so the progress text paints; each derivation blocks the main thread. */
const nextFrame = () => new Promise((resolve) => setTimeout(resolve, 30))

async function run() {
  running.value = true
  copied.value = false
  results.value = []
  try {
    for (const config of CONFIGS) {
      const result: Result = {
        label: config.label,
        memoryKib: config.cost.memorySize,
        iterations: config.cost.iterations,
        parallelism: config.cost.parallelism,
        runsMs: [],
        medianMs: null,
        minMs: null,
        maxMs: null,
        error: null,
      }
      try {
        // One untimed warm-up, so WebAssembly compilation is not billed to the first run.
        progress.value = `${config.label}: warming up`
        await nextFrame()
        await deriveKek('benchmark passphrase', crypto.getRandomValues(new Uint8Array(16)), config.cost)

        for (let i = 1; i <= RUNS; i += 1) {
          progress.value = `${config.label}: run ${i} of ${RUNS}`
          await nextFrame()
          const salt = crypto.getRandomValues(new Uint8Array(16))
          const started = performance.now()
          await deriveKek('benchmark passphrase', salt, config.cost)
          result.runsMs.push(Math.round(performance.now() - started))
        }
        result.medianMs = median(result.runsMs)
        result.minMs = Math.min(...result.runsMs)
        result.maxMs = Math.max(...result.runsMs)
      } catch (error) {
        // A large memory cost can fail outright on a phone. That is a result, not a bug.
        result.error = error instanceof Error ? `${error.name}: ${error.message}` : String(error)
      }
      results.value = [...results.value, result]
    }
    progress.value = 'Done'
  } finally {
    running.value = false
  }
}

async function copyReport() {
  try {
    await navigator.clipboard.writeText(report.value)
    copied.value = true
  } catch {
    // Clipboard access needs a secure context; the text box below is the fallback.
    copied.value = false
  }
}
</script>

<template>
  <section class="product-page">
    <div class="page-container">
      <PageHeader
        eyebrow="Threat-model evidence"
        title="Argon2id benchmark"
        subtitle="Measures how long this device takes to derive the key that unlocks an account, using exactly the code the unlock dialog uses. It does not touch any account. Keep this tab in the foreground and do not use the device while it runs; it takes up to a minute on a phone."
      />

      <div class="rounded-xl border border-border bg-card p-6">
        <dl class="grid gap-2 text-sm">
          <div><dt class="inline text-muted-foreground">Logical CPUs: </dt><dd class="inline text-foreground">{{ device.hardwareConcurrency ?? 'unknown' }}</dd></div>
          <div><dt class="inline text-muted-foreground">Device memory: </dt><dd class="inline text-foreground">{{ device.deviceMemoryGiB ? `${device.deviceMemoryGiB} GiB (approximate)` : 'not reported by this browser' }}</dd></div>
          <div><dt class="text-muted-foreground">User agent:</dt><dd class="break-all text-xs text-foreground">{{ device.userAgent }}</dd></div>
        </dl>

        <button
          type="button"
          :disabled="running"
          class="mt-5 inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          @click="run"
        >
          <Loader2 v-if="running" class="h-4 w-4 animate-spin" />
          <Play v-else class="h-4 w-4" />
          {{ running ? 'Running…' : 'Run benchmark' }}
        </button>
        <p v-if="progress" class="mt-2 text-xs text-muted-foreground">{{ progress }}</p>
      </div>

      <div v-if="results.length" class="mt-6 rounded-xl border border-border bg-card p-6">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-muted-foreground">
              <th class="pb-2 font-medium">Cost</th>
              <th class="pb-2 font-medium">Median</th>
              <th class="pb-2 font-medium">Range</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in results" :key="r.label" class="border-t border-border">
              <td class="py-2 text-foreground">{{ r.label }}</td>
              <td class="py-2 font-semibold text-foreground">
                {{ r.error ? 'failed' : `${r.medianMs} ms` }}
              </td>
              <td class="py-2 text-muted-foreground">
                {{ r.error ?? `${r.minMs}–${r.maxMs} ms` }}
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="!running" class="mt-5">
          <button
            type="button"
            class="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm text-foreground transition-colors hover:bg-secondary"
            @click="copyReport"
          >
            <Clipboard class="h-4 w-4" />
            {{ copied ? 'Copied' : 'Copy results' }}
          </button>
          <textarea
            readonly
            :value="report"
            class="mt-3 h-48 w-full rounded-md border border-border bg-background p-2 font-mono text-xs text-foreground"
          />
        </div>
      </div>
    </div>
  </section>
</template>
