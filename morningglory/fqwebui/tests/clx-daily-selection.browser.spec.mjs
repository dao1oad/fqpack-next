import { test, expect } from '@playwright/test'
import { rm } from 'node:fs/promises'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  startPreviewServer,
  stopDevServer,
  waitForServer,
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18096
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)
const PARTIAL_BATCH_ID = 'clx-2026-03-10-production-v1-partial'

let devServerProcess = null

const partialBatch = {
  batch_id: PARTIAL_BATCH_ID,
  trade_date: '2026-03-10',
  status: 'running',
  release_status: 'partial',
  is_final: false,
  evaluation_profile_id: 'production_v1',
  switch_opt: 1,
  algorithm_version: 'clx18-production-v1',
  data_version: 'qfq-daily-v1',
  counts: {
    stock: { universe_count: 2, evaluated_count: 2, hit_symbol_count: 1, error_count: 0 },
    etf: { universe_count: 0, evaluated_count: 0, hit_symbol_count: 0, error_count: 0 },
    total: { universe_count: 2, evaluated_count: 2, hit_symbol_count: 1, error_count: 0 },
  },
  partitions: {
    stock: {
      asset_type: 'stock',
      status: 'completed',
      selection_key: 'stock-selection',
      attempt_no: 1,
      partition_id: 'stock-output',
      counts: { universe_count: 2, evaluated_count: 2, hit_symbol_count: 1, error_count: 0 },
    },
    etf: {
      asset_type: 'etf',
      status: 'running',
      selection_key: 'etf-selection',
      attempt_no: 2,
    },
  },
}

const resultRow = {
  asset_type: 'stock',
  symbol: 'sz000001',
  code: '000001',
  name: '平安银行',
  distinct_model_count: 2,
  distinct_condition_count: 2,
  signal_event_count: 2,
  model_keys: ['S0003', 'S0007'],
  condition_keys: ['entrypoint_1', 'entrypoint_2'],
  latest_trigger: '2026-03-10',
  above_ma250: { state: 'yes', line_value: 10.08, source: 'daily_close_ma250' },
}

function buildKlinePayload(period = '5m') {
  const suffix = period === '1d' ? '' : ' 15:00:00'
  const dates = [`2026-03-09${suffix}`, `2026-03-10${suffix}`]
  return {
    symbol: 'sz000001',
    name: '平安银行',
    date: dates,
    open: [10, 10.1],
    close: [10.1, 10.2],
    low: [9.9, 10],
    high: [10.2, 10.3],
    bidata: { date: dates, data: [10.1, 10.2] },
    duandata: { date: dates, data: [10.1, 10.2] },
    higherDuanData: { date: dates, data: [10.1, 10.2] },
    zsdata: [],
    zsflag: [],
    duan_zsdata: [],
    duan_zsflag: [],
    higher_duan_zsdata: [],
    higher_duan_zsflag: [],
    updated_at: `2026-03-10:${period}`,
  }
}

async function mockApis(page, requestLog) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname

    if (pathname === '/api/clx-daily-selection/model-catalog') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          models: [
            { model_key: 'S0003', display_name: 'S0003', enabled: true },
            { model_key: 'S0007', display_name: 'S0007', enabled: true },
          ],
          conditions: [
            { key: 'entrypoint_1', label: '买入条件' },
            { key: 'entrypoint_2', label: '卖出条件' },
          ],
        }),
      })
      return
    }

    if (pathname === '/api/clx-daily-selection/batches') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [partialBatch] }) })
      return
    }

    if (pathname === '/api/clx-daily-selection/batches/latest') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'no_ready_batch', release_status: 'final', is_final: false }),
      })
      return
    }

    if (pathname === `/api/clx-daily-selection/batches/${PARTIAL_BATCH_ID}/summary`) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(partialBatch) })
      return
    }

    if (pathname === `/api/clx-daily-selection/batches/${PARTIAL_BATCH_ID}/results`) {
      requestLog.resultQueries.push(request.postDataJSON?.() || {})
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...partialBatch, rows: [resultRow], total: 1 }),
      })
      return
    }

    if (pathname.endsWith('/statistics')) {
      requestLog.statisticsRequests += 1
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }

    if (pathname === '/api/clx-daily-selection/history/signals') {
      requestLog.historyQueries.push(Object.fromEntries(url.searchParams.entries()))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          calculation_profile: {
            id: 'production_v1',
            switch_opt: 1,
            algorithm_version: 'clx18-production-v1',
            data_version: 'qfq-daily-v1',
          },
          future_function_guard: { passed: true },
          markers_by_model: {
            S0003: [{
              marker_id: 'buy-marker',
              date: '2026-03-10',
              direction: 'buy',
              condition_key: 'entrypoint_1',
              signal_value_raw: 301,
              line_value: 10.08,
              source: 'daily_close_ma250',
            }],
            S0007: [{
              marker_id: 'sell-marker',
              date: '2026-03-10',
              direction: 'sell',
              condition_key: 'entrypoint_2',
              signal_value_raw: -702,
            }],
          },
        }),
      })
      return
    }

    if (pathname === '/api/stock_data') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildKlinePayload(url.searchParams.get('period') || '5m')),
      })
      return
    }

    if (pathname === '/api/get_stock_position_list') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([resultRow]) })
      return
    }

    if (
      pathname === '/api/get_stock_must_pools_list' ||
      pathname === '/api/get_stock_pools_list' ||
      pathname === '/api/get_stock_pre_pools_list' ||
      pathname === '/api/gantt/stocks/reasons'
    ) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

