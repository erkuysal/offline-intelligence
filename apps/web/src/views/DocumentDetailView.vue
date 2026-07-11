<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api, readableApiError } from '@/api/client'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useSessionStore } from '@/stores/session'
import type { DocumentChunkRead, DocumentRead } from '@/types/api'

const props = defineProps<{ id: number }>()
const session = useSessionStore()
const document = ref<DocumentRead | null>(null)
const chunks = ref<DocumentChunkRead[]>([])
const error = ref<string | null>(null)

onMounted(async () => {
  if (!session.accessToken) return
  try {
    const [loadedDocument, loadedChunks] = await Promise.all([
      session.authorized(token => api.document(token, props.id)),
      session.authorized(token => api.documentChunks(token, props.id)),
    ])
    document.value = loadedDocument
    chunks.value = loadedChunks
  } catch (err) {
    error.value = readableApiError(err, 'Could not load document')
  }
})
</script>

<template>
  <section class="view-stack">
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <header v-if="document" class="view-header">
      <div>
        <p class="eyebrow">Document</p>
        <h1>{{ document.original_filename }}</h1>
      </div>
      <StatusBadge :status="document.status" />
    </header>

    <div class="chunk-list">
      <article v-for="chunk in chunks" :key="chunk.id" class="chunk-item">
        <header>Chunk {{ chunk.chunk_index }} <span>{{ chunk.source_label ?? `Page ${chunk.source_page ?? '-'}` }}</span></header>
        <p>{{ chunk.content }}</p>
      </article>
    </div>
  </section>
</template>
