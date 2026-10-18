import axios, { type AxiosRequestConfig } from 'axios'

import { currentLocale, i18n, t } from '@/i18n'
import {
  clearSession,
  notifyPasswordChangeRequired,
  notifySessionExpired,
  readAccessToken,
  readRefreshToken,
  writeSession,
} from './session'

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
})

interface ApiFailureBody {
  message?: string
  data?: {
    error_code?: string
    details?: unknown
  }
}

/**
 * Turn an API failure into something a user can act on.
 *
 * The backend answers with `{message, data:{error_code, details}}`, and field
 * validation arrives as a list of locations. Surfacing that beats the bare
 * "Request failed with status code 422" axios produces by default.
 */
export function apiErrorMessage(error: unknown, fallback = 'Request failed'): string {
  if (!axios.isAxiosError(error)) {
    return error instanceof Error ? error.message : fallback
  }

  if (error.response === undefined) {
    return t('errors.unreachable')
  }

  const body = failureBody(error.response.data)
  // In Chinese, a known error code gets its translated message; the server's English is the
  // source of truth for English, so it is left exactly as sent.
  const code = body?.data?.error_code
  if (currentLocale.value !== 'en' && code && i18n.global.te(`errors.${code}`, 'en')) {
    const translated = t(`errors.${code}`)
    const details = body?.data?.details
    return Array.isArray(details) && details.length > 0 ? `${translated}（${describeDetails(details)}）` : translated
  }
  const details = body?.data?.details
  if (Array.isArray(details) && details.length > 0) {
    const described = describeDetails(details)
    if (described) return described
  }

  return body?.message ?? fallback
}

function describeDetails(details: unknown[]): string {
  return details
    .map((detail) => {
      const item = detail as { location?: unknown[]; message?: string }
      const field = Array.isArray(item.location)
        ? item.location.filter((part) => part !== 'body').join('.')
        : ''
      return field ? `${field}: ${item.message ?? 'invalid value'}` : (item.message ?? '')
    })
    .filter(Boolean)
    .join('; ')
}

/** Read the stable backend error code without coupling callers to Axios response shapes. */
export function apiErrorCode(error: unknown): string | undefined {
  if (!axios.isAxiosError(error)) return undefined
  return failureBody(error.response?.data)?.data?.error_code
}

/**
 * A request made with `responseType: 'arraybuffer'` (the downloads) gets its JSON error body as
 * bytes too. Decoding it here is what lets a refused download say why, instead of "failed".
 */
function failureBody(data: unknown): ApiFailureBody | undefined {
  if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) {
    try {
      const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
      return JSON.parse(new TextDecoder().decode(bytes)) as ApiFailureBody
    } catch {
      return undefined
    }
  }
  return data as ApiFailureBody | undefined
}

http.interceptors.request.use((config) => {
  const token = readAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** Set once a request has been retried, so a second 401 cannot loop. */
interface RetriableConfig extends AxiosRequestConfig {
  _retriedAfterRefresh?: boolean
}

const REFRESH_PATH = '/auth/refresh'

/** The error code the server answers with while an administrator's reset is unresolved. */
export const PASSWORD_CHANGE_REQUIRED_CODE = 'password_change_required'

/**
 * One refresh at a time.
 *
 * A page that fires three requests at once gets three 401s at once. Without this, each
 * would start its own refresh, and since the server rotates the refresh token on every
 * call, the second and third would present a token the first had already consumed --
 * turning one recoverable expiry into a forced logout. They now await the same promise.
 */
let inFlightRefresh: Promise<boolean> | undefined

async function refreshSession(): Promise<boolean> {
  const refreshToken = readRefreshToken()
  if (!refreshToken) return false

  try {
    // A bare axios call, not `http`: the interceptors below must not see this response, or
    // a failed refresh would recurse into itself.
    const response = await axios.post(`${http.defaults.baseURL}${REFRESH_PATH}`, {
      refresh_token: refreshToken,
    })
    const data = response.data?.data
    if (!data?.access_token) return false
    writeSession({
      accessToken: data.access_token,
      // The server rotates the refresh token; keeping the old one would work exactly once.
      refreshToken: data.refresh_token ?? '',
    })
    return true
  } catch {
    return false
  }
}

function refreshOnce(): Promise<boolean> {
  inFlightRefresh ??= refreshSession().finally(() => {
    inFlightRefresh = undefined
  })
  return inFlightRefresh
}

/**
 * Renew a session that expired mid-use instead of surfacing the bare authorization error.
 *
 * The access token lasts 30 minutes and the refresh token 7 days, but the refresh token was
 * being discarded at login and never presented -- so a tab left open for half an hour
 * answered "Not authenticated" to the next click, with nothing on screen explaining why or
 * suggesting what to do about it.
 */
http.interceptors.response.use(
  (response) => response,
  async (error) => {
    // The server refuses almost everything while an administrator's temporary password is
    // in place. The request still fails as it would have; this only sends the holder to the
    // card that fixes it, which the router guard already does when it knows in advance.
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 403 &&
      apiErrorCode(error) === PASSWORD_CHANGE_REQUIRED_CODE
    ) {
      notifyPasswordChangeRequired()
      return Promise.reject(error)
    }
    if (!axios.isAxiosError(error) || error.response?.status !== 401) {
      return Promise.reject(error)
    }

    const config = error.config as RetriableConfig | undefined
    // A 401 from the refresh call itself, or from a request already retried, is final.
    if (!config || config._retriedAfterRefresh || config.url?.includes(REFRESH_PATH)) {
      return Promise.reject(error)
    }

    if (await refreshOnce()) {
      config._retriedAfterRefresh = true
      return http.request(config)
    }

    // Out of options: the stored tokens cannot authenticate anything, so clear them rather
    // than leaving the app looking signed in while every request fails.
    clearSession()
    notifySessionExpired()
    return Promise.reject(error)
  },
)
