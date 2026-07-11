import { ref } from 'vue'
import { defineStore } from 'pinia'

import { api, readableApiError } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import type { DocumentRead } from '@/types/api'

export const useDocumentsStore = defineStore('documents', () => {
  const items = ref<DocumentRead[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchDocuments() {
    const session = useSessionStore()
    if (!session.accessToken) return
    loading.value = true
    error.value = null
    try {
      items.value = await session.authorized(token => api.documents(token))
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
    try {
      await session.authorized(token => api.uploadDocument(token, file))
      await fetchDocuments()
    } catch (err) {
      error.value = readableApiError(err, 'Could not upload document')
      throw err
    }
  }

  return { items, loading, error, fetchDocuments, upload }
})
