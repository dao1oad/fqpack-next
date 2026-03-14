import { test, expect } from '@playwright/test'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  startPreviewServer,
  stopDevServer,
  waitForServer
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18089
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/gantt?p=xgb&days=90`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)

let devServerProcess = null

function createGanttPayload({ dateCount = 12, plateCount = 100 } = {}) {
  const dates = Array.from({ length: dateCount }, (_, index) => {
    const day = String(index + 1).padStart(2, '0')
    return `2026-03-${day}`
  })

  const yAxis = Array.from({ length: plateCount }, (_, index) => ({
    id: `plate-${String(index + 1).padStart(3, '0')}`,
    name: `板块${String(index + 1).padStart(3, '0')}`
  }))

  const series = []
  for (let dateIndex = 0; dateIndex < dates.length; dateIndex += 1) {
    for (let plateIndex = 0; plateIndex < yAxis.length; plateIndex += 1) {
      series.push([
        dateIndex,
        plateIndex,
        plateIndex + 1,
        (plateIndex % 5) + 1,
        (plateIndex % 3) + 1,
        [`000${String((plateIndex % 999) + 1).padStart(3, '0')}`]
      ])
    }
  }

  return {
    data: {
      dates,
      y_axis: yAxis,
      series
    },
    meta: {
      reason_map: {}
    }
  }
}

async function runBuild() {
  await runLockedBuild(
    () => {
      return {
        command: process.execPath,
        args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build']
      }
    },
    process.cwd(),
    {
      outDir: PREVIEW_ARTIFACTS.outDirRelative
    }
  )
}

test.beforeAll(async () => {
  test.setTimeout(90000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runBuild()
  devServerProcess = startPreviewServer({
    port: DEV_SERVER_PORT,
    cwd: process.cwd(),
    outDir: PREVIEW_ARTIFACTS.outDirRelative
  })

  await waitForServer(DEV_SERVER_URL)
})

test.afterAll(async () => {
  await stopDevServer(devServerProcess)
  devServerProcess = null
})

test('gantt sidebar rows fit the visible chart window when dense data would otherwise break hover alignment', async ({
  page
}) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }

    if (url.pathname === '/api/gantt/plates') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(createGanttPayload())
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({})
    })
  })

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.gantt-chart')
  await page.waitForSelector('.sidebar-link')
  await page.waitForFunction(() => document.querySelectorAll('.sidebar-link').length >= 35)

  const sidebarMetrics = await page.evaluate(() => {
    const list = document.querySelector('.sidebar-list')
    const links = Array.from(document.querySelectorAll('.sidebar-link'))
    const firstRect = links[0]?.getBoundingClientRect?.()
    return {
      clientHeight: list?.clientHeight || 0,
      scrollHeight: list?.scrollHeight || 0,
      totalRows: links.length,
      firstRowHeight: firstRect?.height || 0
    }
  })
  expect(sidebarMetrics.scrollHeight).toBeLessThanOrEqual(sidebarMetrics.clientHeight + 1)
  expect(sidebarMetrics.firstRowHeight).toBeGreaterThan(0)
  expect(
    Math.abs(sidebarMetrics.firstRowHeight * sidebarMetrics.totalRows - sidebarMetrics.clientHeight)
  ).toBeLessThanOrEqual(sidebarMetrics.totalRows)
})
