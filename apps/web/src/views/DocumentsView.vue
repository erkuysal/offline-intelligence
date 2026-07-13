<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { LoaderCircle, Upload } from '@lucide/vue'

import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useDocumentsStore } from '@/stores/documents'

const documents = useDocumentsStore()
const fileInput = ref<HTMLInputElement | null>(null)

onMounted(() => documents.fetchDocuments())

async function uploadSelected() {
  const file = fileInput.value?.files?.[0]
  if (file) {
    try {
      await documents.upload(file)
    } catch {
      // The document store exposes a user-facing error.
    }
  }
  if (fileInput.value) fileInput.value.value = ''
}
</script>

<template>
  <section class="view-stack">
    <header class="view-header">
      <div>
        <p class="eyebrow">Documents</p>
        <h1>Corpus</h1>
      </div>
      <div class="upload-actions">
        <button
          class="file-button"
          type="button"
          :disabled="documents.uploading"
          @click="fileInput?.click()"
        >
          <LoaderCircle v-if="documents.uploading" class="spin" :size="18" />
          <Upload v-else :size="18" />
          {{ documents.uploading ? 'Uploading' : 'Upload' }}
        </button>
        <span>TXT, MD, PDF, DOCX | 5 MB max</span>
        <input
          ref="fileInput"
          class="visually-hidden"
          type="file"
          aria-label="Upload document"
          accept=".txt,.pdf,.md,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          :disabled="documents.uploading"
          @change="uploadSelected"
        />
      </div>
    </header>

    <p v-if="documents.error" class="form-error" role="alert">{{ documents.error }}</p>

    <div class="table-shell">
      <table>
        <thead><tr><th>Name</th><th>Status</th><th>Chunks</th><th>Version</th><th></th></tr></thead>
        <tbody>
          <tr v-for="document in documents.items" :key="document.id">
            <td>{{ document.original_filename }}</td>
            <td>
              <StatusBadge :status="document.status" />
              <span v-if="document.ingestion_error" class="status-detail">{{ document.ingestion_error }}</span>
            </td>
            <td>{{ document.chunk_count }}</td>
            <td>{{ document.version_number }}</td>
            <td><RouterLink :to="`/documents/${document.id}`">Open</RouterLink></td>
          </tr>
          <tr v-if="!documents.loading && documents.items.length === 0">
            <td colspan="5" class="empty-cell">No documents</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
