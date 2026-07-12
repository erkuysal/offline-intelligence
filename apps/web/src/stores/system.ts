import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, ApiError, readableApiError } from '@/api/client'
import type { HealthResponse } from '@/types/api'

export type HealthKey = 'api' | 'database' | 'redis' | 'embedding' | 'worker' | 'llm'

const HEALTH_ENDPOINTS: Record<HealthKey, Parameters<typeof api.health>[0]> = {
  api: '/health',
  database: '/health/db',
  redis: '/health/redis',
  embedding: '/health/embedding',
  worker: '/health/worker',
  llm: '/health/llm',
}
const REFRESH_INTERVAL_MS = 15_000

export const useSystemStore = defineStore('system', () => {
  const health = ref<Record<HealthKey, HealthResponse | null>>({
    api: null,
    database: null,
    redis: null,
    embedding: null,
    worker: null,
    llm: null,
  })
  const loading = ref(false)
  const lastUpdated = ref<string | null>(null)
  let refreshTimer: number | null = null

  const unavailableCount = computed(
    () => Object.values(health.value).filter(service => service?.status === 'unavailable').length,
  )

  async function refresh() {
    if (loading.value) return
    loading.value = true
    try {
      const entries = await Promise.all(
        Object.entries(HEALTH_ENDPOINTS).map(async ([key, path]) => {
          const service = await fetchServiceHealth(key as HealthKey, path)
          return [key, service] as const
        }),
      )
      health.value = Object.fromEntries(entries) as Record<HealthKey, HealthResponse>
      lastUpdated.value = new Date().toISOString()
    } finally {
      loading.value = false
    }
  }

  function startAutoRefresh() {
    if (refreshTimer !== null) return
    void refresh()
    refreshTimer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS)
  }

  function stopAutoRefresh() {
    if (refreshTimer === null) return
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }

  return {
    health,
    loading,
    lastUpdated,
    unavailableCount,
    refresh,
    startAutoRefresh,
    stopAutoRefresh,
  }
})

async function fetchServiceHealth(
  key: HealthKey,
  path: Parameters<typeof api.health>[0],
): Promise<HealthResponse> {
  try {
    return await api.health(path)
  } catch (error) {
    if (error instanceof ApiError && isHealthResponse(error.detail)) return error.detail
    return {
      service: key,
      status: 'unavailable',
      detail: readableApiError(error, 'Health check failed'),
      code: error instanceof TypeError ? 'network_unavailable' : 'health_check_failed',
      checked_at: new Date().toISOString(),
      metadata: {},
    }
  }
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (!value || typeof value !== 'object') return false
  return (
    'service' in value &&
    typeof value.service === 'string' &&
    'status' in value &&
    typeof value.status === 'string' &&
    'detail' in value &&
    typeof value.detail === 'string'
  )
}
