import { expect, test } from './fixtures'

test('redirects anonymous users to login', async ({ page }) => {
  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})
