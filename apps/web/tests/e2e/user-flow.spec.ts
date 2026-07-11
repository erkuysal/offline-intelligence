import { expect, test } from '@playwright/test'

test('registers, uploads a document, asks a grounded question, and logs out', async ({ page }) => {
  test.setTimeout(120_000)

  const demoPauseMs = Number(process.env.PW_DEMO_PAUSE_MS ?? 0)
  const uniqueId = `${Date.now()}-${test.info().workerIndex}`
  const email = `playwright-${uniqueId}@example.com`
  const filename = `backup-policy-${uniqueId}.txt`

  await page.goto('/register')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('Playwright-Test-2026!')
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page).toHaveURL(/\/documents$/)
  await expect(page.getByRole('heading', { name: 'Corpus' })).toBeVisible()

  await page.locator('input[type="file"]').setInputFiles({
    name: filename,
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'System backup policy\nIncremental backups run every night. A full backup runs every Sunday.',
    ),
  })

  const documentRow = page.getByRole('row').filter({ hasText: filename })
  await expect(documentRow).toBeVisible()
  await expect(documentRow).toContainText('ready')
  await documentRow.getByRole('link', { name: 'Open' }).click()

  await expect(page.getByRole('heading', { name: filename })).toBeVisible()
  await expect(page.getByText('Incremental backups run every night.')).toBeVisible()

  await page.getByRole('link', { name: 'Chat' }).click()
  await page.getByPlaceholder('Ask a question').fill('When do incremental and full backups run?')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.locator('.message.assistant')).not.toBeEmpty()
  await expect(page.locator('.source-item').filter({ hasText: filename })).toBeVisible()
  if (demoPauseMs > 0) await page.waitForTimeout(demoPauseMs)

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('Playwright-Test-2026!')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/documents$/)

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Corpus' })).toBeVisible()

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(
    page.evaluate(() => ({
      access: sessionStorage.getItem('offlineHub.accessToken'),
      refresh: sessionStorage.getItem('offlineHub.refreshToken'),
    })),
  ).resolves.toEqual({ access: null, refresh: null })
})
