<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Upload } from '@lucide/vue'

import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useDocumentsStore } from '@/stores/documents'

const documents = useDocumentsStore()
const fileInput = ref<HTMLInputElement | null>(null)

onMounted(() => documents.fetchDocuments())

async function uploadSelected() {
  const file = fileInput.value?.files?.[0]
  if (file) await documents.upload(file)
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
      <label class="file-button">
        <Upload :size="18" /> Upload
        <input
          ref="fileInput"
          type="file"
          accept=".txt,.pdf,.md,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          @change="uploadSelected"
        />
      </label>
    </header>

    <p v-if="documents.error" class="form-error" role="alert">{{ documents.error }}</p>

    <div class="table-shell">
      <table>
        <thead><tr><th>Name</th><th>Status</th><th>Chunks</th><th>Version</th><th></th></tr></thead>
        <tbody>
          <tr v-for="document in documents.items" :key="document.id">
            <td>{{ document.original_filename }}</td>
            <td><StatusBadge :status="document.status" /></td>
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
