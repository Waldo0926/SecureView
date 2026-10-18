import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()

vi.mock('./http', () => ({
  http: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))

import { adminApi } from './admin_api'

describe('adminApi', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    get.mockResolvedValue({ data: { data: {} } })
    post.mockResolvedValue({ data: { data: {} } })
  })

  it('lists users with pagination params', async () => {
    await adminApi.listUsers({ limit: 25, offset: 50 })
    expect(get).toHaveBeenCalledWith('/admin/users', { params: { limit: 25, offset: 50 } })
  })

  it('reads the dashboard summary from /admin/stats with no parameters', async () => {
    await adminApi.stats()
    expect(get).toHaveBeenCalledWith('/admin/stats')
  })

  it('lists files with pagination params', async () => {
    await adminApi.listFiles({ limit: 10, offset: 0 })
    expect(get).toHaveBeenCalledWith('/admin/files', { params: { limit: 10, offset: 0 } })
  })

  it('disables a user by public id', async () => {
    await adminApi.disableUser('11111111-1111-4111-8111-111111111111')
    expect(post).toHaveBeenCalledWith(
      '/admin/users/11111111-1111-4111-8111-111111111111/disable',
    )
  })

  it('enables a user by public id', async () => {
    await adminApi.enableUser('22222222-2222-4222-8222-222222222222')
    expect(post).toHaveBeenCalledWith(
      '/admin/users/22222222-2222-4222-8222-222222222222/enable',
    )
  })
})
