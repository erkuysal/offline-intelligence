<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  ArrowUpRight,
  CheckCircle2,
  CircleGauge,
  FileText,
  Files,
  LoaderCircle,
  Search,
  TriangleAlert,
  UploadCloud,
} from '@lucide/vue'

import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useDocumentsStore } from '@/stores/documents'
import type { DocumentRead } from '@/types/api'

const documents = useDocumentsStore()
const fileInput = ref<HTMLInputElement | null>(null)
const searchQuery = ref('')
const statusFilter = ref('all')
const draggingFile = ref(false)

const readyCount = computed(
  () => documents.items.filter(document => document.status === 'ready').length,
)
const processingCount = computed(
  () =>
    documents.items.filter(
      document => document.status === 'pending' || document.status === 'processing',
    ).length,
)
const failedCount = computed(
  () => documents.items.filter(document => document.status === 'failed').length,
)
const filteredDocuments = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return documents.items.filter(document => {
    const matchesQuery = !query || document.original_filename.toLocaleLowerCase().includes(query)
    const matchesStatus = statusFilter.value === 'all' || document.status === statusFilter.value
    return matchesQuery && matchesStatus
  })
})
onMounted(() => documents.fetchDocuments())

async function uploadFile(file: File | undefined) {
  if (!file) return
  try {
    await documents.upload(file)
  } catch {
    // The document store exposes a user-facing error.
  }
}

async function uploadSelected() {
  await uploadFile(fileInput.value?.files?.[0])
  if (fileInput.value) fileInput.value.value = ''
}

async function dropFile(event: DragEvent) {
  draggingFile.value = false
  await uploadFile(event.dataTransfer?.files?.[0])
}

