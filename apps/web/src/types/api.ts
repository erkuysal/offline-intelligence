export interface UserRead {
  id: number
  email: string
  is_active: boolean
  is_verified: boolean
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

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface ChatSource {
  document_id: number
  document_filename: string
  chunk_id: number
  chunk_index: number
  source_page: number | null
  source_label: string | null
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

export interface HealthResponse {
  status: string
  [key: string]: string
}
