import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  PassphraseRejectedError,
  enrolAccountKey,
  unlockAccountPrivateKey,
  unlockAccountPrivateKeyDer,
  type SealedAccountKey,
} from '@/utils/account-crypto'

import { fromBase64, toBase64 } from './encoding'
import {
  ACTIVITY_THROTTLE_MS,
  FileIntegrityError,
  FileKeyUnwrapError,
  UNLOCK_IDLE_TIMEOUT_MS,
  forgetUnlockedKeys,
  isUnlocked,
  onRelock,
  unlockWithPrivateKeyPem,
} from './download'

// The relock tests open a real key through `unlockWithPrivateKeyPem`, whose only server call
// is `GET /keys/me`. It answers with whichever bundle the test has set.
let myBundle: () => unknown = () => Promise.reject(new Error('no bundle set'))
vi.mock('@/api/key_api', () => ({ keyApi: { myBundle: () => myBundle() } }))
import { buildUploadPayload, decryptFile, encryptFile, unwrapDek } from './file_envelope'
import { AuthenticationFailure } from './primitives'

const PASSPHRASE = 'a separate encryption passphrase'
const RECOVERY_KEY_ID = '00000000-0000-4000-8000-000000000001'

/** Argon2id at 64 MiB is deliberately slow, so the suite shares one enrolment. */
let enrolment: Awaited<ReturnType<typeof enrolAccountKey>>

async function sharedEnrolment() {
  enrolment ??= await enrolAccountKey(PASSPHRASE)
  return enrolment
}

function sealed(material: Awaited<ReturnType<typeof enrolAccountKey>>['keyMaterial']) {
  return {
    key_id: material.key_id,
    protection: material.protection,
    private_key_bundle: material.private_key_bundle,
  } satisfies SealedAccountKey
}

describe('unlocking the account key', () => {
  it('recovers exactly the private key that was sealed', async () => {
    const { keyMaterial, privateKeyPem } = await sharedEnrolment()

    const der = await unlockAccountPrivateKeyDer(sealed(keyMaterial), PASSPHRASE)

    // `publicKeyPemToDer` refuses a private key by design, so unarmour it here.
    const expected = privateKeyPem
      .replace(/-----(BEGIN|END) PRIVATE KEY-----/g, '')
      .replace(/\s+/g, '')
    expect(toBase64(der)).toBe(expected)
  })

  it('rejects a wrong passphrase at the first envelope', async () => {
    const { keyMaterial } = await sharedEnrolment()

    await expect(
      unlockAccountPrivateKeyDer(sealed(keyMaterial), 'not the passphrase'),
    ).rejects.toBeInstanceOf(PassphraseRejectedError)
  })

  it('uses the KDF cost the profile records, not the current default', async () => {
    // The cost is on the wire precisely so it can be raised later without locking out
    // accounts enrolled under the old one. Deriving with today's constants against
    // yesterday's profile silently produces a different key and reads as a wrong
    // passphrase -- the least debuggable failure available.
    const { keyMaterial } = await sharedEnrolment()
    const wrongCost = {
      ...sealed(keyMaterial),
      protection: { ...keyMaterial.protection, kdf_iterations: keyMaterial.protection.kdf_iterations + 1 },
    }

    await expect(unlockAccountPrivateKeyDer(wrongCost, PASSPHRASE)).rejects.toBeInstanceOf(
      PassphraseRejectedError,
    )
  })

  it('returns a key that can decrypt but cannot be read back out', async () => {
    const { keyMaterial } = await sharedEnrolment()

    const key = await unlockAccountPrivateKey(sealed(keyMaterial), PASSPHRASE)

    expect(key.usages).toEqual(['decrypt'])
    expect(key.extractable).toBe(false)
  })
})