function clearFilters() {
  searchQuery.value = ''
  statusFilter.value = 'all'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatUpdated(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function fileKind(document: DocumentRead): string {
  const extension = document.original_filename.split('.').pop()?.toUpperCase()
  return extension || document.content_type
}
</script>

<template>
  <section class="view-stack documents-view">
    <header class="view-header documents-header">
      <div>
        <p class="eyebrow">Knowledge workspace</p>
        <h1>Document corpus</h1>
        <p class="view-description">
          Manage the private sources used to ground local AI answers.
        </p>
      </div>
      <button
        class="primary-button"
        type="button"
        :disabled="documents.uploading"
        @click="fileInput?.click()"
      >
        <LoaderCircle v-if="documents.uploading" class="spin" :size="18" />
        <UploadCloud v-else :size="18" />
        {{ documents.uploading ? 'Uploading' : 'Upload document' }}
      </button>
    </header>

    <section class="corpus-overview" aria-label="Corpus summary">
      <article class="metric-card">
        <span class="metric-icon"><Files :size="20" /></span>
        <span><strong>{{ documents.items.length }}</strong><small>Total documents</small></span>
      </article>
      <article class="metric-card" data-tone="success">
        <span class="metric-icon"><CheckCircle2 :size="20" /></span>
        <span><strong>{{ readyCount }}</strong><small>Ready for retrieval</small></span>
      </article>
      <article class="metric-card" data-tone="warning">
        <span class="metric-icon"><CircleGauge :size="20" /></span>
        <span><strong>{{ processingCount }}</strong><small>Processing</small></span>
      </article>
      <article class="metric-card" data-tone="danger">
        <span class="metric-icon"><TriangleAlert :size="20" /></span>
        <span><strong>{{ failedCount }}</strong><small>Need attention</small></span>
      </article>
    </section>

    <section
      class="upload-dropzone"
      :class="{ dragging: draggingFile, uploading: documents.uploading }"
      aria-label="Document upload area"
      @dragenter.prevent="draggingFile = true"
      @dragover.prevent="draggingFile = true"
      @dragleave.prevent="draggingFile = false"
      @drop.prevent="dropFile"
    >
      <span class="upload-dropzone-icon">
        <LoaderCircle v-if="documents.uploading" class="spin" :size="22" />
        <UploadCloud v-else :size="22" />
      </span>
      <span class="upload-dropzone-copy">
        <strong>{{ documents.uploading ? 'Uploading and preparing document' : 'Drop a document here' }}</strong>
        <small>TXT, Markdown, PDF, or DOCX · 5 MB maximum</small>
      </span>
      <button
        class="secondary-button"
        type="button"
        :disabled="documents.uploading"
        @click="fileInput?.click()"
      >
        Choose file
      </button>
      <input
        ref="fileInput"
        class="visually-hidden"
        type="file"
        aria-label="Upload document"
        accept=".txt,.pdf,.md,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        :disabled="documents.uploading"
        @change="uploadSelected"
      />
    </section>

    <p v-if="documents.error" class="form-error alert-panel" role="alert">
      {{ documents.error }}
    </p>

    <section class="corpus-panel" aria-labelledby="corpus-list-heading">
      <div class="corpus-toolbar">
        <div>
          <h2 id="corpus-list-heading">Your documents</h2>
          <p>{{ filteredDocuments.length }} of {{ documents.items.length }} shown</p>
        </div>
        <div class="corpus-controls">
          <label class="search-control">
            <span class="visually-hidden">Search documents</span>
            <Search :size="17" aria-hidden="true" />
            <input v-model="searchQuery" type="search" placeholder="Search documents" />
          </label>
          <label class="filter-control">
            <span class="visually-hidden">Filter by status</span>
            <select v-model="statusFilter" aria-label="Filter by status">
              <option value="all">All statuses</option>
              <option value="ready">Ready</option>
              <option value="pending">Pending</option>
              <option value="processing">Processing</option>
              <option value="failed">Failed</option>
            </select>
          </label>
        </div>
      </div>

      <div v-if="documents.loading" class="document-skeleton-list" aria-label="Loading documents">
        <span v-for="index in 4" :key="index" class="document-skeleton" aria-hidden="true" />
      </div>

      <template v-else-if="documents.items.length">
        <div class="table-shell document-table-shell">
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Status</th>
                <th>Chunks</th>
                <th>Version</th>
                <th>Updated</th>
                <th><span class="visually-hidden">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="document in filteredDocuments" :key="document.id">
                <td>
                  <div class="document-name-cell">
                    <span class="file-type-icon"><FileText :size="19" /></span>
                    <span>
                      <strong>{{ document.original_filename }}</strong>
                      <small>{{ fileKind(document) }} · {{ formatBytes(document.size_bytes) }}</small>
                    </span>
                  </div>
                </td>
                <td>
                  <StatusBadge :status="document.status" />
                  <span v-if="document.ingestion_error" class="status-detail">
                    {{ document.ingestion_error }}
                  </span>
                </td>
                <td>{{ document.chunk_count }}</td>
                <td>v{{ document.version_number }}</td>
                <td>{{ formatUpdated(document.updated_at) }}</td>
                <td>
                  <RouterLink class="open-document-link" :to="`/documents/${document.id}`">
                    Open <ArrowUpRight :size="15" />
                  </RouterLink>
                </td>
              </tr>
              <tr v-if="filteredDocuments.length === 0">
                <td colspan="6" class="empty-cell">
                  No documents match the current search and status filter.
                  <button class="text-button" type="button" @click="clearFilters">Clear filters</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="document-card-list">
          <article v-for="document in filteredDocuments" :key="document.id" class="document-card">
            <header>
              <span class="file-type-icon"><FileText :size="19" /></span>
              <StatusBadge :status="document.status" />
            </header>
            <div>
              <h3>{{ document.original_filename }}</h3>
              <p>{{ fileKind(document) }} · {{ formatBytes(document.size_bytes) }}</p>
            </div>
            <dl>
              <div><dt>Chunks</dt><dd>{{ document.chunk_count }}</dd></div>
              <div><dt>Version</dt><dd>v{{ document.version_number }}</dd></div>
              <div><dt>Updated</dt><dd>{{ formatUpdated(document.updated_at) }}</dd></div>
            </dl>
            <RouterLink class="open-document-link" :to="`/documents/${document.id}`">
              Open document <ArrowUpRight :size="15" />
            </RouterLink>
          </article>
          <div v-if="filteredDocuments.length === 0" class="empty-corpus compact">
            <Search :size="24" />
            <strong>No matching documents</strong>
            <button class="text-button" type="button" @click="clearFilters">Clear filters</button>
          </div>
        </div>
      </template>

      <div v-else class="empty-corpus">
        <span class="empty-corpus-icon"><FileText :size="28" /></span>
        <h2>Build your private knowledge corpus</h2>
        <p>Upload a document to make its content available for grounded conversations.</p>
        <button class="primary-button" type="button" @click="fileInput?.click()">
          <UploadCloud :size="18" /> Upload your first document
        </button>
      </div>
    </section>
  </section>
</template>
