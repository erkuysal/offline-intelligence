<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

import { api, readableApiError } from '@/api/client'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useSessionStore } from '@/stores/session'
import type { DocumentChunkRead, DocumentRead } from '@/types/api'

const props = defineProps<{ id: number }>()
const session = useSessionStore()
const document = ref<DocumentRead | null>(null)
const chunks = ref<DocumentChunkRead[]>([])
const error = ref<string | null>(null)
const loading = ref(true)
let pollTimer: number | null = null

async function loadDocument() {
  if (!session.accessToken) return
  try {
    const loadedDocument = await session.authorized(token => api.document(token, props.id))
    document.value = loadedDocument
    chunks.value =
      loadedDocument.status === 'ready'
        ? await session.authorized(token => api.documentChunks(token, props.id))
        : []
    if (loadedDocument.status === 'pending' || loadedDocument.status === 'processing') {
      pollTimer = window.setTimeout(() => void loadDocument(), 1_000)
    }
  } catch (err) {
    error.value = readableApiError(err, 'Could not load document')
  } finally {
    loading.value = false
  }
}

onMounted(loadDocument)
onUnmounted(() => {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
})
</script>

<template>
  <section class="view-stack">
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="muted-status">Loading document...</p>
    <header v-if="document" class="view-header">
      <div>
        <p class="eyebrow">Document</p>
        <h1>{{ document.original_filename }}</h1>
      </div>
      <StatusBadge :status="document.status" />
    </header>

    <p v-if="document?.status === 'failed'" class="form-error" role="alert">
      {{ document.ingestion_error ?? 'Document processing failed' }}
    </p>
    <p v-else-if="document && document.status !== 'ready'" class="muted-status" aria-live="polite">
      Document is {{ document.status }}. This view updates automatically.
    </p>

    <div class="chunk-list">
      <article v-for="chunk in chunks" :key="chunk.id" class="chunk-item">
        <header>Chunk {{ chunk.chunk_index }} <span>{{ chunk.source_label ?? `Page ${chunk.source_page ?? '-'}` }}</span></header>
        <p>{{ chunk.content }}</p>
      </article>
    </div>
  </section>
</template>
