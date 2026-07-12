import { describe, expect, it, vi } from 'vitest'

import { createSseParser } from '@/api/sse'

describe('SSE parser', () => {
  it('parses events split across arbitrary network chunks', () => {
    const onEvent = vi.fn()
    const parser = createSseParser(onEvent)

    parser.feed('event: sou')
    parser.feed('rces\r\ndata: [{"document')
    parser.feed('_id":1}]\r')
    parser.feed('\n\r\ndata: {"choices":[{"delta":{"content":"Hel')
    parser.feed('lo"}}]}\n\n')

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([
      { event: 'sources', data: '[{"document_id":1}]' },
      { event: 'message', data: '{"choices":[{"delta":{"content":"Hello"}}]}' },
    ])
  })

  it('joins multiline data and flushes a final unterminated frame', () => {
    const events: Array<{ event: string; data: string }> = []
    const parser = createSseParser(event => events.push(event))

    parser.feed(': keepalive\ndata: first\ndata: second')
    parser.finish()

    expect(events).toEqual([{ event: 'message', data: 'first\nsecond' }])
  })
})
