import { expect, test } from '@playwright/test'

test('redirects anonymous users to login', async ({ page }) => {
  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})
