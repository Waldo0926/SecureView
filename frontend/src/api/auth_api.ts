import { http } from './http'
import type { ApiEnvelope } from './types'
import type { ClientKeyMaterial } from '@/utils/account-crypto'

export type VerificationPurpose = 'REGISTRATION' | 'PASSWORD_RESET'

export interface LoginPayload {
  username: string
  password: string
}

export interface SendVerificationCodePayload {
  email: string
  purpose: VerificationPurpose
}

export interface SendVerificationCodeData {
  code_sent: boolean
  expires_in_seconds: number
  resend_available_in_seconds: number
}

export interface RegisterPayload {
  username: string
  email: string
  password: string
  verification_code: string
  key_material: ClientKeyMaterial
}

/** Mirrors the backend `AuthUserResponse`, which is what `/auth/me` and login both return. */
export interface AuthUserOut {
  id: string
  username: string
  email: string
  role: string
  status: string
  email_verified: boolean
  created_at: string
  last_login_at: string | null
  has_avatar: boolean
  /** True after an administrator reset the login password, until the holder sets their own. */
  must_change_password: boolean
}

export interface AuthMeData {
  user: AuthUserOut
}

export interface RegisterData {
  user: AuthUserOut
  key_id: string
  public_key_fingerprint: string
}

export interface ResetPasswordPayload {
  username: string
  email: string
  verification_code: string
  new_password: string
}

export interface ResetPasswordData {
  password_reset: boolean
  revoked_sessions: number
  key_envelopes_unchanged: boolean
}

/**
 * Re-exported so the existing `from './auth_api'` imports keep working.
 *
 * There used to be a second, narrower `ApiEnvelope` declared here, missing the `status`
 * and `code` the API actually sends. Because both were spelled the same, the mismatch
 * only showed up as `unwrapData` rejecting the very responses it exists to unwrap — and
 * only once type checking could run again. One declaration, in `types.ts`.
 */
export type { ApiEnvelope } from './types'

export interface DeleteAccountPayload {
  password: string
  /** The literal word, so a stray click cannot produce this request. */
  confirmation: 'DELETE'
}

export interface DeleteAccountData {
  files_deleted: number
  sessions_revoked: number
}

export const authApi = {
  sendVerificationCode(payload: SendVerificationCodePayload) {
    return http.post<ApiEnvelope<SendVerificationCodeData>>(
      '/auth/verification-codes/send',
      payload,
    )
  },
  register(payload: RegisterPayload) {
    return http.post<ApiEnvelope<RegisterData>>('/auth/register', payload)
  },
  resetPassword(payload: ResetPasswordPayload) {
    return http.post<ApiEnvelope<ResetPasswordData>>('/auth/password-reset', payload)
  },
  /** Signed in: change the login password. The server then signs out every session, this one too. */
  changePassword(payload: { current_password: string; new_password: string }) {
    return http.post<ApiEnvelope<{ revoked_sessions: number }>>('/auth/change-password', payload)
  },
  login(payload: LoginPayload) {
    return http.post('/auth/login', payload)
  },
  logout() {
    return http.post('/auth/logout')
  },
  me() {
    return http.get<ApiEnvelope<AuthMeData>>('/auth/me')
  },
  /** Close the account and destroy the files it owns. Not reversible. */
  deleteAccount(payload: DeleteAccountPayload) {
    return http.post<ApiEnvelope<DeleteAccountData>>('/auth/delete-account', payload)
  },
}