describe('the upload and download halves compose', () => {
  it('round trips a file through wrap, unwrap, and decrypt', async () => {
    // The property the whole product rests on: bytes that went in come back out, using
    // only what the server stores plus the passphrase. Nothing here needs the server.
    const { keyMaterial } = await sharedEnrolment()
    const plaintext = new TextEncoder().encode('chapter one, and everything after it')

    const envelope = await encryptFile({
      plaintext,
      originalFilename: 'dissertation.pdf',
      mimeType: 'application/pdf',
    })
    const payload = await buildUploadPayload({
      envelope,
      ownerKeyId: keyMaterial.key_id,
      ownerPublicKeyPem: keyMaterial.public_key_pem,
      recoveryKeyId: RECOVERY_KEY_ID,
      recoveryPublicKeyPem: keyMaterial.public_key_pem,
    })

    const privateKey = await unlockAccountPrivateKey(sealed(keyMaterial), PASSPHRASE)
    const dek = await unwrapDek(privateKey, fromBase64(payload.metadata.wrapped_file_key))
    const recovered = await decryptFile({
      identity: {
        fileId: payload.metadata.file_id,
        originalFilename: payload.metadata.original_filename,
        plaintextSize: payload.metadata.plaintext_size,
        mimeType: payload.metadata.mime_type,
        envelopeVersion: payload.metadata.envelope_version,
        aadVersion: payload.metadata.aad_version,
        encryptionAlgorithm: payload.metadata.encryption_algorithm,
      },
      dek,
      nonce: fromBase64(payload.metadata.nonce),
      ciphertext: payload.ciphertext,
      authTag: fromBase64(payload.metadata.auth_tag),
    })

    expect(new TextDecoder().decode(recovered)).toBe('chapter one, and everything after it')
  })

  it('refuses a file whose declared filename was changed after upload', async () => {
    // The AAD binds the cleartext columns the server could otherwise rewrite. A server
    // that serves a document under a different name must produce a decryption failure,
    // not a document with a misleading name.
    const { keyMaterial } = await sharedEnrolment()
    const envelope = await encryptFile({
      plaintext: new TextEncoder().encode('payload'),
      originalFilename: 'salary-review.pdf',
      mimeType: 'application/pdf',
    })
    const payload = await buildUploadPayload({
      envelope,
      ownerKeyId: keyMaterial.key_id,
      ownerPublicKeyPem: keyMaterial.public_key_pem,
      recoveryKeyId: RECOVERY_KEY_ID,
      recoveryPublicKeyPem: keyMaterial.public_key_pem,
    })

    const privateKey = await unlockAccountPrivateKey(sealed(keyMaterial), PASSPHRASE)
    const dek = await unwrapDek(privateKey, fromBase64(payload.metadata.wrapped_file_key))

    await expect(
      decryptFile({
        identity: {
          fileId: payload.metadata.file_id,
          originalFilename: 'holiday-photo.jpg',
          plaintextSize: payload.metadata.plaintext_size,
          mimeType: payload.metadata.mime_type,
        },
        dek,
        nonce: fromBase64(payload.metadata.nonce),
        ciphertext: payload.ciphertext,
        authTag: fromBase64(payload.metadata.auth_tag),
      }),
    ).rejects.toBeInstanceOf(AuthenticationFailure)
  })

  it('refuses ciphertext that was altered in storage', async () => {
    const { keyMaterial } = await sharedEnrolment()
    const envelope = await encryptFile({
      plaintext: new TextEncoder().encode('payload that must not be silently mangled'),
      originalFilename: 'notes.txt',
      mimeType: 'text/plain',
    })
    const payload = await buildUploadPayload({
      envelope,
      ownerKeyId: keyMaterial.key_id,
      ownerPublicKeyPem: keyMaterial.public_key_pem,
      recoveryKeyId: RECOVERY_KEY_ID,
      recoveryPublicKeyPem: keyMaterial.public_key_pem,
    })

    const tampered = Uint8Array.from(payload.ciphertext)
    tampered[0] ^= 0xff

    const privateKey = await unlockAccountPrivateKey(sealed(keyMaterial), PASSPHRASE)
    const dek = await unwrapDek(privateKey, fromBase64(payload.metadata.wrapped_file_key))

    await expect(
      decryptFile({
        identity: {
          fileId: payload.metadata.file_id,
          originalFilename: payload.metadata.original_filename,
          plaintextSize: payload.metadata.plaintext_size,
          mimeType: payload.metadata.mime_type,
        },
        dek,
        nonce: fromBase64(payload.metadata.nonce),
        ciphertext: tampered,
        authTag: fromBase64(payload.metadata.auth_tag),
      }),
    ).rejects.toBeInstanceOf(AuthenticationFailure)
  })

  it('cannot unwrap a file key with the wrong account key', async () => {
    const { keyMaterial } = await sharedEnrolment()
    const stranger = await enrolAccountKey('a different account passphrase')

    const envelope = await encryptFile({
      plaintext: new TextEncoder().encode('private'),
      originalFilename: 'private.txt',
      mimeType: 'text/plain',
    })
    const payload = await buildUploadPayload({
      envelope,
      ownerKeyId: keyMaterial.key_id,
      ownerPublicKeyPem: keyMaterial.public_key_pem,
      recoveryKeyId: RECOVERY_KEY_ID,
      recoveryPublicKeyPem: keyMaterial.public_key_pem,
    })

    const strangerKey = await unlockAccountPrivateKey(
      sealed(stranger.keyMaterial),
      'a different account passphrase',
    )

    await expect(
      unwrapDek(strangerKey, fromBase64(payload.metadata.wrapped_file_key)),
    ).rejects.toBeInstanceOf(AuthenticationFailure)
  })
})


