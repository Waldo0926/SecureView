import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { gettingStartedProgress, hideGettingStarted, isGettingStartedHidden } from './getting-started'

describe('gettingStartedProgress', () => {
  it('ticks each step only when its event is in the trail', () => {
    expect(gettingStartedProgress([])).toEqual({ upload: false, share: false, download: false })
    expect(gettingStartedProgress(['AUTH_LOGIN_SUCCEEDED', 'FILE_UPLOADED'])).toEqual({
      upload: true,
      share: false,
      download: false,
    })
    expect(gettingStartedProgress(['FILE_UPLOADED', 'FILE_SHARED', 'FILE_DOWNLOAD_AUTHORIZED'])).toEqual({
      upload: true,
      share: true,
      download: true,
    })
  })
})

describe('hiding the checklist', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('is remembered per account', () => {
    expect(isGettingStartedHidden('alice')).toBe(false)
    hideGettingStarted('alice')
    expect(isGettingStartedHidden('alice')).toBe(true)
    expect(isGettingStartedHidden('bob')).toBe(false)
  })
})
