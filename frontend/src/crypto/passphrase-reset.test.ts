import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  PassphraseRejectedError,
  enrolAccountKey,
  unlockAccountPrivateKeyDer,
} from '@/utils/account-crypto'

import { bytesEqual, fromBase64, toBase64 } from './encoding'
import { PrivateKeyMismatchError } from './download'
import { privateKeyPemToDer, publicKeyPemToDer, randomBytes } from './primitives'

/**
 * A stand-in for the key endpoints that behaves like the backend where it matters: it hands
 * out a challenge, refuses a body that changed after the challenge was issued, and accepts
 * the reset only if the RSA-PSS signature verifies against the stored public key.
 */
const server = vi.hoisted(() => ({
  state: undefined as any,
  pending: undefined as { body: string; challenge: Uint8Array } | undefined,
  writes: 0,
  corruptStoredEnvelope: false,
}))

vi.mock('@/api/key_api', () => ({
  keyApi: {
    myBundle: async () => ({ data: { data: structuredClone(server.state) } }),
    resetProtectionSigningPayload: async (body: any) => {
      if (
        body.expected_profile_revision !== server.state.protection.revision ||
        body.expected_bundle_revision !== server.state.private_key_bundle.revision
      ) {
        throw new Error('409 key_bundle_revision_conflict')
      }
      const challenge = globalThis.crypto.getRandomValues(new Uint8Array(32))
      server.pending = { body: JSON.stringify(body), challenge }
      return {
        data: {
          data: { authorization_algorithm: 'RSA-PSS-SHA256', authorization_payload: toBase64(challenge) },
        },
      }
    },
    resetProtection: async ({ authorization_signature, ...body }: any) => {
      if (!server.pending || server.pending.body !== JSON.stringify(body)) {
        throw new Error('400 body differs from the one that was signed')
      }
      const publicKey = await globalThis.crypto.subtle.importKey(
        'spki',
        publicKeyPemToDer(server.state.key.public_key_pem) as BufferSource,
        { name: 'RSA-PSS', hash: 'SHA-256' },
        false,
        ['verify'],
      )
      const valid = await globalThis.crypto.subtle.verify(
        { name: 'RSA-PSS', saltLength: 32 },
        publicKey,
        fromBase64(authorization_signature) as BufferSource,
        server.pending.challenge as BufferSource,
      )
      if (!valid) throw new Error('400 invalid_key_bundle')

      server.writes += 1
      const protection = { ...server.state.protection, ...body.protection }
      if (server.corruptStoredEnvelope) protection.wrapped_amk = toBase64(randomBytes(32))
      server.state = {
        key: server.state.key,
        protection: { ...protection, revision: server.state.protection.revision + 1 },
        private_key_bundle: {
          ...server.state.private_key_bundle,
          ...body.private_key_bundle,
          revision: server.state.private_key_bundle.revision + 1,
        },
      }
      return {
        data: {
          data: {
            profile_id: server.state.protection.profile_id,
            profile_revision: server.state.protection.revision,
            bundle_id: server.state.private_key_bundle.bundle_id,
            bundle_revision: server.state.private_key_bundle.revision,
            updated_at: '2026-09-23T00:00:00Z',
          },
        },
      }
    },
  },
}))

const {
  PassphraseTooShortError,
  ResetVerificationError,
  SamePassphraseError,
  changePassphrase,
  resetPassphraseWithPrivateKeyPem,
} = await import('./passphrase-reset')

const OLD_PASSPHRASE = 'the passphrase that was forgotten'
const NEW_PASSPHRASE = 'a brand new encryption passphrase'

/** Argon2id at 64 MiB is deliberately slow, so the suite shares one enrolment. */
let enrolment: Awaited<ReturnType<typeof enrolAccountKey>>

beforeEach(async () => {
  enrolment ??= await enrolAccountKey(OLD_PASSPHRASE)
  const { keyMaterial } = enrolment
  server.state = {
    key: { key_id: keyMaterial.key_id, public_key_pem: keyMaterial.public_key_pem },
    protection: { ...keyMaterial.protection, revision: 3 },
    private_key_bundle: { ...keyMaterial.private_key_bundle, revision: 1 },
  }
  server.pending = undefined
  server.writes = 0
  server.corruptStoredEnvelope = false
})

function storedEnvelopes() {
  return {
    key_id: server.state.key.key_id,
    protection: server.state.protection,
    private_key_bundle: server.state.private_key_bundle,
  }
}

