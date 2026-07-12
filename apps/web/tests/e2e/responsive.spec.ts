import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'

test('keeps operational and chat surfaces within the viewport', async ({ page }) => {
  await page.route('**/health**', async route => {
    const path = new URL(route.request().url()).pathname
    const service = path === '/health' ? 'api' : path.split('/').at(-1) ?? 'api'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        service,
        status: 'healthy',
        detail: `${service} is ready`,
        code: null,
        checked_at: '2026-07-13T00:00:00Z',
        metadata: {},
      }),
    })
  })
  await register(page)
  await page.getByRole('link', { name: 'System' }).click()
  await expect(page.locator('.health-item')).toHaveCount(6)
  await expectNoHorizontalOverflow(page)

  await page.getByRole('link', { name: 'Chat' }).click()
  const history = page.locator('.history-panel')
  const conversation = page.locator('.conversation-panel')
  const sources = page.locator('.sources-panel')
  await expect(history).toBeVisible()
  await expect(conversation).toBeVisible()
  await expect(sources).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await expectNoOverlap(history, conversation)
  await expectNoOverlap(conversation, sources)
})

async function register(page: Page) {
  await page.goto('/register')
  await page.getByLabel('Email').fill(`playwright-responsive-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('Playwright-Test-2026!')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/documents$/)
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
    .toBe(true)
}

async function expectNoOverlap(first: Locator, second: Locator) {
  const [a, b] = await Promise.all([first.boundingBox(), second.boundingBox()])
  expect(a).not.toBeNull()
  expect(b).not.toBeNull()
  if (!a || !b) return
  const overlapX = a.x < b.x + b.width && a.x + a.width > b.x
  const overlapY = a.y < b.y + b.height && a.y + a.height > b.y
  expect(overlapX && overlapY).toBe(false)
}
