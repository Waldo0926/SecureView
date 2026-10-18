/**
 * The real-browser smoke test: Chromium clicking the built pages through the golden path.
 *
 * It runs against the disposable stack `backend/tests/e2e/run_live_stack.sh` starts, which
 * builds the frontend against that API and passes the variables below (see
 * docs/E2E_TESTING.md). There is no fallback and no self-skip: without a stack the run
 * refuses to start, so a misconfigured job fails instead of reporting an empty pass.
 */
import { defineConfig, devices } from '@playwright/test'

const required = ['E2E_MAILBOX_DIR', 'E2E_WEB_DIR'] as const
const missing = required.filter((name) => !process.env[name])
if (missing.length > 0) {
  throw new Error(
    `The browser smoke test needs ${missing.join(', ')}. Run it through ` +
      'backend/tests/e2e/run_live_stack.sh with E2E_BROWSER=1 (docs/E2E_TESTING.md).',
  )
}

const CI = Boolean(process.env.CI)
// 127.0.0.1:5173 is one of the API's default CORS origins, so the built pages can call the
// disposable API with no configuration change on the server side.
const WEB_PORT = 5173
const BASE_URL = `http://127.0.0.1:${WEB_PORT}`
const REPORT_DIR = process.env.E2E_BROWSER_REPORT_DIR ?? 'playwright-report'

export default defineConfig({
  testDir: './browser-tests',
  testMatch: '*.browser.ts',
  // One worker, in order: the steps share two accounts and must not race each other.
  workers: 1,
  fullyParallel: false,
  // A retry would turn a flaky failure into a pass, so there are none, and a test that
  // somehow passes only on a second attempt still fails the run.
  retries: 0,
  failOnFlakyTests: true,
  forbidOnly: CI,
  // Generating an RSA-3072 key and running Argon2id in the page take seconds each, twice
  // per account, so the whole path gets generous room. Individual waits stay web-first.
  timeout: 180_000,
  expect: { timeout: 15_000 },
  outputDir: `${REPORT_DIR}/test-results`,
  reporter: [
    ['list'],
    ['junit', { outputFile: `${REPORT_DIR}/junit.xml` }],
    ['html', { outputFolder: `${REPORT_DIR}/html`, open: 'never' }],
  ],
  use: {
    baseURL: BASE_URL,
    // Traces record every request header and body, DOM snapshots and typed values: bearer
    // tokens, the private key the register page shows once, the file's plaintext. Even
    // from throwaway accounts that is not something CI publishes, so CI records none.
    // Locally a failed run keeps one for debugging; it never leaves the machine.
    trace: CI ? 'off' : 'retain-on-failure',
    // Failure screenshots are taken by the spec itself, with key material masked out.
    screenshot: 'off',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // The production build, served statically: the same bundle a deployment ships, not
    // the dev server's on-the-fly transforms.
    command: `npx vite preview --host 127.0.0.1 --port ${WEB_PORT} --strictPort --outDir "${process.env.E2E_WEB_DIR}"`,
    url: BASE_URL,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
