import type { AgentPriority, AgentReport } from '@/api/admin_api'

/**
 * How the security agent's findings are presented.
 *
 * The four priorities are the contract with the administrator: CRITICAL means act now, HIGH
 * today, MEDIUM this week, LOW when convenient. They are shown as words as well as colour, so the
 * ranking survives a colour-blind reader and a printed report.
 */
export interface PriorityStyle {
  label: string
  meaning: string
  badge: string
  card: string
}

const STYLES: Record<AgentPriority, PriorityStyle> = {
  CRITICAL: {
    label: 'Critical',
    meaning: 'Act now',
    badge: 'bg-destructive text-white',
    card: 'border-destructive/50 bg-destructive/5',
  },
  HIGH: {
    label: 'High',
    meaning: 'Act today',
    badge: 'bg-orange-600 text-white',
    card: 'border-orange-500/50 bg-orange-500/5',
  },
  MEDIUM: {
    label: 'Medium',
    meaning: 'Look into it this week',
    badge: 'bg-amber-500 text-black',
    card: 'border-amber-500/50 bg-amber-500/5',
  },
  LOW: {
    label: 'Low',
    meaning: 'When convenient',
    badge: 'bg-secondary text-foreground',
    card: 'border-border bg-card',
  },
}

export function priorityStyle(priority: string): PriorityStyle {
  return STYLES[priority as AgentPriority] ?? STYLES.LOW
}

export const WINDOWS = [
  { hours: 24, label: 'Last 24 hours' },
  { hours: 168, label: 'Last 7 days' },
] as const

export function windowLabel(hours: number): string {
  return WINDOWS.find((w) => w.hours === hours)?.label.toLowerCase() ?? `last ${hours} hours`
}

/** One sentence for the top of the report. */
export function headline(report: AgentReport): string {
  const { critical, high, medium, low } = report.counts
  const total = critical + high + medium + low
  const window = windowLabel(report.window_hours)
  if (total === 0) {
    return `Nothing needs attention in the ${window}.`
  }
  const parts = [
    critical && `${critical} critical`,
    high && `${high} high`,
    medium && `${medium} medium`,
    low && `${low} low`,
  ].filter(Boolean)
  return `${total} ${total === 1 ? 'finding' : 'findings'} in the ${window}: ${parts.join(', ')}.`
}

/**
 * What a quiet report was based on. "No findings" from an agent that read nothing would be
 * misleading, so the report says how much it actually looked at.
 */
export function coverageLine(report: AgentReport): string {
  const i = report.inputs
  const checked = i.files_checkable - i.files_never_checked
  const line =
    `Read ${i.audit_events_read.toLocaleString('en-US')} audit events, verified ` +
    `${i.audit_chain_entries_verified.toLocaleString('en-US')} audit-chain entries, and ` +
    `${checked.toLocaleString('en-US')} of ${i.files_checkable.toLocaleString('en-US')} stored files have been integrity-checked.`
  const capped = i.event_types_capped ?? []
  if (!capped.length) return line
  return (
    `${line} So many ${capped.join(', ')} events were recorded that only the newest were read; ` +
    'choose a shorter window to see all of them.'
  )
}
