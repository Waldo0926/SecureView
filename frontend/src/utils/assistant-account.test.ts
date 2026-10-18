import { describe, expect, it, vi } from 'vitest'

import type { SharedUser } from '@/api/share_api'
import type { AuditLogOut, FileListOut, FileSummaryOut } from '@/api/types'

import { fileLink, runAccountCheck, SHARE_SCAN_LIMIT, type AccountApi, type AccountResult } from './assistant-account'

function file(name: string, extra: Partial<FileSummaryOut> = {}): FileSummaryOut {
  return {
    file_id: `id-${name}`,
    original_filename: name,
    plaintext_size: 10,
    ciphertext_size: 10,
    ciphertext_sha256: 'a'.repeat(64),
    mime_type: null,
    encryption_algorithm: 'AES-256-GCM',
    status: 'ACTIVE',
    owner: true,
    owner_username: 'me',
    folder_id: null,
    created_at: '2026-09-30T10:00:00Z',
    updated_at: '2026-09-30T10:00:00Z',
    ...extra,
  }
}

function user(username: string, extra: Partial<SharedUser> = {}): SharedUser {
  return {
    user_id: `u-${username}`,
    username,
    key_id: 'k',
    can_download: true,
    can_share: false,
    is_owner: false,
    granted_at: '2026-09-29T08:00:00Z',
    ...extra,
  }
}

function log(action: string, extra: Partial<AuditLogOut> = {}): AuditLogOut {
  return {
    action,
    resource_type: 'FILE',
    resource_id: 'id-x',
    actor_user_id: null,
    actor_username: 'me',
    target_user_id: null,
    target_username: null,
    result: 'SUCCESS',
    description: null,
    metadata: {},
    created_at: '2026-10-01T09:30:00Z',
    ...extra,
  }
}

/** A fake server holding `files`, with the same search and scope rules as `GET /files`. */
function fakeApi(
  files: FileSummaryOut[],
  options: { holders?: Record<string, SharedUser[]>; logs?: AuditLogOut[]; recent?: AuditLogOut[]; unseen?: string[] } = {},
) {
  const api: AccountApi = {
    listFiles: vi.fn(async ({ scope, page = 1, page_size, search }) => {
      const matching = files.filter(
        (f) =>
          (scope === 'all' || (scope === 'mine') === f.owner) &&
          (!search || f.original_filename.toLowerCase().includes(search.toLowerCase())),
      )
      const result: FileListOut = {
        items: matching.slice((page - 1) * page_size, page * page_size),
        page,
        page_size,
        total: matching.length,
        owned_total: files.filter((f) => f.owner).length,
        shared_total: files.filter((f) => !f.owner).length,
      }
      return result
    }),
    listFolders: vi.fn(async () => []),
    sharedUsers: vi.fn(async (id: string) => [user('me', { is_owner: true }), ...(options.holders?.[id] ?? [])]),
    fileLogs: vi.fn(async () => options.logs ?? []),
    recentLogs: vi.fn(async () => options.recent ?? []),
    unseen: vi.fn((ids: string[]) => ids.filter((id) => (options.unseen ?? []).includes(id))),
  }
  return api
}

function result(r: AccountResult) {
  if (r.kind !== 'result') throw new Error(`expected a result, got ${r.kind}`)
  return r
}

