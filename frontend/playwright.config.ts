import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the deployed Sovereign Defence frontend.
 *
 * Default base URL: the public OCI Native IC LB. Override with
 *   PLAYWRIGHT_BASE_URL=http://localhost:5173 npx playwright test
 * to run against `npm run dev` instead.
 *
 * Browsers are pre-installed via `npx playwright install chromium`. Only
 * Chromium runs by default to keep the demo fast; uncomment the firefox
 * project for cross-browser smoke.
 */
export default defineConfig({
  testDir: './e2e',
  // No parallel suites — the demo backends have only 2 replicas; serial
  // requests keep latency reports clean and avoid pool contention.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://152.70.18.236',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    extraHTTPHeaders: {
      'X-Tenant-Id': 'T001',
    },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // { name: 'firefox',  use: { ...devices['Desktop Firefox'] } },
  ],
});
