/**
 * Encrypted upload: turn a browser File into what `POST /files/upload` accepts.
 *
 * The plaintext never leaves this module. It is read into memory, encrypted under a fresh
 * data encryption key, and only the ciphertext and the envelope metadata are handed to the
 * API layer. The one exception is the `sample` progress event: a copy of the first bytes of
 * plaintext and ciphertext for the page to show side by side. It stays in the browser.
 */

import { fileApi } from '@/api/file_api'
import { keyApi } from '@/api/key_api'
import { recoveryApi } from '@/api/recovery_api'

import { buildUploadPayload, encryptFile, type UploadPayload } from './file_envelope'
import {
  DEFAULT_ENCRYPTION_ALGORITHM,
  type EncryptionAlgorithm,
  publicKeyFingerprint,
} from './primitives'

/**
 * Mirrors the backend `MAX_UPLOAD_SIZE_BYTES` default so oversize files fail before work.
 *
 * Shown to people as "500 MB". The exact figure is 524,288,000 bytes, so a file that is 500 MB by
 * either convention fits: 500,000,000 bytes (what macOS and most websites call 500 MB) and
 * 524,288,000 bytes (what Windows Explorer calls 500 MB) are both at or under the limit. Do not
 * lower it to a round decimal figure without noticing that a Windows "500 MB" file would then fail.
 */
export const MAX_UPLOAD_BYTES = 500 * 1024 * 1024

/**
 * From this size the browser is told, before encryption starts, that the file may not fit.
 *
 * Encryption happens entirely in memory (docs/THREAT_MODEL.md, T-D3 / F-19): the plaintext
 * is read into one buffer and the ciphertext, the self-test decryption and the request body
 * are held next to it, so the peak is roughly four times the file. At 100 MiB that is about
 * 400 MiB, which a desktop browser shrugs off and a phone tab may not.
 */
export const LARGE_FILE_WARNING_BYTES = 100 * 1024 * 1024

export type UploadSizeClass = 'ok' | 'large' | 'too-large'

/** Tell the user about a size problem at selection time, not after minutes of encryption. */
export function classifyUploadSize(sizeBytes: number): UploadSizeClass {
  if (sizeBytes > MAX_UPLOAD_BYTES) return 'too-large'
  if (sizeBytes >= LARGE_FILE_WARNING_BYTES) return 'large'
  return 'ok'
}

/**
 * The files a press of Start Encryption should send: everything not already uploaded.
 *
 * A file marked done is on the server, so sending it again would store a second copy. This is
 * why the upload page can never re-upload a batch it has just finished.
 */
export function filesStillToUpload<T extends { status: string }>(files: readonly T[]): T[] {
  return files.filter((file) => file.status !== 'done')
}

/**
 * The browser refuses to allocate a buffer this big as a bare `RangeError` ("Array buffer
 * allocation failed"), or fails the read itself. Neither tells a non-expert what to do.
 */
export function isMemoryExhaustion(error: unknown): boolean {
  if (error instanceof RangeError) return true
  return (
    typeof DOMException !== 'undefined' &&
    error instanceof DOMException &&
    (error.name === 'NotReadableError' || error.name === 'QuotaExceededError')
  )
}

/**
 * `File.type` is advisory: browsers leave it empty for unknown extensions, and the API
 * requires a well-formed media type. Fall back rather than sending something it will reject.
 */
export const DEFAULT_MIME_TYPE = 'application/octet-stream'

/** The public keys an upload wraps its file key to. No private key is involved. */
export interface UploadRecipients {
  ownerKeyId: string
  ownerPublicKeyPem: string
  recoveryKeyId: string
  recoveryPublicKeyPem: string
  /** Locally recomputed, for the caller to pin. Never taken from the API response. */
  recoveryKeyFingerprint: string
}

export function resolveMimeType(type: string | undefined): string {
  const normalized = (type ?? '').trim().toLowerCase()
  // Browsers also report placeholder values for files they cannot classify.
  if (normalized === '' || normalized === 'unknown') {
    return DEFAULT_MIME_TYPE
  }
  return normalized
}

/**
 * Finder and other file pickers can preserve invisible whitespace at either edge of a
 * filename. The API deliberately rejects that ambiguous form, so canonicalise only those
 * edges before the name is authenticated as AAD. Ordinary spaces inside the name remain.
 */
export function resolveUploadFilename(name: string): string {
  return name.normalize('NFC').trim()
}

/**
 * Fetch the owner and recovery public keys.
 *
 * The recovery fingerprint is recomputed from the PEM rather than read from the response
 * field. A server that substitutes the recovery key can substitute the field describing it
 * just as easily, and this is the one wrapping no client can ever verify.
 */
export async function fetchUploadRecipients(): Promise<UploadRecipients> {
  const [bundle, recovery] = await Promise.all([keyApi.myBundle(), recoveryApi.getPublicKey()])
  const ownerKey = bundle.data.data.key
  const recoveryKey = recovery.data.data

  if (recoveryKey.status !== 'ACTIVE') {
    throw new Error('The recovery key is not active. Ask an administrator to register one.')
  }

  return {
    ownerKeyId: ownerKey.key_id,
    ownerPublicKeyPem: ownerKey.public_key_pem,
    recoveryKeyId: recoveryKey.key_id,
    recoveryPublicKeyPem: recoveryKey.public_key_pem,
    recoveryKeyFingerprint: await publicKeyFingerprint(recoveryKey.public_key_pem),
  }
}