describe('the two authentication failures are told apart', () => {
  it('names a key that cannot open the wrapping separately from a content failure', () => {
    // They mean different things and need different answers: one is "this file is not
    // yours to open", the other is "these bytes are not the bytes that were encrypted".
    // Collapsing both into one message is what made a tamper finding look like a network
    // hiccup.
    expect(new FileKeyUnwrapError()).toBeInstanceOf(Error)
    expect(new FileIntegrityError('x')).toBeInstanceOf(Error)
    expect(new FileKeyUnwrapError()).not.toBeInstanceOf(FileIntegrityError)
    expect(new FileIntegrityError('x')).not.toBeInstanceOf(FileKeyUnwrapError)
  })
})

describe('the unlocked key relocks itself', () => {
  it('starts locked and clears on demand', () => {
    forgetUnlockedKeys()
    expect(isUnlocked()).toBe(false)
  })

  it('keeps the idle timeout short enough to matter on a shared machine', () => {
    // A key that stays open for as long as the tab does is open indefinitely on an
    // unattended machine. The exact figure is a judgement call; that it is bounded, and
    // bounded in minutes rather than hours, is not.
    expect(UNLOCK_IDLE_TIMEOUT_MS).toBeGreaterThan(60_000)
    expect(UNLOCK_IDLE_TIMEOUT_MS).toBeLessThanOrEqual(30 * 60_000)
  })
})

