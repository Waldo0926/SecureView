/**
 * Screenshot capture for the presentation, not a test run. Same stack and build as the
 * browser smoke test, but only `*.capture.ts` files, no JUnit, and never in CI. See
 * browser-tests/capture/ and `E2E_BROWSER=capture` in backend/tests/e2e/run_live_stack.sh.
 */
import { defineConfig } from '@playwright/test'

import base from './playwright.config'

export default defineConfig({
  ...base,
  testDir: './browser-tests/capture',
  testMatch: '*.capture.ts',
  reporter: [['list']],
})
