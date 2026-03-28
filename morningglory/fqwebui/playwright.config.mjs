import { defineConfig } from '@playwright/test'

const baseURL = process.env.FQ_WEBUI_BASE_URL || 'http://127.0.0.1:18080'
const executablePath = process.env.FQ_PLAYWRIGHT_EXECUTABLE_PATH || undefined

export default defineConfig({
  testDir: './tests',
  testMatch: /.*\.browser\.spec\.mjs/,
  timeout: 60_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  reporter: 'list',
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
        ...(executablePath
          ? {
              launchOptions: {
                executablePath,
              },
            }
          : {}),
      },
    },
  ],
})
