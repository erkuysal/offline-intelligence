import { ref } from 'vue'
import { defineStore } from 'pinia'

import { api, readableApiError } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import type { DocumentRead } from '@/types/api'

const MAX_UPLOAD_SIZE_BYTES = Number(import.meta.env.VITE_MAX_UPLOAD_SIZE_BYTES ?? 5 * 1024 * 1024)
const INGESTION_POLL_INTERVAL_MS = 1_000
const INGESTION_POLL_ATTEMPTS = 60
const SUPPORTED_UPLOADS = new Map([
  ['.txt', 'text/plain'],
  ['.md', 'text/markdown'],
  ['.pdf', 'application/pdf'],
  ['.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
])

export const useDocumentsStore = defineStore('documents', () => {
  const items = ref<DocumentRead[]>([])
  const loading = ref(false)
  const uploading = ref(false)
  const error = ref<string | null>(null)
  const pollingIds = new Set<number>()

  async function fetchDocuments() {
    const session = useSessionStore()
    if (!session.accessToken) return
    loading.value = true
    error.value = null
    try {
      items.value = await session.authorized(token => api.documents(token))
      for (const document of items.value) {
        if (isIngestionActive(document.status)) void pollDocument(document.id)
      }
    } catch (err) {
      error.value = readableApiError(err, 'Could not load documents')
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File) {
    const session = useSessionStore()
    if (!session.accessToken) return
    error.value = null
    const validationError = validateDocumentFile(file)
    if (validationError) {
      error.value = validationError
      return
    }
    uploading.value = true
    try {
      const document = await session.authorized(token => api.uploadDocument(token, file))
      upsertDocument(document)
      if (isIngestionActive(document.status)) void pollDocument(document.id)
    } catch (err) {
      error.value = readableApiError(err, 'Could not upload document')
      throw err
    } finally {
      uploading.value = false
    }
  }

  async function pollDocument(documentId: number) {
    if (pollingIds.has(documentId)) return
    const session = useSessionStore()
    if (!session.accessToken) return
    pollingIds.add(documentId)
    try {
      for (let attempt = 0; attempt < INGESTION_POLL_ATTEMPTS; attempt += 1) {
        await delay(INGESTION_POLL_INTERVAL_MS)
        const document = await session.authorized(token => api.document(token, documentId))
        upsertDocument(document)
        if (!isIngestionActive(document.status)) return
      }
      error.value = 'Document processing is taking longer than expected. Refresh to check again.'
    } catch (err) {
      error.value = readableApiError(err, 'Could not refresh document status')
    } finally {
      pollingIds.delete(documentId)
    }
  }

  function upsertDocument(document: DocumentRead) {
    const existingIndex = items.value.findIndex(item => item.id === document.id)
    if (existingIndex === -1) {
      items.value.unshift(document)
    } else {
      items.value[existingIndex] = document
    }
  }

  return { items, loading, uploading, error, fetchDocuments, upload, pollDocument }
})

export function validateDocumentFile(file: File): string | null {
  const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  const expectedType = SUPPORTED_UPLOADS.get(suffix)
  if (!expectedType) return 'Choose a TXT, Markdown, PDF, or DOCX file'
  if (file.type !== expectedType) return 'File extension does not match its content type'
  if (file.size === 0) return 'File is empty'
  if (file.size > MAX_UPLOAD_SIZE_BYTES) return 'File exceeds the 5 MB upload limit'
  return null
}

function isIngestionActive(status: string): boolean {
  return status === 'pending' || status === 'processing'
}

function delay(milliseconds: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds))
}