describe('who has access to one of my files', () => {
  const files = [file('budget.xlsx'), file('thesis-final.docx'), file('photo.jpg', { owner: false, owner_username: 'sam' })]

  it('names everyone but the owner, and how to revoke', async () => {
    const api = fakeApi(files, { holders: { 'id-budget.xlsx': [user('alice'), user('bob', { can_share: true })] } })
    const r = result(await runAccountCheck('who-has-access', { fileName: 'budget.xlsx' }, 'me', api))
    expect(r.headline).toBe('Besides you, 2 people can open budget.xlsx: alice and bob.')
    expect(r.rows.map((row) => row.text)).toEqual(['alice', 'bob'])
    expect(r.rows[1]!.detail).toContain('can share it on')
    expect(r.note).toMatch(/Revoke/)
    expect(r.links[0]!.to).toBe('/files?q=budget.xlsx')
  })

  it('says so plainly when nobody else has it', async () => {
    const r = result(await runAccountCheck('who-has-access', { fileName: 'budget' }, 'me', fakeApi(files)))
    expect(r.headline).toBe('Only you can open budget.xlsx. It is not shared with anyone.')
    expect(r.note).toBeUndefined()
  })

  it('finds the file from one word of a longer name', async () => {
    const r = result(await runAccountCheck('who-has-access', { fileName: 'thesis draft' }, 'me', fakeApi(files)))
    expect(r.headline).toContain('thesis-final.docx')
  })

  it('asks which file when none is named, offering only the visitor’s own', async () => {
    const r = await runAccountCheck('who-has-access', {}, 'me', fakeApi(files))
    expect(r.kind).toBe('choose')
    if (r.kind !== 'choose') return
    expect(r.choices.map((c) => c.name)).toEqual(['budget.xlsx', 'thesis-final.docx'])
  })

  it('never looks at a file shared with the visitor, which only its owner may list', async () => {
    const api = fakeApi(files)
    const r = await runAccountCheck('who-has-access', { fileName: 'photo.jpg' }, 'me', api)
    expect(r.kind).toBe('choose')
    if (r.kind === 'choose') expect(r.prompt).toContain('None of your own files is called “photo.jpg”')
    expect(api.sharedUsers).not.toHaveBeenCalled()
  })

  it('asks which one when several match, then answers for the one picked', async () => {
    const two = [file('report-q1.pdf'), file('report-q2.pdf')]
    const api = fakeApi(two)
    const ask = await runAccountCheck('who-has-access', { fileName: 'report' }, 'me', api)
    expect(ask.kind).toBe('choose')
    if (ask.kind === 'choose') expect(ask.prompt).toBe('2 of your files match “report”. Which one?')
    const r = result(await runAccountCheck('who-has-access', { fileId: 'id-report-q2.pdf' }, 'me', api))
    expect(r.headline).toContain('report-q2.pdf')
  })

  it('has nothing to check before the first upload', async () => {
    const r = result(await runAccountCheck('who-has-access', {}, 'me', fakeApi([])))
    expect(r.headline).toMatch(/not uploaded any files/)
  })
})

describe('one file’s history', () => {
  it('counts other people’s downloads and lists the events', async () => {
    const logs = [
      log('FILE_DOWNLOAD_AUTHORIZED', { actor_username: 'alice', created_at: '2026-10-01T09:30:00Z' }),
      log('FILE_DOWNLOAD_AUTHORIZED', { actor_username: 'alice', created_at: '2026-09-30T09:30:00Z' }),
      log('FILE_DOWNLOAD_AUTHORIZED', { actor_username: 'me' }),
      log('FILE_SHARED', { target_username: 'alice' }),
      log('FILE_CIPHERTEXT_PREVIEWED'),
      log('FILE_UPLOADED'),
    ]
    const r = result(await runAccountCheck('file-activity', { fileName: 'budget' }, 'me', fakeApi([file('budget.xlsx')], { logs })))
    expect(r.headline).toMatch(/^budget\.xlsx was downloaded 2 times by alice; most recently /)
    expect(r.rows.map((row) => row.text)).toEqual([
      'alice downloaded it',
      'alice downloaded it',
      'You downloaded it',
      'You shared it with alice',
      'You uploaded it',
    ])
  })

  it('flags a failed integrity check and says who can restore it', async () => {
    const logs = [log('FILE_INTEGRITY_CHECKED', { result: 'FAIL', actor_username: null }), log('FILE_INTEGRITY_CHECKED')]
    const r = result(await runAccountCheck('file-activity', { fileName: 'budget' }, 'me', fakeApi([file('budget.xlsx')], { logs })))
    expect(r.headline).toBe('Nobody else has downloaded budget.xlsx.')
    expect(r.rows).toEqual([expect.objectContaining({ tone: 'warn' })])
    expect(r.note).toMatch(/administrator to restore it/)
  })
})

