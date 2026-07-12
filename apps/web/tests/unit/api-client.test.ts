import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, readableApiError } from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('adds bearer tokens to authenticated requests', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }))

    await api.documents('token-123')

    const headers = fetchMock.mock.calls[0][1]?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer token-123')
  })

  it('raises typed errors for failed requests', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Nope' }), { status: 401 }),
    )

    await expect(api.documents('bad-token')).rejects.toBeInstanceOf(ApiError)
  })

  it.each([
    [401, 'Your session has expired'],
    [403, 'You do not have permission to perform this action'],
    [404, 'The requested resource was not found'],
    [413, 'The request exceeds the configured size limit'],
    [429, 'The model is busy. Try again shortly'],
    [502, 'The model returned an invalid response'],
    [503, 'A required service is unavailable'],
    [504, 'The model request timed out'],
  ])('maps HTTP %i when the API provides no safe detail', (status, expected) => {
    expect(readableApiError(new ApiError('failed', status, null), 'Fallback')).toBe(expected)
  })

  it('streams split token, source, and completion events incrementally', async () => {
    const encoder = new TextEncoder()
    const chunks = [
      'event: sources\ndata: [{"document_id":1,"document_filename":"policy.txt","chunk_id":2,"chunk_index":0,"source_page":null,"source_label":"policy.txt","score":0.9}]\n\n',
      'data: {"choices":[{"delta":{"content":"Hel',
      'lo"}}]}\n\nevent: complete\ndata: {"conversation_id":3,"model":"local","usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\ndata: [DONE]\n\n',
    ]
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk)))
            controller.close()
          },
        }),
        { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
      ),
    )
    const onToken = vi.fn()
    const onSources = vi.fn()
    const onComplete = vi.fn()

    await api.streamChat(
      'token-123',
      { messages: [{ role: 'user', content: 'Hello' }] },
      { onToken, onSources, onComplete },
    )

    expect(onToken).toHaveBeenCalledWith('Hello')
    expect(onSources).toHaveBeenCalledWith([expect.objectContaining({ document_filename: 'policy.txt' })])
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ conversation_id: 3, usage: expect.objectContaining({ total_tokens: 2 }) }),
    )
  })
})
