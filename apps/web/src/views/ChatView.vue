<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  ArrowUpRight,
  Bot,
  BookOpen,
  Clock3,
  Database,
  FileSearch,
  FileText,
  LoaderCircle,
  MessageSquarePlus,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  UserRound,
} from '@lucide/vue'
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
const currentConversation = computed(
  () => conversations.value.find(conversation => conversation.id === currentConversationId.value) ?? null,
)
const groundingSummary = computed(() => {
  if (!grounded.value) return 'General conversation'
  if (useAllDocuments.value) return `${readyDocuments.value.length} ready documents`
  return `${selectedDocumentIds.value.length} selected documents`
})
const suggestedPrompts = [
  'Summarize the most important policies in my documents.',
  'What information is missing or ambiguous in the available sources?',
  'Create a concise action list from the relevant documents.',
]

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

function useSuggestion(suggestion: string) {
  prompt.value = suggestion
}

function formatConversationTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
  }).format(new Date(value))
}
</script>

<template>
  <section class="chat-workspace">
    <header class="chat-page-header">
      <div>
        <p class="eyebrow">Grounded workspace</p>
        <h1>Chat with your knowledge</h1>
      </div>
      <div class="chat-context-summary">
        <span :data-active="grounded">
          <ShieldCheck v-if="grounded" :size="15" />
          <Sparkles v-else :size="15" />
          {{ groundingSummary }}
        </span>
      </div>
    </header>

    <div class="chat-layout">
      <aside class="history-panel" aria-labelledby="history-heading">
        <header class="panel-heading">
          <div>
            <p class="panel-eyebrow">Workspace</p>
            <h2 id="history-heading">Conversations</h2>
          </div>
          <button
            class="icon-button"
            type="button"
            title="New conversation"
            aria-label="New conversation"
            @click="startNewConversation()"
          >
            <MessageSquarePlus :size="18" />
          </button>
        </header>
        <button class="new-conversation-button" type="button" @click="startNewConversation()">
          <MessageSquarePlus :size="17" /> New conversation
        </button>
        <nav class="conversation-list" aria-label="Conversation history">
          <div v-for="conversation in conversations" :key="conversation.id" class="conversation-row">
            <button
              class="conversation-link"
              :class="{ active: currentConversationId === conversation.id }"
              type="button"
              @click="selectConversation(conversation.id)"
            >
              <span>{{ conversation.title || 'Untitled conversation' }}</span>
              <small><Clock3 :size="11" /> {{ formatConversationTime(conversation.updated_at) }}</small>
            </button>
            <button
              class="icon-button conversation-delete"
              type="button"
              title="Delete conversation"
              aria-label="Delete conversation"
              @click="confirmDelete(conversation)"
            >
              <Trash2 :size="15" />
            </button>
          </div>
          <div v-if="conversations.length === 0" class="history-empty">
            <MessageSquarePlus :size="22" />
            <strong>No saved conversations</strong>
            <span>Your grounded chats will appear here.</span>
          </div>
        </nav>
      </aside>

      <section class="conversation-panel" aria-label="Conversation">
        <header class="conversation-header">
          <div class="assistant-identity">
            <span class="assistant-avatar"><Bot :size="19" /></span>
            <span>
              <strong>{{ currentConversation?.title || 'Local knowledge assistant' }}</strong>
              <small><span class="online-dot" /> Ready on this device</small>
            </span>
          </div>
          <span class="conversation-security"><ShieldCheck :size="14" /> Private session</span>
        </header>

        <div v-if="loadingConversation" class="conversation-loading" aria-live="polite">
          <LoaderCircle class="spin" :size="18" /> Loading conversation
        </div>

        <div class="message-list" aria-live="polite">
          <section v-if="messages.length === 0 && !loadingConversation" class="chat-empty-state">
            <span class="chat-empty-icon"><Sparkles :size="26" /></span>
            <h2>Ask your private knowledge base</h2>
            <p>
              Answers can use only the document scope you select, with inspectable source passages.
            </p>
            <div class="suggestion-grid" aria-label="Suggested questions">
              <button
                v-for="suggestion in suggestedPrompts"
                :key="suggestion"
                type="button"
                @click="useSuggestion(suggestion)"
              >
                <BookOpen :size="16" />
                <span>{{ suggestion }}</span>
              </button>
            </div>
          </section>

          <article
            v-for="(message, index) in messages"
            :key="message.key"
            class="message"
            :class="message.role"
            :aria-label="`${message.role === 'assistant' ? 'Assistant' : 'User'} message`"
            :aria-busy="loading && index === messages.length - 1"
          >
            <span class="message-avatar" aria-hidden="true">
              <Bot v-if="message.role === 'assistant'" :size="17" />
              <UserRound v-else :size="17" />
            </span>
            <div class="message-body">
              <header>
                <strong>{{ message.role === 'assistant' ? 'Assistant' : 'You' }}</strong>
                <span v-if="message.model">{{ message.model }}</span>
              </header>
              <div class="message-content">
                {{ message.content }}<span
                  v-if="loading && index === messages.length - 1"
                  class="stream-cursor"
                  aria-hidden="true"
                />
                <span
                  v-if="loading && index === messages.length - 1 && !message.content"
                  class="thinking-dots"
                  aria-label="Generating answer"
                ><i /><i /><i /></span>
              </div>
              <footer v-if="message.role === 'assistant' && message.sources.length">
                <span v-if="message.sources.length"><BookOpen :size="13" /> {{ message.sources.length }} sources</span>
              </footer>
            </div>
          </article>
        </div>

        <div class="conversation-footer">
          <div v-if="generationState !== 'idle'" class="generation-status" aria-live="polite">
            <span class="generation-state" :data-state="generationState">
              <span class="generation-dot" /> {{ generationState }}
            </span>
            <span v-if="result">{{ result.model }}</span>
            <span v-if="result">{{ result.usage.total_tokens }} tokens</span>
          </div>
          <p v-if="error" class="form-error chat-error" role="alert">{{ error }}</p>
          <form class="composer" @submit.prevent="submit">
            <textarea
              v-model="prompt"
              rows="3"
              placeholder="Ask a question"
              aria-label="Ask a question"
              :disabled="loading"
            />
            <div class="composer-footer">
              <span class="composer-context">
                <Database v-if="grounded" :size="14" />
                <Sparkles v-else :size="14" />
                {{ groundingSummary }}
              </span>
              <div class="composer-actions">
                <button v-if="loading" class="secondary-button" type="button" @click="stop">
                  <Square :size="15" fill="currentColor" /> Stop
                </button>
                <button class="primary-button send-button" type="submit" :disabled="!canSubmit">
                  <Send :size="17" /> Send
                </button>
              </div>
            </div>
          </form>
          <p class="composer-hint">Responses stay local. Verify important information in the cited source.</p>
        </div>
      </section>

      <aside class="sources-panel" aria-labelledby="sources-heading">
        <div class="grounding-controls">
          <div class="panel-heading">
            <div>
              <p class="panel-eyebrow">Retrieval</p>
              <h2>Grounding</h2>
            </div>
            <Database :size="18" />
          </div>
          <label class="toggle-control">
            <span>
              <strong>Document grounding</strong>
              <small>Answer from accessible sources</small>
            </span>
            <input v-model="grounded" type="checkbox" :disabled="loading" />
          </label>
          <fieldset v-if="grounded" class="document-scope" :disabled="loading || documents.loading">
            <legend>Retrieval scope</legend>
            <label class="check-control scope-all-control">
              <input v-model="useAllDocuments" type="checkbox" />
              <span>
                <strong>All ready documents</strong>
                <small>{{ readyDocuments.length }} available</small>
              </span>
            </label>
            <div v-if="!useAllDocuments" class="document-options">
              <label v-for="document in readyDocuments" :key="document.id" class="check-control">
                <input v-model="selectedDocumentIds" type="checkbox" :value="document.id" />
                <FileText :size="16" />
                <span>{{ document.original_filename }}</span>
              </label>
              <p v-if="!documents.loading && readyDocuments.length === 0" class="muted-status">
                No ready documents
              </p>
            </div>
            <p v-if="needsDocumentSelection" class="selection-error">Select at least one document</p>
          </fieldset>
        </div>

        <div class="sources-heading-row">
          <div>
            <p class="panel-eyebrow">Evidence</p>
            <h2 id="sources-heading">Sources</h2>
          </div>
          <span>{{ activeSources.length }}</span>
        </div>

        <div v-if="activeSources.length === 0" class="sources-empty">
          <FileSearch :size="23" />
          <strong>No sources yet</strong>
          <p>Source passages from the latest grounded answer will appear here.</p>
        </div>

        <article
          v-for="(source, sourceIndex) in activeSources"
          :key="`${source.document_id}-${source.chunk_index}`"
          class="source-item"
          :aria-label="`Source: ${source.document_filename}`"
        >
          <header>
            <span class="source-number">{{ sourceIndex + 1 }}</span>
            <div>
              <strong>{{ source.document_filename }}</strong>
              <small>{{ source.source_label ?? `Chunk ${source.chunk_index}` }}</small>
            </div>
          </header>
          <div class="source-metadata">
            <span v-if="source.source_page !== null">Page {{ source.source_page }}</span>
            <span>Score {{ source.score.toFixed(3) }}</span>
          </div>
          <p v-if="source.content">{{ source.content }}</p>
          <RouterLink
            v-if="sourceAccessible(source) && source.chunk_id !== null"
            :to="`/documents/${source.document_id}#chunk-${source.chunk_id}`"
          >
            Open passage <ArrowUpRight :size="14" />
          </RouterLink>
          <span v-else class="source-unavailable">Document unavailable</span>
        </article>
      </aside>
    </div>

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