describe('the files I have shared', () => {
  it('lists each shared file with its recipients', async () => {
    const files = [file('a.txt'), file('b.txt'), file('c.txt')]
    const api = fakeApi(files, { holders: { 'id-b.txt': [user('alice'), user('bob'), user('cy')] } })
    const r = result(await runAccountCheck('my-shares', {}, 'me', api))
    expect(r.headline).toBe('1 of your 3 files is shared.')
    expect(r.rows).toEqual([{ text: 'b.txt', detail: 'with alice, bob and cy', to: '/files?q=b.txt' }])
  })

  it('checks only the newest files, and says how many it skipped', async () => {
    const files = Array.from({ length: SHARE_SCAN_LIMIT + 3 }, (_, i) => file(`f${i}.txt`))
    const api = fakeApi(files)
    const r = result(await runAccountCheck('my-shares', {}, 'me', api))
    expect(api.sharedUsers).toHaveBeenCalledTimes(SHARE_SCAN_LIMIT)
    expect(r.headline).toBe(`None of your ${SHARE_SCAN_LIMIT} newest files is shared with anyone.`)
    expect(r.note).toBe('3 older files not checked.')
  })
})

describe('what is shared with me', () => {
  it('marks the files not seen yet and links to the shared tab', async () => {
    const files = [file('x.pdf', { owner: false, owner_username: 'sam' }), file('y.pdf', { owner: false, owner_username: 'kim' })]
    const r = result(await runAccountCheck('shared-with-me', {}, 'me', fakeApi(files, { unseen: ['id-y.pdf'] })))
    expect(r.headline).toBe('2 files are shared with you; 1 is new since you last looked.')
    expect(r.rows[1]).toMatchObject({ text: 'y.pdf', tone: 'new', to: '/files?q=y.pdf&tab=shared' })
    expect(r.rows[0]!.detail).toMatch(/^from sam · /)
  })

  it('handles nothing shared yet', async () => {
    const r = result(await runAccountCheck('shared-with-me', {}, 'me', fakeApi([file('mine.txt')])))
    expect(r.headline).toBe('Nobody has shared a file with you yet.')
  })
})

describe('files marked Modified', () => {
  it('pages through every file and lists the corrupted ones', async () => {
    const files = Array.from({ length: 150 }, (_, i) => file(`f${i}.bin`, i === 120 ? { status: 'CORRUPTED' } : {}))
    const api = fakeApi(files)
    const r = result(await runAccountCheck('modified-files', {}, 'me', api))
    expect(api.listFiles).toHaveBeenCalledTimes(2)
    expect(r.headline).toBe('1 of your 150 files is marked Modified.')
    expect(r.rows).toEqual([expect.objectContaining({ text: 'f120.bin', tone: 'warn' })])
  })

  it('says when nothing is flagged', async () => {
    const r = result(await runAccountCheck('modified-files', {}, 'me', fakeApi([file('ok.txt')])))
    expect(r.headline).toBe('Your one file is not marked Modified.')
  })
})

describe('recent activity and the overview', () => {
  it('counts failed sign-ins and points to changing the password', async () => {
    const recent = [
      log('AUTH_LOGIN_FAILED', { actor_username: null }),
      log('AUTH_SESSION_REFRESHED'),
      log('AUTH_LOGIN_FAILED', { actor_username: null }),
      log('FILE_DOWNLOAD_AUTHORIZED', { actor_username: 'alice', resource_id: 'id-plan.pdf' }),
    ]
    const r = result(await runAccountCheck('recent-activity', {}, 'me', fakeApi([file('plan.pdf')], { recent })))
    expect(r.headline).toBe('2 failed sign-ins among your latest 3 events. If that was not you, change your password.')
    expect(r.rows.map((row) => row.text)).toEqual(['Sign-in failed', 'Sign-in failed', 'Downloaded plan.pdf by alice'])
    expect(r.links.map((l) => l.to)).toContain('/settings')
  })

  it('counts own files, shared files and the ones not seen yet', async () => {
    const files = [file('a'), file('b', { owner: false })]
    const r = result(await runAccountCheck('overview', {}, 'me', fakeApi(files, { unseen: ['id-b'] })))
    expect(r.headline).toBe('You have 1 file of your own and 1 shared with you.')
    expect(r.rows[r.rows.length - 1]).toMatchObject({ tone: 'new', text: '1 shared file you have not looked at yet' })
  })
})

describe('links to one file', () => {
  it('open the right tab, searched for its name', () => {
    expect(fileLink({ original_filename: 'a b&c.pdf', owner: true })).toBe('/files?q=a+b%26c.pdf')
    expect(fileLink({ original_filename: 'x.pdf', owner: false })).toBe('/files?q=x.pdf&tab=shared')
  })
})