describe('activity in the page keeps the key open', () => {
  const MINUTE = 60_000

  /**
   * Node has no `window` or `document`. A pair of EventTargets stands in, with the
   * listener counts tracked so the tests can see the listeners come and go.
   */
  function fakePage() {
    const win = new EventTarget()
    const doc = new EventTarget() as EventTarget & { visibilityState: DocumentVisibilityState }
    doc.visibilityState = 'visible'
    let listeners = 0
    const counted = (target: EventTarget) => ({
      addEventListener: (type: string, fn: EventListener, options?: AddEventListenerOptions) => {
        listeners += 1
        target.addEventListener(type, fn, options)
      },
      removeEventListener: (type: string, fn: EventListener) => {
        listeners -= 1
        target.removeEventListener(type, fn)
      },
      dispatchEvent: (event: Event) => target.dispatchEvent(event),
    })
    vi.stubGlobal('window', counted(win))
    // `document.visibilityState` is read-only in the DOM typings; the stub reads it from `doc`.
    vi.stubGlobal('document', Object.assign(counted(doc), {
      get visibilityState() {
        return doc.visibilityState
      },
    }))
    const setVisibility = (state: DocumentVisibilityState) => {
      doc.visibilityState = state
      document.dispatchEvent(new Event('visibilitychange'))
    }
    return {
      click: () => window.dispatchEvent(new Event('click')),
      hide: () => setVisibility('hidden'),
      show: () => setVisibility('visible'),
      listeners: () => listeners,
    }
  }

  /** Open the shared account key with its private key file, as Settings' recovery path does. */
  async function unlock() {
    const { keyMaterial, privateKeyPem } = await sharedEnrolment()
    myBundle = () =>
      Promise.resolve({ data: { data: { key: { key_id: keyMaterial.key_id, public_key_pem: keyMaterial.public_key_pem } } } })
    await unlockWithPrivateKeyPem(privateKeyPem)
  }

  afterEach(() => {
    forgetUnlockedKeys()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('relocks after the idle timeout when nobody touches the page', async () => {
    // Enrolment and the RSA probe use real WebCrypto, so they run before the clock is faked.
    await sharedEnrolment()
    const page = fakePage()
    vi.useFakeTimers()
    const relocked = vi.fn()
    const stop = onRelock(relocked)

    await unlock()
    expect(isUnlocked()).toBe(true)
    expect(page.listeners()).toBeGreaterThan(0)

    vi.advanceTimersByTime(UNLOCK_IDLE_TIMEOUT_MS - 1)
    expect(isUnlocked()).toBe(true)
    vi.advanceTimersByTime(1)

    expect(isUnlocked()).toBe(false)
    expect(relocked).toHaveBeenCalledTimes(1)
    // Nothing is left listening on a locked session, so a later click cannot wake a dead timer.
    expect(page.listeners()).toBe(0)
    stop()
  })

  it('postpones the relock when the person clicks or types', async () => {
    await sharedEnrolment()
    const page = fakePage()
    vi.useFakeTimers()

    await unlock()
    vi.advanceTimersByTime(10 * MINUTE)
    page.click()
    // Twenty minutes after unlocking, five past the old deadline, the key is still open.
    vi.advanceTimersByTime(10 * MINUTE)
    expect(isUnlocked()).toBe(true)

    // ...and it relocks fifteen minutes after that last click, not a moment later.
    vi.advanceTimersByTime(5 * MINUTE - 1)
    expect(isUnlocked()).toBe(true)
    vi.advanceTimersByTime(1)
    expect(isUnlocked()).toBe(false)
  })

  it('counts returning to the tab as activity, but not leaving it', async () => {
    await sharedEnrolment()
    const page = fakePage()
    vi.useFakeTimers()

    await unlock()
    vi.advanceTimersByTime(10 * MINUTE)
    page.hide()
    // Hiding the tab restarted nothing: the deadline is still fifteen minutes from the unlock.
    vi.advanceTimersByTime(4 * MINUTE)
    page.show()
    vi.advanceTimersByTime(2 * MINUTE)
    expect(isUnlocked()).toBe(true)
    vi.advanceTimersByTime(13 * MINUTE)
    expect(isUnlocked()).toBe(false)
  })

  it('restarts the clock at most once per throttle window', async () => {
    await sharedEnrolment()
    const page = fakePage()
    vi.useFakeTimers()

    await unlock()
    vi.advanceTimersByTime(14 * MINUTE)
    page.click()
    // A second click inside the window is ignored, so the deadline stays at the first click.
    vi.advanceTimersByTime(ACTIVITY_THROTTLE_MS - 1)
    page.click()
    vi.advanceTimersByTime(UNLOCK_IDLE_TIMEOUT_MS - ACTIVITY_THROTTLE_MS + 1)
    expect(isUnlocked()).toBe(false)
  })

  it('ignores activity while locked, and stops listening once relocked by hand', async () => {
    await sharedEnrolment()
    const page = fakePage()
    vi.useFakeTimers()

    await unlock()
    forgetUnlockedKeys()
    expect(page.listeners()).toBe(0)
    page.click()
    expect(isUnlocked()).toBe(false)
  })
})
