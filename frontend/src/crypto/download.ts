/**
 * Encrypted download: turn what `POST /files/{id}/download` returns back into the file.
 *
 * The mirror of `upload.ts`. The server hands over ciphertext and an envelope describing
 * it; everything that makes those bytes readable happens here, in the page, under a key
 * the server has never held.
 *
 * Until this existed a file could be uploaded and never retrieved: the download button
 * fetched the ciphertext and discarded it, so the plaintext was gone the moment the
 * uploading tab closed.
 */

import { fileApi } from '@/api/file_api'
import { keyApi } from '@/api/key_api'
import type { FileOut } from '@/api/types'
import { saveFile } from '@/utils/file-download'
import {
  type SealedAccountKey,
  unlockAccountPrivateKey,
} from '@/utils/account-crypto'

import { fromBase64 } from './encoding'
import { decryptFile, unwrapDek } from './file_envelope'
import {
  AuthenticationFailure,
  importRsaOaepPrivateKey,
  importRsaOaepPublicKey,
  privateKeyPemToDer,
  randomBytes,
  rsaOaepUnwrap,
  rsaOaepWrap,
} from './primitives'

/**
 * Account keys opened for the operation in progress, keyed by the id they were opened for.
 *
 * A key is opened for one decrypted download or one share and forgotten as soon as that
 * operation finishes, whether it worked or not (see `downloadAndDecrypt` and
 * `shareFileWithRecipient`). So someone who signs in with a stolen password still needs the
 * passphrase for every file they try to open or share, even in a tab where the owner typed it
 * a minute ago. Keys are non-extractable and live only in this module's closure: nothing is
 * written to storage, and a reload discards them.
 *
 * Keyed by id rather than held as a single key because a file stays wrapped to whichever
 * key was active when it was uploaded. After a rotation an account can legitimately need
 * an older key to read an older file, and `GET /keys/me/{key_id}` still serves it.
 */
const unlockedKeys = new Map<string, CryptoKey>()

/**
 * How long an unlocked key survives without any sign of the person.
 *
 * Keys are now forgotten after every download or share, so this is only a backstop for a key
 * that was opened and then never used (for example a passphrase dialog that succeeded while
 * the request behind it hung). Without it such a key would stay open for as long as the tab
 * does. The clock used to be reset only by decrypting,
 * which relocked the key under someone who was plainly still at the keyboard -- reading a
 * file list, filing folders, writing a share -- and sent them back to the passphrase dialog
 * mid-task. It is now reset by any activity in the page (see `ACTIVITY_EVENTS`) as well as
 * by use, so only a tab nobody has touched for fifteen minutes relocks.
 */
export const UNLOCK_IDLE_TIMEOUT_MS = 15 * 60 * 1000

/**
 * Page events that count as the person still being there. Mouse movement is deliberately
 * not one of them: a cat on the desk is not activity, and a listener per pixel is wasteful.
 * `visibilitychange` is handled separately, because only the change *to* visible counts.
 */
const ACTIVITY_EVENTS = ['click', 'keydown', 'pointerdown'] as const

/**
 * A burst of typing must not restart the timer on every keystroke. One restart per half
 * minute is indistinguishable from continuous renewal at the fifteen-minute scale.
 */
export const ACTIVITY_THROTTLE_MS = 30 * 1000

let idleTimer: ReturnType<typeof setTimeout> | undefined
const relockListeners = new Set<() => void>()
/** When the idle clock last restarted, so activity within the throttle window is ignored. */
let lastRestartAt = 0
let listeningForActivity = false

/** Notified when the keys relock on their own, so a view can stop claiming to be unlocked. */
export function onRelock(listener: () => void): () => void {
  relockListeners.add(listener)
  return () => relockListeners.delete(listener)
}

function clearIdleTimer(): void {
  if (idleTimer !== undefined) {
    clearTimeout(idleTimer)
    idleTimer = undefined
  }
}

function restartIdleTimer(): void {
  clearIdleTimer()
  lastRestartAt = Date.now()
  idleTimer = setTimeout(() => {
    if (unlockedKeys.size === 0) return
    unlockedKeys.clear()
    stopListeningForActivity()
    for (const listener of relockListeners) listener()
  }, UNLOCK_IDLE_TIMEOUT_MS)
}

/** Activity renews the key only while there is a key to renew, and at most once per window. */
function onActivity(): void {
  if (unlockedKeys.size === 0) return
  if (Date.now() - lastRestartAt < ACTIVITY_THROTTLE_MS) return
  restartIdleTimer()
}

/** Coming back to the tab is activity; leaving it is not. */
function onVisibilityChange(): void {
  if (document.visibilityState === 'visible') onActivity()
}

/**
 * Listeners exist only while a key is open, so a locked session costs nothing per click and
 * cannot restart a timer that is not running. Guarded for the unit tests, which run in Node.
 */
