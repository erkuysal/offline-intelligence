import type { APIRequestContext, Page } from '@playwright/test'

import { expect, test } from './fixtures'

type ChatMockMode = 'incremental' | 'filter' | 'cancel' | 'errors'

const readyDocuments = [
  documentFixture(101, 'policy.txt'),
  documentFixture(202, 'handbook.md'),
]

test.beforeEach(async ({ page, request }) => {
  await authenticate(page, request)
  await page.route('**/api/v1/documents', async route => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(readyDocuments),
    })
  })
})

test('renders streamed text incrementally', async ({ page }) => {
  await installChatMock(page, 'incremental')
  await page.goto('/chat')

  await page.getByPlaceholder('Ask a question').fill('Stream an answer')
  await page.getByRole('button', { name: 'Send' }).click()

  const answer = page.getByRole('article', { name: 'Assistant message' })
  await expect(answer).toContainText('First chunk')
  await expect(answer).not.toContainText('final chunk')
  await expect(answer).toContainText('First chunk and final chunk', { timeout: 4_000 })
  await expect(page.getByText('completed', { exact: true })).toBeVisible()
  await expect(page.getByText('4 tokens', { exact: true })).toBeVisible()
})

test('filters grounding to selected document ids', async ({ page }) => {
  await installChatMock(page, 'filter')
  await page.goto('/chat')

  await page.getByLabel('All ready documents').uncheck()
  await page.getByLabel('policy.txt').check()
  await page.getByPlaceholder('Ask a question').fill('Use only the policy')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText('completed', { exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Source: policy.txt' })).toBeVisible()
  const requests = await chatRequests(page)
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ use_documents: true, document_ids: [101] })
})

test('stops a stream and permits a subsequent request', async ({ page }) => {
  await installChatMock(page, 'cancel')
  await page.goto('/chat')

  await page.getByPlaceholder('Ask a question').fill('Long answer')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('article', { name: 'Assistant message' })).toContainText('Partial answer')
  await page.getByRole('button', { name: 'Stop' }).click()

  await expect(page.getByText('cancelled', { exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Assistant message' })).toContainText('Partial answer')

  await page.getByPlaceholder('Ask a question').fill('Second answer')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('article', { name: 'Assistant message' }).last()).toContainText('Recovered answer')
  await expect(page.getByText('completed', { exact: true })).toBeVisible()
  await expect.poll(async () => (await chatRequests(page)).length).toBe(2)
})

test('shows stable busy and unavailable states', async ({ page }) => {
  await installChatMock(page, 'errors')
  await page.goto('/chat')

  await page.getByPlaceholder('Ask a question').fill('Try model')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('alert')).toHaveText('LLM backend is busy')
  await expect(page.getByText('failed', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('alert')).toHaveText('LLM backend is unavailable')
  await expect(page.getByText('failed', { exact: true })).toBeVisible()
})

async function authenticate(page: Page, request: APIRequestContext) {
  const email = `playwright-chat-${Date.now()}-${test.info().workerIndex}@example.com`
  const password = 'Playwright-Test-2026!'
  const register = await request.post('/api/v1/auth/register', { data: { email, password } })
  expect(register.status()).toBe(201)
  const login = await request.post('/api/v1/auth/login', { data: { email, password } })
  expect(login.ok()).toBe(true)
  const tokens = (await login.json()) as { access_token: string; refresh_token: string }
  await page.addInitScript(tokens => {
    sessionStorage.setItem('offlineHub.accessToken', tokens.access_token)
    sessionStorage.setItem('offlineHub.refreshToken', tokens.refresh_token)
  }, tokens)
}

async function installChatMock(page: Page, mode: ChatMockMode) {
  await page.addInitScript(mode => {
    const state = window as typeof window & { __chatRequests: Array<Record<string, unknown>> }
    state.__chatRequests = []
    const nativeFetch = window.fetch.bind(window)
    const encoder = new TextEncoder()

    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (!url.endsWith('/api/v1/chat/completions')) return nativeFetch(input, init)

      const payload = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      const requestIndex = state.__chatRequests.push(payload) - 1
      if (mode === 'errors' && requestIndex === 0) {
        return new Response(JSON.stringify({ detail: 'LLM backend is busy' }), {
          status: 429,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      const frames = createFrames(mode, requestIndex)
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          const timers: number[] = []
          let closed = false
          const close = () => {
            if (closed) return
            closed = true
            controller.close()
          }
          frames.forEach(({ delay, frame, done }) => {
            timers.push(
              window.setTimeout(() => {
                if (closed) return
                controller.enqueue(encoder.encode(frame))
                if (done) close()
              }, delay),
            )
          })
          init?.signal?.addEventListener(
            'abort',
            () => {
              timers.forEach(timer => window.clearTimeout(timer))
              if (closed) return
              closed = true
              controller.error(new DOMException('Aborted', 'AbortError'))
            },
            { once: true },
          )
        },
      })
      return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    }

    function createFrames(selectedMode: ChatMockMode, requestIndex: number) {
      const complete =
        'event: complete\ndata: {"conversation_id":77,"model":"mock-model","usage":{"prompt_tokens":2,"completion_tokens":2,"total_tokens":4}}\n\n' +
        'data: [DONE]\n\n'
      const token = (content: string) =>
        `data: ${JSON.stringify({ choices: [{ delta: { content } }] })}\n\n`
      if (selectedMode === 'incremental') {
        return [
          { delay: 0, frame: token('First chunk'), done: false },
          { delay: 1_000, frame: token(' and final chunk'), done: false },
          { delay: 1_100, frame: complete, done: true },
        ]
      }
      if (selectedMode === 'filter') {
        const sources =
          'event: sources\ndata: [{"document_id":101,"document_filename":"policy.txt","chunk_id":501,"chunk_index":0,"source_page":null,"source_label":"policy.txt","score":0.99}]\n\n'
        return [{ delay: 0, frame: sources + token('Filtered answer') + complete, done: true }]
      }
      if (selectedMode === 'cancel' && requestIndex === 0) {
        return [
          { delay: 0, frame: token('Partial answer'), done: false },
          { delay: 10_000, frame: complete, done: true },
        ]
      }
      if (selectedMode === 'errors') {
        return [
          {
            delay: 0,
            frame:
              'event: error\ndata: {"code":"llm_unavailable","detail":"LLM backend is unavailable","retryable":true}\n\n',
            done: true,
          },
        ]
      }
      return [{ delay: 0, frame: token('Recovered answer') + complete, done: true }]
    }
  }, mode)
}

async function chatRequests(page: Page) {
  return page.evaluate(() => {
    const state = window as typeof window & { __chatRequests: Array<Record<string, unknown>> }
    return state.__chatRequests
  })
}

function documentFixture(id: number, originalFilename: string) {
  return {
    id,
    owner_id: 1,
    original_filename: originalFilename,
    content_type: originalFilename.endsWith('.md') ? 'text/markdown' : 'text/plain',
    size_bytes: 100,
    checksum_sha256: `checksum-${id}`,
    status: 'ready',
    chunk_count: 1,
    ingestion_error: null,
    version_number: 1,
    created_at: '2026-07-12T00:00:00Z',
    updated_at: '2026-07-12T00:00:00Z',
  }
}
