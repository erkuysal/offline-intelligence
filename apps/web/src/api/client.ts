import type {
  ChatCompletionResponse,
  DocumentChunkRead,
  DocumentRead,
  HealthResponse,
  TokenPair,
  UserRead,
} from '@/types/api'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

export interface RequestOptions extends RequestInit {
  token?: string | null
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.token) headers.set('Authorization', `Bearer ${options.token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    let detail: unknown = null
    try {
      detail = await response.json()
    } catch {
      detail = await response.text()
    }
    throw new ApiError(`Request failed with ${response.status}`, response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  register(email: string, password: string) {
    return request<UserRead>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },
  login(email: string, password: string) {
    return request<TokenPair>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },
  refresh(refreshToken: string) {
    return request<TokenPair>('/api/v1/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
  },
  me(token: string) {
    return request<UserRead>('/api/v1/users/me', { token })
  },
  documents(token: string) {
    return request<DocumentRead[]>('/api/v1/documents', { token })
  },
  document(token: string, id: number) {
    return request<DocumentRead>(`/api/v1/documents/${id}`, { token })
  },
  documentChunks(token: string, id: number) {
    return request<DocumentChunkRead[]>(`/api/v1/documents/${id}/chunks`, { token })
  },
  uploadDocument(token: string, file: File) {
    const body = new FormData()
    body.set('file', file)
    return request<DocumentRead>('/api/v1/documents', { method: 'POST', token, body })
  },
  deleteDocument(token: string, id: number) {
    return request<void>(`/api/v1/documents/${id}`, { method: 'DELETE', token })
  },
  chat(token: string, payload: Record<string, unknown>) {
    return request<ChatCompletionResponse>('/api/v1/chat/completions', {
      method: 'POST',
      token,
      body: JSON.stringify(payload),
    })
  },
  health(path: '/health' | '/health/db' | '/health/redis' | '/health/llm') {
    return request<HealthResponse>(path)
  },
}
