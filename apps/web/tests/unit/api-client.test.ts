import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('adds bearer tokens to authenticated requests', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }))

    await api.documents('token-123')

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer token-123')
  })

  it('raises typed errors for failed requests', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Nope' }), { status: 401 }),
    )

    await expect(api.documents('bad-token')).rejects.toBeInstanceOf(ApiError)
  })
})
