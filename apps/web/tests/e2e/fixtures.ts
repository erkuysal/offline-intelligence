import { expect, test as base, type Page } from '@playwright/test'

const PASSWORD = 'Playwright-Test-2026!'

type Credentials = {
  email: string
  password: string
}

type UploadedDocument = {
  id: number
  [key: string]: unknown
}

type WorkflowFixtures = {
  credentials: Credentials
  registerUser: (label?: string) => Promise<Credentials>
  loginUser: (credentials: Credentials) => Promise<void>
  uploadTextDocument: (name: string, content: string) => Promise<UploadedDocument>
}

export const test = base.extend<WorkflowFixtures>({
  credentials: async ({}, use, testInfo) => {
    const slug = testInfo.title.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase()
    await use({
      email: `playwright-${slug}-${testInfo.workerIndex}-${Date.now()}@example.com`,
      password: PASSWORD,
    })
  },
  page: async ({ page }, use, testInfo) => {
    const browserErrors: string[] = []
    page.on('console', message => {
      if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`)
    })
    page.on('pageerror', error => browserErrors.push(`page: ${error.message}`))
    page.on('requestfailed', request => {
      browserErrors.push(
        `network: ${request.method()} ${request.url()} (${request.failure()?.errorText ?? 'unknown'})`,
      )
    })

    await use(page)

    const allowedPatterns = testInfo.annotations
      .filter(annotation => annotation.type === 'allow-browser-error' && annotation.description)
      .map(annotation => new RegExp(annotation.description!))
    const unexpectedErrors = browserErrors.filter(
      error => !allowedPatterns.some(pattern => pattern.test(error)),
    )
    expect(unexpectedErrors, 'Unexpected browser errors or failed network requests').toEqual([])
  },
  registerUser: async ({ page, credentials }, use) => {
    await use(async label => {
      const selected = label
        ? { ...credentials, email: credentials.email.replace('playwright-', `playwright-${label}-`) }
        : credentials
      await register(page, selected)
      return selected
    })
  },
  loginUser: async ({ page }, use) => {
    await use(credentials => login(page, credentials))
  },
  uploadTextDocument: async ({ page }, use) => {
    await use((name, content) => uploadTextDocument(page, name, content))
  },
})

async function register(page: Page, credentials: Credentials) {
  await page.goto('/register')
  await page.getByLabel('Email').fill(credentials.email)
  await page.getByLabel('Password').fill(credentials.password)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/documents$/)
}

async function login(page: Page, credentials: Credentials) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(credentials.email)
  await page.getByLabel('Password').fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/documents$/)
}

async function uploadTextDocument(page: Page, name: string, content: string) {
  const responsePromise = page.waitForResponse(
    response => response.request().method() === 'POST' && response.url().endsWith('/api/v1/documents'),
  )
  await page.getByLabel('Upload document').setInputFiles({
    name,
    mimeType: 'text/plain',
    buffer: Buffer.from(content),
  })
  const response = await responsePromise
  expect(response.ok()).toBe(true)
  await expect(page.getByRole('row').filter({ hasText: name })).toContainText('ready')
  return (await response.json()) as UploadedDocument
}

export { expect }
