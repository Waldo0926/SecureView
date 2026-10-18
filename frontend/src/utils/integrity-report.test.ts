import { describe, expect, it } from 'vitest'

import type { AdminIntegrityScan } from '@/api/admin_api'
import { findingText, restoreCommand, scanSummary } from './integrity-report'

const scan = (over: Partial<AdminIntegrityScan> = {}): AdminIntegrityScan => ({
  scanned: 5,
  valid: 5,
  damaged: 0,
  candidates: 5,
  stopped_early: false,
  damaged_file_ids: [],
  ...over,
})

describe('findingText', () => {
  it('says MODIFIED is about the bytes and MISSING/ERROR are about the storage', () => {
    expect(findingText('MODIFIED')).toMatch(/no longer match the SHA-256/)
    expect(findingText('MISSING')).toMatch(/missing from storage/)
    expect(findingText('ERROR')).toMatch(/not proof of tampering/)
  })

  it('has a fallback for a file marked corrupted with no recent check on record', () => {
    expect(findingText(null)).toMatch(/earlier check/)
  })
})

describe('restoreCommand', () => {
  it('is a command that runs as pasted: no placeholders, the nightly backup by default', () => {
    const command = restoreCommand('11111111-1111-4111-8111-111111111111')

    expect(command).toBe(
      'cd /opt/mcs21/current/backend && sudo .venv/bin/python scripts/restore_file.py --file-id 11111111-1111-4111-8111-111111111111',
    )
    expect(command).not.toContain('<')
  })

  it('adds --apply for the second run', () => {
    expect(restoreCommand('11111111-1111-4111-8111-111111111111', true)).toMatch(/ --apply$/)
  })
})

describe('scanSummary', () => {
  it('reports a clean full pass', () => {
    expect(scanSummary(scan())).toBe('Checked 5 files of 5. All of them match their recorded SHA-256.')
  })

  it('reports damage with correct plurals', () => {
    expect(scanSummary(scan({ scanned: 3, valid: 2, damaged: 1, candidates: 3 }))).toBe(
      'Checked 3 files of 3. 1 file damaged, 2 intact.',
    )
  })

  it('says what to do when the pass did not cover everything', () => {
    expect(scanSummary(scan({ scanned: 2, candidates: 9, stopped_early: true }))).toMatch(
      /stopped at the time limit; scan again/,
    )
    expect(scanSummary(scan({ scanned: 50, candidates: 90 }))).toMatch(/^Checked 50 files of 90\..*Scan again/)
  })
})
