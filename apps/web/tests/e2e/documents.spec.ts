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

  await page.getByLabel('Upload document').setInputFiles({
    name: 'records.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('id,value\n1,test'),
  })

  await expect(page.getByRole('alert')).toContainText('TXT, Markdown, PDF, or DOCX')

  await page.getByLabel('Upload document').setInputFiles({
    name: 'large.txt',
    mimeType: 'text/plain',
    buffer: Buffer.alloc(5 * 1024 * 1024 + 1),
  })

  await expect(page.getByRole('alert')).toContainText('5 MB upload limit')
  expect(uploadRequests).toBe(0)
})

test('searches and filters the corpus without changing stored documents', async ({ page, uploadTextDocument }) => {
  await uploadTextDocument('backup-policy.txt', 'Backups run nightly.')
  await uploadTextDocument('incident-guide.txt', 'Incident updates run every thirty minutes.')

  await expect(page.getByText('2 of 2 shown')).toBeVisible()
  await page.getByPlaceholder('Search documents').fill('backup')

  await expect(page.getByRole('row').filter({ hasText: 'backup-policy.txt' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'incident-guide.txt' })).toHaveCount(0)
  await expect(page.getByText('1 of 2 shown')).toBeVisible()

  await page.getByLabel('Filter by status').selectOption('failed')
  await expect(page.getByText('No documents match the current search and status filter.')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).click()

  await expect(page.getByRole('row').filter({ hasText: 'backup-policy.txt' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'incident-guide.txt' })).toBeVisible()
  await expect(page.getByText('2 of 2 shown')).toBeVisible()
})

test('renders Markdown chunks as readable structured content', async ({ page }) => {
  await page.getByLabel('Upload document').setInputFiles({
    name: 'retrieval-notes.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from([
      '# Retrieval notes',
      '',
      'Use these settings:',
      '',
      '- Preserve **source labels**',
      '- Return inspectable citations',
      '',
      '`top_k = 5`',
      '',
      ...Array.from({ length: 18 }, (_, index) => [
        `## Reference section ${index + 1}`,
        '',
        `Operational detail ${index + 1} remains grounded in the indexed source material.`,
        '',
      ]).flat(),
    ].join('\n')),
  })

  const documentRow = page.getByRole('row').filter({ hasText: 'retrieval-notes.md' })
  await expect(documentRow).toContainText('ready')
  await documentRow.getByRole('link', { name: 'Open' }).click()

  const chunk = page.getByRole('article', { name: 'Chunk 0' })
  await expect(chunk.getByRole('heading', { name: 'Retrieval notes' })).toBeVisible()
  const breadcrumb = page.getByRole('navigation', { name: 'Breadcrumb' })
  await expect(breadcrumb.getByRole('link', { name: 'Documents' })).toHaveAttribute('href', '/documents')
  const contents = page.getByRole('complementary', { name: 'Document contents' })
  await expect(contents.locator('.document-outline-inner')).toHaveCSS('position', 'static')
  await expect(contents.getByRole('navigation')).toHaveCSS('overflow-y', 'auto')
  const readerContent = page.locator('.document-reader-content')
  await expect(readerContent).toHaveCSS('overflow-y', 'auto')
  await expect.poll(() => readerContent.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
  const outlineTop = (await contents.boundingBox())?.y ?? 0
  await readerContent.evaluate(element => element.scrollTo({ top: element.scrollHeight }))
  await expect.poll(() => readerContent.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
  expect((await contents.boundingBox())?.y ?? 0).toBeCloseTo(outlineTop, 0)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  const headingLink = contents.getByRole('link', { name: 'Retrieval notes' })
  await expect(headingLink).toBeVisible()
  await headingLink.click()
  await expect(page).toHaveURL(/#chunk-\d+-retrieval-notes$/)
  await expect(chunk.getByRole('listitem')).toHaveCount(2)
  await expect(chunk.getByText('source labels', { exact: true })).toHaveJSProperty('tagName', 'STRONG')
  await expect(chunk.locator('code')).toHaveText('top_k = 5')
  await chunk.getByText('Retrieval details', { exact: true }).click()
  await expect(chunk.getByText('Characters', { exact: true })).toBeVisible()
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

  await page.getByLabel('Upload document').setInputFiles({
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
  await versionHistory.getByText('Version history', { exact: true }).click()
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
  await page.getByLabel('Upload document').setInputFiles({
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
