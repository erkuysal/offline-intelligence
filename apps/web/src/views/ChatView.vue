<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { FileText, MessageSquarePlus, Send, Square, Trash2 } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

import { api, ChatStreamApiError, readableApiError } from '@/api/client'
import { useDocumentsStore } from '@/stores/documents'
import { useSessionStore } from '@/stores/session'
import type {
  ChatMessage,
  ChatSource,
  ChatStreamComplete,
  ConversationMessageRead,
  ConversationRead,
  ConversationSourceRead,
} from '@/types/api'

type DisplaySource = ChatSource | ConversationSourceRead
interface DisplayMessage {
  key: string
  role: 'user' | 'assistant'
  content: string
  sources: DisplaySource[]
  model: string | null
  totalTokens: number | null
}

const session = useSessionStore()
const documents = useDocumentsStore()
const route = useRoute()
const router = useRouter()
const prompt = ref('')
const messages = ref<DisplayMessage[]>([])
const conversations = ref<ConversationRead[]>([])
const currentConversationId = ref<number | null>(null)
const loading = ref(false)
const loadingConversation = ref(false)
const error = ref<string | null>(null)
const result = ref<ChatStreamComplete | null>(null)
const generationState = ref<'idle' | 'generating' | 'completed' | 'cancelled' | 'failed'>('idle')
const grounded = ref(true)
const useAllDocuments = ref(true)
const selectedDocumentIds = ref<number[]>([])
const deleteDialog = ref<HTMLDialogElement | null>(null)
const pendingDelete = ref<ConversationRead | null>(null)
let controller: AbortController | null = null

const readyDocuments = computed(() => documents.items.filter(document => document.status === 'ready'))
const needsDocumentSelection = computed(
  () => grounded.value && !useAllDocuments.value && selectedDocumentIds.value.length === 0,
)
const canSubmit = computed(
  () => Boolean(prompt.value.trim()) && !loading.value && !needsDocumentSelection.value,
)
const activeSources = computed(
  () => [...messages.value].reverse().find(message => message.role === 'assistant')?.sources ?? [],
)

onMounted(async () => {
  await Promise.all([documents.fetchDocuments(), loadConversations()])
  await restoreRouteConversation()
})

watch(
  () => route.query.conversation,
  () => void restoreRouteConversation(),
)

async function loadConversations() {
  if (!session.accessToken) return
  try {
    conversations.value = await session.authorized(token => api.conversations(token))
  } catch (err) {
    error.value = readableApiError(err, 'Could not load conversations')
  }
}

async function restoreRouteConversation() {
  const rawId = Array.isArray(route.query.conversation)
    ? route.query.conversation[0]
    : route.query.conversation
  const conversationId = rawId ? Number(rawId) : null
  if (!conversationId || !Number.isInteger(conversationId)) {
    if (currentConversationId.value !== null) startNewConversation(false)
    return
  }
  if (conversationId === currentConversationId.value && messages.value.length > 0) return
  await loadConversation(conversationId)
}

async function loadConversation(conversationId: number) {
  if (!session.accessToken || loading.value) return
  loadingConversation.value = true
  error.value = null
  try {
    const persisted = await session.authorized(token => api.conversationMessages(token, conversationId))
    messages.value = persisted.flatMap(toDisplayMessage)
    currentConversationId.value = conversationId
    generationState.value = 'idle'
    result.value = null
  } catch (err) {
    error.value = readableApiError(err, 'Could not load conversation')
    await router.replace({ name: 'chat' })
  } finally {
    loadingConversation.value = false
  }
}

function toDisplayMessage(message: ConversationMessageRead): DisplayMessage[] {
  if (message.role !== 'user' && message.role !== 'assistant') return []
  return [{
    key: `persisted-${message.id}`,
    role: message.role,
    content: message.content,
    sources: message.sources,
    model: message.model,
    totalTokens: message.total_tokens,
  }]
}

async function selectConversation(conversationId: number) {
  if (loading.value) return
  await router.push({ name: 'chat', query: { conversation: String(conversationId) } })
}

