import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
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
    vi.spyOn(api, 'conversations').mockResolvedValue([])
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
    const wrapper = await mountChat(pinia)

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
    const wrapper = await mountChat(pinia)
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
    const selectedWrapper = await mountChat(selectedPinia)
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

  it('restores a routed conversation and renders authorized citation details', async () => {
    vi.mocked(api.conversations).mockResolvedValue([
      {
        id: 7,
        owner_id: 1,
        title: 'Backup policy',
        created_at: '2026-07-12T00:00:00Z',
        updated_at: '2026-07-12T00:00:00Z',
      },
    ])
    vi.spyOn(api, 'conversationMessages').mockResolvedValue([
      messageFixture(1, 'user', 'When are backups run?', []),
      messageFixture(2, 'assistant', 'Backups run nightly.', [
        {
          id: 9,
          document_id: 101,
          document_filename: 'policy.txt',
          chunk_id: 501,
          chunk_index: 0,
          source_page: 2,
          source_label: 'Retention',
          content: 'Backups run nightly.',
          char_start: 0,
          char_end: 20,
          document_accessible: true,
          score: 0.987,
        },
        {
          id: 10,
          document_id: 202,
          document_filename: 'removed.md',
          chunk_id: null,
          chunk_index: 1,
          source_page: null,
          source_label: 'Removed section',
          content: null,
          char_start: 21,
          char_end: 40,
          document_accessible: false,
          score: 0.5,
        },
      ]),
    ])
    const pinia = createPinia()
    setActivePinia(pinia)

    const wrapper = await mountChat(pinia, '/chat?conversation=7')
    await flushPromises()

    expect(wrapper.text()).toContain('When are backups run?')
    expect(wrapper.text()).toContain('Backups run nightly.')
    expect(wrapper.text()).toContain('Retention')
    expect(wrapper.text()).toContain('Page 2')
    expect(wrapper.text()).toContain('Score 0.987')
    expect(wrapper.get('a[href="/documents/101#chunk-501"]')).toBeTruthy()
    expect(wrapper.text()).toContain('Document unavailable')
    expect(wrapper.find('a[href="/documents/202"]').exists()).toBe(false)
  })

  it('preserves recoverable prompt input after a network failure', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    vi.spyOn(api, 'streamChat').mockRejectedValue(new TypeError('network failed'))
    const wrapper = await mountChat(pinia)

    await checkboxFor(wrapper, 'Document grounding').setValue(false)
    await wrapper.get('textarea').setValue('Keep this recoverable prompt')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => expect(wrapper.get('[role="alert"]').text()).toBe('Unable to reach the API'))

    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(
      'Keep this recoverable prompt',
    )
  })
})

function checkboxFor(wrapper: VueWrapper, label: string) {
  const control = wrapper.findAll('label').find(candidate => candidate.text().includes(label))
  if (!control) throw new Error(`Missing checkbox: ${label}`)
  return control.get('input[type="checkbox"]')
}

async function mountChat(pinia: ReturnType<typeof createPinia>, path = '/chat') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/chat', name: 'chat', component: ChatView },
      { path: '/documents/:id', name: 'document-detail', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  return mount(ChatView, { global: { plugins: [pinia, router] } })
}

function messageFixture(
  id: number,
  role: string,
  content: string,
  sources: import('@/types/api').ConversationSourceRead[],
) {
  return {
    id,
    conversation_id: 7,
    role,
    content,
    model: role === 'assistant' ? 'local-model' : null,
    prompt_tokens: role === 'assistant' ? 4 : null,
    completion_tokens: role === 'assistant' ? 3 : null,
    total_tokens: role === 'assistant' ? 7 : null,
    sources,
    created_at: '2026-07-12T00:00:00Z',
  }
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
