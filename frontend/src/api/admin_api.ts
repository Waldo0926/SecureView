import { http } from './http'
import type { ApiEnvelope } from './types'

export interface AdminUserOut {
  user_id: string
  username: string
  email?: string | null
  email_verified?: boolean | null
  role: string
  status: string
  created_at: string
  last_login_at: string | null
  password_changed_at?: string | null
}

/** One account as an administrator sees it: counts only, never a password, hash or key. */
export interface AdminUserDetail extends AdminUserOut {
  file_count: number
  stored_bytes: number
  shared_by_them: number
  shared_with_them: number
  active_sessions: number
}

export interface AdminPasswordReset {
  user_id: string
  username: string
  /** Shown once; only its hash is stored. */
  temporary_password: string
  revoked_sessions: number
  notice_sent: boolean
}

export type AdminUserStatusFilter = 'CURRENT' | 'ACTIVE' | 'DISABLED' | 'DELETED'
export type AdminFileStatusFilter = 'CURRENT' | 'ACTIVE' | 'CORRUPTED' | 'DELETED'

export interface AdminUserList {
  users: AdminUserOut[]
  limit: number
  offset: number
  has_more: boolean
}

export interface AdminFileOut {
  file_id: string
  owner_id: string
  owner_username: string
  original_filename: string
  mime_type: string | null
  file_size: number
  encrypted_size: number | null
  status: string
  created_at: string
  updated_at: string
}

export interface AdminFileList {
  files: AdminFileOut[]
  limit: number
  offset: number
  has_more: boolean
}

export interface AdminStats {
  generated_at: string
  users: {
    total: number
    active: number
    disabled: number
    deleted: number
    administrators: number
    created_last_7_days: number
    signed_in_last_24_hours: number
  }
  files: {
    total: number
    active: number
    corrupted: number
    deleted: number
    uploaded_last_24_hours: number
    original_bytes: number
    stored_bytes: number
    by_algorithm: Record<string, number>
  }
  shares: { active_shares: number; files_shared: number }
  integrity: { checks_last_24_hours: number; failed_checks_last_24_hours: number }
  recovery: { pending_requests: number }
  audit: {
    events_total: number
    events_last_24_hours: number
    failures_last_24_hours: number
    recent_failures: {
      action: string
      result: string
      created_at: string
      actor_username: string | null
    }[]
  }
}

export interface AdminDamagedFile {
  file_id: string
  owner_username: string
  original_filename: string
  status: string
  last_result: string | null
  last_message: string | null
  last_checked_at: string | null
}

export interface AdminIntegrityReport {
  generated_at: string
  coverage: {
    candidates: number
    never_checked: number
    checked_last_24_hours: number
    last_sweep_at: string | null
  }
  damaged: AdminDamagedFile[]
  has_more: boolean
}

export interface AdminIntegrityScan {
  scanned: number
  valid: number
  damaged: number
  candidates: number
  stopped_early: boolean
  damaged_file_ids: string[]
}

export type AgentPriority = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

export interface AgentFinding {
  rule_id: string
  priority: AgentPriority
  title: string
  summary: string
  evidence: string[]
  recommended_action: string
  file_id: string | null
}

export interface AgentReport {
  generated_at: string
  window_hours: number
  counts: { critical: number; high: number; medium: number; low: number }
  findings: AgentFinding[]
  rules: { rule_id: string; name: string; watches: string; threshold: string; findings: number }[]
  inputs: {
    audit_events_read: number
    /** Event types that hit the per-type read cap, so their oldest events were not read. */
    event_types_capped: string[]
    files_checkable: number
    files_never_checked: number
    audit_chain_entries_verified: number
    last_scan_at: string | null
  }
  boundaries: string[]
}

export interface AdminUserStatusResult {
  user_id: string
  status: string
  changed: boolean
  revoked_sessions: number
}

export const adminApi = {
  /** `status` CURRENT means every account that has not been deleted; omit it for all. */
  listUsers(params?: { limit?: number; offset?: number; status?: AdminUserStatusFilter }) {
    return http.get<ApiEnvelope<AdminUserList>>('/admin/users', { params })
  },
  /** Counts only: how big the platform is and how healthy. No names, keys or addresses. */
  stats() {
    return http.get<ApiEnvelope<AdminStats>>('/admin/stats')
  },
  /** Which files are damaged, and how much of the store has been verified at all. */
  integrityReport() {
    return http.get<ApiEnvelope<AdminIntegrityReport>>('/admin/integrity')
  },
  /** Verify a bounded batch of stored objects now, least recently checked first. */
  scanIntegrity() {
    return http.post<ApiEnvelope<AdminIntegrityScan>>('/admin/integrity/scan')
  },
  /** The security agent's ranked findings: read-only, rule-based, metadata only. */
  agentReport(windowHours: number) {
    return http.get<ApiEnvelope<AgentReport>>('/admin/agent/report', {
      params: { window_hours: windowHours },
    })
  },
  /** `status` CURRENT means every file that has not been deleted; omit it for all. */
  listFiles(params?: { limit?: number; offset?: number; status?: AdminFileStatusFilter }) {
    return http.get<ApiEnvelope<AdminFileList>>('/admin/files', { params })
  },
  getUser(userId: string) {
    return http.get<ApiEnvelope<AdminUserDetail>>(`/admin/users/${userId}`)
  },
  resetUserPassword(userId: string) {
    return http.post<ApiEnvelope<AdminPasswordReset>>(`/admin/users/${userId}/reset-password`)
  },
  disableUser(userId: string) {
    return http.post<ApiEnvelope<AdminUserStatusResult>>(`/admin/users/${userId}/disable`)
  },
  enableUser(userId: string) {
    return http.post<ApiEnvelope<AdminUserStatusResult>>(`/admin/users/${userId}/enable`)
  },
}
