import { expect, test } from './fixtures'

test('shows an actionable error for invalid credentials', async ({ page }) => {
  allowExpected401()
  await page.goto('/login')
  await page.getByLabel('Email').fill('missing-user@example.com')
  await page.getByLabel('Password').fill('incorrect-password')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByText('Invalid email or password')).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)
})

test('refreshes an invalid access token and restores the session', async ({ page, request }) => {
  allowExpected401()
  const email = `playwright-refresh-${Date.now()}-${test.info().workerIndex}@example.com`
  const password = 'Playwright-Test-2026!'

  const registerResponse = await request.post('/api/v1/auth/register', {
    data: { email, password },
  })
  expect(registerResponse.status()).toBe(201)

  const loginResponse = await request.post('/api/v1/auth/login', {
    data: { email, password },
  })
  expect(loginResponse.ok()).toBe(true)
  const tokens = (await loginResponse.json()) as { refresh_token: string }

  await page.addInitScript(
    ({ refreshToken }) => {
      sessionStorage.setItem('offlineHub.accessToken', 'invalid.access.token')
      sessionStorage.setItem('offlineHub.refreshToken', refreshToken)
    },
    { refreshToken: tokens.refresh_token },
  )

  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Corpus' })).toBeVisible()
  await expect(page).toHaveURL(/\/documents$/)
  await expect(page.evaluate(() => sessionStorage.getItem('offlineHub.accessToken'))).resolves.not.toBe(
    'invalid.access.token',
  )

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
})

function allowExpected401() {
  test.info().annotations.push({
    type: 'allow-browser-error',
    description: 'console: Failed to load resource:.*401',
  })
}
