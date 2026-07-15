<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  ArrowLeft,
  CalendarClock,
  ChevronDown,
  FileText,
  Hash,
  Layers3,
  RefreshCw,
  Trash2,
} from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

import { api, readableApiError } from '@/api/client'
import MarkdownContent from '@/components/content/MarkdownContent.vue'
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
const headingsByChunk = ref<Record<number, OutlineHeading[]>>({})
const activeOutlineId = ref('document-overview')
let pollTimer: number | null = null

interface OutlineHeading {
  id: string
  level: number
  text: string
}

const contentOutline = computed<OutlineHeading[]>(() => {
  const markdownHeadings = chunks.value.flatMap(chunk => headingsByChunk.value[chunk.id] ?? [])
  const contentItems = markdownHeadings.length
    ? markdownHeadings.map(heading => ({ ...heading, level: Math.min(heading.level + 1, 4) }))
    : chunks.value.map(chunk => ({
        id: `chunk-${chunk.id}`,
        level: 2,
        text: chunk.source_label ?? `Passage ${chunk.chunk_index + 1}`,
      }))

  return [
    { id: 'document-overview', level: 1, text: 'Overview' },
    { id: 'chunks-heading', level: 1, text: 'Indexed content' },
    ...contentItems,
  ]
})

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

function contentTypeLabel(contentType: string): string {
  const labels: Record<string, string> = {
    'application/pdf': 'PDF',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
    'text/markdown': 'Markdown',
    'text/plain': 'Plain text',
  }
  return labels[contentType] ?? contentType
}

function setChunkHeadings(chunkId: number, headings: OutlineHeading[]) {
  headingsByChunk.value = { ...headingsByChunk.value, [chunkId]: headings }
}

onMounted(loadDocument)
onUnmounted(() => {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
})
</script>

<template>
  <section class="view-stack document-detail-view">
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="muted-status">Loading document...</p>
    <RouterLink class="detail-back-link" to="/documents"><ArrowLeft :size="15" /> Back to corpus</RouterLink>
    <header v-if="document" id="document-overview" class="view-header document-detail-header">
      <div class="document-detail-title">
        <span class="document-detail-icon"><FileText :size="23" /></span>
        <div>
          <p class="eyebrow">Document reader</p>
          <h1>{{ document.original_filename }}</h1>
          <div class="document-detail-summary">
            <span><Layers3 :size="13" /> {{ document.chunk_count }} chunks</span>
            <span><FileText :size="13" /> {{ contentTypeLabel(document.content_type) }}</span>
            <span><CalendarClock :size="13" /> Updated {{ formatDate(document.updated_at) }}</span>
          </div>
        </div>
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

    <div v-if="document" class="document-reader-layout">
      <aside class="document-outline" aria-label="Document contents">
        <div class="document-outline-inner">
          <p class="eyebrow">Contents</p>
          <h2>On this page</h2>
          <nav>
            <a
              v-for="item in contentOutline"
              :key="item.id"
              :class="[`outline-level-${item.level}`, { active: activeOutlineId === item.id }]"
              :href="`#${item.id}`"
              :title="item.text"
              @click="activeOutlineId = item.id"
            >
              {{ item.text }}
            </a>
          </nav>
          <div class="document-outline-summary">
            <span>{{ chunks.length }} passages</span>
            <span>{{ versions.length }} {{ versions.length === 1 ? 'version' : 'versions' }}</span>
          </div>
        </div>
      </aside>

      <div class="document-reader-content">
        <section
          v-if="versions.length"
          class="detail-section version-section"
          aria-labelledby="versions-heading"
        >
          <details class="version-disclosure">
            <summary class="detail-section-heading">
              <div><p class="eyebrow">Provenance</p><h2 id="versions-heading">Version history</h2></div>
              <span class="disclosure-summary-meta">
                {{ versions.length }} {{ versions.length === 1 ? 'version' : 'versions' }}
                <ChevronDown :size="15" />
              </span>
            </summary>
            <div class="table-shell version-table-shell">
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
          </details>
        </section>

        <section class="detail-section chunk-section" aria-labelledby="chunks-heading">
          <div class="detail-section-heading">
            <div>
              <p class="eyebrow">Reading view</p>
              <h2 id="chunks-heading">Indexed chunks</h2>
              <p>Passages produced during ingestion and used for retrieval.</p>
            </div>
            <span>{{ chunks.length }} passages</span>
          </div>
          <div class="chunk-list">
            <article
              v-for="chunk in chunks"
              :id="`chunk-${chunk.id}`"
              :key="chunk.id"
              class="chunk-item"
              :aria-label="`Chunk ${chunk.chunk_index}`"
            >
              <header class="chunk-header">
                <div class="chunk-identity">
                  <span class="chunk-number"><Hash :size="13" />{{ chunk.chunk_index }}</span>
                  <span>
                    <strong>Indexed passage</strong>
                    <small>{{ chunk.source_label ?? `Page ${chunk.source_page ?? '-'}` }}</small>
                  </span>
                </div>
                <a class="chunk-anchor" :href="`#chunk-${chunk.id}`">Link to passage</a>
              </header>
              <MarkdownContent
                v-if="document?.content_type === 'text/markdown'"
                :content="chunk.content"
                :heading-prefix="`chunk-${chunk.id}`"
                @headings="setChunkHeadings(chunk.id, $event)"
              />
              <div v-else class="plain-chunk-content">{{ chunk.content }}</div>
              <details class="chunk-technical-details">
                <summary>
                  <span>Retrieval details</span>
                  <span>{{ chunk.token_end - chunk.token_start }} tokens <ChevronDown :size="14" /></span>
                </summary>
                <dl class="chunk-metadata">
                  <div><dt>Characters</dt><dd>{{ chunk.char_start }}–{{ chunk.char_end }}</dd></div>
                  <div><dt>Tokens</dt><dd>{{ chunk.token_start }}–{{ chunk.token_end }}</dd></div>
                  <div><dt>Embedding</dt><dd>{{ chunk.embedding_model ?? 'Not embedded' }}</dd></div>
                </dl>
              </details>
            </article>
            <p v-if="document?.status === 'ready' && chunks.length === 0" class="muted-status">
              No indexed chunks
            </p>
          </div>
        </section>
      </div>
    </div>

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
