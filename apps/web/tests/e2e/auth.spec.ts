import { expect, test } from './fixtures'

for (const entryRoute of ['/login', '/register']) {
  test(`enters the demo workspace from ${entryRoute}`, async ({ page }) => {
    let submittedCredentials: unknown
    await page.route('**/api/v1/auth/login', async route => {
      submittedCredentials = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'demo-access-token',
          refresh_token: 'demo-refresh-token',
          token_type: 'bearer',
        }),
      })
    })
    await page.route('**/api/v1/users/me', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 1,
          email: 'demo.visual@offline-hub.local',
          is_active: true,
          is_verified: false,
          roles: [],
        }),
      }),
    )
    await page.route('**/api/v1/documents', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    )

    await page.goto(entryRoute)
    await page.getByRole('button', { name: 'Use demo account' }).click()

    await expect(page).toHaveURL(/\/documents$/)
    await expect(page.getByRole('heading', { name: 'Document corpus' })).toBeVisible()
    expect(submittedCredentials).toEqual({
      email: 'demo.visual@offline-hub.local',
      password: 'DemoWorkspace2026!',
    })
  })
}

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
  await expect(page.getByRole('heading', { name: 'Document corpus', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/documents$/)
  await expect(page.evaluate(() => sessionStorage.getItem('offlineHub.accessToken'))).resolves.not.toBe(
    'invalid.access.token',
  )

  await page.getByRole('button', { name: 'User menu' }).click()
  await page.getByRole('menuitem', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
})

function allowExpected401() {
  test.info().annotations.push({
    type: 'allow-browser-error',
    description: 'console: Failed to load resource:.*401',
  })
}
