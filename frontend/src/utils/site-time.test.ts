import { describe, expect, it } from 'vitest'

import { formatSiteDate, formatSiteDateTime, siteDayBoundary } from './site-time'

describe('site time', () => {
  it('shows a UTC instant in Kuala Lumpur time with its zone', () => {
    // The moment the security agent first saw the demo damage: 18:19 UTC is 02:19 next day.
    expect(formatSiteDateTime('2026-10-12T18:19:42Z')).toBe('2026-10-13 02:19:42 MYT')
    expect(formatSiteDateTime('2026-10-12T18:19:42Z', { seconds: false })).toBe('2026-10-13 02:19 MYT')
    expect(formatSiteDateTime(new Date(Date.UTC(2026, 0, 1, 0, 0, 0)))).toBe('2026-01-01 08:00:00 MYT')
  })

  it('reads a server timestamp without an offset as UTC only when it says so', () => {
    expect(formatSiteDateTime('2026-10-12T21:30:14+00:00')).toBe('2026-10-13 05:30:14 MYT')
  })

  it('gives the Kuala Lumpur calendar day', () => {
    expect(formatSiteDate('2026-10-12T15:59:59Z')).toBe('2026-10-12')
    expect(formatSiteDate('2026-10-12T16:00:00Z')).toBe('2026-10-13')
  })

  it('leaves anything that is not a time as it was', () => {
    expect(formatSiteDateTime('not a date')).toBe('not a date')
    expect(formatSiteDate('')).toBe('')
  })

  it('bounds a Kuala Lumpur day in UTC', () => {
    expect(siteDayBoundary(2026, 10, 13, 'start')).toBe('2026-10-12T16:00:00.000Z')
    expect(siteDayBoundary(2026, 10, 13, 'end')).toBe('2026-10-13T15:59:59.999Z')
  })
})
