<script setup lang="ts">
import { ref } from 'vue'
import { Send } from '@lucide/vue'

import { api } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import type { ChatSource } from '@/types/api'

const session = useSessionStore()
const prompt = ref('')
const answer = ref('')
const sources = ref<ChatSource[]>([])
const loading = ref(false)

async function submit() {
  if (!session.accessToken || !prompt.value.trim()) return
  loading.value = true
  try {
    const response = await api.chat(session.accessToken, {
      messages: [{ role: 'user', content: prompt.value }],
      use_documents: true,
      stream: false,
    })
    answer.value = response.choices[0]?.message.content ?? ''
    sources.value = response.sources ?? []
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="chat-layout">
    <div class="conversation-panel">
      <div v-if="answer" class="message assistant">{{ answer }}</div>
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
