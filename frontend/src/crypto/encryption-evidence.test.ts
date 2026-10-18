/**
 * Evidence that uploads are really encrypted, at sizes where a rename could not pass for it.
 *
 * Why this exists: the file list shows the original and encrypted sizes side by side and they
 * match, which looks like "only the name changed". They match because AES-GCM and
 * ChaCha20-Poly1305 add no padding (the 12-byte nonce and 16-byte tag are stored beside the
 * file), so what has to be shown is that the *bytes* differ, not the length. For each of the
 * four algorithms this takes a 20 MiB file (the size a supervisor asked about) made of the
 * easiest-to-spot plaintext there is, a repeated sentence, runs it through the real
 * `prepareUpload` path, and checks the ciphertext:
 *
 *  - is exactly as long as the original, as the backend requires;
 *  - looks random: entropy near the 8 bits/byte maximum, where the plaintext sits near 4;
 *  - shares no recognisable prefix and agrees with the plaintext at about 1 byte in 256;
 *  - hashes to something different, and decrypts back to the exact original;
 *  - fails authentication if a single byte in the middle is flipped.
 *
 * It prints the figures so `docs/ENCRYPTION_EVIDENCE.md` can quote a real run.
 */

import { describe, expect, it } from 'vitest'

import { fromBase64, toBase64 } from './encoding'
import { decryptFile, unwrapDek } from './file_envelope'
import {
  ENCRYPTION_ALGORITHMS,
  type EncryptionAlgorithm,
  publicKeyFingerprint,
  sha256Hex,
  nonceBytesForAlgorithm,
} from './primitives'
import { prepareUpload, type UploadRecipients } from './upload'

const MIB = 1024 * 1024
const FILE_BYTES = 20 * MIB

async function rsaPair(): Promise<{ pair: CryptoKeyPair; pem: string }> {
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

/** A repeated English sentence: highly structured, entropy about 4 bits per byte. */
function structuredPlaintext(length: number): Uint8Array {
  const sentence = new TextEncoder().encode('The quick brown fox jumps over the lazy dog. ')
  const out = new Uint8Array(length)
  for (let offset = 0; offset < length; offset += sentence.length) {
    out.set(sentence.subarray(0, Math.min(sentence.length, length - offset)), offset)
  }
  return out
}

/** Shannon entropy in bits per byte: 8 is the maximum, and random data sits very close to it. */
function entropy(data: Uint8Array): number {
  const counts = new Float64Array(256)
  for (let index = 0; index < data.length; index += 1) counts[data[index]] += 1
  let bits = 0
  for (const count of counts) {
    if (count === 0) continue
    const p = count / data.length
    bits -= p * Math.log2(p)
  }
  return bits
}

function matchingPositions(a: Uint8Array, b: Uint8Array): number {
  let same = 0
  for (let index = 0; index < a.length; index += 1) if (a[index] === b[index]) same += 1
  return same
}

describe.each([...ENCRYPTION_ALGORITHMS] as EncryptionAlgorithm[])(
  '20 MiB through the real upload path with %s',
  (algorithm) => {
    it('is genuinely encrypted: random-looking, same length, different hash, tamper-evident', async () => {
      const { pair: ownerPair, pem: ownerPem } = await rsaPair()
      const { pem: recoveryPem } = await rsaPair()
      const recipients: UploadRecipients = {
        ownerKeyId: '11111111-1111-4111-8111-111111111111',
        ownerPublicKeyPem: ownerPem,
        recoveryKeyId: '22222222-2222-4222-8222-222222222222',
        recoveryPublicKeyPem: recoveryPem,
        recoveryKeyFingerprint: await publicKeyFingerprint(recoveryPem),
      }
      const plaintext = structuredPlaintext(FILE_BYTES)

      const started = performance.now()
      const payload = await prepareUpload({
        file: {
          name: 'evidence.txt',
          size: plaintext.length,
          type: 'text/plain',
          arrayBuffer: async () => plaintext.slice().buffer,
        },
        recipients,
        algorithm,
      })
      const encryptSeconds = (performance.now() - started) / 1000
      const ciphertext = payload.ciphertext

      // 1. Same length, because no padding; the nonce and tag live in the metadata.
      expect(ciphertext.length).toBe(plaintext.length)
      expect(fromBase64(payload.metadata.nonce)).toHaveLength(nonceBytesForAlgorithm(algorithm))
      expect(fromBase64(payload.metadata.auth_tag)).toHaveLength(16)

      // 2. Random-looking where the plaintext is not.
      const plainEntropy = entropy(plaintext)
      const cipherEntropy = entropy(ciphertext)
      expect(plainEntropy).toBeLessThan(5)
      expect(cipherEntropy).toBeGreaterThan(7.999)

      // 3. Not the same bytes: no shared prefix, and agreement at chance level (1/256).
      expect(Array.from(ciphertext.slice(0, 64))).not.toEqual(Array.from(plaintext.slice(0, 64)))
      const agreement = matchingPositions(ciphertext, plaintext) / ciphertext.length
      expect(agreement).toBeLessThan(0.01)

      // 4. A different digest, and the exact original comes back.
      const plainHash = await sha256Hex(plaintext)
      const cipherHash = await sha256Hex(ciphertext)
      expect(cipherHash).not.toBe(plainHash)

      const dek = await unwrapDek(ownerPair.privateKey, fromBase64(payload.metadata.wrapped_file_key))
      const open = (data: Uint8Array) =>
        decryptFile({
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
          ciphertext: data,
          authTag: fromBase64(payload.metadata.auth_tag),
        })
      const recovered = await open(ciphertext)
      expect(recovered.length).toBe(plaintext.length)
      expect(await sha256Hex(recovered)).toBe(plainHash)

      // 5. One flipped byte in the middle is caught, not silently decrypted to garbage.
      const tampered = ciphertext.slice()
      tampered[Math.floor(tampered.length / 2)] ^= 0x01
      await expect(open(tampered)).rejects.toThrow()

      console.info(
        `[encryption-evidence] ${algorithm}: ${FILE_BYTES} bytes in, ${ciphertext.length} bytes out; ` +
          `entropy ${plainEntropy.toFixed(3)} -> ${cipherEntropy.toFixed(5)} bits/byte; ` +
          `bytes equal to plaintext ${(agreement * 100).toFixed(3)}% (chance 0.391%); ` +
          `sha256 ${plainHash.slice(0, 12)}... vs ${cipherHash.slice(0, 12)}...; ` +
          `encrypt+self-test ${encryptSeconds.toFixed(2)}s`,
      )
    }, 180_000)
  },
)