test.beforeAll(async () => {
  test.setTimeout(120000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runLockedBuild(
    () => ({
      command: process.execPath,
      args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build'],
    }),
    process.cwd(),
    { outDir: PREVIEW_ARTIFACTS.outDirRelative },
  )
  devServerProcess = startPreviewServer({
    port: DEV_SERVER_PORT,
    cwd: process.cwd(),
    outDir: PREVIEW_ARTIFACTS.outDirRelative,
  })
  await waitForServer(DEV_SERVER_URL)
})

test.afterAll(async () => {
  await stopDevServer(devServerProcess)
  devServerProcess = null
  await rm(PREVIEW_ARTIFACTS.outDir, { recursive: true, force: true })
})

test('partial page stays explicit and Kline renders guarded CLX markers', async ({ page }) => {
  const requestLog = { resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  await page.setViewportSize({ width: 1600, height: 900 })
  await mockApis(page, requestLog)

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('最新运行 2026-03-10')).toBeVisible()
  await expect(page.getByText('股票已完成')).toBeVisible()
  await expect(page.getByText('ETF运行中')).toBeVisible()
  expect(requestLog.resultQueries).toHaveLength(0)

  await page.getByRole('button', { name: '查看部分结果' }).click()
  await expect(page.getByText(/当前是部分结果/)).toBeVisible()
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  expect(requestLog.statisticsRequests).toBe(0)

  await page.goto(
    `${DEV_SERVER_URL}/kline-slim?symbol=sz000001&period=5m&endDate=2026-03-10&clxScope=${PARTIAL_BATCH_ID}&clxWorkbench=1`,
    { waitUntil: 'domcontentloaded' },
  )
  await expect(page.locator('.kline-slim-clx-workbench')).toBeVisible()
  await expect(page.locator('.clx-workbench-meta')).toContainText('production_v1')
  await expect.poll(() => requestLog.historyQueries.length).toBeGreaterThan(0)
  expect(requestLog.historyQueries.at(-1).includeRaw).toBe('1')

  const markerState = await expect.poll(async () => page.evaluate(() => {
    const chart = window.__klineSlimChart
    if (!chart) return null
    const series = (chart.getOption()?.series || []).find((item) => String(item.id || '').startsWith('clx-signal-'))
    const point = series?.data?.[0]
    return series && point
      ? {
          type: series.type,
          count: series.data.length,
          direction: point.clxGroup?.direction,
          symbol: point.symbol,
        }
      : null
  })).not.toBeNull()
  void markerState

  const rendered = await page.evaluate(() => {
    const chart = window.__klineSlimChart
    const series = (chart.getOption()?.series || []).find((item) => String(item.id || '').startsWith('clx-signal-'))
    const point = series.data[0]
    const canvas = document.querySelector('.kline-slim-chart canvas')
    const context = canvas?.getContext('2d')
    const pixels = context?.getImageData(0, 0, Math.min(canvas.width, 320), Math.min(canvas.height, 180)).data || []
    let nonTransparentPixels = 0
    for (let index = 3; index < pixels.length; index += 4) {
      if (pixels[index] > 0) nonTransparentPixels += 1
    }
    return {
      type: series.type,
      count: series.data.length,
      direction: point.clxGroup.direction,
      symbol: point.symbol,
      nonTransparentPixels,
    }
  })

  expect(rendered).toMatchObject({ type: 'scatter', count: 1, direction: 'mixed', symbol: 'diamond' })
  expect(rendered.nonTransparentPixels).toBeGreaterThan(100)
})
