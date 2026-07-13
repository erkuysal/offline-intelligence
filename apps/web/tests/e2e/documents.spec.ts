import { expect, test } from './fixtures'

test.beforeEach(async ({ registerUser }) => {
  await registerUser('documents')
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

test('shows version history after uploading changed content with the same filename', async ({ page, uploadTextDocument }) => {
  await uploadTextDocument('versioned-policy.txt', 'Backups run nightly.')
  await uploadTextDocument('versioned-policy.txt', 'Backups run nightly and verify monthly.')

  const documentRow = page.getByRole('row').filter({ hasText: 'versioned-policy.txt' })
  await expect(documentRow).toContainText('2')
  await documentRow.getByRole('link', { name: 'Open' }).click()

  const versionHistory = page.getByRole('region', { name: 'Version history' })
  await expect(versionHistory.getByRole('cell', { name: 'v1' })).toBeVisible()
  await expect(versionHistory.getByRole('cell', { name: 'v2' })).toBeVisible()
})

test('requires confirmation and deletes a document', async ({ page, uploadTextDocument }) => {
  test.info().annotations.push({
    type: 'allow-browser-error',
    description: 'network: DELETE .*/api/v1/documents/\\d+.*ERR_ABORTED',
  })
  await uploadTextDocument('temporary-policy.txt', 'Temporary retention policy.')
  const documentRow = page.getByRole('row').filter({ hasText: 'temporary-policy.txt' })
  await documentRow.getByRole('link', { name: 'Open' }).click()

  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete document?' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()

  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await dialog.getByRole('button', { name: 'Delete permanently' }).click()

  await expect(page).toHaveURL(/\/documents$/)
  await expect(page.getByRole('row').filter({ hasText: 'temporary-policy.txt' })).toHaveCount(0)
})

test('reindexes an owned document and returns to ready', async ({ page, uploadTextDocument }) => {
  const uploaded = await uploadTextDocument('reindex-policy.txt', 'Reindex this policy.')
  const documentRow = page.getByRole('row').filter({ hasText: 'reindex-policy.txt' })
  await documentRow.getByRole('link', { name: 'Open' }).click()

  await page.route(`**/api/v1/documents/${uploaded.id}/reindex`, async route => {
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ ...uploaded, status: 'pending', chunk_count: 0 }),
    })
  })

  await page.getByRole('button', { name: 'Reindex' }).click()
  await expect(page.getByText('pending', { exact: true })).toBeVisible()
  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 3_000 })
})

test('shows failed ingestion and recovers with a corrected version', async ({ page, uploadTextDocument }) => {
  await page.locator('input[type="file"]').setInputFiles({
    name: 'recover-policy.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from([0xff, 0xfe]),
  })

  const documentRow = page.getByRole('row').filter({ hasText: 'recover-policy.txt' })
  await expect(documentRow).toContainText('failed')

  await uploadTextDocument('recover-policy.txt', 'Corrected recovery policy.')
  await expect(documentRow).toContainText('ready')
  await expect(documentRow).toContainText('2')
})
