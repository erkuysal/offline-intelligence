import { ref } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'
import type { HealthResponse } from '@/types/api'

type HealthKey = 'api' | 'database' | 'redis' | 'llm'

export const useSystemStore = defineStore('system', () => {
  const health = ref<Record<HealthKey, HealthResponse | null>>({
    api: null,
    database: null,
    redis: null,
    llm: null,
  })
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      const [apiHealth, dbHealth, redisHealth, llmHealth] = await Promise.all([
        api.health('/health'),
        api.health('/health/db'),
        api.health('/health/redis'),
        api.health('/health/llm'),
      ])
      health.value = { api: apiHealth, database: dbHealth, redis: redisHealth, llm: llmHealth }
    } finally {
      loading.value = false
    }
  }

  return { health, loading, refresh }
})
