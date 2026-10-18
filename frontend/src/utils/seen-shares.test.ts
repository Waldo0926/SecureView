import { beforeEach, describe, expect, it, vi } from 'vitest'

const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
})

const { forgetSeenShares, markSharesSeen, unseenSharedIds } = await import('./seen-shares')

beforeEach(() => {
  store.clear()
})

describe('unseenSharedIds', () => {
  it('treats everything as new before anything has been seen', () => {
    expect(unseenSharedIds(['a', 'b'])).toEqual(['a', 'b'])
  })

  it('stops counting a file once the shared list has been shown', () => {
    markSharesSeen(['a', 'b'])

    expect(unseenSharedIds(['a', 'b'])).toEqual([])
  })

  it('counts a file shared after the last visit', () => {
    markSharesSeen(['a'])

    expect(unseenSharedIds(['a', 'b'])).toEqual(['b'])
  })

  it('forgets a file that is no longer shared, so re-sharing it counts again', () => {
    markSharesSeen(['a', 'b'])
    // 'b' was revoked; only 'a' is still shared when the list is next shown.
    markSharesSeen(['a'])

    expect(unseenSharedIds(['a', 'b'])).toEqual(['b'])
  })

  it('survives junk in the storage key rather than throwing', () => {
    localStorage.setItem('seen_shared_file_ids', 'not json at all')

    expect(unseenSharedIds(['a'])).toEqual(['a'])
  })

  it('ignores non-string entries someone else may have written', () => {
    localStorage.setItem('seen_shared_file_ids', JSON.stringify(['a', 42, null]))

    expect(unseenSharedIds(['a', 'b'])).toEqual(['b'])
  })

  it('clears on logout so the next person does not inherit the marker', () => {
    markSharesSeen(['a'])
    forgetSeenShares()

    expect(unseenSharedIds(['a'])).toEqual(['a'])
  })
})
