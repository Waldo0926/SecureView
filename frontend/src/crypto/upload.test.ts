import { describe, expect, it } from 'vitest'

import { fromBase64, toBase64 } from './encoding'
import { decryptFile, unwrapDek } from './file_envelope'
import { publicKeyFingerprint } from './primitives'
import {
  classifyUploadSize,
  DEFAULT_MIME_TYPE,
  filesStillToUpload,
  isMemoryExhaustion,
  LARGE_FILE_WARNING_BYTES,
  MAX_UPLOAD_BYTES,
  prepareUpload,
  resolveMimeType,
  resolveUploadFilename,
  SAMPLE_BYTES,
  type UploadEvent,
  type UploadRecipients,
  type UploadableFile,
} from './upload'

function fakeFile(name: string, bytes: Uint8Array, type?: string): UploadableFile {
  return {
    name,
    size: bytes.length,
    type,
    arrayBuffer: async () => bytes.slice().buffer,
  }
}

async function newRsaPairAndPem(): Promise<{ pair: CryptoKeyPair; pem: string }> {
  const pair = (await globalThis.crypto.subtle.generateKey(
    {
      name: 'RSA-OAEP',
      modulusLength: 2048,
      publicExponent: new Uint8Array([0x01, 0x00, 0x01]),
      hash: 'SHA-256',
    },
    true,
    ['encrypt', 'decrypt'],
  )) as CryptoKeyPair
  const spki = new Uint8Array(await globalThis.crypto.subtle.exportKey('spki', pair.publicKey))
  const body = toBase64(spki).replace(/(.{64})/g, '$1\n')
  return { pair, pem: `-----BEGIN PUBLIC KEY-----\n${body}\n-----END PUBLIC KEY-----\n` }
}

async function recipientsFor(ownerPem: string, recoveryPem: string): Promise<UploadRecipients> {
  return {
    ownerKeyId: '11111111-1111-4111-8111-111111111111',
    ownerPublicKeyPem: ownerPem,
    recoveryKeyId: '22222222-2222-4222-8222-222222222222',
    recoveryPublicKeyPem: recoveryPem,
    recoveryKeyFingerprint: await publicKeyFingerprint(recoveryPem),
  }
}

describe('resolveMimeType', () => {
  it('falls back when the browser reports nothing usable', () => {
    // File.type is empty for extensions the browser does not recognise, and the API
    // requires a well-formed media type.
    expect(resolveMimeType('')).toBe(DEFAULT_MIME_TYPE)
    expect(resolveMimeType(undefined)).toBe(DEFAULT_MIME_TYPE)
    expect(resolveMimeType('   ')).toBe(DEFAULT_MIME_TYPE)
    expect(resolveMimeType('unknown')).toBe(DEFAULT_MIME_TYPE)
  })

  it('lowercases and trims what the browser does report', () => {
    expect(resolveMimeType('Application/PDF')).toBe('application/pdf')
    expect(resolveMimeType(' text/plain ')).toBe('text/plain')
  })
})

describe('resolveUploadFilename', () => {
  it('removes invisible surrounding whitespace but preserves spaces within a filename', () => {
    expect(resolveUploadFilename(' FIT3162 First Individual Vlog 35925248.mp4 ')).toBe(
      'FIT3162 First Individual Vlog 35925248.mp4',
    )
  })

  it('normalizes equivalent Unicode before the filename becomes authenticated metadata', () => {
    expect(resolveUploadFilename(' re\u0301sume\u0301.pdf')).toBe('r\u00e9sum\u00e9.pdf')
  })
})

