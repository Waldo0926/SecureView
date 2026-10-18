import { describe, expect, it } from 'vitest'

import { enrolAccountKey, unlockAccountPrivateKey, type SealedAccountKey } from '@/utils/account-crypto'

import { fromBase64 } from './encoding'
import { buildUploadPayload, decryptFile, encryptFile, unwrapDek } from './file_envelope'
import { importRsaOaepPublicKey, rsaOaepWrap } from './primitives'

/**
 * The rewrap at the heart of sharing, exercised end to end against real WebCrypto.
 *
 * `shareFileWithUsername` itself is a thin shell over these steps plus two API calls; what
 * has to be true is that the recipient can open the file with their own key and nobody
 * else's, which is what the proposal promises: "An authorized recipient can decrypt and
 * download a file shared with them, with only his/her passphrase and without the owner's
 * passphrase."
 *
 * Argon2id at 64 MiB is deliberately slow, so the two enrolments are shared.
 */
const RECOVERY_KEY_ID = '00000000-0000-4000-8000-000000000001'

let owner: Awaited<ReturnType<typeof enrolAccountKey>>
let recipient: Awaited<ReturnType<typeof enrolAccountKey>>
let stranger: Awaited<ReturnType<typeof enrolAccountKey>>

const OWNER_PASSPHRASE = 'the owner encryption passphrase'
const RECIPIENT_PASSPHRASE = 'a totally different recipient passphrase'
const STRANGER_PASSPHRASE = 'an uninvited third party passphrase'

async function parties() {
  owner ??= await enrolAccountKey(OWNER_PASSPHRASE)
  recipient ??= await enrolAccountKey(RECIPIENT_PASSPHRASE)
  stranger ??= await enrolAccountKey(STRANGER_PASSPHRASE)
  return { owner, recipient, stranger }
}

function sealed(material: Awaited<ReturnType<typeof enrolAccountKey>>['keyMaterial']) {
  return {
    key_id: material.key_id,
    protection: material.protection,
    private_key_bundle: material.private_key_bundle,
  } satisfies SealedAccountKey
}

/** Upload a file as the owner, then rewrap its DEK to the recipient, as sharing does. */
async function shareOneFile(plaintextText: string) {
  const { owner, recipient } = await parties()
  const plaintext = new TextEncoder().encode(plaintextText)

  const envelope = await encryptFile({
    plaintext,
    originalFilename: 'meeting-minutes.pdf',
    mimeType: 'application/pdf',
  })
  const payload = await buildUploadPayload({
    envelope,
    ownerKeyId: owner.keyMaterial.key_id,
    ownerPublicKeyPem: owner.keyMaterial.public_key_pem,
    recoveryKeyId: RECOVERY_KEY_ID,
    recoveryPublicKeyPem: owner.keyMaterial.public_key_pem,
  })

  const ownerPrivateKey = await unlockAccountPrivateKey(sealed(owner.keyMaterial), OWNER_PASSPHRASE)
  const dek = await unwrapDek(ownerPrivateKey, fromBase64(payload.metadata.wrapped_file_key))

  const recipientPublicKey = await importRsaOaepPublicKey(recipient.keyMaterial.public_key_pem)
  const wrappedForRecipient = await rsaOaepWrap(recipientPublicKey, dek)

  return { payload, wrappedForRecipient, plaintextText }
}

function identityOf(payload: Awaited<ReturnType<typeof shareOneFile>>['payload']) {
  return {
    fileId: payload.metadata.file_id,
    originalFilename: payload.metadata.original_filename,
    plaintextSize: payload.metadata.plaintext_size,
    mimeType: payload.metadata.mime_type,
  }
}

describe('sharing rewraps the file key to the recipient', () => {
  it('lets the recipient decrypt with their own passphrase and never the owner\'s', async () => {
    const { recipient } = await parties()
    const { payload, wrappedForRecipient, plaintextText } = await shareOneFile(
      'the week four meeting minutes',
    )

    // Everything from here uses only the recipient's own credentials.
    const recipientPrivateKey = await unlockAccountPrivateKey(
      sealed(recipient.keyMaterial),
      RECIPIENT_PASSPHRASE,
    )
    const dek = await unwrapDek(recipientPrivateKey, wrappedForRecipient)
    const recovered = await decryptFile({
      identity: identityOf(payload),
      dek,
      nonce: fromBase64(payload.metadata.nonce),
      ciphertext: payload.ciphertext,
      authTag: fromBase64(payload.metadata.auth_tag),
    })

    expect(new TextDecoder().decode(recovered)).toBe(plaintextText)
  })

  it('does not let an uninvited account open the shared wrapping', async () => {
    const { stranger } = await parties()
    const { wrappedForRecipient } = await shareOneFile('commercial in confidence')

    const strangerPrivateKey = await unlockAccountPrivateKey(
      sealed(stranger.keyMaterial),
      STRANGER_PASSPHRASE,
    )

    await expect(unwrapDek(strangerPrivateKey, wrappedForRecipient)).rejects.toThrow()
  })

  it('leaves the owner\'s own wrapping working, so sharing does not cost them access', async () => {
    const { owner } = await parties()
    const { payload } = await shareOneFile('still mine afterwards')

    const ownerPrivateKey = await unlockAccountPrivateKey(
      sealed(owner.keyMaterial),
      OWNER_PASSPHRASE,
    )

    await expect(
      unwrapDek(ownerPrivateKey, fromBase64(payload.metadata.wrapped_file_key)),
    ).resolves.toHaveLength(32)
  })

  it('ships a wrapping the share schema will accept', async () => {
    // The backend requires 256..512 decoded bytes and rejects anything else, which is the
    // check that would have caught the old `{ target_username }` payload immediately.
    const { wrappedForRecipient } = await shareOneFile('length matters')

    expect(wrappedForRecipient.length).toBeGreaterThanOrEqual(256)
    expect(wrappedForRecipient.length).toBeLessThanOrEqual(512)
  })

  it('sends a different wrapping to the recipient than the owner holds', async () => {
    // If these matched, the DEK would not have been rewrapped at all -- the recipient would
    // be handed a ciphertext only the owner's key opens.
    const { payload, wrappedForRecipient } = await shareOneFile('rewrapped, not forwarded')

    const ownerWrapping = fromBase64(payload.metadata.wrapped_file_key)
    expect(Array.from(wrappedForRecipient)).not.toEqual(Array.from(ownerWrapping))
  })
})
