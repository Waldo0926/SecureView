import { describe, expect, it } from 'vitest'

import { mapFileLifecycle, mapFileStatus } from './types'

describe('mapFileLifecycle', () => {
  it('reads the vocabulary GET /files actually answers with', () => {
    expect(mapFileLifecycle('ACTIVE')).toBe('verified')
    expect(mapFileLifecycle('CORRUPTED')).toBe('modified')
    expect(mapFileLifecycle('DELETED')).toBe('pending')
  })

  it('distinguishes a healthy file from a damaged one', () => {
    // The whole point of the badge. Running files.status through mapFileStatus sent both
    // down the fallback branch, so the server could positively mark a file as damaged and
    // the table would render it identically to every healthy row.
    expect(mapFileLifecycle('ACTIVE')).not.toBe(mapFileLifecycle('CORRUPTED'))
  })

  it('does not claim a file is healthy on an unknown status', () => {
    expect(mapFileLifecycle('SOMETHING_NEW')).toBe('pending')
    expect(mapFileLifecycle('')).toBe('pending')
  })

  it('is case insensitive', () => {
    expect(mapFileLifecycle('active')).toBe('verified')
    expect(mapFileLifecycle('corrupted')).toBe('modified')
  })
})

describe('mapFileStatus', () => {
  it('reads the vocabulary the integrity check answers with', () => {
    expect(mapFileStatus('VALID')).toBe('verified')
    expect(mapFileStatus('MODIFIED')).toBe('modified')
    expect(mapFileStatus('MISSING')).toBe('pending')
    expect(mapFileStatus('ERROR')).toBe('pending')
  })

  it('does not accept a lifecycle status as if it were a verdict', () => {
    // ACTIVE is not an integrity result. Keeping this explicit is what stops the two
    // vocabularies from being merged back into one lookup.
    expect(mapFileStatus('ACTIVE')).toBe('pending')
  })
})
