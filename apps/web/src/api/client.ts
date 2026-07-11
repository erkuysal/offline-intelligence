import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
  ConversationMessageRead,
  ConversationRead,
  CurrentUserRead,
  DocumentChunkRead,
  DocumentPermissionRead,
  DocumentRead,
  DocumentSearchResult,
  DocumentVersionRead,
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

export function readableApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === 'string') return error.detail
    if (error.detail && typeof error.detail === 'object' && 'detail' in error.detail) {
      return String(error.detail.detail)
    }
    if (error.status === 403) return 'You do not have permission to perform this action'
    return fallback
  }
  if (error instanceof TypeError) return 'Unable to reach the API'
  return fallback
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
    return request<CurrentUserRead>('/api/v1/users/me', { token })
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
  documentVersions(token: string, id: number) {
    return request<DocumentVersionRead[]>(`/api/v1/documents/${id}/versions`, { token })
  },
  documentPermissions(token: string, id: number) {
    return request<DocumentPermissionRead[]>(`/api/v1/documents/${id}/permissions`, { token })
  },
  grantDocumentPermission(token: string, id: number, userEmail: string) {
    return request<DocumentPermissionRead>(`/api/v1/documents/${id}/permissions`, {
      method: 'POST',
      token,
      body: JSON.stringify({ user_email: userEmail, permission: 'read' }),
    })
  },
  searchDocuments(token: string, query: string, limit = 5) {
    return request<DocumentSearchResult[]>('/api/v1/documents/search', {
      method: 'POST',
      token,
      body: JSON.stringify({ query, limit }),
    })
  },
  uploadDocument(token: string, file: File) {
    const body = new FormData()
    body.set('file', file)
    return request<DocumentRead>('/api/v1/documents', { method: 'POST', token, body })
  },
  deleteDocument(token: string, id: number) {
    return request<void>(`/api/v1/documents/${id}`, { method: 'DELETE', token })
  },
  chat(token: string, payload: ChatCompletionRequest) {
    return request<ChatCompletionResponse>('/api/v1/chat/completions', {
      method: 'POST',
      token,
      body: JSON.stringify(payload),
    })
  },
  conversations(token: string) {
    return request<ConversationRead[]>('/api/v1/chat/conversations', { token })
  },
  conversationMessages(token: string, id: number) {
    return request<ConversationMessageRead[]>(`/api/v1/chat/conversations/${id}/messages`, { token })
  },
  health(path: '/health' | '/health/db' | '/health/redis' | '/health/llm') {
    return request<HealthResponse>(path)
  },
}
