import axios from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// A map is enough: these tests only read and write the two token keys.
const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
})

const { apiErrorCode, http } = await import('./http')
const { notifySessionExpired, setPasswordChangeRequiredHandler, setSessionExpiredHandler, writeSession } =
  await import('./session')

/** An axios error shaped the way an interceptor sees one. */
const unauthorized = (config: Record<string, unknown>) =>
  Object.assign(new Error('Request failed with status code 401'), {
    isAxiosError: true,
    response: { status: 401, data: { message: 'Not authenticated' } },
    config,
  })

beforeEach(() => {
  store.clear()
  setSessionExpiredHandler(undefined)
  setPasswordChangeRequiredHandler(undefined)
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

/** Drive the response interceptor directly, without a server. */
const rejectThrough = (error: unknown) => {
  const handlers = (
    http.interceptors.response as unknown as {
      handlers: { rejected: (error: unknown) => Promise<unknown> }[]
    }
  ).handlers.filter(Boolean)
  return handlers[handlers.length - 1].rejected(error)
}

describe('the 401 refresh interceptor', () => {
  it('renews the session and retries the request that failed', async () => {
    writeSession({ accessToken: 'expired', refreshToken: 'still-good' })

    const post = vi.spyOn(axios, 'post').mockResolvedValue({
      data: { data: { access_token: 'fresh', refresh_token: 'rotated' } },
    })
    const request = vi.spyOn(http, 'request').mockResolvedValue({ data: 'retried' })

    const result = await rejectThrough(unauthorized({ url: '/files', method: 'get' }))

    expect(post).toHaveBeenCalledOnce()
    expect(result).toEqual({ data: 'retried' })
    expect(localStorage.getItem('access_token')).toBe('fresh')
    // The server rotates the refresh token; keeping the old one would work exactly once.
    expect(localStorage.getItem('refresh_token')).toBe('rotated')
    expect(request).toHaveBeenCalledOnce()
  })

  it('refreshes once for a burst of simultaneous 401s', async () => {
    // Three requests in flight give three 401s. Three refreshes would present a rotated
    // token twice and turn a recoverable expiry into a forced logout.
    writeSession({ accessToken: 'expired', refreshToken: 'still-good' })

    const post = vi.spyOn(axios, 'post').mockResolvedValue({
      data: { data: { access_token: 'fresh', refresh_token: 'rotated' } },
    })
    vi.spyOn(http, 'request').mockResolvedValue({ data: 'retried' })

    await Promise.all([
      rejectThrough(unauthorized({ url: '/files' })),
      rejectThrough(unauthorized({ url: '/keys/me' })),
      rejectThrough(unauthorized({ url: '/audit-logs' })),
    ])

    expect(post).toHaveBeenCalledOnce()
  })

  it('gives up and clears the session when the refresh token is rejected', async () => {
    writeSession({ accessToken: 'expired', refreshToken: 'also-expired' })
    vi.spyOn(axios, 'post').mockRejectedValue(new Error('401'))

    const expired = vi.fn()
    setSessionExpiredHandler(expired)

    await expect(rejectThrough(unauthorized({ url: '/files' }))).rejects.toThrow()

    // Leaving the tokens behind would keep the app looking signed in while every request
    // fails -- the exact confusing state this work exists to remove.
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
    expect(expired).toHaveBeenCalledOnce()
  })

  it('does not try to refresh when there is no refresh token', async () => {
    writeSession({ accessToken: 'expired', refreshToken: '' })
    const post = vi.spyOn(axios, 'post')

    await expect(rejectThrough(unauthorized({ url: '/files' }))).rejects.toThrow()

    expect(post).not.toHaveBeenCalled()
  })

  it('does not retry a request that already came back from a retry', async () => {
    writeSession({ accessToken: 'expired', refreshToken: 'still-good' })
    const post = vi.spyOn(axios, 'post')

    await expect(
      rejectThrough(unauthorized({ url: '/files', _retriedAfterRefresh: true })),
    ).rejects.toThrow()

    expect(post).not.toHaveBeenCalled()
  })

  it('does not recurse when the refresh call is itself the thing that 401s', async () => {
    writeSession({ accessToken: 'expired', refreshToken: 'still-good' })
    const post = vi.spyOn(axios, 'post')

    await expect(rejectThrough(unauthorized({ url: '/auth/refresh' }))).rejects.toThrow()

    expect(post).not.toHaveBeenCalled()
  })

  it('passes a non-401 failure straight through', async () => {
    writeSession({ accessToken: 'good', refreshToken: 'still-good' })
    const post = vi.spyOn(axios, 'post')

    const serverError = Object.assign(new Error('500'), {
      isAxiosError: true,
      response: { status: 500, data: {} },
      config: { url: '/files' },
    })

    await expect(rejectThrough(serverError)).rejects.toThrow()
    expect(post).not.toHaveBeenCalled()
  })
})

describe('the password_change_required interceptor', () => {
  const refused = (code: string) =>
    Object.assign(new Error('Request failed with status code 403'), {
      isAxiosError: true,
      response: { status: 403, data: { message: 'Refused', data: { error_code: code } } },
      config: { url: '/files' },
    })

  it('tells the app, so the holder is sent to the password card, and still fails the request', async () => {
    writeSession({ accessToken: 'good', refreshToken: 'still-good' })
    const required = vi.fn()
    setPasswordChangeRequiredHandler(required)
    const post = vi.spyOn(axios, 'post')

    await expect(rejectThrough(refused('password_change_required'))).rejects.toThrow()

    expect(required).toHaveBeenCalledOnce()
    // The session is fine; only the password needs replacing.
    expect(post).not.toHaveBeenCalled()
    expect(localStorage.getItem('access_token')).toBe('good')
  })

  it('leaves any other 403 alone', async () => {
    const required = vi.fn()
    setPasswordChangeRequiredHandler(required)

    await expect(rejectThrough(refused('access_denied'))).rejects.toThrow()

    expect(required).not.toHaveBeenCalled()
  })
})

describe('session storage', () => {
  it('stores an absent refresh token as an absence, not as an empty credential', () => {
    writeSession({ accessToken: 'a', refreshToken: '' })
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })

  it('does nothing when no expiry handler is registered', () => {
    expect(() => notifySessionExpired()).not.toThrow()
  })
})

describe('apiErrorCode', () => {
  it('reads the stable backend code used to distinguish a revoked stale file row', () => {
    const error = Object.assign(new Error('404'), {
      isAxiosError: true,
      response: { status: 404, data: { data: { error_code: 'file_not_found' } } },
    })

    expect(apiErrorCode(error)).toBe('file_not_found')
  })
})
