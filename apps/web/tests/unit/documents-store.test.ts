import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useDocumentsStore, validateDocumentFile } from '@/stores/documents'
import type { DocumentRead } from '@/types/api'

describe('document file validation', () => {
  it('accepts supported files within the upload limit', () => {
    const file = new File(['backup policy'], 'backup-policy.txt', { type: 'text/plain' })

    expect(validateDocumentFile(file)).toBeNull()
  })

  it('rejects unsupported extensions and mismatched content types', () => {
    expect(validateDocumentFile(new File(['data'], 'policy.csv', { type: 'text/csv' }))).toContain(
      'TXT',
    )
    expect(validateDocumentFile(new File(['data'], 'policy.pdf', { type: 'text/plain' }))).toContain(
      'does not match',
    )
  })

  it('rejects empty and oversized files', () => {
    expect(validateDocumentFile(new File([], 'empty.txt', { type: 'text/plain' }))).toBe('File is empty')
    const oversized = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'large.txt', {
      type: 'text/plain',
    })

    expect(validateDocumentFile(oversized)).toContain('5 MB')
  })
})

describe('documents store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    sessionStorage.setItem('offlineHub.accessToken', 'access-token')
    sessionStorage.setItem('offlineHub.refreshToken', 'refresh-token')
    vi.restoreAllMocks()
    vi.useFakeTimers()
  })

  it('polls an asynchronously ingested document until it is ready', async () => {
    const pending = documentFixture('pending')
    const ready = documentFixture('ready')
    vi.spyOn(api, 'uploadDocument').mockResolvedValue(pending)
    vi.spyOn(api, 'document').mockResolvedValue(ready)
    const store = useDocumentsStore()

    await store.upload(new File(['backup policy'], 'backup-policy.txt', { type: 'text/plain' }))
    expect(store.items[0]?.status).toBe('pending')

    await vi.advanceTimersByTimeAsync(1_000)
    await vi.waitFor(() => expect(store.items[0]?.status).toBe('ready'))
    expect(api.document).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })
})

function documentFixture(status: string): DocumentRead {
  return {
    id: 1,
    owner_id: 1,
    original_filename: 'backup-policy.txt',
    content_type: 'text/plain',
    size_bytes: 13,
    checksum_sha256: 'abc123',
    status,
    chunk_count: status === 'ready' ? 1 : 0,
    ingestion_error: null,
    version_number: 1,
    created_at: '2026-07-11T00:00:00Z',
    updated_at: '2026-07-11T00:00:00Z',
  }
}
