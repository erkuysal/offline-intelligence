import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const API_BASE_URL = process.env.PACKAGE4_API_BASE_URL ?? 'http://127.0.0.1:8000'

test.beforeEach(async ({ page }) => {
  await forwardApi(page)
})

test('restores the active conversation after reload', async ({ page }) => {
  await registerInBrowser(page, 'reload')
  await page.getByRole('link', { name: 'Chat' }).click()
  await page.getByLabel('Document grounding').uncheck()
  await page.getByPlaceholder('Ask a question').fill('Remember this persisted answer')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText('completed', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/conversation=\d+/)
  await expect(page.getByRole('navigation', { name: 'Conversation history' })).toContainText(
    'Remember this persisted answer',
  )

  await page.reload()

  await expect(page.locator('.message.user')).toContainText('Remember this persisted answer')
  await expect(page.locator('.message.assistant')).toContainText(
    'Fake LLM response: Remember this persisted answer',
  )
})

test('inspects a persisted citation and opens its exact document chunk', async ({ page }) => {
  await registerInBrowser(page, 'source')
  const filename = `retention-${Date.now()}.txt`
  await page.locator('input[type="file"]').setInputFiles({
    name: filename,
    mimeType: 'text/plain',
    buffer: Buffer.from('Retention policy: encrypted backups are retained for ninety days.'),
  })
  await expect(page.getByRole('row').filter({ hasText: filename })).toContainText('ready')
  await page.getByRole('link', { name: 'Chat' }).click()
  await page.getByPlaceholder('Ask a question').fill('How long are encrypted backups retained?')
  await page.getByRole('button', { name: 'Send' }).click()

  const source = page.locator('.source-item').filter({ hasText: filename })
  await expect(source).toContainText('Retention policy: encrypted backups are retained for ninety days.')
  await expect(source).toContainText('Score')
  await source.getByRole('link', { name: 'Open passage' }).click()

  await expect(page).toHaveURL(/\/documents\/\d+#chunk-\d+$/)
  const chunkId = new URL(page.url()).hash
  await expect(page.locator(chunkId)).toBeVisible()
  await expect(page.locator(chunkId)).toContainText('encrypted backups are retained for ninety days')
})

test('deletes the active conversation with confirmation', async ({ page }) => {
  await registerInBrowser(page, 'delete')
  await page.getByRole('link', { name: 'Chat' }).click()
  await page.getByLabel('Document grounding').uncheck()
  await page.getByPlaceholder('Ask a question').fill('Disposable conversation')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('completed', { exact: true })).toBeVisible()

  const history = page.getByRole('navigation', { name: 'Conversation history' })
  await expect(history).toContainText('Disposable conversation')
  await history.getByRole('button', { name: 'Delete conversation' }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete conversation?' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete permanently' }).click()

  await expect(history).not.toContainText('Disposable conversation')
  await expect(page.locator('.message')).toHaveCount(0)
  await expect(page).not.toHaveURL(/conversation=/)
})

test('prevents a second user from reading another users conversations and sources', async ({ request }) => {
  const owner = await createApiUser(request, 'owner')
  const other = await createApiUser(request, 'other')
  const upload = await request.post(`${API_BASE_URL}/api/v1/documents`, {
    headers: { Authorization: `Bearer ${owner.access_token}` },
    multipart: {
      file: {
        name: `private-${Date.now()}.txt`,
        mimeType: 'text/plain',
        buffer: Buffer.from('Private citation passage for the owner only.'),
      },
    },
  })
  expect(upload.status()).toBe(201)
  const document = (await upload.json()) as { id: number }
  const completion = await request.post(`${API_BASE_URL}/api/v1/chat/completions`, {
    headers: { Authorization: `Bearer ${owner.access_token}` },
    data: {
      messages: [{ role: 'user', content: 'What is private?' }],
      use_documents: true,
      document_ids: [document.id],
    },
  })
  expect(completion.ok()).toBe(true)
  const conversationId = ((await completion.json()) as { conversation_id: number }).conversation_id

  const otherHeaders = { Authorization: `Bearer ${other.access_token}` }
  const list = await request.get(`${API_BASE_URL}/api/v1/chat/conversations`, {
    headers: otherHeaders,
  })
  expect(await list.json()).toEqual([])
  for (const path of [
    `/api/v1/chat/conversations/${conversationId}`,
    `/api/v1/chat/conversations/${conversationId}/messages`,
  ]) {
    const response = await request.get(`${API_BASE_URL}${path}`, { headers: otherHeaders })
    expect(response.status()).toBe(404)
    expect(await response.json()).toEqual({ detail: 'Conversation not found' })
  }
})

async function forwardApi(page: Page) {
  await page.route('**/api/v1/**', async route => {
    const source = new URL(route.request().url())
    const response = await route.fetch({ url: `${API_BASE_URL}${source.pathname}${source.search}` })
    await route.fulfill({ response })
  })
}

async function registerInBrowser(page: Page, label: string) {
  await page.goto('/register')
  await page.getByLabel('Email').fill(`playwright-package4-${label}-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('Playwright-Test-2026!')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/documents$/)
}

async function createApiUser(request: APIRequestContext, label: string) {
  const email = `playwright-package4-${label}-${Date.now()}@example.com`
  const password = 'Playwright-Test-2026!'
  const registration = await request.post(`${API_BASE_URL}/api/v1/auth/register`, {
    data: { email, password },
  })
  expect(registration.status()).toBe(201)
  const login = await request.post(`${API_BASE_URL}/api/v1/auth/login`, {
    data: { email, password },
  })
  expect(login.ok()).toBe(true)
  return (await login.json()) as { access_token: string; refresh_token: string }
}
