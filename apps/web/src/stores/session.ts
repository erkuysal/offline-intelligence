import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, ApiError, readableApiError } from '@/api/client'
import type { CurrentUserRead } from '@/types/api'

const ACCESS_TOKEN_KEY = 'offlineHub.accessToken'
const REFRESH_TOKEN_KEY = 'offlineHub.refreshToken'

export const useSessionStore = defineStore('session', () => {
  const accessToken = ref<string | null>(sessionStorage.getItem(ACCESS_TOKEN_KEY))
  const refreshToken = ref<string | null>(sessionStorage.getItem(REFRESH_TOKEN_KEY))
  const user = ref<CurrentUserRead | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let refreshInFlight: Promise<string> | null = null

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

  function expireSession() {
    clear()
    window.dispatchEvent(new Event('offlineHub:session-expired'))
  }

  async function refreshAccessToken(): Promise<string> {
    if (!refreshToken.value) {
      expireSession()
      throw new Error('Session expired')
    }
    if (!refreshInFlight) {
      refreshInFlight = api
        .refresh(refreshToken.value)
        .then(tokens => {
          setTokens(tokens.access_token, tokens.refresh_token)
          return tokens.access_token
        })
        .catch(err => {
          expireSession()
          throw err
        })
        .finally(() => {
          refreshInFlight = null
        })
    }
    return refreshInFlight
  }

  async function authorized<T>(operation: (token: string) => Promise<T>): Promise<T> {
    if (!accessToken.value) throw new Error('Authentication required')
    const attemptedToken = accessToken.value
    try {
      return await operation(attemptedToken)
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 401) throw err
    }

    const token = accessToken.value !== attemptedToken ? accessToken.value : await refreshAccessToken()
    if (!token) throw new Error('Authentication required')
    try {
      return await operation(token)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) expireSession()
      throw err
    }
  }

  async function login(email: string, password: string) {
    loading.value = true
    error.value = null
    try {
      const tokens = await api.login(email, password)
      setTokens(tokens.access_token, tokens.refresh_token)
      user.value = await api.me(tokens.access_token)
    } catch (err) {
      clear()
      error.value = readableApiError(err, 'Login failed')
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
      const tokens = await api.login(email, password)
      setTokens(tokens.access_token, tokens.refresh_token)
      user.value = await api.me(tokens.access_token)
    } catch (err) {
      clear()
      error.value = readableApiError(err, 'Registration failed')
      throw err
    } finally {
      loading.value = false
    }
  }

  async function loadUser() {
    if (!accessToken.value) return
    try {
      user.value = await authorized(token => api.me(token))
    } catch {
      clear()
    }
  }

  return {
    accessToken,
    refreshToken,
    user,
    loading,
    error,
    isAuthenticated,
    login,
    register,
    loadUser,
    authorized,
    clear,
  }
})
