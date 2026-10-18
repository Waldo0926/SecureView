import { beforeEach, describe, expect, it, vi } from 'vitest'

const post = vi.fn()
const get = vi.fn()

vi.mock('./http', () => ({
  http: {
    post: (...args: unknown[]) => post(...args),
    get: (...args: unknown[]) => get(...args),
  },
}))

import { avatarApi } from './avatar_api'

describe('avatarApi', () => {
  beforeEach(() => {
    post.mockReset()
    get.mockReset()
  })

  it('uploads multipart to /auth/avatar/upload', async () => {
    post.mockResolvedValue({ data: { success: true } })
    const file = new Blob([new Uint8Array([0x89, 0x50])], { type: 'image/png' })
    await avatarApi.upload(file)
    expect(post).toHaveBeenCalledWith('/auth/avatar/upload', expect.any(FormData))
  })

  it('downloads avatar bytes', async () => {
    get.mockResolvedValue({ data: new ArrayBuffer(4) })
    await avatarApi.download()
    expect(get).toHaveBeenCalledWith('/auth/avatar', { responseType: 'arraybuffer' })
  })

  it('deletes the avatar', async () => {
    post.mockResolvedValue({ data: { success: true } })
    await avatarApi.delete()
    expect(post).toHaveBeenCalledWith('/auth/avatar/delete')
  })
})
