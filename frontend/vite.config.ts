import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
  },
  test: {
    coverage: {
      provider: 'v8',
      // The logic layers: API clients, client-side crypto, stores, routing, utilities.
      // Pages and components are not measured -- they have no component tests yet, and
      // counting them would only dilute the number these thresholds protect.
      include: ['src/{api,crypto,utils,router,stores}/**/*.ts'],
      exclude: ['**/*.test.ts'],
      // Summaries and machine-readable line data only. No HTML report: it embeds the
      // source, and the source carries example addresses and fixture strings that the
      // published CI artifact is checked not to contain.
      reporter: ['text-summary', 'json-summary', 'cobertura'],
      // Measured offline (`npm run test:coverage`, live suites skipped) at 56.86% statements,
      // 55.57% branches, 54.25% functions, 57.50% lines. Set a little below so a real
      // regression fails the build and noise does not. See issue #58.
      thresholds: {
        statements: 55,
        branches: 53,
        functions: 52,
        lines: 55,
      },
    },
  },
})
