import { expect, test } from './fixtures'

test('redirects anonymous users to login', async ({ page }) => {
  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})

test('collapses the desktop sidebar and remembers the preference', async ({ page, registerUser }) => {
  await registerUser('shell-collapse')
  const sidebar = page.getByRole('complementary', { name: 'Primary' })
  const expandedWidth = (await sidebar.boundingBox())?.width ?? 0

  const collapseButton = sidebar.getByRole('button', { name: 'Collapse sidebar' })
  await expect(collapseButton).toBeVisible()
  await expect(page.locator('.desktop-appbar').getByRole('button', { name: 'Collapse sidebar' })).toHaveCount(0)
  await collapseButton.click()
  await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()
  await expect.poll(async () => (await sidebar.boundingBox())?.width ?? 0).toBeLessThan(expandedWidth)
  await expect(page.getByRole('link', { name: 'Documents' })).toBeVisible()

  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('offlineHub.sidebarCollapsed')))
    .toBe('true')
})