export type UploadStage = 'read' | 'encrypt' | 'wrap' | 'upload'

/** How many leading bytes of plaintext and ciphertext the `sample` event carries. */
export const SAMPLE_BYTES = 16

/**
 * What the upload page shows while a file is processed. `timed` carries the measured duration
 * of the work alone; any pause the listener adds is not counted in it.
 */
export type UploadEvent =
  | { type: 'stage'; stage: UploadStage }
  | { type: 'timed'; stage: UploadStage; ms: number }
  | { type: 'sample'; plaintextHead: Uint8Array; ciphertextHead: Uint8Array }
  | { type: 'upload-progress'; fraction: number }

/** A listener may return a promise to hold the pipeline, e.g. so a step stays on screen. */
export type UploadListener = (event: UploadEvent) => void | Promise<void>

/** Run one stage, reporting its start and its own duration. */
async function timedStage<T>(
  stage: UploadStage,
  onEvent: UploadListener | undefined,
  work: () => Promise<T>,
): Promise<T> {
  await onEvent?.({ type: 'stage', stage })
  const started = performance.now()
  const result = await work()
  const ms = performance.now() - started
  await onEvent?.({ type: 'timed', stage, ms })
  return result
}

/** The subset of `File` this module needs, so tests do not have to build a real one. */
export interface UploadableFile {
  name: string
  size: number
  type?: string
  arrayBuffer(): Promise<ArrayBuffer>
}

/**
 * Encrypt one file and assemble its upload payload. Performs no network calls.
 *
 * `encryptFile` self-tests its own output before this returns, so a payload produced here
 * is known to decrypt back to the exact input bytes.
 */
export async function prepareUpload(params: {
  file: UploadableFile
  recipients: UploadRecipients
  algorithm?: EncryptionAlgorithm
  onEvent?: UploadListener
}): Promise<UploadPayload> {
  const { file, recipients, onEvent } = params

  if (file.size > MAX_UPLOAD_BYTES) {
    throw new RangeError(
      `${file.name} is ${file.size} bytes; the upload limit is ${MAX_UPLOAD_BYTES} bytes`,
    )
  }

  let envelope: Awaited<ReturnType<typeof encryptFile>>
  let plaintextHead: Uint8Array
  try {
    const plaintext = await timedStage(
      'read',
      onEvent,
      async () => new Uint8Array(await file.arrayBuffer()),
    )
    // slice() copies, so the event never keeps the whole plaintext buffer alive.
    plaintextHead = plaintext.slice(0, SAMPLE_BYTES)
    envelope = await timedStage('encrypt', onEvent, () =>
      encryptFile({
        plaintext,
        originalFilename: resolveUploadFilename(file.name),
        mimeType: resolveMimeType(file.type),
        algorithm: params.algorithm ?? DEFAULT_ENCRYPTION_ALGORITHM,
      }),
    )
  } catch (error) {
    if (isMemoryExhaustion(error)) {
      throw new Error(
        `${file.name} is too large for this browser to encrypt: encryption needs about four times the file's size in memory. Close other tabs, or try a desktop browser.`,
      )
    }
    throw error
  }

  await onEvent?.({
    type: 'sample',
    plaintextHead,
    ciphertextHead: envelope.ciphertext.slice(0, SAMPLE_BYTES),
  })

  return timedStage('wrap', onEvent, () =>
    buildUploadPayload({
      envelope,
      ownerKeyId: recipients.ownerKeyId,
      ownerPublicKeyPem: recipients.ownerPublicKeyPem,
      recoveryKeyId: recipients.recoveryKeyId,
      recoveryPublicKeyPem: recipients.recoveryPublicKeyPem,
    }),
  )
}

export interface UploadResult {
  fileId: string
  originalFilename: string
  plaintextSize: number
  ciphertextSize: number
  encryptionAlgorithm: string
  recoveryKeyFingerprint: string
}

/** Encrypt and upload one file. Fetches the recipient keys if the caller has not. */
export async function encryptAndUpload(
  file: UploadableFile,
  recipients?: UploadRecipients,
  algorithm?: EncryptionAlgorithm,
  onEvent?: UploadListener,
): Promise<UploadResult> {
  const resolved = recipients ?? (await fetchUploadRecipients())
  const payload = await prepareUpload({ file, recipients: resolved, algorithm, onEvent })

  await timedStage('upload', onEvent, () =>
    fileApi.uploadEncrypted(payload, (fraction) => {
      void onEvent?.({ type: 'upload-progress', fraction })
    }),
  )

  return {
    fileId: payload.metadata.file_id,
    originalFilename: payload.metadata.original_filename,
    plaintextSize: payload.metadata.plaintext_size,
    ciphertextSize: payload.ciphertext.length,
    encryptionAlgorithm: payload.metadata.encryption_algorithm,
    recoveryKeyFingerprint: payload.recoveryKeyFingerprint,
  }
}