describe('resetting the passphrase with the private key file', () => {
  it('makes the new passphrase open the same private key, and the old one stop', async () => {
    const before = structuredClone(server.state)

    const outcome = await resetPassphraseWithPrivateKeyPem(enrolment.privateKeyPem, NEW_PASSPHRASE)

    const reopened = await unlockAccountPrivateKeyDer(storedEnvelopes(), NEW_PASSPHRASE)
    expect(bytesEqual(reopened, privateKeyPemToDer(enrolment.privateKeyPem))).toBe(true)
    await expect(
      unlockAccountPrivateKeyDer(storedEnvelopes(), OLD_PASSPHRASE),
    ).rejects.toBeInstanceOf(PassphraseRejectedError)

    // The key pair is not touched, which is why no file needs re-encrypting.
    expect(server.state.key).toEqual(before.key)
    expect(outcome.keyId).toBe(before.key.key_id)
    expect(outcome.profileRevision).toBe(4)
    expect(outcome.bundleRevision).toBe(2)
    // A fresh AMK, so every envelope byte changes -- not only the KDF salt.
    expect(server.state.protection.wrapped_amk).not.toBe(before.protection.wrapped_amk)
    expect(server.state.private_key_bundle.encrypted_private_key).not.toBe(
      before.private_key_bundle.encrypted_private_key,
    )
    expect(server.state.protection.profile_id).toBe(before.protection.profile_id)
    expect(server.state.private_key_bundle.bundle_id).toBe(before.private_key_bundle.bundle_id)
  }, 60_000)

  it('refuses a key file from another account before sending anything', async () => {
    const stranger = await enrolAccountKey('an unrelated account passphrase')

    await expect(
      resetPassphraseWithPrivateKeyPem(stranger.privateKeyPem, NEW_PASSPHRASE),
    ).rejects.toBeInstanceOf(PrivateKeyMismatchError)
    expect(server.pending).toBeUndefined()
    expect(server.writes).toBe(0)
  }, 60_000)

  it('refuses a short passphrase before reading the key file', async () => {
    await expect(
      resetPassphraseWithPrivateKeyPem(enrolment.privateKeyPem, 'too short'),
    ).rejects.toBeInstanceOf(PassphraseTooShortError)
    expect(server.writes).toBe(0)
  })

  it('reports it when the stored envelopes do not open afterwards', async () => {
    // What the next unlock reads is what counts, so the flow re-reads and re-opens it.
    server.corruptStoredEnvelope = true

    await expect(
      resetPassphraseWithPrivateKeyPem(enrolment.privateKeyPem, NEW_PASSPHRASE),
    ).rejects.toBeInstanceOf(ResetVerificationError)
  }, 60_000)

  it('signs with the account key, which is what the server verifies', async () => {
    // The fake server above accepts only a PSS signature that verifies against the stored
    // public key, so completing at all proves an OAEP-generated key signs for PSS.
    await resetPassphraseWithPrivateKeyPem(enrolment.privateKeyPem, NEW_PASSPHRASE)
    expect(server.writes).toBe(1)
  }, 60_000)
})

describe('changing the passphrase with the current one', () => {
  it('makes the new passphrase open the same private key, and the current one stop', async () => {
    const before = structuredClone(server.state)

    const outcome = await changePassphrase(OLD_PASSPHRASE, NEW_PASSPHRASE)

    const reopened = await unlockAccountPrivateKeyDer(storedEnvelopes(), NEW_PASSPHRASE)
    expect(bytesEqual(reopened, privateKeyPemToDer(enrolment.privateKeyPem))).toBe(true)
    await expect(
      unlockAccountPrivateKeyDer(storedEnvelopes(), OLD_PASSPHRASE),
    ).rejects.toBeInstanceOf(PassphraseRejectedError)
    expect(server.state.key).toEqual(before.key)
    expect(outcome.profileRevision).toBe(4)
    expect(server.writes).toBe(1)
  }, 60_000)

  it('refuses a wrong current passphrase before sending anything', async () => {
    await expect(
      changePassphrase('not the current passphrase at all', NEW_PASSPHRASE),
    ).rejects.toBeInstanceOf(PassphraseRejectedError)
    expect(server.pending).toBeUndefined()
    expect(server.writes).toBe(0)
  }, 60_000)

  it('refuses a new passphrase equal to the current one', async () => {
    await expect(changePassphrase(OLD_PASSPHRASE, OLD_PASSPHRASE)).rejects.toBeInstanceOf(
      SamePassphraseError,
    )
    expect(server.writes).toBe(0)
  })

  it('refuses a short new passphrase before deriving anything', async () => {
    await expect(changePassphrase(OLD_PASSPHRASE, 'too short')).rejects.toBeInstanceOf(
      PassphraseTooShortError,
    )
    expect(server.writes).toBe(0)
  })
})
