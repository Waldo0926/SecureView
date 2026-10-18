/**
 * Sharing: hand a file to another account without the server ever seeing its key.
 *
 * The mirror of the rewrap half of `download.ts`. `docs/SECURITY_FLOWS.md` describes the
 * flow exactly: the sender unwraps the file's DEK with their own account key, wraps the
 * same DEK to the recipient's public key, and submits only that ciphertext. The server can
 * check the shape of the bytes but never learns the DEK.
 *
 * Until this existed the share dialog posted `{ target_username }` and nothing else, which
 * the strict schema rejected as a 422 -- three required fields missing and one forbidden
 * field present -- while the UI reported "Share request sent". Nothing was ever shared.
 */

import axios from 'axios'

import { fileApi } from '@/api/file_api'
import { keyApi } from '@/api/key_api'
import { shareApi } from '@/api/share_api'
import type { FileOut } from '@/api/types'

import { fromBase64, toBase64 } from './encoding'
import {
  FileKeyUnwrapError,
  KeyNotUnlockedError,
  NotUnlockedError,
  forgetUnlockedKeys,
  isUnlocked,
  unlockedKeyFor,
} from './download'
import { unwrapDek } from './file_envelope'
import {
  AuthenticationFailure,
  importRsaOaepPublicKey,
  publicKeyFingerprint,
  rsaOaepWrap,
} from './primitives'

/** No active account by that username/email, or it has no key a file could be wrapped to. */
export class RecipientNotFoundError extends Error {
  constructor(identifier: string) {
    super(`No active account matching "${identifier}" that can receive a shared file`)
    this.name = 'RecipientNotFoundError'
  }
}

/** The recipient named is the sender. The owner already holds the file. */
export class ShareWithSelfError extends Error {
  constructor() {
    super('You already have access to this file')
    this.name = 'ShareWithSelfError'
  }
}

/** The server's stated fingerprint disagrees with the key it returned. Never share to it. */
export class RecipientKeyMismatchError extends Error {
  constructor() {
    super('The server returned a key whose fingerprint does not match it, so it was not used')
    this.name = 'RecipientKeyMismatchError'
  }
}

export interface ShareOutcome {
  username: string
  /** False when the grant already existed and was updated rather than created. */
  created: boolean
}

/** A recipient's active key, looked up and fingerprinted here, for the sender to confirm. */
export interface RecipientCandidate {
  identifier: string
  userId: string
  keyId: string
  publicKeyPem: string
  /** SHA-256 of the key, computed in this browser rather than taken from the server. */
  fingerprint: string
}

/**
 * Find the account a share would go to, so the sender can confirm it before anything is sent.
 *
 * The fingerprint is recomputed from the key itself. The server's own `fingerprint` field must
 * agree; a server that returned one key and described another is not trusted with the share.
 */
export async function lookupRecipient(identifier: string): Promise<RecipientCandidate> {
  const name = identifier.trim()
  if (!name) throw new RecipientNotFoundError(identifier)
  let recipient
  try {
    recipient = (await keyApi.activePublicKeyByIdentifier(name)).data.data
  } catch (error) {
    // A 404 is the ordinary case -- a typo in a colleague's name -- and gets the "no such
    // account" message. Anything else (the server down, a 500, an expired session) used to
    // be folded into it too, which told someone to check the spelling of a name that was
    // spelled perfectly. Those keep their own message, so the dialog can say what happened.
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      throw new RecipientNotFoundError(name)
    }
    throw error
  }
  const fingerprint = await publicKeyFingerprint(recipient.public_key_pem)
  if (recipient.fingerprint && recipient.fingerprint.toLowerCase() !== fingerprint) {
    throw new RecipientKeyMismatchError()
  }
  return {
    identifier: name,
    userId: recipient.user_id,
    keyId: recipient.key_id,
    publicKeyPem: recipient.public_key_pem,
    fingerprint,
  }
}

/**
 * Rewrap a file's key to another account and record the grant.
 *
 * Given a confirmed `RecipientCandidate`, the file key is wrapped to exactly that key, with no
 * second lookup that could return a different one. Given a name, it looks the recipient up first.
 * Requires the sender's account key to be unlocked, for the same reason downloading does: the
 * DEK is reachable only through it. Like a download, a share uses the key once: it is
 * forgotten when this returns or throws, so the next share asks for the passphrase again.
 */
export async function shareFileWithRecipient(
  fileId: string,
  target: string | RecipientCandidate,
  options: { canDownload?: boolean; canShare?: boolean } = {},
): Promise<ShareOutcome> {
  try {
    if (typeof target === 'string' && !target.trim()) throw new RecipientNotFoundError(target)
    if (!isUnlocked()) throw new NotUnlockedError()
    return await rewrapAndGrant(fileId, target, options)
  } finally {
    forgetUnlockedKeys()
  }
}

async function rewrapAndGrant(
  fileId: string,
  target: string | RecipientCandidate,
  options: { canDownload?: boolean; canShare?: boolean },
): Promise<ShareOutcome> {
  const recipient = typeof target === 'string' ? await lookupRecipient(target) : target
  const name = recipient.identifier

  const metadata = (await fileApi.getFile(fileId)).data.data as FileOut
  const envelope = metadata.crypto_envelope
  // The envelope is the sender's own wrapping, so its key id is the sender's active key. The
  // sender's own username or email resolves like anyone else's, but they already hold the
  // file; refusing here keeps a pointless grant off the server and the audit log, and does it
  // without reading the signed-in user from a store, so this module stays usable from tests
  // and scripts that have no Pinia.
  if (recipient.keyId === envelope.key_id) throw new ShareWithSelfError()

  const privateKey = unlockedKeyFor(envelope.key_id)
  if (privateKey === undefined) {
    // Ordinary after a key rotation: the file is wrapped to a key this session has not
    // opened. Naming it lets the caller offer to unlock that key.
    throw new KeyNotUnlockedError(envelope.key_id)
  }

  let dek: Uint8Array
  try {
    dek = await unwrapDek(privateKey, fromBase64(envelope.wrapped_file_key))
  } catch (error) {
    if (error instanceof AuthenticationFailure) throw new FileKeyUnwrapError()
    throw error
  }

  // RSA-OAEP authenticates, and unwrapDek checks the length, so a DEK that reaches here is
  // the one that was sealed. The sender cannot verify the outgoing wrapping -- that needs
  // the recipient's private key -- which is why the server also checks its shape.
  const recipientKey = await importRsaOaepPublicKey(recipient.publicKeyPem)
  const wrappedForRecipient = await rsaOaepWrap(recipientKey, dek)

  const response = await shareApi.shareFile(fileId, {
    target_user_id: recipient.userId,
    target_key_id: recipient.keyId,
    wrapped_file_key: toBase64(wrappedForRecipient),
    can_download: options.canDownload ?? true,
    can_share: options.canShare ?? false,
  })

  return { username: name, created: response.data.data?.created ?? true }
}

/** Compatibility name for callers written before email recipient lookup was supported. */
export const shareFileWithUsername = shareFileWithRecipient
