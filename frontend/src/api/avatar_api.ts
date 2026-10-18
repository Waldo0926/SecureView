import { http } from './http'
import type { ApiEnvelope } from './types'

export interface AvatarMetaOut {
  has_avatar: boolean
  content_type: string | null
  updated_at: string | null
  size_bytes: number | null
}

export const avatarApi = {
  /** Upload a PNG or JPEG. Replaces any existing picture. */
  upload(file: File | Blob) {
    const form = new FormData()
    form.append('file', file)
    return http.post<ApiEnvelope<AvatarMetaOut>>('/auth/avatar/upload', form)
  },

  /** Raw image bytes for the signed-in account. Caller builds an object URL. */
  download() {
    return http.get<ArrayBuffer>('/auth/avatar', { responseType: 'arraybuffer' })
  },

  delete() {
    return http.post<ApiEnvelope<AvatarMetaOut>>('/auth/avatar/delete')
  },
}
