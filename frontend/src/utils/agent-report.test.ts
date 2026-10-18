import { describe, expect, it } from 'vitest'

import type { AgentReport } from '@/api/admin_api'
import { coverageLine, headline, priorityStyle, windowLabel } from './agent-report'

const report = (over: Partial<AgentReport> = {}): AgentReport => ({
  generated_at: '2026-10-02T12:00:00Z',
  window_hours: 24,
  counts: { critical: 0, high: 0, medium: 0, low: 0 },
  findings: [],
  rules: [],
  inputs: {
    audit_events_read: 1234,
    event_types_capped: [],
    files_checkable: 10,
    files_never_checked: 2,
    audit_chain_entries_verified: 5678,
    last_scan_at: null,
  },
  boundaries: [],
  ...over,
})

describe('priorityStyle', () => {
  it('names each priority in words and says how urgent it is', () => {
    expect(priorityStyle('CRITICAL')).toMatchObject({ label: 'Critical', meaning: 'Act now' })
    expect(priorityStyle('HIGH').meaning).toBe('Act today')
    expect(priorityStyle('MEDIUM').meaning).toMatch(/this week/)
    expect(priorityStyle('LOW').meaning).toBe('When convenient')
  })

  it('treats a priority it does not know as the lowest rather than hiding the finding', () => {
    expect(priorityStyle('SOMETHING_NEW')).toEqual(priorityStyle('LOW'))
  })
})

describe('headline', () => {
  it('says plainly when nothing needs attention', () => {
    expect(headline(report())).toBe('Nothing needs attention in the last 24 hours.')
  })

  it('counts findings by priority, most urgent first, with correct plurals', () => {
    expect(headline(report({ counts: { critical: 1, high: 0, medium: 2, low: 0 } }))).toBe(
      '3 findings in the last 24 hours: 1 critical, 2 medium.',
    )
    expect(headline(report({ counts: { critical: 0, high: 0, medium: 0, low: 1 }, window_hours: 168 }))).toBe(
      '1 finding in the last 7 days: 1 low.',
    )
  })
})

describe('coverageLine', () => {
  it('states how much a quiet report actually looked at', () => {
    expect(coverageLine(report())).toBe(
      'Read 1,234 audit events, verified 5,678 audit-chain entries, and 8 of 10 stored files have been integrity-checked.',
    )
  })
})

describe('coverageLine when the read was capped', () => {
  it('says which event types were cut short instead of looking complete', () => {
    const r = report()
    r.inputs.event_types_capped = ['FILE_DOWNLOAD_AUTHORIZED']

    expect(coverageLine(r)).toMatch(
      /So many FILE_DOWNLOAD_AUTHORIZED events were recorded that only the newest were read/,
    )
  })
})

describe('windowLabel', () => {
  it('has a readable label for a custom window too', () => {
    expect(windowLabel(168)).toBe('last 7 days')
    expect(windowLabel(48)).toBe('last 48 hours')
  })
})
