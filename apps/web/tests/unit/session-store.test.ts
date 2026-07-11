import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const tokenPair = {
  access_token: 'fresh-access',
  refresh_token: 'fresh-refresh',
  token_type: 'bearer',
}

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('refreshes once and retries a request rejected with 401', async () => {
    seedSession()
    const store = useSessionStore()
    vi.spyOn(api, 'refresh').mockResolvedValue(tokenPair)
    const operation = vi.fn(async (token: string) => {
      if (token === 'expired-access') throw unauthorized()
      return token
    })

    await expect(store.authorized(operation)).resolves.toBe('fresh-access')

    expect(api.refresh).toHaveBeenCalledOnce()
    expect(operation).toHaveBeenCalledTimes(2)
    expect(sessionStorage.getItem('offlineHub.accessToken')).toBe('fresh-access')
    expect(sessionStorage.getItem('offlineHub.refreshToken')).toBe('fresh-refresh')
  })

  it('deduplicates concurrent refresh attempts', async () => {
    seedSession()
    const store = useSessionStore()
    let releaseRefresh!: (tokens: typeof tokenPair) => void
    const refreshPromise = new Promise<typeof tokenPair>(resolve => {
      releaseRefresh = resolve
    })
    vi.spyOn(api, 'refresh').mockReturnValue(refreshPromise)
    const operation = vi.fn(async (token: string) => {
      if (token === 'expired-access') throw unauthorized()
      return token
    })

    const requests = Promise.all([store.authorized(operation), store.authorized(operation)])
    await vi.waitFor(() => expect(api.refresh).toHaveBeenCalledOnce())
    releaseRefresh(tokenPair)

    await expect(requests).resolves.toEqual(['fresh-access', 'fresh-access'])
    expect(api.refresh).toHaveBeenCalledOnce()
  })

  it('clears browser credentials when refresh fails', async () => {
    seedSession()
    const store = useSessionStore()
    vi.spyOn(api, 'refresh').mockRejectedValue(unauthorized())

    await expect(store.authorized(async () => Promise.reject(unauthorized()))).rejects.toBeInstanceOf(
      ApiError,
    )

    expect(store.isAuthenticated).toBe(false)
    expect(sessionStorage.getItem('offlineHub.accessToken')).toBeNull()
    expect(sessionStorage.getItem('offlineHub.refreshToken')).toBeNull()
  })
})

function seedSession() {
  sessionStorage.setItem('offlineHub.accessToken', 'expired-access')
  sessionStorage.setItem('offlineHub.refreshToken', 'valid-refresh')
}

function unauthorized() {
  return new ApiError('Request failed with 401', 401, { detail: 'Invalid access token' })
}
