import { defineConfig, devices } from '@playwright/test'

const slowMo = Number(process.env.PW_SLOW_MO ?? 0)

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    launchOptions: slowMo > 0 ? { slowMo } : undefined,
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
