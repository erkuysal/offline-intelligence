<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { FileText, Send, Square } from '@lucide/vue'

import { api, ChatStreamApiError, readableApiError } from '@/api/client'
import { useDocumentsStore } from '@/stores/documents'
import { useSessionStore } from '@/stores/session'
import type { ChatSource, ChatStreamComplete } from '@/types/api'

const session = useSessionStore()
const documents = useDocumentsStore()
const prompt = ref('')
const answer = ref('')
const submittedPrompt = ref('')
const sources = ref<ChatSource[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const result = ref<ChatStreamComplete | null>(null)
const generationState = ref<'idle' | 'generating' | 'completed' | 'cancelled' | 'failed'>('idle')
const grounded = ref(true)
const useAllDocuments = ref(true)
const selectedDocumentIds = ref<number[]>([])
let controller: AbortController | null = null

const readyDocuments = computed(() => documents.items.filter(document => document.status === 'ready'))
const needsDocumentSelection = computed(
  () => grounded.value && !useAllDocuments.value && selectedDocumentIds.value.length === 0,
)
const canSubmit = computed(
  () => Boolean(prompt.value.trim()) && !loading.value && !needsDocumentSelection.value,
)

onMounted(() => documents.fetchDocuments())

async function submit() {
  const content = prompt.value.trim()
  if (!session.accessToken || !content || loading.value) return
  if (needsDocumentSelection.value) {
    error.value = 'Select at least one ready document'
    return
  }
  loading.value = true
  generationState.value = 'generating'
  error.value = null
  answer.value = ''
  sources.value = []
  result.value = null
  submittedPrompt.value = content
  controller = new AbortController()
  try {
    await session.authorized(token =>
      api.streamChat(
        token,
        {
          messages: [{ role: 'user', content }],
          use_documents: grounded.value,
          document_ids:
            grounded.value && !useAllDocuments.value ? selectedDocumentIds.value : undefined,
        },
        {
          onToken: tokenContent => (answer.value += tokenContent),
          onSources: streamSources => (sources.value = streamSources),
          onComplete: completion => (result.value = completion),
        },
        controller?.signal,
      ),
    )
    generationState.value = 'completed'
    prompt.value = ''
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
  if (!controller) return
  controller.abort()
}
</script>

<template>
  <section class="chat-layout">
    <div class="conversation-panel">
      <div class="message-list" aria-live="polite">
        <div v-if="submittedPrompt" class="message user">{{ submittedPrompt }}</div>
        <div v-if="answer || loading" class="message assistant" :aria-busy="loading">
          {{ answer }}<span v-if="loading" class="stream-cursor" aria-hidden="true" />
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
    </div>
    <aside class="sources-panel">
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
            <p v-if="!documents.loading && readyDocuments.length === 0" class="muted-status">
              No ready documents
            </p>
          </div>
          <p v-if="needsDocumentSelection" class="selection-error">Select at least one document</p>
        </fieldset>
      </div>
      <h2>Sources</h2>
      <article v-for="source in sources" :key="source.chunk_id" class="source-item">
        <strong>{{ source.document_filename }}</strong>
        <span>{{ source.source_label ?? `Chunk ${source.chunk_index}` }}</span>
      </article>
    </aside>
  </section>
</template>
