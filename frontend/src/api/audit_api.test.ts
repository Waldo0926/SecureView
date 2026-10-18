import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()

vi.mock('./http', () => ({
  http: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))

import { auditApi, auditLogParams } from './audit_api'

describe('auditApi', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    get.mockResolvedValue({ data: { data: {} } })
    post.mockResolvedValue({ data: { data: {} } })
  })

  it('lists a page with no filters as the plain route', async () => {
    await auditApi.listLogs({ limit: 100, offset: 200 })
    expect(get).toHaveBeenCalledWith('/audit-logs', { params: { limit: 100, offset: 200 } })
  })

  it('sends every filter under the name the server reads', async () => {
    await auditApi.listLogs({
      limit: 100,
      offset: 0,
      action: 'FILE_SHARED',
      result: 'FAIL',
      from: '2026-09-30T14:00:00.000Z',
      to: '2026-10-01T13:59:59.999Z',
      q: 'report',
    })
    expect(get).toHaveBeenCalledWith('/audit-logs', {
      params: {
        limit: 100,
        offset: 0,
        action: 'FILE_SHARED',
        result: 'FAIL',
        from: '2026-09-30T14:00:00.000Z',
        to: '2026-10-01T13:59:59.999Z',
        q: 'report',
      },
    })
  })

  it('leaves an empty filter off the query string instead of sending action=', async () => {
    // `action=` is an unknown action to the server (a 422), not "no filter".
    await auditApi.listLogs({ limit: 100, action: '', result: undefined, q: '' })
    expect(get).toHaveBeenCalledWith('/audit-logs', { params: { limit: 100 } })
  })

  it('works with no arguments at all', async () => {
    await auditApi.listLogs()
    expect(get).toHaveBeenCalledWith('/audit-logs', { params: {} })
  })

  it('verifies the chain with POST and no body', async () => {
    await auditApi.verifyChain()
    expect(post).toHaveBeenCalledWith('/audit-logs/verify-chain')
  })
})

describe('auditLogParams', () => {
  it('keeps zero, which is a real offset', () => {
    expect(auditLogParams({ offset: 0 })).toEqual({ offset: 0 })
  })
})
