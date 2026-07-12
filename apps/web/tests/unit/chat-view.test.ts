import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import ChatView from '@/views/ChatView.vue'

describe('ChatView streaming', () => {
  beforeEach(() => {
    sessionStorage.clear()
    sessionStorage.setItem('offlineHub.accessToken', 'access-token')
    sessionStorage.setItem('offlineHub.refreshToken', 'refresh-token')
    vi.restoreAllMocks()
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
})
