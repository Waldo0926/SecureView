import { describe, expect, it } from 'vitest'

import type { AdminStats } from '@/api/admin_api'
import { algorithmMix, attentionItems } from './admin-stats'

const healthy = (): AdminStats => ({
  generated_at: '2026-10-01T12:00:00Z',
  users: { total: 5, active: 4, disabled: 1, deleted: 0, administrators: 1, created_last_7_days: 2, signed_in_last_24_hours: 3 },
  files: { total: 9, active: 9, corrupted: 0, deleted: 2, uploaded_last_24_hours: 1, original_bytes: 100, stored_bytes: 100, by_algorithm: { 'AES-256-GCM': 9 } },
  shares: { active_shares: 3, files_shared: 2 },
  integrity: { checks_last_24_hours: 4, failed_checks_last_24_hours: 0 },
  recovery: { pending_requests: 0 },
  audit: { events_total: 100, events_last_24_hours: 10, failures_last_24_hours: 0, recent_failures: [] },
})

describe('attentionItems', () => {
  it('says nothing when everything is healthy', () => {
    expect(attentionItems(healthy())).toEqual([])
  })

  it('treats damaged files and failed checks as critical and names the remedy', () => {
    const stats = healthy()
    stats.files.corrupted = 1
    stats.integrity.failed_checks_last_24_hours = 2

    const items = attentionItems(stats)

    expect(items.map((item) => item.id)).toEqual(['corrupted-files', 'failed-checks'])
    expect(items.every((item) => item.severity === 'critical')).toBe(true)
    expect(items[0].message).toBe('1 file failed the integrity check and is marked corrupted. Restore it from backup.')
    expect(items[1].message).toMatch(/^2 integrity checks did not come back valid/)
  })

  it('flags a pending recovery request and recent failures as notices, with correct plurals', () => {
    const stats = healthy()
    stats.recovery.pending_requests = 1
    stats.audit.failures_last_24_hours = 6

    const items = attentionItems(stats)

    expect(items).toEqual([
      {
        id: 'pending-recovery',
        severity: 'notice',
        message: '1 recovery request awaiting review.',
        tab: 'recovery',
        action: 'Review requests',
      },
      {
        id: 'audit-failures',
        severity: 'notice',
        message: '6 failed or blocked events in the last 24 hours.',
        tab: 'agent',
        action: 'Ask the security agent',
      },
    ])
  })

  it('links every item to the section that resolves it', () => {
    const stats = healthy()
    stats.files.corrupted = 1
    stats.integrity.failed_checks_last_24_hours = 1

    expect(attentionItems(stats).map((item) => item.tab)).toEqual(['integrity', 'integrity'])
  })
})

describe('algorithmMix', () => {
  it('orders the algorithms by how many files use them, then by name', () => {
    expect(algorithmMix({ 'ChaCha20-Poly1305': 3, 'AES-256-GCM': 9, 'AES-128-GCM': 3 })).toEqual([
      { name: 'AES-256-GCM', count: 9 },
      { name: 'AES-128-GCM', count: 3 },
      { name: 'ChaCha20-Poly1305', count: 3 },
    ])
    expect(algorithmMix({})).toEqual([])
  })
})
