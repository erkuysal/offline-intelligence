<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw, Trash2 } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

import { api, readableApiError } from '@/api/client'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useSessionStore } from '@/stores/session'
import type { DocumentChunkRead, DocumentRead, DocumentVersionRead } from '@/types/api'

const props = defineProps<{ id: number }>()
const session = useSessionStore()
const router = useRouter()
const route = useRoute()
const document = ref<DocumentRead | null>(null)
const chunks = ref<DocumentChunkRead[]>([])
const versions = ref<DocumentVersionRead[]>([])
const error = ref<string | null>(null)
const loading = ref(true)
const actionLoading = ref(false)
const deleteDialog = ref<HTMLDialogElement | null>(null)
let pollTimer: number | null = null

async function loadDocument() {
  if (!session.accessToken) return
  try {
    const loadedDocument = await session.authorized(token => api.document(token, props.id))
    document.value = loadedDocument
    const [loadedChunks, loadedVersions] = await Promise.all([
      loadedDocument.status === 'ready'
        ? session.authorized(token => api.documentChunks(token, props.id))
        : Promise.resolve([]),
      session.authorized(token => api.documentVersions(token, props.id)),
    ])
    chunks.value = loadedChunks
    versions.value = loadedVersions
    if (/^#chunk-\d+$/.test(route.hash)) {
      await nextTick()
      globalThis.document.querySelector(route.hash)?.scrollIntoView({ block: 'center' })
    }
    if (loadedDocument.status === 'pending' || loadedDocument.status === 'processing') {
      pollTimer = window.setTimeout(() => void loadDocument(), 1_000)
    }
  } catch (err) {
    error.value = readableApiError(err, 'Could not load document')
  } finally {
    loading.value = false
  }
}

async function reindexDocument() {
  if (!session.accessToken || !document.value) return
  actionLoading.value = true
  error.value = null
  try {
    document.value = await session.authorized(token => api.reindexDocument(token, props.id))
    chunks.value = []
    if (document.value.status === 'pending' || document.value.status === 'processing') {
      pollTimer = window.setTimeout(() => void loadDocument(), 1_000)
    } else {
      await loadDocument()
    }
  } catch (err) {
    error.value = readableApiError(err, 'Could not reindex document')
  } finally {
    actionLoading.value = false
  }
}

async function deleteDocument() {
  if (!session.accessToken || !document.value) return
  actionLoading.value = true
  error.value = null
  try {
    await session.authorized(token => api.deleteDocument(token, props.id))
    deleteDialog.value?.close()
    await router.push({ name: 'documents' })
  } catch (err) {
    error.value = readableApiError(err, 'Could not delete document')
  } finally {
    actionLoading.value = false
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )
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
      <div class="header-actions">
        <StatusBadge :status="document.status" />
        <template v-if="session.user?.id === document.owner_id">
          <button
            class="secondary-button"
            type="button"
            :disabled="actionLoading || document.status === 'pending' || document.status === 'processing'"
            title="Reindex document"
            @click="reindexDocument"
          >
            <RefreshCw :size="17" /> Reindex
          </button>
          <button
            class="danger-button"
            type="button"
            :disabled="actionLoading"
            title="Delete document"
            @click="deleteDialog?.showModal()"
          >
            <Trash2 :size="17" /> Delete
          </button>
        </template>
      </div>
    </header>

    <p v-if="document?.status === 'failed'" class="form-error" role="alert">
      {{ document.ingestion_error ?? 'Document processing failed' }}
    </p>
    <p v-else-if="document && document.status !== 'ready'" class="muted-status" aria-live="polite">
      Document is {{ document.status }}. This view updates automatically.
    </p>

    <section v-if="versions.length" class="detail-section" aria-labelledby="versions-heading">
      <h2 id="versions-heading">Version history</h2>
      <div class="table-shell">
        <table>
          <thead><tr><th>Version</th><th>Uploaded</th><th>Size</th><th>Checksum</th></tr></thead>
          <tbody>
            <tr v-for="version in versions" :key="version.id">
              <td>v{{ version.version_number }}</td>
              <td>{{ formatDate(version.created_at) }}</td>
              <td>{{ formatBytes(version.size_bytes) }}</td>
              <td class="checksum">{{ version.checksum_sha256 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="detail-section" aria-labelledby="chunks-heading">
      <h2 id="chunks-heading">Indexed chunks</h2>
      <div class="chunk-list">
        <article
          v-for="chunk in chunks"
          :id="`chunk-${chunk.id}`"
          :key="chunk.id"
          class="chunk-item"
          :aria-label="`Chunk ${chunk.chunk_index}`"
        >
          <header>
            <span>Chunk {{ chunk.chunk_index }}</span>
            <span>{{ chunk.source_label ?? `Page ${chunk.source_page ?? '-'}` }}</span>
          </header>
          <small>Characters {{ chunk.char_start }}-{{ chunk.char_end }} | Tokens {{ chunk.token_start }}-{{ chunk.token_end }} | {{ chunk.embedding_model ?? 'Not embedded' }}</small>
          <p>{{ chunk.content }}</p>
        </article>
        <p v-if="document?.status === 'ready' && chunks.length === 0" class="muted-status">No indexed chunks</p>
      </div>
    </section>

    <dialog ref="deleteDialog" class="confirm-dialog" aria-labelledby="delete-dialog-title">
      <form method="dialog" @submit.prevent>
        <h2 id="delete-dialog-title">Delete document?</h2>
        <p>This permanently removes every version, indexed chunk, and stored file.</p>
        <div class="dialog-actions">
          <button class="secondary-button" type="button" :disabled="actionLoading" @click="deleteDialog?.close()">
            Cancel
          </button>
          <button class="danger-button" type="button" :disabled="actionLoading" @click="deleteDocument">
            <Trash2 :size="17" /> Delete permanently
          </button>
        </div>
      </form>
    </dialog>
  </section>
</template>
