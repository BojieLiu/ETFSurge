// E2E test configuration for ETF Surge frontend
// Uses `export default` as required by Playwright with ESM project.
import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  testDir: path.resolve(__dirname, '../specs'),
  timeout: 60000,
  retries: 1,
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  // globalSetup / globalTeardown manage backend (uvicorn) + frontend (Vite) lifecycle.
  // We use absolute .mjs paths to avoid ESM resolution issues.
  globalSetup: path.resolve(__dirname, '../utils/server-setup.js'),
  globalTeardown: path.resolve(__dirname, '../utils/server-teardown.js'),
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
})
