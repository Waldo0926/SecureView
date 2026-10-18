import { AxiosError, type AxiosResponse } from 'axios'
import { describe, expect, it } from 'vitest'

import { apiErrorCode, apiErrorMessage } from './http'

function refusedDownload(): AxiosError {
  const body = { success: false, message: 'The encrypted file could not be verified', data: { error_code: 'integrity_verification_failed', details: null } }
  const bytes = new TextEncoder().encode(JSON.stringify(body)).buffer
  const response = { status: 409, data: bytes, headers: {}, statusText: 'Conflict', config: {} } as unknown as AxiosResponse
  return new AxiosError('Request failed with status code 409', '409', undefined, undefined, response)
}

describe('a refused download, whose error body arrives as bytes', () => {
  it('still yields the server message and error code', () => {
    const error = refusedDownload()
    expect(apiErrorCode(error)).toBe('integrity_verification_failed')
    expect(apiErrorMessage(error, 'Download failed')).toBe('The encrypted file could not be verified')
  })
})