function startListeningForActivity(): void {
  if (listeningForActivity || typeof window === 'undefined' || typeof document === 'undefined') return
  for (const event of ACTIVITY_EVENTS) window.addEventListener(event, onActivity, { passive: true })
  document.addEventListener('visibilitychange', onVisibilityChange)
  listeningForActivity = true
}

function stopListeningForActivity(): void {
  if (!listeningForActivity) return
  for (const event of ACTIVITY_EVENTS) window.removeEventListener(event, onActivity)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  listeningForActivity = false
}

/** Called whenever a key has just been opened: arm the clock and start watching for the person. */
function keyOpened(): void {
  restartIdleTimer()
  startListeningForActivity()
}

export function forgetUnlockedKeys(): void {
  clearIdleTimer()
  stopListeningForActivity()
  unlockedKeys.clear()
}

export function isUnlocked(): boolean {
  return unlockedKeys.size > 0
}

/**
 * The opened key for `keyId`, if this session holds it.
 *
 * Exported for the sharing rewrap, which needs the same key the download path uses and must
 * not keep its own copy. Handing the key out counts as use, so the idle clock is reset here.
 */
export function unlockedKeyFor(keyId: string): CryptoKey | undefined {
  const key = unlockedKeys.get(keyId)
  if (key !== undefined) restartIdleTimer()
  return key
}

async function openBundle(
  bundle: { key: { key_id: string }; protection: unknown; private_key_bundle: unknown },
  passphrase: string,
): Promise<string> {
  const sealed = {
    key_id: bundle.key.key_id,
    protection: bundle.protection,
    private_key_bundle: bundle.private_key_bundle,
  } as SealedAccountKey
  unlockedKeys.set(sealed.key_id, await unlockAccountPrivateKey(sealed, passphrase))
  keyOpened()
  return sealed.key_id
}

/** Open the account's active key. Throws `PassphraseRejectedError` if the passphrase is wrong. */
export async function unlockWithPassphrase(passphrase: string): Promise<void> {
  const response = await keyApi.myBundle()
  await openBundle(response.data.data, passphrase)
}

/** Open a superseded key, for a file uploaded before the account rotated. */
export async function unlockOwnedKey(keyId: string, passphrase: string): Promise<void> {
  const response = await keyApi.ownedBundle(keyId)
  await openBundle(response.data.data, passphrase)
}

/** The supplied private key file is well-formed but belongs to a different account key. */
export class PrivateKeyMismatchError extends Error {
  constructor() {
    super('This private key file does not match your account key')
    this.name = 'PrivateKeyMismatchError'
  }
}

/**
 * Prove the imported private key is the partner of the account's public key.
 *
 * `importKey` accepts any well-formed PKCS#8 RSA key, so without this the wrong file --
 * a key from a different account, or from a different platform entirely -- would import
 * cleanly and then fail much later as an unwrap error on a file, which reads like the file
 * is damaged rather than like the wrong key was supplied.
 *
 * A random probe is wrapped to the public key and unwrapped with the candidate private key.
 * The probe is discarded; only whether it survives the round trip matters.
 */
export async function assertKeyPairMatches(privateKey: CryptoKey, publicKeyPem: string): Promise<void> {
  const probe = randomBytes(32)
  let recovered: Uint8Array
  try {
    const publicKey = await importRsaOaepPublicKey(publicKeyPem)
    recovered = await rsaOaepUnwrap(privateKey, await rsaOaepWrap(publicKey, probe))
  } catch {
    throw new PrivateKeyMismatchError()
  }
  if (recovered.length !== probe.length || recovered.some((byte, i) => byte !== probe[i])) {
    throw new PrivateKeyMismatchError()
  }
}

/**
 * Open an account key with the private key file saved at registration, not the passphrase.
 *
 * The registration page exports the plaintext PKCS#8 key once and tells the user to keep it
 * safe, and until now nothing could read it back: every unlock path derived the key from the
 * passphrase, so a forgotten passphrase meant every uploaded file was unreadable even though
 * the user was holding the key that opens them. `docs/SECURITY_FLOWS.md` is explicit that the
 * offline recovery workflow "cannot recover a forgotten encryption passphrase" -- this file is
 * the only escape hatch that exists, and it needed a door.
 *
 * The passphrase is not involved and nothing is re-enrolled: this unlocks the current session
 * only, exactly as `unlockWithPassphrase` does.
 */
export async function unlockWithPrivateKeyPem(pem: string, keyId?: string): Promise<string> {
  const response = keyId ? await keyApi.ownedBundle(keyId) : await keyApi.myBundle()
  const key = response.data.data.key

  const privateKey = await importRsaOaepPrivateKey(privateKeyPemToDer(pem))
  await assertKeyPairMatches(privateKey, key.public_key_pem)

  unlockedKeys.set(key.key_id, privateKey)
  keyOpened()
  return key.key_id
}

