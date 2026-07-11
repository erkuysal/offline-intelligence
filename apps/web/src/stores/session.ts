import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, ApiError } from '@/api/client'
import type { UserRead } from '@/types/api'

const ACCESS_TOKEN_KEY = 'offlineHub.accessToken'
const REFRESH_TOKEN_KEY = 'offlineHub.refreshToken'

export const useSessionStore = defineStore('session', () => {
  const accessToken = ref<string | null>(sessionStorage.getItem(ACCESS_TOKEN_KEY))
  const refreshToken = ref<string | null>(sessionStorage.getItem(REFRESH_TOKEN_KEY))
  const user = ref<UserRead | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => Boolean(accessToken.value))

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    refreshToken.value = refresh
    sessionStorage.setItem(ACCESS_TOKEN_KEY, access)
    sessionStorage.setItem(REFRESH_TOKEN_KEY, refresh)
  }

  function clear() {
    accessToken.value = null
    refreshToken.value = null
    user.value = null
    sessionStorage.removeItem(ACCESS_TOKEN_KEY)
    sessionStorage.removeItem(REFRESH_TOKEN_KEY)
  }

  async function login(email: string, password: string) {
    loading.value = true
    error.value = null
    try {
      const tokens = await api.login(email, password)
      setTokens(tokens.access_token, tokens.refresh_token)
      user.value = await api.me(tokens.access_token)
    } catch (err) {
      error.value = err instanceof ApiError ? readableDetail(err.detail) : 'Login failed'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function register(email: string, password: string) {
    loading.value = true
    error.value = null
    try {
      await api.register(email, password)
      await login(email, password)
    } finally {
      loading.value = false
    }
  }

  async function loadUser() {
    if (!accessToken.value) return
    try {
      user.value = await api.me(accessToken.value)
    } catch {
      clear()
    }
  }

  return { accessToken, refreshToken, user, loading, error, isAuthenticated, login, register, loadUser, clear }
})

function readableDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'detail' in detail) return String(detail.detail)
  return 'Authentication failed'
}