function startNewConversation(updateRoute = true) {
  if (loading.value) return
  currentConversationId.value = null
  messages.value = []
  result.value = null
  generationState.value = 'idle'
  error.value = null
  if (updateRoute) void router.push({ name: 'chat' })
}

async function submit() {
  const content = prompt.value.trim()
  if (!session.accessToken || !content || loading.value) return
  if (needsDocumentSelection.value) {
    error.value = 'Select at least one ready document'
    return
  }
  const requestMessages: ChatMessage[] = messages.value.map(message => ({
    role: message.role,
    content: message.content,
  }))
  requestMessages.push({ role: 'user', content })
  messages.value.push({
    key: `user-${Date.now()}`,
    role: 'user',
    content,
    sources: [],
    model: null,
    totalTokens: null,
  })
  const assistantIndex = messages.value.push({
    key: `assistant-${Date.now()}`,
    role: 'assistant',
    content: '',
    sources: [],
    model: null,
    totalTokens: null,
  }) - 1
  loading.value = true
  generationState.value = 'generating'
  error.value = null
  result.value = null
  controller = new AbortController()
  try {
    await session.authorized(token =>
      api.streamChat(
        token,
        {
          messages: requestMessages,
          use_documents: grounded.value,
          document_ids:
            grounded.value && !useAllDocuments.value ? selectedDocumentIds.value : undefined,
          conversation_id: currentConversationId.value ?? undefined,
        },
        {
          onToken: tokenContent => (messages.value[assistantIndex]!.content += tokenContent),
          onSources: sources => (messages.value[assistantIndex]!.sources = sources),
          onComplete: completion => {
            result.value = completion
            messages.value[assistantIndex]!.model = completion.model
            messages.value[assistantIndex]!.totalTokens = completion.usage.total_tokens
          },
        },
        controller?.signal,
      ),
    )
    generationState.value = 'completed'
    prompt.value = ''
    const completion = result.value as ChatStreamComplete | null
    if (completion) {
      currentConversationId.value = completion.conversation_id
      await router.replace({ name: 'chat', query: { conversation: String(completion.conversation_id) } })
      await loadConversations()
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      generationState.value = 'cancelled'
    } else {
      generationState.value = 'failed'
      error.value =
        err instanceof ChatStreamApiError
          ? err.detail.detail
          : readableApiError(err, err instanceof Error ? err.message : 'Could not generate an answer')
    }
  } finally {
    controller = null
    loading.value = false
  }
}

function stop() {
  controller?.abort()
}

function confirmDelete(conversation: ConversationRead) {
  pendingDelete.value = conversation
  deleteDialog.value?.showModal()
}

async function deleteConversation() {
  if (!session.accessToken || !pendingDelete.value) return
  const conversationId = pendingDelete.value.id
  try {
    await session.authorized(token => api.deleteConversation(token, conversationId))
    deleteDialog.value?.close()
    pendingDelete.value = null
    if (currentConversationId.value === conversationId) startNewConversation()
    await loadConversations()
  } catch (err) {
    error.value = readableApiError(err, 'Could not delete conversation')
  }
}

function sourceAccessible(source: DisplaySource): boolean {
  return !('document_accessible' in source) || source.document_accessible
}
</script>

