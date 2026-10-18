import { afterEach, describe, expect, it, vi } from 'vitest'

import { auditApi } from '@/api/audit_api'

import {
  EMPTY_AUDIT_FILTERS,
  fetchAuditPage,
  hasAuditFilters,
  PAGE_SIZE,
  toAuditLogFilters,
} from './audit-trail'

const row = (i: number) => ({
  action: 'FILE_DOWNLOAD_AUTHORIZED',
  resource_type: 'FILE',
  resource_id: `file-${i}`,
  actor_user_id: 'u',
  actor_username: 'waldo',
  target_user_id: null,
  target_username: null,
  result: 'SUCCESS',
  description: null,
  metadata: {},
  created_at: '2026-09-01T00:00:00Z',
})

const page = (count: number, hasMore: boolean, from = 0) => ({
  data: {
    success: true,
    status: 'ok',
    message: '',
    code: 200,
    data: {
      logs: Array.from({ length: count }, (_, i) => row(from + i)),
      limit: PAGE_SIZE,
      offset: from,
      has_more: hasMore,
    },
  },
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('fetchAuditPage', () => {
  it('asks for exactly one page and reports whether more remain', async () => {
    // The old walker issued ten requests on a long-lived account before the page could draw
    // anything. One request per page, and the person decides whether to load the next.
    const list = vi.spyOn(auditApi, 'listLogs').mockResolvedValue(page(PAGE_SIZE, true) as never)

    const result = await fetchAuditPage({}, 0)

    expect(result.logs).toHaveLength(PAGE_SIZE)
    expect(result.hasMore).toBe(true)
    expect(list).toHaveBeenCalledOnce()
    expect(list).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: 0 })
  })

  it('asks for the next page by offset, with the same filters', async () => {
    const list = vi.spyOn(auditApi, 'listLogs').mockResolvedValue(page(12, false, 200) as never)

    const result = await fetchAuditPage({ result: 'FAIL', q: 'report' }, 200)

    expect(result.logs).toHaveLength(12)
    expect(result.hasMore).toBe(false)
    expect(list).toHaveBeenCalledWith({ result: 'FAIL', q: 'report', limit: PAGE_SIZE, offset: 200 })
  })

  it('survives a page that carries no rows at all', async () => {
    vi.spyOn(auditApi, 'listLogs').mockResolvedValue({
      data: { success: true, status: 'ok', message: '', code: 200, data: { logs: null, has_more: false } },
    } as never)

    await expect(fetchAuditPage({}, 0)).resolves.toEqual({ logs: [], hasMore: false })
  })
})

describe('toAuditLogFilters', () => {
  it('sends nothing for an empty form', () => {
    expect(toAuditLogFilters({ ...EMPTY_AUDIT_FILTERS })).toEqual({})
    expect(hasAuditFilters({ ...EMPTY_AUDIT_FILTERS })).toBe(false)
  })

  it('turns a Kuala Lumpur calendar day into its first and last UTC instant', () => {
    // Whatever zone the browser is in, the window is that whole day in Kuala Lumpur (UTC+8),
    // the zone every time on the site is shown in.
    const filters = toAuditLogFilters({ ...EMPTY_AUDIT_FILTERS, from: '2026-10-01', to: '2026-10-03' })

    expect(filters.from).toBe('2026-09-30T16:00:00.000Z')
    expect(filters.to).toBe('2026-10-03T15:59:59.999Z')
    expect(filters.from!.endsWith('Z')).toBe(true)
  })

  it('drops a date that is not a real day instead of sending it', () => {
    const filters = toAuditLogFilters({ ...EMPTY_AUDIT_FILTERS, from: '2026-02-30', to: 'yesterday' })
    expect(filters).toEqual({})
  })

  it('passes the event type and result through and trims the keyword', () => {
    const filters = toAuditLogFilters({
      action: 'FILE_SHARED',
      result: 'FAIL',
      from: '',
      to: '',
      q: '  report  ',
    })
    expect(filters).toEqual({ action: 'FILE_SHARED', result: 'FAIL', q: 'report' })
    expect(hasAuditFilters({ action: 'FILE_SHARED', result: '', from: '', to: '', q: '' })).toBe(true)
  })

  it('caps the keyword at the 100 characters the server accepts', () => {
    const filters = toAuditLogFilters({ ...EMPTY_AUDIT_FILTERS, q: 'x'.repeat(140) })
    expect(filters.q).toHaveLength(100)
  })
})
