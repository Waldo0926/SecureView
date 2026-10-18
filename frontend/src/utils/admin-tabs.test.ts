import { describe, expect, it } from 'vitest'

import { consoleTitle, defaultTab, tabFromQuery, tabGroupsFor } from './admin-tabs'

describe('admin console tabs', () => {
  it('gives an administrator all eight sections in three groups', () => {
    const groups = tabGroupsFor(true)
    expect(groups.map((g) => g.label)).toEqual(['Monitor', 'Manage', 'Recovery'])
    expect(groups.flatMap((g) => g.tabs.map((t) => t.id))).toEqual([
      'overview', 'agent', 'integrity', 'audit', 'users', 'files', 'recovery', 'recovery-key',
    ])
  })

  it('gives a recovery officer only the recovery queue', () => {
    const groups = tabGroupsFor(false)
    expect(groups).toHaveLength(1)
    expect(groups[0]!.tabs.map((t) => t.id)).toEqual(['recovery'])
    expect(defaultTab(false)).toBe('recovery')
    expect(defaultTab(true)).toBe('overview')
  })

  it('reads the tab from the URL only when the role may open it', () => {
    expect(tabFromQuery('agent', true)).toBe('agent')
    expect(tabFromQuery('agent', false)).toBe('recovery')
    expect(tabFromQuery('nonsense', true)).toBe('overview')
    expect(tabFromQuery(['agent'], true)).toBe('overview')
    expect(tabFromQuery(undefined, true)).toBe('overview')
  })

  it('names the page for the role', () => {
    expect(consoleTitle('ADMIN').title).toBe('Admin console')
    expect(consoleTitle('RECOVERY_OFFICER').title).toBe('Recovery review')
    expect(consoleTitle('USER').title).toBe('Recovery requests')
    expect(consoleTitle(undefined).title).toBe('Recovery requests')
  })
})
