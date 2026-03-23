import { test, expect } from '@playwright/test'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  installVmHelpers,
  readChartState,
  startPreviewServer,
  stopDevServer,
  waitForChartReady,
  waitForServer
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18087
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/kline-slim?symbol=sh512000&period=5m`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)

let devServerProcess = null

function buildStockDataPayload() {
  return {
    symbol: 'sh512000',
    name: '券商ETF',
    period: '5m',
    date: [
      '2026-03-20 14:35',
      '2026-03-20 14:40',
      '2026-03-20 14:45',
      '2026-03-20 14:50',
      '2026-03-20 14:55',
      '2026-03-20 15:00'
    ],
    open: [0.562, 0.561, 0.56, 0.558, 0.557, 0.556],
    close: [0.561, 0.56, 0.558, 0.557, 0.556, 0.555],
    low: [0.559, 0.558, 0.556, 0.555, 0.554, 0.553],
    high: [0.563, 0.562, 0.561, 0.559, 0.558, 0.557],
    bidata: {
      date: ['2026-03-20 14:35', '2026-03-20 14:50', '2026-03-20 15:00'],
      data: [0.562, 0.557, 0.555]
    },
    duandata: {
      date: ['2026-03-20 14:35', '2026-03-20 15:00'],
      data: [0.562, 0.555]
    },
    higherDuanData: {
      date: ['2026-03-20 14:35', '2026-03-20 15:00'],
      data: [0.563, 0.556]
    },
    zsdata: [],
    zsflag: [],
    duan_zsdata: [],
    duan_zsflag: [],
    higher_duan_zsdata: [],
    higher_duan_zsflag: [],
    _bar_time: '2026-03-20 15:00',
    updated_at: '2026-03-20 15:00',
    dt: '2026-03-20 15:00'
  }
}

function buildSubjectDetailPayload() {
  return {
    subject: {
      symbol: '512000',
      name: '券商ETF'
    },
    guardian_buy_grid_config: {
      enabled: true,
      buy_enabled: [true, true, true],
      buy_1: 0.51,
      buy_2: 0.48,
      buy_3: 0.46
    },
    guardian_buy_grid_state: null,
    takeprofit: {
      state: {
        armed_levels: {
          1: true,
          2: true,
          3: true
        }
      },
      tiers: [
        { level: 1, enabled: true, price: 0.55 },
        { level: 2, enabled: true, price: 0.61 },
        { level: 3, enabled: true, price: 0.65 }
      ]
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

test('kline slim loads real subject price guides on first entry and keeps auto-fit focused on main candles', async ({
  page
}) => {
  const subjectDetailRequests = []

  await installVmHelpers(page)
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname

    if (pathname === '/api/stock_data') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildStockDataPayload())
      })
      return
    }

    if (pathname === '/api/subject-management/sh512000') {
      subjectDetailRequests.push(route.request().url())
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSubjectDetailPayload())
      })
      return
    }

    if (
      pathname === '/api/get_stock_position_list' ||
      pathname === '/api/get_stock_must_pools_list' ||
      pathname === '/api/get_stock_pools_list' ||
      pathname === '/api/get_stock_pre_pools_list' ||
      pathname === '/api/gantt/stocks/reasons'
    ) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([])
      })
      return
    }

    if (pathname === '/api/stock_data_chanlun_structure') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          source: 'history_fullcalc',
          asof: '2026-03-20 15:00',
          message: '',
          structure: {}
        })
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
  await waitForChartReady(page)
  await page.waitForFunction(() => {
    const vm = window.__klineSlimVm
    return (
      vm?.lastSubjectDetailSymbol === 'sh512000' &&
      vm?.guardianDraft?.buy_1 === 0.51 &&
      vm?.guardianDraft?.buy_2 === 0.48 &&
      vm?.guardianDraft?.buy_3 === 0.46 &&
      vm?.takeprofitDrafts?.[0]?.price === 0.55 &&
      vm?.takeprofitDrafts?.[1]?.price === 0.61 &&
      vm?.takeprofitDrafts?.[2]?.price === 0.65
    )
  })

  const state = await readChartState(page)

  expect(subjectDetailRequests.length).toBeGreaterThan(0)
  expect(state.yAxis.max).toBeLessThan(0.62)
  expect(state.yAxis.min).toBeGreaterThan(0.5)
})
