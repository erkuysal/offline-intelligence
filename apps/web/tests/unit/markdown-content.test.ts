import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MarkdownContent from '@/components/content/MarkdownContent.vue'

describe('MarkdownContent', () => {
  it('renders common Markdown structures', () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        headingPrefix: 'chunk-42',
        content: [
          '## Retrieval notes',
          '',
          '- Preserve **source labels**',
          '- Keep citations',
          '',
          '`top_k = 5`',
          '',
          '| Metric | Value |',
          '| --- | ---: |',
          '| Recall | 0.92 |',
        ].join('\n'),
      },
    })

    expect(wrapper.get('h2').text()).toBe('Retrieval notes')
    expect(wrapper.get('h2').attributes('id')).toBe('chunk-42-retrieval-notes')
    expect(wrapper.emitted('headings')?.at(-1)?.[0]).toEqual([
      { id: 'chunk-42-retrieval-notes', level: 2, text: 'Retrieval notes' },
    ])
    expect(wrapper.findAll('li')).toHaveLength(2)
    expect(wrapper.get('strong').text()).toBe('source labels')
    expect(wrapper.get('code').text()).toBe('top_k = 5')
    expect(wrapper.get('table').text()).toContain('Recall')
  })

  it('removes executable HTML and unsafe link targets', () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: [
          '<script>window.compromised = true</script>',
          '<img src="x" onerror="window.compromised = true">',
          '[unsafe](javascript:alert(1))',
        ].join('\n'),
      },
    })

    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.get('img').attributes('onerror')).toBeUndefined()
    expect(wrapper.find('a').exists()).toBe(false)
  })
})
