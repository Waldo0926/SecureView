import { describe, expect, it } from 'vitest'

import {
  PASSPHRASE_MIN_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  evaluatePassword,
  passphraseLength,
  passwordCharacterClasses,
  weakPassphraseReason,
} from './password-policy'

describe('encryption passphrase policy', () => {
  it('uses a 10-character minimum and counts Unicode characters consistently', () => {
    expect(PASSPHRASE_MIN_LENGTH).toBe(10)
    expect(passphraseLength('1234567890')).toBe(PASSPHRASE_MIN_LENGTH)
    expect(passphraseLength('🔐'.repeat(10))).toBe(PASSPHRASE_MIN_LENGTH)
  })
})

describe('passwordCharacterClasses', () => {
  it('buckets characters the way the server does', () => {
    expect([...passwordCharacterClasses('Ab1!')].sort()).toEqual([
      'lowercase',
      'number',
      'symbol',
      'uppercase',
    ])
    expect([...passwordCharacterClasses('abc')]).toEqual(['lowercase'])
  })

  it('counts a space as a symbol, so a plain passphrase qualifies', () => {
    expect([...passwordCharacterClasses('two words')].sort()).toEqual(['lowercase', 'symbol'])
  })

  it('puts caseless scripts in one class rather than none', () => {
    expect([...passwordCharacterClasses('密码密码密码密码')]).toEqual(['symbol'])
  })
})

describe('evaluatePassword', () => {
  it('accepts any two character classes at the minimum length', () => {
    for (const password of ['Abcdefgh', 'abcd1234', 'ABCD1234', 'abcd!@#$', '1234!@#$']) {
      expect(evaluatePassword(password).ok, password).toBe(true)
    }
  })

  it('reports how far a short password still has to go', () => {
    const result = evaluatePassword('Ab1')
    expect(result.ok).toBe(false)
    expect(result.tooShort).toBe(true)
    expect(result.message).toBe(`Use at least ${PASSWORD_MIN_LENGTH} characters (3 so far).`)
  })

  it('rejects a password drawn from a single character class', () => {
    const result = evaluatePassword('abcdefghij')
    expect(result.ok).toBe(false)
    expect(result.tooFewClasses).toBe(true)
    expect(result.message).toContain('Mix at least 2 of')
  })

  it('rejects a password built around the username or email local part', () => {
    expect(evaluatePassword('Alice2024!', ['alice', 'alice@example.com']).ok).toBe(false)
    expect(evaluatePassword('x9-owner-Qz', ['someone', 'owner@example.com'])).toMatchObject({
      ok: false,
      usesAccountDetails: true,
    })
  })

  it('ignores account fragments too short to mean anything', () => {
    expect(evaluatePassword('Th1s-is-fine', ['a@example.com']).ok).toBe(true)
  })

  it('ignores blank context values', () => {
    expect(evaluatePassword('Th1s-is-fine', ['', '   ']).ok).toBe(true)
  })

  it('treats an empty password as incomplete rather than as a rule violation', () => {
    const result = evaluatePassword('')
    expect(result).toMatchObject({ ok: false, isEmpty: true, tooShort: false, tooFewClasses: false })
    expect(result.message).toBe('Enter a password')
  })

  it('enforces the upper bound the API also enforces', () => {
    const result = evaluatePassword('Ab1'.padEnd(PASSWORD_MAX_LENGTH + 1, 'c'))
    expect(result.ok).toBe(false)
    expect(result.tooLong).toBe(true)
  })

  it('measures length in code points, so an emoji is one character', () => {
    // Eight code points, two classes. A UTF-16 .length check would read this as 12
    // and wave through a password the server would then reject.
    expect(evaluatePassword('🔐🔐🔐🔐ab🔐🔐').length).toBe(8)
    expect(evaluatePassword('🔐🔐🔐ab🔐🔐').ok).toBe(false)
  })
})

describe('weakPassphraseReason (threat model F-04)', () => {
  it.each([
    ['password123', 'common'],
    ['Pass Word 123', 'common'],
    ['correct horse battery staple', 'common'],
    ['SecureView123', 'common'],
    ['aaaaaaaaaa', 'pattern'],
    ['abcabcabcabc', 'pattern'],
    ['1212121212', 'pattern'],
    ['abcdefghijk', 'pattern'],
    ['9876543210', 'pattern'],
    ['qwertyuiop', 'pattern'],
    ['lkjhgfdsa1', ''],
    ['aabbaabbab', 'pattern'],
  ])('flags %j as %j', (passphrase, reason) => {
    expect(weakPassphraseReason(passphrase)).toBe(reason)
  })

  it('flags a passphrase that is mostly the username or email', () => {
    const context = ['samuel', 'samuel.lee@example.com']
    expect(weakPassphraseReason('samuel2026!', context)).toBe('account')
    expect(weakPassphraseReason('Samuel.Lee 1', context)).toBe('account')
  })

  it('lets a real phrase through even when it contains the name', () => {
    const context = ['samuel', 'samuel.lee@example.com']
    expect(weakPassphraseReason('samuel rides purple tractors at noon', context)).toBe('')
  })

  it('accepts four random words and other strong passphrases', () => {
    expect(weakPassphraseReason('maple orbit sunlit gravel')).toBe('')
    expect(weakPassphraseReason('throwaway alice passphrase 5d8c1e9a')).toBe('')
    expect(weakPassphraseReason('我的猫喜欢在窗台上晒太阳')).toBe('')
  })

  it('says nothing about an empty value, which has its own message', () => {
    expect(weakPassphraseReason('')).toBe('')
  })
})
