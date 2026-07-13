import { defineConfig, devices } from '@playwright/test'

const slowMo = Number(process.env.PW_SLOW_MO ?? 0)
const webPort = Number(process.env.E2E_WEB_PORT ?? 5174)
const apiPort = Number(process.env.E2E_API_PORT ?? 8002)
const webBaseUrl = `http://127.0.0.1:${webPort}`
const apiBaseUrl = `http://127.0.0.1:${apiPort}`

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  timeout: 30_000,
  globalTeardown: './tests/e2e/global-teardown.ts',
  use: {
    baseURL: webBaseUrl,
    launchOptions: slowMo > 0 ? { slowMo } : undefined,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'bash ../../scripts/e2e_api.sh start',
      url: `${apiBaseUrl}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `VITE_API_PROXY_TARGET=${apiBaseUrl} npm run dev -- --port ${webPort}`,
      url: webBaseUrl,
      reuseExistingServer: false,
    },
  ],
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    {
      name: 'mobile-chromium',
      testMatch: /responsive\.spec\.ts/,
      use: { ...devices['Pixel 7'] },
    },
  ],
})
