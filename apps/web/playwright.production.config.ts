import { defineConfig, devices } from '@playwright/test'

const slowMo = Number(process.env.PW_SLOW_MO ?? 0)
const baseURL = process.env.E2E_PRODUCTION_BASE_URL ?? 'http://127.0.0.1:18081'

process.env.E2E_API_BASE_URL ??= baseURL

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  timeout: 30_000,
  use: {
    baseURL,
    launchOptions: slowMo > 0 ? { slowMo } : undefined,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    {
      name: 'mobile-chromium',
      testMatch: /responsive\.spec\.ts/,
      use: { ...devices['Pixel 7'] },
    },
  ],
})
