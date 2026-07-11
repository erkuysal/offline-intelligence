import { ref } from 'vue'
import { defineStore } from 'pinia'

import { api } from '@/api/client'
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
      items.value = await api.documents(session.accessToken)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Could not load documents'
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File) {
    const session = useSessionStore()
    if (!session.accessToken) return
    await api.uploadDocument(session.accessToken, file)
    await fetchDocuments()
  }

  return { items, loading, error, fetchDocuments, upload }
})
