import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'

test('keeps operational and chat surfaces within the viewport', async ({ page, registerUser }) => {
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
  await registerUser('responsive')
  await page.getByRole('link', { name: 'System' }).click()
  await expect(page.getByRole('article')).toHaveCount(6)
  await expectNoHorizontalOverflow(page)

  await page.getByRole('link', { name: 'Chat' }).click()
  const history = page.getByRole('complementary', { name: 'Conversations' })
  const conversation = page.getByRole('region', { name: 'Conversation' })
  const sources = page.getByRole('complementary', { name: 'Sources' })
  await expect(history).toBeVisible()
  await expect(conversation).toBeVisible()
  await expect(sources).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await expectNoOverlap(history, conversation)
  await expectNoOverlap(conversation, sources)
})

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
