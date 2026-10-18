import { describe, expect, it } from 'vitest'

import { matchesSearch, statusBadgeClass } from './admin-lists'

describe('admin list helpers', () => {
  it('matches any field, ignoring case and surrounding spaces', () => {
    expect(matchesSearch('', 'alice')).toBe(true)
    expect(matchesSearch('  ALI ', 'alice')).toBe(true)
    expect(matchesSearch('report', 'notes.txt', 'Report Q3.pdf')).toBe(true)
    expect(matchesSearch('bob', 'alice', null, undefined)).toBe(false)
  })

  it('gives damage and disabling their own colours and leaves deleted muted', () => {
    expect(statusBadgeClass('ACTIVE')).toContain('text-primary')
    expect(statusBadgeClass('CORRUPTED')).toContain('text-destructive')
    expect(statusBadgeClass('DISABLED')).toContain('amber')
    expect(statusBadgeClass('DELETED')).toContain('text-muted-foreground')
  })
})
