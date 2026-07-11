<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/api/client'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useSessionStore } from '@/stores/session'
import type { DocumentChunkRead, DocumentRead } from '@/types/api'

const props = defineProps<{ id: number }>()
const session = useSessionStore()
const document = ref<DocumentRead | null>(null)
const chunks = ref<DocumentChunkRead[]>([])

onMounted(async () => {
  if (!session.accessToken) return
  document.value = await api.document(session.accessToken, props.id)
  chunks.value = await api.documentChunks(session.accessToken, props.id)
})
</script>

<template>
  <section class="view-stack">
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
