import { describe, expect, it } from 'vitest'
import { aesDecrypt, aesEncrypt } from './crypto-playground'

describe('aesDecrypt', () => {
  it('reads back what aesEncrypt wrote under the same password', async () => {
    const { ciphertext } = await aesEncrypt('HELLO SECUREVIEW', 'correct horse')
    await expect(aesDecrypt(ciphertext, 'correct horse')).resolves.toBe('HELLO SECUREVIEW')
  })

  // WebCrypto rejects with an OperationError whose message is empty in Chrome and Safari, so
  // the playground showed a blank error line. The message must say what probably happened.
  it('explains a wrong password instead of throwing an empty error', async () => {
    const { ciphertext } = await aesEncrypt('HELLO SECUREVIEW', 'correct horse')
    await expect(aesDecrypt(ciphertext, 'wrong horse')).rejects.toThrow(
      'Wrong password, or the ciphertext was changed.',
    )
  })

  it('explains tampered ciphertext the same way', async () => {
    const { ciphertext } = await aesEncrypt('HELLO SECUREVIEW', 'correct horse')
    const bytes = Uint8Array.from(atob(ciphertext), (c) => c.charCodeAt(0))
    bytes[bytes.length - 1] ^= 0x01
    const tampered = btoa(String.fromCharCode(...bytes))
    await expect(aesDecrypt(tampered, 'correct horse')).rejects.toThrow(
      'Wrong password, or the ciphertext was changed.',
    )
  })
})
