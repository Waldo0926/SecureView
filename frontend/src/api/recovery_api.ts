import { http } from './http'
import type { ApiEnvelope } from './types'

/**
 * The active recovery public key.
 *
 * Every upload must wrap its file key to this key as well as to the owner's. The matching
 * private key is held offline, so a client can never verify that wrapping — see
 * `docs/crypto/FILE_ENVELOPE.md`, "Required self-tests".
 */
export interface RecoveryPublicKey {
  key_id: string
  algorithm: 'RSA-OAEP-SHA256'
  key_size_bits: number
  public_key_pem: string
  fingerprint: string
  status: 'ACTIVE' | 'REVOKED'
  created_at: string
}

export type RecoveryStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXECUTED' | 'CANCELLED'

export interface RecoveryRequestOut {
  request_id: string
  file_id: string
  requested_by: string
  target_key_id: string
  reviewer_id: string | null
  executor_id: string | null
  reason: string
  rejection_reason: string | null
  status: RecoveryStatus
  created_at: string
  updated_at: string
  expires_at: string
  approved_at: string | null
  rejected_at: string | null
  executed_at: string | null
  cancelled_at: string | null
}

export interface RecoveryRequestList {
  requests: RecoveryRequestOut[]
  page: number
  page_size: number
  total: number
}

export interface RecoveryRequestAction {
  request: RecoveryRequestOut
  changed: boolean
}

export interface RecoveryKeyRegistration {
  key: RecoveryPublicKey
  created: boolean
  rotated_keys: number
}

export interface RecoveryKeyStatus {
  key_id: string
  status: 'REVOKED'
  changed: boolean
}

export interface RecoveryExecutionKey {
  key_id: string
  algorithm: string
  key_size_bits: number
  public_key_pem: string
  fingerprint: string
}

/**
 * What a recovery officer takes offline to unwrap with the recovery private key and rewrap
 * to the requester's target public key. The private key never enters this client.
 */
export interface RecoveryExecutionPackage {
  request_id: string
  file_id: string
  requester_id: string
  expires_at: string
  recovery_key: RecoveryExecutionKey
  recovery_wrapped_file_key: string
  target_key: RecoveryExecutionKey
}

export const recoveryApi = {
  getPublicKey() {
    return http.get<ApiEnvelope<RecoveryPublicKey>>('/recovery/public-key')
  },
  registerPublicKey(payload: {
    key_id: string
    public_key_pem: string
    algorithm?: 'RSA-OAEP-SHA256'
  }) {
    return http.post<ApiEnvelope<RecoveryKeyRegistration>>('/recovery/public-key/register', {
      algorithm: 'RSA-OAEP-SHA256',
      ...payload,
    })
  },
  revokePublicKey(keyId: string) {
    return http.post<ApiEnvelope<RecoveryKeyStatus>>(`/recovery/public-key/${keyId}/revoke`)
  },
  createRequest(payload: { file_id: string; reason: string; target_key_id: string }) {
    return http.post<ApiEnvelope<RecoveryRequestOut>>('/recovery/request', payload)
  },
  approve(requestId: string) {
    return http.post<ApiEnvelope<RecoveryRequestAction>>(`/recovery/${requestId}/approve`)
  },
  reject(requestId: string, rejection_reason: string) {
    return http.post<ApiEnvelope<RecoveryRequestAction>>(`/recovery/${requestId}/reject`, {
      rejection_reason,
    })
  },
  cancel(requestId: string) {
    return http.post<ApiEnvelope<RecoveryRequestAction>>(`/recovery/${requestId}/cancel`)
  },
  execute(
    requestId: string,
    payload: { wrapped_file_key: string; recovery_key_id: string; target_key_id: string },
  ) {
    return http.post<ApiEnvelope<RecoveryRequestAction>>(`/recovery/${requestId}/execute`, payload)
  },
  getExecutionPackage(requestId: string) {
    return http.get<ApiEnvelope<RecoveryExecutionPackage>>(
      `/recovery/${requestId}/execution-package`,
    )
  },
  listRequests(params?: { page?: number; page_size?: number }) {
    return http.get<ApiEnvelope<RecoveryRequestList>>('/recovery/requests', { params })
  },
}