/**
 * The file is wrapped to a key this session has not opened.
 *
 * Carries the id so the caller can offer to unlock that key rather than reporting a dead
 * end -- the situation is ordinary after a key rotation, not an error in the file.
 */
export class KeyNotUnlockedError extends Error {
  readonly keyId: string

  constructor(keyId: string) {
    super(`This file is wrapped to account key ${keyId}, which is not unlocked`)
    this.name = 'KeyNotUnlockedError'
    this.keyId = keyId
  }
}

/**
 * The wrapped file key did not open with this account key.
 *
 * Distinct from a content failure: the ciphertext may be perfectly intact and simply
 * wrapped to a key this account does not hold, which is what a revoked share or a
 * mis-addressed wrapping looks like.
 */
export class FileKeyUnwrapError extends Error {
  constructor() {
    super('Your account key does not open this file\'s key')
    this.name = 'FileKeyUnwrapError'
  }
}

/**
 * The ciphertext, or the metadata bound into its AAD, failed authentication.
 *
 * The AAD covers the filename, MIME type and size, so this also fires when the server
 * serves a document under details it did not have at upload -- which is the point of
 * binding them. Either way the bytes on offer are not the bytes that were encrypted, and
 * that is an integrity finding rather than a network or authorization problem.
 */
export class FileIntegrityError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'FileIntegrityError'
  }
}

export class NotUnlockedError extends Error {
  constructor() {
    super('The account key is locked; a passphrase is required first')
    this.name = 'NotUnlockedError'
  }
}

export interface DecryptedFile {
  filename: string
  mimeType: string
  bytes: Uint8Array
}

/**
 * Download one file and decrypt it.
 *
 * The envelope is fetched separately from the ciphertext because the two answer different
 * questions: `GET /files/{id}` carries the caller's own wrapped file key, the nonce and the
 * tag, while the download route streams bytes the server has already verified against the
 * digest recorded at upload.
 */
export async function downloadAndDecrypt(fileId: string): Promise<DecryptedFile> {
  if (unlockedKeys.size === 0) {
    throw new NotUnlockedError()
  }
  // One passphrase, one download: the key is dropped whether this worked or not.
  try {
    return await decryptWithOpenKey(fileId)
  } finally {
    forgetUnlockedKeys()
  }
}

async function decryptWithOpenKey(fileId: string): Promise<DecryptedFile> {
  const metadata = (await fileApi.getFile(fileId)).data.data as FileOut
  const envelope = metadata.crypto_envelope

  // The envelope carries the key id this caller's wrapping was made for. Naming a missing
  // key beats an unexplained authentication failure three steps further in.
  const privateKey = unlockedKeys.get(envelope.key_id)
  if (privateKey === undefined) {
    throw new KeyNotUnlockedError(envelope.key_id)
  }

  const response = await fileApi.download(fileId)
  const ciphertext = new Uint8Array(response.data as ArrayBuffer)

  let dek: Uint8Array
  try {
    dek = await unwrapDek(privateKey, fromBase64(envelope.wrapped_file_key))
  } catch (error) {
    if (error instanceof AuthenticationFailure) throw new FileKeyUnwrapError()
    throw error
  }

  let plaintext: Uint8Array
  try {
    plaintext = await decryptFile({
      identity: {
        fileId: metadata.file_id,
        originalFilename: metadata.original_filename,
        plaintextSize: metadata.plaintext_size,
        mimeType: metadata.mime_type ?? 'application/octet-stream',
        envelopeVersion: envelope.envelope_version,
        aadVersion: envelope.aad_version,
        encryptionAlgorithm: envelope.encryption_algorithm,
      },
      dek,
      nonce: fromBase64(envelope.nonce),
      ciphertext,
      authTag: fromBase64(envelope.auth_tag),
    })
  } catch (error) {
    if (error instanceof AuthenticationFailure) {
      throw new FileIntegrityError(
        'This file failed authentication: its ciphertext or the details it was encrypted ' +
          'under have changed since upload.',
      )
    }
    throw error
  }

  // The AAD binds plaintext_size, so a mismatch here should be unreachable. Checking costs
  // nothing and turns a corrupted save into a refusal the user can act on.
  if (plaintext.length !== metadata.plaintext_size) {
    throw new FileIntegrityError(
      `Decrypted ${plaintext.length} bytes but the envelope declares ${metadata.plaintext_size}`,
    )
  }

  return {
    filename: metadata.original_filename,
    mimeType: metadata.mime_type ?? 'application/octet-stream',
    bytes: plaintext,
  }
}

/** Hand the decrypted bytes to the browser as a download. */
export function saveDecryptedFile(file: DecryptedFile): void {
  saveFile(file)
}