describe('prepareUpload', () => {
  it('reports each stage in order, and the byte sample is the real plaintext and ciphertext', async () => {
    const { pem: ownerPem } = await newRsaPairAndPem()
    const { pem: recoveryPem } = await newRsaPairAndPem()
    const plaintext = new TextEncoder().encode('%PDF-1.7 a document long enough to sample')
    const events: UploadEvent[] = []

    const payload = await prepareUpload({
      file: fakeFile('report.pdf', plaintext, 'application/pdf'),
      recipients: await recipientsFor(ownerPem, recoveryPem),
      onEvent: (event) => {
        events.push(event)
      },
    })

    expect(events.map((e) => ('stage' in e ? `${e.type}:${e.stage}` : e.type))).toEqual([
      'stage:read',
      'timed:read',
      'stage:encrypt',
      'timed:encrypt',
      'sample',
      'stage:wrap',
      'timed:wrap',
    ])
    for (const event of events) {
      if (event.type === 'timed') expect(event.ms).toBeGreaterThanOrEqual(0)
    }
    const sample = events.find((e) => e.type === 'sample')
    if (sample?.type !== 'sample') throw new Error('no sample event')
    expect(sample.plaintextHead).toEqual(plaintext.slice(0, SAMPLE_BYTES))
    expect(sample.ciphertextHead).toEqual(payload.ciphertext.slice(0, SAMPLE_BYTES))
    expect(sample.ciphertextHead).not.toEqual(sample.plaintextHead)
  })

  it('produces metadata that satisfies every shape the upload contract checks', async () => {
    const { pem: ownerPem } = await newRsaPairAndPem()
    const { pem: recoveryPem } = await newRsaPairAndPem()
    const plaintext = new TextEncoder().encode('quarterly numbers, confidential')

    const payload = await prepareUpload({
      file: fakeFile('report.pdf', plaintext, 'application/pdf'),
      recipients: await recipientsFor(ownerPem, recoveryPem),
    })

    const meta = payload.metadata
    expect(meta.original_filename).toBe('report.pdf')
    expect(meta.mime_type).toBe('application/pdf')
    expect(meta.encryption_algorithm).toBe('AES-256-GCM')
    expect(meta.key_wrapping_algorithm).toBe('RSA-OAEP-SHA256')
    expect(meta.envelope_version).toBe(1)
    expect(meta.aad_version).toBe(1)

    // file_service requires ciphertext length to equal plaintext_size exactly.
    expect(meta.plaintext_size).toBe(plaintext.length)
    expect(payload.ciphertext.length).toBe(plaintext.length)

    expect(fromBase64(meta.nonce)).toHaveLength(12)
    expect(fromBase64(meta.auth_tag)).toHaveLength(16)
    expect(fromBase64(meta.wrapped_file_key)).toHaveLength(256)
    expect(fromBase64(meta.recovery_wrapped_file_key)).toHaveLength(256)
    expect(meta.file_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })

  it('round trips: the owner can unwrap the key and recover the exact bytes', async () => {
    // The strongest check available without a server. It exercises the whole chain the
    // upload depends on: wrap, unwrap, AAD reconstruction, and authenticated decryption.
    const { pair: ownerPair, pem: ownerPem } = await newRsaPairAndPem()
    const { pem: recoveryPem } = await newRsaPairAndPem()
    const plaintext = new TextEncoder().encode('the quick brown fox jumps over the lazy dog')

    const payload = await prepareUpload({
      file: fakeFile('notes.txt', plaintext, 'text/plain'),
      recipients: await recipientsFor(ownerPem, recoveryPem),
    })

    const dek = await unwrapDek(ownerPair.privateKey, fromBase64(payload.metadata.wrapped_file_key))
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

    expect(new TextDecoder().decode(recovered)).toBe(
      'the quick brown fox jumps over the lazy dog',
    )
  })

  it('wraps the same key separately to the owner and the recovery key', async () => {
    const { pair: ownerPair, pem: ownerPem } = await newRsaPairAndPem()
    const { pair: recoveryPair, pem: recoveryPem } = await newRsaPairAndPem()

    const payload = await prepareUpload({
      file: fakeFile('a.bin', new Uint8Array([1, 2, 3])),
      recipients: await recipientsFor(ownerPem, recoveryPem),
    })

    const viaOwner = await unwrapDek(ownerPair.privateKey, fromBase64(payload.metadata.wrapped_file_key))
    const viaRecovery = await unwrapDek(
      recoveryPair.privateKey,
      fromBase64(payload.metadata.recovery_wrapped_file_key),
    )
    expect(viaRecovery).toEqual(viaOwner)
    expect(payload.metadata.wrapped_file_key).not.toBe(payload.metadata.recovery_wrapped_file_key)
  })

  it('defaults the MIME type when the browser reports none', async () => {
    const { pem } = await newRsaPairAndPem()
    const payload = await prepareUpload({
      file: fakeFile('archive.xyz', new Uint8Array([7])),
      recipients: await recipientsFor(pem, pem),
    })
    expect(payload.metadata.mime_type).toBe(DEFAULT_MIME_TYPE)
  })

  it('uploads a filename with internal spaces after trimming its hidden leading space', async () => {
    const { pem } = await newRsaPairAndPem()
    const payload = await prepareUpload({
      file: fakeFile(
        ' FIT3162 First Individual Vlog Reflections Shuoxun Wen 35925248.mp4',
        new Uint8Array([7]),
        'video/mp4',
      ),
      recipients: await recipientsFor(pem, pem),
    })
    expect(payload.metadata.original_filename).toBe(
      'FIT3162 First Individual Vlog Reflections Shuoxun Wen 35925248.mp4',
    )
    expect(payload.metadata.mime_type).toBe('video/mp4')
  })

  it('handles an empty file', async () => {
    const { pem } = await newRsaPairAndPem()
    const payload = await prepareUpload({
      file: fakeFile('empty.bin', new Uint8Array()),
      recipients: await recipientsFor(pem, pem),
    })
    expect(payload.metadata.plaintext_size).toBe(0)
    expect(payload.ciphertext).toHaveLength(0)
    expect(fromBase64(payload.metadata.auth_tag)).toHaveLength(16)
  })

  it('rejects an oversize file before doing any cryptographic work', async () => {
    const { pem } = await newRsaPairAndPem()
    const oversize: UploadableFile = {
      name: 'huge.iso',
      size: MAX_UPLOAD_BYTES + 1,
      type: 'application/octet-stream',
      arrayBuffer: async () => {
        throw new Error('must not read an oversize file into memory')
      },
    }
    await expect(
      prepareUpload({ file: oversize, recipients: await recipientsFor(pem, pem) }),
    ).rejects.toBeInstanceOf(RangeError)
  })

  it('surfaces a filename the API would reject rather than sending it', async () => {
    const { pem } = await newRsaPairAndPem()
    await expect(
      prepareUpload({
        file: fakeFile('bad/name.txt', new Uint8Array([1])),
        recipients: await recipientsFor(pem, pem),
      }),
    ).rejects.toThrow(/path separator/)
  })
})

describe('filesStillToUpload', () => {
  it('sends nothing again once every file has uploaded', () => {
    expect(filesStillToUpload([{ status: 'done' }, { status: 'done' }])).toEqual([])
  })

  it('sends only the new or failed files when a finished batch gets more', () => {
    const files = [
      { name: 'a', status: 'done' },
      { name: 'b', status: 'failed' },
      { name: 'c', status: 'pending' },
    ]
    expect(filesStillToUpload(files).map((file) => file.name)).toEqual(['b', 'c'])
  })
})

describe('classifyUploadSize', () => {
  it('warns from 100 MiB and refuses only above the 500 MiB limit', () => {
    expect(classifyUploadSize(0)).toBe('ok')
    expect(classifyUploadSize(LARGE_FILE_WARNING_BYTES - 1)).toBe('ok')
    expect(classifyUploadSize(LARGE_FILE_WARNING_BYTES)).toBe('large')
    expect(classifyUploadSize(MAX_UPLOAD_BYTES)).toBe('large')
    expect(classifyUploadSize(MAX_UPLOAD_BYTES + 1)).toBe('too-large')
  })
})

describe('memory exhaustion', () => {
  it('recognises the errors a browser raises when a buffer will not fit', () => {
    expect(isMemoryExhaustion(new RangeError('Array buffer allocation failed'))).toBe(true)
    expect(isMemoryExhaustion(new DOMException('read failed', 'NotReadableError'))).toBe(true)
    expect(isMemoryExhaustion(new Error('something else'))).toBe(false)
    expect(isMemoryExhaustion(new DOMException('bad key', 'OperationError'))).toBe(false)
  })

  it('turns an allocation failure into advice a non-expert can act on', async () => {
    const big: UploadableFile = {
      name: 'holiday.mov',
      size: 300 * 1024 * 1024,
      type: 'video/quicktime',
      arrayBuffer: async () => {
        throw new RangeError('Array buffer allocation failed')
      },
    }
    // The recipients are never reached: the file cannot even be read into memory.
    await expect(
      prepareUpload({ file: big, recipients: {} as UploadRecipients }),
    ).rejects.toThrow(/too large for this browser.*four times/)
  })
})
