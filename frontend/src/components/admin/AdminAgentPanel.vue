<script setup lang="ts">
import { Bot, CheckCircle, ChevronDown, Loader2, RefreshCw } from 'lucide-vue-next'
import { onMounted, ref, watch } from 'vue'
import { adminApi } from '@/api/admin_api'
import type { AgentReport } from '@/api/admin_api'
import { apiErrorMessage } from '@/api/http'
import { unwrapData } from '@/api/types'
import { coverageLine, headline, priorityStyle, WINDOWS } from '@/utils/agent-report'
import { formatSiteDateTime } from '@/utils/site-time'

/**
 * The security agent: it reads what the platform already records -- the audit log, the
 * integrity checks, file status, recovery requests -- and ranks what needs an administrator's
 * attention, with the evidence and a recommended action for each. It is read-only, rule-based
 * (every finding names its rule and threshold) and sees metadata only, never file contents or
 * keys. It recommends; the administrator acts.
 */
const report = ref<AgentReport | null>(null)
const windowHours = ref<number>(24)
const loading = ref(false)
const errorMessage = ref('')

async function run() {
  loading.value = true
  errorMessage.value = ''
  try {
    report.value = unwrapData(await adminApi.agentReport(windowHours.value))
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, 'The security agent could not produce a report')
  } finally {
    loading.value = false
  }
}

onMounted(() => void run())
watch(windowHours, () => void run())

const asOf = (value: string) => formatSiteDateTime(value)
</script>

<template>
  <div data-testid="admin-agent">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Bot class="h-5 w-5 text-primary" /> Security agent
        </h2>
        <p class="text-sm text-muted-foreground">
          Ranks what needs your attention from the audit log, integrity checks and recovery
          requests. Read-only, rule-based, and it never sees file contents or keys.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <label class="sr-only" for="agent-window">Time window</label>
        <select
          id="agent-window"
          v-model.number="windowHours"
          class="h-9 rounded-md border border-border bg-background px-2 text-sm"
          :disabled="loading"
          data-testid="agent-window"
        >
          <option v-for="w in WINDOWS" :key="w.hours" :value="w.hours">{{ w.label }}</option>
        </select>
        <button
          type="button"
          class="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          :disabled="loading"
          data-testid="agent-run"
          @click="run()"
        >
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
          Run analysis
        </button>
      </div>
    </div>

    <p v-if="errorMessage" class="mb-3 text-sm text-destructive" role="alert">{{ errorMessage }}</p>
    <p v-if="loading && !report" class="flex items-center gap-2 py-10 text-sm text-muted-foreground">
      <Loader2 class="h-4 w-4 animate-spin" /> Analysing…
    </p>

    <template v-if="report">
      <p class="mb-3 text-base font-medium text-foreground" data-testid="agent-headline">{{ headline(report) }}</p>

      <ul class="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="agent-counts">
        <li
          v-for="key in (['critical', 'high', 'medium', 'low'] as const)"
          :key="key"
          class="rounded-lg border border-border bg-card p-3"
        >
          <span class="inline-flex rounded-full px-2 py-0.5 text-xs font-semibold uppercase" :class="priorityStyle(key.toUpperCase()).badge">
            {{ priorityStyle(key.toUpperCase()).label }}
          </span>
          <p class="mt-2 text-2xl font-semibold text-foreground">{{ report.counts[key] }}</p>
          <p class="text-xs text-muted-foreground">{{ priorityStyle(key.toUpperCase()).meaning }}</p>
        </li>
      </ul>

      <p
        v-if="!report.findings.length"
        class="mb-4 flex items-start gap-2 rounded-lg border border-border bg-secondary/50 px-3 py-3 text-sm text-foreground"
        data-testid="agent-clean"
      >
        <CheckCircle class="mt-0.5 h-4 w-4 shrink-0 text-success" />
        <span>
          No finding from any of the {{ report.rules.length }} rules.
          <span class="text-muted-foreground">{{ coverageLine(report) }} A quiet report is not proof that nothing happened: the agent can only see what the platform recorded.</span>
        </span>
      </p>

      <ul v-else class="mb-4 space-y-3" data-testid="agent-findings">
        <li
          v-for="(finding, index) in report.findings"
          :key="`${finding.rule_id}-${index}`"
          class="rounded-lg border p-4"
          :class="priorityStyle(finding.priority).card"
          data-testid="agent-finding"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase" :class="priorityStyle(finding.priority).badge">
              {{ priorityStyle(finding.priority).label }}
            </span>
            <span class="text-xs text-muted-foreground">{{ finding.rule_id }}</span>
          </div>
          <h3 class="mt-2 font-medium text-foreground [overflow-wrap:anywhere]">{{ finding.title }}</h3>
          <p class="mt-1 text-sm text-muted-foreground">{{ finding.summary }}</p>

          <p class="mt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Why it was flagged</p>
          <ul class="mt-1 list-disc space-y-0.5 pl-5 text-sm text-foreground">
            <li v-for="line in finding.evidence" :key="line" class="[overflow-wrap:anywhere]">{{ line }}</li>
          </ul>

          <p class="mt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Recommended action</p>
          <p class="mt-1 text-sm text-foreground [overflow-wrap:anywhere]" data-testid="agent-action">{{ finding.recommended_action }}</p>
        </li>
      </ul>

      <p class="mb-4 text-xs text-muted-foreground">
        Generated {{ asOf(report.generated_at) }}. {{ coverageLine(report) }}
      </p>

      <details class="rounded-lg border border-border bg-card p-4 text-sm" data-testid="agent-how">
        <summary class="flex cursor-pointer items-center gap-2 font-medium text-foreground">
          <ChevronDown class="h-4 w-4" /> How the agent decides
        </summary>
        <p class="mt-3 text-muted-foreground">
          Each rule below is a plain, fixed check with a stated threshold. The same evidence always
          gives the same report, and the right-hand column says how many findings each rule raised
          this time.
        </p>
        <div class="mt-3 overflow-x-auto">
          <table class="w-full min-w-[34rem] text-left text-xs">
            <thead class="text-muted-foreground">
              <tr>
                <th class="py-1 pr-3 font-medium">Rule</th>
                <th class="py-1 pr-3 font-medium">Watches</th>
                <th class="py-1 pr-3 font-medium">Raises</th>
                <th class="py-1 text-right font-medium">Now</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in report.rules" :key="rule.rule_id" class="border-t border-border align-top">
                <td class="py-1.5 pr-3 font-medium text-foreground">{{ rule.name }}</td>
                <td class="py-1.5 pr-3 text-muted-foreground">{{ rule.watches }}</td>
                <td class="py-1.5 pr-3 text-muted-foreground">{{ rule.threshold }}</td>
                <td class="py-1.5 text-right text-foreground">{{ rule.findings }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-4 font-medium text-foreground">What it will not do</p>
        <ul class="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
          <li v-for="line in report.boundaries" :key="line">{{ line }}</li>
        </ul>
      </details>
    </template>
  </div>
</template>
