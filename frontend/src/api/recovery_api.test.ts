import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()

vi.mock('./http', () => ({
  http: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))

import { recoveryApi } from './recovery_api'

describe('recoveryApi', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    get.mockResolvedValue({ data: { data: {} } })
    post.mockResolvedValue({ data: { data: {} } })
  })

  it('fetches the active recovery public key', async () => {
    await recoveryApi.getPublicKey()
    expect(get).toHaveBeenCalledWith('/recovery/public-key')
  })

  it('registers a recovery public key', async () => {
    await recoveryApi.registerPublicKey({
      key_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      public_key_pem: '-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----\n',
    })
    expect(post).toHaveBeenCalledWith('/recovery/public-key/register', {
      algorithm: 'RSA-OAEP-SHA256',
      key_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      public_key_pem: '-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----\n',
    })
  })

  it('revokes a recovery public key', async () => {
    await recoveryApi.revokePublicKey('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
    expect(post).toHaveBeenCalledWith(
      '/recovery/public-key/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/revoke',
    )
  })

  it('creates a recovery request', async () => {
    const payload = {
      file_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      reason: 'Lost passphrase',
      target_key_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    }
    await recoveryApi.createRequest(payload)
    expect(post).toHaveBeenCalledWith('/recovery/request', payload)
  })

  it('approves, rejects, cancels, and executes by request id', async () => {
    const id = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
    await recoveryApi.approve(id)
    expect(post).toHaveBeenCalledWith(`/recovery/${id}/approve`)

    await recoveryApi.reject(id, 'Not justified')
    expect(post).toHaveBeenCalledWith(`/recovery/${id}/reject`, {
      rejection_reason: 'Not justified',
    })

    await recoveryApi.cancel(id)
    expect(post).toHaveBeenCalledWith(`/recovery/${id}/cancel`)

    await recoveryApi.execute(id, {
      wrapped_file_key: 'AAAA',
      recovery_key_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      target_key_id: '00000000-0000-4000-8000-000000000001',
    })
    expect(post).toHaveBeenCalledWith(`/recovery/${id}/execute`, {
      wrapped_file_key: 'AAAA',
      recovery_key_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      target_key_id: '00000000-0000-4000-8000-000000000001',
    })
  })

  it('loads an execution package and lists requests', async () => {
    const id = '11111111-1111-4111-8111-111111111111'
    await recoveryApi.getExecutionPackage(id)
    expect(get).toHaveBeenCalledWith(`/recovery/${id}/execution-package`)

    await recoveryApi.listRequests({ page: 2, page_size: 25 })
    expect(get).toHaveBeenCalledWith('/recovery/requests', {
      params: { page: 2, page_size: 25 },
    })
  })
})
