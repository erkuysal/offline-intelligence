import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from '@/api/client'
import { useSystemStore } from '@/stores/system'
import type { HealthResponse } from '@/types/api'

describe('system store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('keeps healthy services when another service returns structured 503', async () => {
    vi.spyOn(api, 'health').mockImplementation(async path => {
      if (path === '/health/redis') {
        const failure = healthFixture('redis', 'unavailable', 'Redis connection failed')
        throw new ApiError('503', 503, failure)
      }
      if (path === '/health/embedding') throw new TypeError('network failed')
      return healthFixture(path.split('/').at(-1) || 'api', 'healthy', 'Ready')
    })
    const store = useSystemStore()

    await store.refresh()

    expect(store.health.api?.status).toBe('healthy')
    expect(store.health.redis).toMatchObject({
      status: 'unavailable',
      detail: 'Redis connection failed',
    })
    expect(store.health.embedding).toMatchObject({
      status: 'unavailable',
      code: 'network_unavailable',
      detail: 'Unable to reach the API',
    })
    expect(store.unavailableCount).toBe(2)
    expect(store.lastUpdated).not.toBeNull()
  })

  it('starts one refresh interval and stops it cleanly', async () => {
    vi.useFakeTimers()
    const health = vi.spyOn(api, 'health').mockResolvedValue(healthFixture('api', 'healthy', 'Ready'))
    const store = useSystemStore()

    store.startAutoRefresh()
    store.startAutoRefresh()
    await vi.waitFor(() => expect(health).toHaveBeenCalledTimes(6))
    await vi.advanceTimersByTimeAsync(15_000)
    await vi.waitFor(() => expect(health).toHaveBeenCalledTimes(12))
    store.stopAutoRefresh()
    await vi.advanceTimersByTimeAsync(30_000)

    expect(health).toHaveBeenCalledTimes(12)
    vi.useRealTimers()
  })
})

function healthFixture(
  service: string,
  status: HealthResponse['status'],
  detail: string,
): HealthResponse {
  return {
    service,
    status,
    detail,
    code: status === 'unavailable' ? `${service}_unavailable` : null,
    checked_at: '2026-07-13T00:00:00Z',
    metadata: {},
  }
}
