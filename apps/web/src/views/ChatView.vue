<script setup lang="ts">
import { ref } from 'vue'
import { Send } from '@lucide/vue'

import { api, readableApiError } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import type { ChatSource } from '@/types/api'

const session = useSessionStore()
const prompt = ref('')
const answer = ref('')
const sources = ref<ChatSource[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

async function submit() {
  if (!session.accessToken || !prompt.value.trim()) return
  loading.value = true
  error.value = null
  try {
    const response = await session.authorized(token =>
      api.chat(token, {
        messages: [{ role: 'user', content: prompt.value }],
        use_documents: true,
        stream: false,
      }),
    )
    answer.value = response.choices[0]?.message.content ?? ''
    sources.value = response.sources ?? []
  } catch (err) {
    error.value = readableApiError(err, 'Could not generate an answer')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="chat-layout">
    <div class="conversation-panel">
      <div v-if="answer" class="message assistant">{{ answer }}</div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <form class="composer" @submit.prevent="submit">
        <textarea v-model="prompt" rows="4" placeholder="Ask a question" />
        <button class="primary-button" type="submit" :disabled="loading"><Send :size="18" /> Send</button>
      </form>
    </div>
    <aside class="sources-panel">
      <h2>Sources</h2>
      <article v-for="source in sources" :key="source.chunk_id" class="source-item">
        <strong>{{ source.document_filename }}</strong>
        <span>{{ source.source_label ?? `Chunk ${source.chunk_index}` }}</span>
      </article>
    </aside>
  </section>
</template>
