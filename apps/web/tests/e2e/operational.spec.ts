import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

test.beforeEach(async ({ registerUser }) => {
  await registerUser('operational')
})

test('shows an isolated service outage and recovers on manual refresh', async ({ page }) => {
  test.info().annotations.push({
    type: 'allow-browser-error',
    description: 'Failed to load resource:.*503',
  })
  let redisChecks = 0
  await page.route('**/health**', async route => {
    const service = serviceFromHealthPath(new URL(route.request().url()).pathname)
    const unavailable = service === 'redis' && redisChecks++ === 0
    await route.fulfill({
      status: unavailable ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(healthFixture(service, unavailable ? 'unavailable' : 'healthy')),
    })
  })

  await page.getByRole('link', { name: 'System' }).click()

  const redis = page.getByRole('article', { name: 'Redis' })
  const api = page.getByRole('article', { name: 'API' })
  await expect(redis).toContainText('unavailable')
  await expect(redis).toContainText('redis_unavailable')
  await expect(api).toContainText('healthy')
  await expect(page.getByRole('status')).toContainText('1 unavailable')

  await page.getByRole('button', { name: 'Refresh' }).click()

  await expect(redis).toContainText('healthy')
  await expect(redis).not.toContainText('redis_unavailable')
  await expect(page.getByRole('status')).toContainText('Services checked')
})

test('supports keyboard navigation through primary actions', async ({ page }) => {
  await mockHealthyServices(page)
  await page.getByRole('link', { name: 'System' }).click()
  await expect(page.getByRole('heading', { name: 'Health' })).toBeVisible()

  await page.getByRole('link', { name: 'Documents' }).focus()
  await expect(page.getByRole('link', { name: 'Documents' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Chat' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'System' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Collapse sidebar' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'User menu' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Refresh' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('status')).toContainText(/Checking services|Services checked/)
})

test('disables operational animation when reduced motion is requested', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('**/health**', async route => {
    await new Promise(resolve => setTimeout(resolve, 250))
    const service = serviceFromHealthPath(new URL(route.request().url()).pathname)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(healthFixture(service, 'healthy')),
    })
  })

  await page.getByRole('link', { name: 'System' }).click()
  const spinner = page.getByRole('button', { name: 'Refresh' }).locator('svg')
  await expect(spinner).toBeVisible()
  await expect(spinner).toHaveCSS('animation-name', 'none')
  await expect(page.getByRole('status')).toContainText('Services checked')
})

async function mockHealthyServices(page: Page) {
  await page.route('**/health**', async route => {
    const service = serviceFromHealthPath(new URL(route.request().url()).pathname)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(healthFixture(service, 'healthy')),
    })
  })
}

function serviceFromHealthPath(path: string): string {
  return path === '/health' ? 'api' : path.split('/').at(-1) ?? 'api'
}

function healthFixture(service: string, status: 'healthy' | 'unavailable') {
  return {
    service,
    status,
    detail: status === 'healthy' ? `${service} is ready` : `${service} connection failed`,
    code: status === 'unavailable' ? `${service}_unavailable` : null,
    checked_at: '2026-07-13T00:00:00Z',
    metadata: service === 'embedding' ? { model: 'fake-bow', dimensions: 768 } : {},
  }
}
