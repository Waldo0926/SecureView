import { AxiosError, type AxiosResponse } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { toBase64 } from './encoding'
import { formatFingerprint } from './fingerprint'
import { publicKeyFingerprint } from './primitives'
import { knownFingerprint, rememberFingerprint } from '@/utils/known-keys'

const lookup = vi.fn()
// A plain function in front of the spy, so one test can fail the lookup without a spy recording it.
let respond: (id: string) => unknown = (id) => lookup(id)
vi.mock('@/api/key_api', () => ({ keyApi: { activePublicKeyByIdentifier: (id: string) => respond(id) } }))

const { lookupRecipient, RecipientKeyMismatchError, RecipientNotFoundError } = await import('./share')

async function publicPem(): Promise<string> {
  const pair = (await globalThis.crypto.subtle.generateKey(
    { name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
    true,
    ['encrypt', 'decrypt'],
  )) as CryptoKeyPair
  const spki = new Uint8Array(await globalThis.crypto.subtle.exportKey('spki', pair.publicKey))
  return `-----BEGIN PUBLIC KEY-----\n${toBase64(spki)}\n-----END PUBLIC KEY-----\n`
}

describe('formatFingerprint', () => {
  it('shows the first 128 bits as eight upper-case groups of four', () => {
    expect(formatFingerprint('ab12cd34ef56789001234567890abcdeffffffff')).toBe(
      'AB12 CD34 EF56 7890 0123 4567 890A BCDE',
    )
  })
})

describe('lookupRecipient', () => {
  beforeEach(() => {
    lookup.mockReset()
    respond = (id) => lookup(id)
  })

  it('fingerprints the key in this browser and returns what will be shared to', async () => {
    const pem = await publicPem()
    const expected = await publicKeyFingerprint(pem)
    lookup.mockResolvedValue({
      data: { data: { user_id: 'u-1', key_id: 'k-1', public_key_pem: pem, fingerprint: expected.toUpperCase() } },
    })

    const found = await lookupRecipient('  bob  ')

    expect(lookup).toHaveBeenCalledWith('bob')
    expect(found).toMatchObject({ identifier: 'bob', userId: 'u-1', keyId: 'k-1', fingerprint: expected })
  })

  it('refuses a key the server describes with a different fingerprint', async () => {
    lookup.mockResolvedValue({
      data: { data: { user_id: 'u-1', key_id: 'k-1', public_key_pem: await publicPem(), fingerprint: 'ab'.repeat(32) } },
    })

    await expect(lookupRecipient('bob')).rejects.toBeInstanceOf(RecipientKeyMismatchError)
  })

  it('treats a 404 as no such recipient', async () => {
    respond = () =>
      Promise.reject(new AxiosError('Not Found', 'ERR_BAD_REQUEST', undefined, undefined, { status: 404 } as AxiosResponse))
    const outcome = await lookupRecipient('nobody').catch((error: unknown) => error)
    // By name: under vi.mock the class can be loaded twice, which defeats instanceof.
    expect((outcome as Error).name).toBe(RecipientNotFoundError.name)
  })

  it('passes any other failure through, so a server error is not blamed on the spelling', async () => {
    // A 500 or a dead network used to come back as "no account matches", sending the sender
    // off to re-check a name that was right all along.
    const failure = new AxiosError('Internal Server Error', 'ERR_BAD_RESPONSE', undefined, undefined, { status: 500 } as AxiosResponse)
    respond = () => Promise.reject(failure)
    await expect(lookupRecipient('bob')).rejects.toBe(failure)

    const offline = new TypeError('network down')
    respond = () => Promise.reject(offline)
    await expect(lookupRecipient('bob')).rejects.toBe(offline)
  })
})

describe('known recipient keys', () => {
  // The unit tests run in Node, which has no localStorage; a Map stands in for it.
  beforeEach(() => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      clear: () => store.clear(),
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('remembers the last fingerprint per recipient, so a change can be noticed', () => {
    expect(knownFingerprint('u-1')).toBeNull()
    rememberFingerprint('u-1', 'aa')
    rememberFingerprint('u-2', 'bb')
    rememberFingerprint('u-1', 'cc')
    expect(knownFingerprint('u-1')).toBe('cc')
    expect(knownFingerprint('u-2')).toBe('bb')
  })

  it('survives unreadable storage by remembering nothing', () => {
    localStorage.setItem('secureview.knownRecipientKeys', '{not json')
    expect(knownFingerprint('u-1')).toBeNull()
  })
})
