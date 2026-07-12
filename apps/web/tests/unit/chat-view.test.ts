import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import ChatView from '@/views/ChatView.vue'

describe('ChatView streaming', () => {
  beforeEach(() => {
    sessionStorage.clear()
    sessionStorage.setItem('offlineHub.accessToken', 'access-token')
    sessionStorage.setItem('offlineHub.refreshToken', 'refresh-token')
    vi.restoreAllMocks()
    vi.spyOn(api, 'documents').mockResolvedValue([
      documentFixture(1, 'policy.txt', 'ready'),
      documentFixture(2, 'notes.md', 'ready'),
      documentFixture(3, 'draft.txt', 'processing'),
    ])
  })

  it('stops generation, preserves partial output, and prevents overlap', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const stream = vi.spyOn(api, 'streamChat').mockImplementation(
      async (_token, _payload, handlers, signal) => {
        handlers.onToken('Partial answer')
        await new Promise<void>((_resolve, reject) => {
          signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        })
      },
    )
    const wrapper = mount(ChatView, { global: { plugins: [pinia] } })

    await wrapper.get('textarea').setValue('Question one')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Partial answer'))

    expect(wrapper.get('button.primary-button').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit')
    expect(stream).toHaveBeenCalledOnce()

    await wrapper.get('button.secondary-button').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('cancelled'))
    expect(wrapper.text()).toContain('Partial answer')
  })

  it('sends ungrounded and selected-document retrieval modes', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const stream = vi.spyOn(api, 'streamChat').mockResolvedValue(undefined)
    const wrapper = mount(ChatView, { global: { plugins: [pinia] } })
    await flushPromises()

    await checkboxFor(wrapper, 'All ready documents').setValue(false)
    expect(wrapper.text()).toContain('policy.txt')
    expect(wrapper.text()).toContain('notes.md')
    expect(wrapper.text()).not.toContain('draft.txt')

    await checkboxFor(wrapper, 'Document grounding').setValue(false)
    await wrapper.get('textarea').setValue('Ungrounded question')
    await wrapper.get('form').trigger('submit')
    expect(stream.mock.calls[0]?.[1]).toMatchObject({ use_documents: false })
    expect(stream.mock.calls[0]?.[1].document_ids).toBeUndefined()
    wrapper.unmount()

    const selectedPinia = createPinia()
    setActivePinia(selectedPinia)
    const selectedWrapper = mount(ChatView, { global: { plugins: [selectedPinia] } })
    await flushPromises()
    await checkboxFor(selectedWrapper, 'All ready documents').setValue(false)
    await checkboxFor(selectedWrapper, 'policy.txt').setValue(true)
    await selectedWrapper.get('textarea').setValue('Grounded question')
    await selectedWrapper.get('form').trigger('submit')

    expect(stream.mock.calls[1]?.[1]).toMatchObject({
      use_documents: true,
      document_ids: [1],
    })
  })
})

function checkboxFor(wrapper: VueWrapper, label: string) {
  const control = wrapper.findAll('label').find(candidate => candidate.text().includes(label))
  if (!control) throw new Error(`Missing checkbox: ${label}`)
  return control.get('input[type="checkbox"]')
}

function documentFixture(id: number, originalFilename: string, status: string) {
  return {
    id,
    owner_id: 1,
    original_filename: originalFilename,
    content_type: 'text/plain',
    size_bytes: 12,
    checksum_sha256: `checksum-${id}`,
    status,
    chunk_count: status === 'ready' ? 1 : 0,
    ingestion_error: null,
    version_number: 1,
    created_at: '2026-07-12T00:00:00Z',
    updated_at: '2026-07-12T00:00:00Z',
  }
}
