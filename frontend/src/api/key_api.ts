import { http } from './http'
import type { ApiEnvelope } from './auth_api'

/** A public encryption key as the API returns it. Never contains private material. */
export interface PublicEncryptionKey {
  key_id: string
  user_id: string
  algorithm: string
  key_size_bits: number
  public_key_pem: string
  fingerprint: string
  created_at: string
}

export interface KeyProtectionProfile {
  profile_id: string
  format_version: number
  kdf_algorithm: string
  kdf_version: number
  kdf_salt: string
  kdf_memory_kib: number
  kdf_iterations: number
  kdf_parallelism: number
  derived_key_length: number
  amk_wrapping_algorithm: string
  wrapped_amk: string
  amk_nonce: string
  amk_auth_tag: string
  aad_version: number
  revision: number
  updated_at: string
}

export interface EncryptedPrivateKeyBundle {
  bundle_id: string
  format_version: number
  private_key_format: string
  derivation_algorithm: string
  derivation_salt: string
  encryption_algorithm: string
  encrypted_private_key: string
  nonce: string
  auth_tag: string
  aad_version: number
  ciphertext_sha256: string
  revision: number
  updated_at: string
}

export interface MyKeyBundle {
  key: PublicEncryptionKey
  protection: KeyProtectionProfile
  private_key_bundle: EncryptedPrivateKeyBundle
}

/** The two envelopes a passphrase reset replaces, exactly as `sealAccountKey` builds them. */
export interface ResetKeyProtectionBody {
  authorizing_key_id: string
  expected_profile_revision: number
  expected_bundle_revision: number
  protection: {
    profile_id: string
    kdf_salt: string
    kdf_memory_kib: number
    kdf_iterations: number
    kdf_parallelism: number
    wrapped_amk: string
    amk_nonce: string
    amk_auth_tag: string
  }
  private_key_bundle: {
    bundle_id: string
    derivation_salt: string
    encrypted_private_key: string
    nonce: string
    auth_tag: string
    ciphertext_sha256: string
  }
}

export interface ResetKeyProtectionResult {
  profile_id: string
  profile_revision: number
  bundle_id: string
  bundle_revision: number
  updated_at: string
}

export const keyApi = {
  /** The caller's active public key plus the encrypted envelopes only they can open. */
  myBundle() {
    return http.get<ApiEnvelope<MyKeyBundle>>('/keys/me')
  },
  /** A historical bundle, needed to decrypt files still wrapped to a superseded key. */
  ownedBundle(keyId: string) {
    return http.get<ApiEnvelope<MyKeyBundle>>(`/keys/me/${keyId}`)
  },
  /** The digest the account private key must sign to authorize a passphrase reset. */
  resetProtectionSigningPayload(body: ResetKeyProtectionBody) {
    return http.post<ApiEnvelope<{ authorization_algorithm: string; authorization_payload: string }>>(
      '/keys/me/reset-protection/signing-payload',
      body,
    )
  },
  /** Replace both envelopes. The signature proves possession of the private key. */
  resetProtection(body: ResetKeyProtectionBody & { authorization_signature: string }) {
    return http.post<ApiEnvelope<ResetKeyProtectionResult>>('/keys/me/reset-protection', body)
  },
  /** Another user's active public key, for wrapping a shared file key to them. */
  activePublicKey(userId: string) {
    return http.get<ApiEnvelope<PublicEncryptionKey>>(`/keys/users/${userId}/active`)
  },
  /**
   * A recipient's active public key, addressed by the name the sender knows them by.
   *
   * The share contract speaks in `target_user_id`, which no sender has to hand. Exact
   * match: this resolves someone already known, and is not a directory to search.
   */
  activePublicKeyByIdentifier(identifier: string) {
    return http.get<ApiEnvelope<PublicEncryptionKey>>(
      `/keys/users/by-identifier/${encodeURIComponent(identifier)}/active`,
    )
  },
}
