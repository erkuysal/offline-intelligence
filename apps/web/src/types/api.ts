export interface UserRead {
  id: number
  email: string
  is_active: boolean
  is_verified: boolean
}

export interface CurrentUserRead extends UserRead {
  roles: string[]
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface DocumentRead {
  id: number
  owner_id: number
  original_filename: string
  content_type: string
  size_bytes: number
  checksum_sha256: string
  status: 'pending' | 'processing' | 'ready' | 'failed' | string
  chunk_count: number
  ingestion_error: string | null
  version_number: number
  created_at: string
  updated_at: string
}

export interface DocumentChunkRead {
  id: number
  document_id: number
  chunk_index: number
  content: string
  char_start: number
  char_end: number
  token_start: number
  token_end: number
  source_page: number | null
  source_label: string | null
  embedding_model: string | null
}

export interface DocumentVersionRead {
  id: number
  document_id: number
  version_number: number
  original_filename: string
  content_type: string
  size_bytes: number
  checksum_sha256: string
  created_at: string
}

export interface DocumentPermissionRead {
  id: number
  document_id: number
  user_id: number
  permission: 'read'
  created_at: string
}

export interface DocumentSearchResult {
  document_id: number
  document_filename: string
  chunk_id: number
  chunk_index: number
  content: string
  source_page: number | null
  source_label: string | null
  score: number
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface ChatCompletionRequest {
  model?: string | null
  messages: ChatMessage[]
  temperature?: number
  max_tokens?: number
  stream?: boolean
  use_documents?: boolean
  document_ids?: number[] | null
  retrieval_limit?: number | null
  retrieval_strategy?: 'dense' | 'lexical' | 'hybrid' | 'reranked' | 'multi_query' | null
  conversation_id?: number | null
}

export interface ChatSource {
  document_id: number
  document_filename: string
  chunk_id: number
  chunk_index: number
  source_page: number | null
  source_label: string | null
  content: string
  char_start: number
  char_end: number
  score: number
}

export interface ChatCompletionResponse {
  id: string
  object: 'chat.completion'
  created: number
  model: string
  choices: Array<{ index: number; message: ChatMessage; finish_reason: string }>
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null
  sources: ChatSource[] | null
  conversation_id: number | null
}

export interface ChatUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface ChatStreamComplete {
  conversation_id: number
  model: string
  usage: ChatUsage
}

export interface ChatStreamError {
  code: 'llm_timeout' | 'llm_unavailable' | 'llm_invalid_response' | string
  detail: string
  retryable: boolean
}

export interface ConversationRead {
  id: number
  owner_id: number
  title: string | null
  created_at: string
  updated_at: string
}

export interface ConversationSourceRead
  extends Omit<ChatSource, 'chunk_id' | 'content' | 'char_start' | 'char_end'> {
  id: number
  chunk_id: number | null
  content: string | null
  char_start: number | null
  char_end: number | null
  document_accessible: boolean
}

export interface ConversationMessageRead {
  id: number
  conversation_id: number
  role: string
  content: string
  model: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  sources: ConversationSourceRead[]
  created_at: string
}

export interface HealthResponse {
  service: string
  status: 'healthy' | 'degraded' | 'unavailable' | 'disabled'
  detail: string
  code: string | null
  checked_at: string
  metadata: Record<string, string | number | boolean | null>
}
