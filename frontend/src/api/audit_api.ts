import { http } from './http'
import type { ApiEnvelope, AuditLogOut } from './types'

export interface AuditLogPage {
  logs: AuditLogOut[]
  limit: number
  offset: number
  has_more: boolean
}

/**
 * The optional filters `GET /audit-logs` accepts. Each one narrows the caller's own page and
 * none widens it: the server applies its visibility rule first and these on top.
 *
 * `from` and `to` are ISO 8601 instants in UTC (inclusive). `action` must be one of the
 * server's event types or the request is a 422, and `q` is capped at 100 characters.
 */
export interface AuditLogFilters {
  action?: string
  result?: 'SUCCESS' | 'FAIL'
  from?: string
  to?: string
  q?: string
}

export interface AuditLogListParams extends AuditLogFilters {
  limit?: number
  offset?: number
}

/**
 * Only the keys that carry a value go on the query string.
 *
 * axios already drops `undefined`, but an empty select or a cleared text box gives `''`, and
 * `action=` would be refused by the server as an unknown action rather than ignored.
 */
export function auditLogParams(params?: AuditLogListParams): Record<string, string | number> {
  const query: Record<string, string | number> = {}
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === '') continue
    query[key] = value as string | number
  }
  return query
}

// Every audit route answers through the same `ok(...)` envelope as the rest of the API.
// These three declared the inner payload as if it arrived bare, so `unwrapData` was
// reaching through a wrapper TypeScript had been told was not there.
export const auditApi = {
  /**
   * One page of the caller's audit trail, optionally filtered.
   *
   * `limit` caps at 100 server-side and defaults to 50, and the response says whether more
   * remain. The page shows what it has loaded and offers the next page on request; it no
   * longer walks the whole trail up front.
   */
  listLogs(params?: AuditLogListParams) {
    return http.get<ApiEnvelope<AuditLogPage>>('/audit-logs', { params: auditLogParams(params) })
  },
  listFileLogs(fileId: string) {
    return http.get<ApiEnvelope<{ file_id: string; logs: AuditLogOut[] }>>(
      `/audit-logs/file/${fileId}`,
    )
  },
  /**
   * ADMIN only. Recomputes every hash in the table, so a non-admin gets a 403 -- which is a
   * permission answer, not a finding about the chain.
   */
  verifyChain() {
    return http.post<
      ApiEnvelope<{
        status: string
        valid: boolean
        checked_entries: number
        first_invalid_position: number | null
      }>
    >('/audit-logs/verify-chain')
  },
}