<template>
  <section class="chat-layout">
    <aside class="history-panel" aria-labelledby="history-heading">
      <header>
        <h2 id="history-heading">Conversations</h2>
        <button class="icon-button" type="button" title="New conversation" aria-label="New conversation" @click="startNewConversation()">
          <MessageSquarePlus :size="18" />
        </button>
      </header>
      <nav class="conversation-list" aria-label="Conversation history">
        <div v-for="conversation in conversations" :key="conversation.id" class="conversation-row">
          <button
            class="conversation-link"
            :class="{ active: currentConversationId === conversation.id }"
            type="button"
            @click="selectConversation(conversation.id)"
          >
            {{ conversation.title || 'Untitled conversation' }}
          </button>
          <button
            class="icon-button"
            type="button"
            title="Delete conversation"
            aria-label="Delete conversation"
            @click="confirmDelete(conversation)"
          >
            <Trash2 :size="16" />
          </button>
        </div>
        <p v-if="conversations.length === 0" class="muted-status">No conversations</p>
      </nav>
    </aside>

    <section class="conversation-panel" aria-label="Conversation">
      <p v-if="loadingConversation" class="muted-status">Loading conversation...</p>
      <div class="message-list" aria-live="polite">
        <div
          v-for="(message, index) in messages"
          :key="message.key"
          class="message"
          :class="message.role"
          role="article"
          :aria-label="`${message.role === 'assistant' ? 'Assistant' : 'User'} message`"
          :aria-busy="loading && index === messages.length - 1"
        >
          {{ message.content }}<span v-if="loading && index === messages.length - 1" class="stream-cursor" aria-hidden="true" />
        </div>
      </div>
      <div v-if="generationState !== 'idle'" class="generation-status" aria-live="polite">
        <span>{{ generationState }}</span>
        <span v-if="result">{{ result.model }}</span>
        <span v-if="result">{{ result.usage.total_tokens }} tokens</span>
      </div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <form class="composer" @submit.prevent="submit">
        <textarea v-model="prompt" rows="4" placeholder="Ask a question" :disabled="loading" />
        <div class="composer-actions">
          <button v-if="loading" class="secondary-button" type="button" @click="stop">
            <Square :size="16" fill="currentColor" /> Stop
          </button>
          <button class="primary-button" type="submit" :disabled="!canSubmit">
            <Send :size="18" /> Send
          </button>
        </div>
      </form>
    </section>

    <aside class="sources-panel" aria-labelledby="sources-heading">
      <div class="grounding-controls">
        <label class="toggle-control">
          <input v-model="grounded" type="checkbox" :disabled="loading" />
          <span>Document grounding</span>
        </label>
        <fieldset v-if="grounded" class="document-scope" :disabled="loading || documents.loading">
          <legend>Retrieval scope</legend>
          <label class="check-control">
            <input v-model="useAllDocuments" type="checkbox" />
            <span>All ready documents</span>
          </label>
          <div v-if="!useAllDocuments" class="document-options">
            <label v-for="document in readyDocuments" :key="document.id" class="check-control">
              <input v-model="selectedDocumentIds" type="checkbox" :value="document.id" />
              <FileText :size="16" />
              <span>{{ document.original_filename }}</span>
            </label>
            <p v-if="!documents.loading && readyDocuments.length === 0" class="muted-status">No ready documents</p>
          </div>
          <p v-if="needsDocumentSelection" class="selection-error">Select at least one document</p>
        </fieldset>
      </div>
      <h2 id="sources-heading">Sources</h2>
      <article
        v-for="source in activeSources"
        :key="`${source.document_id}-${source.chunk_index}`"
        class="source-item"
        :aria-label="`Source: ${source.document_filename}`"
      >
        <strong>{{ source.document_filename }}</strong>
        <span>{{ source.source_label ?? `Chunk ${source.chunk_index}` }}</span>
        <span v-if="source.source_page !== null">Page {{ source.source_page }}</span>
        <span>Score {{ source.score.toFixed(3) }}</span>
        <p v-if="source.content">{{ source.content }}</p>
        <RouterLink
          v-if="sourceAccessible(source) && source.chunk_id !== null"
          :to="`/documents/${source.document_id}#chunk-${source.chunk_id}`"
        >
          Open passage
        </RouterLink>
        <span v-else class="source-unavailable">Document unavailable</span>
      </article>
    </aside>

    <dialog ref="deleteDialog" class="confirm-dialog" aria-labelledby="delete-conversation-title">
      <form method="dialog" @submit.prevent>
        <h2 id="delete-conversation-title">Delete conversation?</h2>
        <p>This permanently removes the conversation and its saved citations.</p>
        <div class="dialog-actions">
          <button class="secondary-button" type="button" @click="deleteDialog?.close()">Cancel</button>
          <button class="danger-button" type="button" @click="deleteConversation">
            <Trash2 :size="17" /> Delete permanently
          </button>
        </div>
      </form>
    </dialog>
  </section>
</template>
