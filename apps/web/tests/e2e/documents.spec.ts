import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  const uniqueId = `${Date.now()}-${test.info().workerIndex}`
  await page.goto('/register')
  await page.getByLabel('Email').fill(`playwright-documents-${uniqueId}@example.com`)
  await page.getByLabel('Password').fill('Playwright-Test-2026!')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/documents$/)
})

test('rejects unsupported and oversized files before upload', async ({ page }) => {
  let uploadRequests = 0
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/api/v1/documents')) {
      uploadRequests += 1
    }
  })

  await page.locator('input[type="file"]').setInputFiles({
    name: 'records.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('id,value\n1,test'),
  })

  await expect(page.getByRole('alert')).toContainText('TXT, Markdown, PDF, or DOCX')

  await page.locator('input[type="file"]').setInputFiles({
    name: 'large.txt',
    mimeType: 'text/plain',
    buffer: Buffer.alloc(5 * 1024 * 1024 + 1),
  })

  await expect(page.getByRole('alert')).toContainText('5 MB upload limit')
  expect(uploadRequests).toBe(0)
})

test('polls asynchronous ingestion from pending to ready', async ({ page }) => {
  const timestamp = new Date().toISOString()
  const document = {
    id: 9001,
    owner_id: 1,
    original_filename: 'async-policy.txt',
    content_type: 'text/plain',
    size_bytes: 13,
    checksum_sha256: 'e2e-checksum',
    status: 'pending',
    chunk_count: 0,
    ingestion_error: null,
    version_number: 1,
    created_at: timestamp,
    updated_at: timestamp,
  }
  let statusChecks = 0

  await page.route('**/api/v1/documents', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(document) })
  })
  await page.route('**/api/v1/documents/9001', async route => {
    statusChecks += 1
    const status = statusChecks === 1 ? 'processing' : 'ready'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...document, status, chunk_count: status === 'ready' ? 1 : 0 }),
    })
  })

  await page.locator('input[type="file"]').setInputFiles({
    name: 'async-policy.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('backup policy'),
  })

  const documentRow = page.getByRole('row').filter({ hasText: 'async-policy.txt' })
  await expect(documentRow).toContainText('pending')
  await expect(documentRow).toContainText('processing', { timeout: 3_000 })
  await expect(documentRow).toContainText('ready', { timeout: 3_000 })
  expect(statusChecks).toBe(2)
})
