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
const FINAL_BATCH_ID = 'clx-2026-02-28-production-v1-final'
const DEEP_LINK_BATCH_ID = 'clx-2026-01-30-production-v1-final'
const RACE_SCOPE_A = 'clx-route-race-a'
const RACE_SCOPE_B = 'clx-route-race-b'

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

const finalBatch = {
  ...partialBatch,
  batch_id: FINAL_BATCH_ID,
  trade_date: '2026-02-28',
  status: 'completed',
  release_status: 'final',
  is_final: true,
  publication: { status: 'published' },
  counts: {
    stock: { universe_count: 2, evaluated_count: 2, hit_symbol_count: 1, error_count: 0 },
    etf: { universe_count: 1, evaluated_count: 1, hit_symbol_count: 1, error_count: 0 },
    total: { universe_count: 3, evaluated_count: 3, hit_symbol_count: 2, error_count: 0 },
  },
  partitions: {
    stock: {
      ...partialBatch.partitions.stock,
      snapshot_hash: 'stock-snapshot-final',
      content_hash: 'stock-content-final',
    },
    etf: {
      asset_type: 'etf',
      status: 'completed',
      selection_key: 'etf-selection-final',
      attempt_no: 1,
      partition_id: 'etf-output-final',
      snapshot_hash: 'etf-snapshot-final',
      content_hash: 'etf-content-final',
      counts: { universe_count: 1, evaluated_count: 1, hit_symbol_count: 1, error_count: 0 },
    },
  },
}

const deepLinkedFinalBatch = {
  ...finalBatch,
  batch_id: DEEP_LINK_BATCH_ID,
  trade_date: '2026-01-30',
  updated_at: '2026-01-30T18:00:00+08:00',
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

const buildNewerPartialWindow = () => Array.from({ length: 30 }, (_, index) => ({
  ...partialBatch,
  batch_id: `partial-window-${String(index + 1).padStart(2, '0')}`,
  trade_date: `2026-03-${String(30 - index).padStart(2, '0')}`,
  updated_at: `2026-03-${String(30 - index).padStart(2, '0')}T18:00:00+08:00`,
}))

const finalStatisticsPayload = {
  counts: { stock: 1, etf: 1, total: 2 },
  by_model: [{ model_key: 'S0003', symbol_count: 1 }],
  by_condition: [{ condition_key: 'entrypoint_1', symbol_count: 1 }],
  resonance_distribution: [{ distinct_model_count: 2, symbol_count: 1 }],
}

async function mockApis(page, requestLog, {
  batchItems = [partialBatch],
  latestPayload = { status: 'no_ready_batch', release_status: 'final', is_final: false },
  activeBatch = partialBatch,
  batchPayloads = [],
  resultRowsByBatch = {},
  resultFailureCounts = {},
  emptyResultQueries = [],
  responseDelays = {},
  statisticsPayload = {},
  tdxImportPayload = { success: true, group_name: 'clx_18', written_count: 321 },
} = {}) {
  const knownBatches = new Map()
  for (const batch of [
    ...batchItems,
    activeBatch,
    ...batchPayloads,
    latestPayload?.batch,
    latestPayload?.scope,
  ].filter(Boolean)) {
    knownBatches.set(batch.batch_id || batch.scope_id, batch)
  }
  const waitForResponse = async (kind, batchId = '') => {
    const configured = responseDelays[kind]
    const delay = Number(
      configured && typeof configured === 'object'
        ? configured[batchId] || 0
        : configured || 0,
    )
    if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay))
  }

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname

    if (pathname === '/api/clx-daily-selection/model-catalog') {
      await waitForResponse('catalog')
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
      requestLog.batchRequests = (requestLog.batchRequests || 0) + 1
      await waitForResponse('batches')
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: batchItems }) })
      return
    }

    if (pathname === '/api/clx-daily-selection/batches/latest') {
      await waitForResponse('latest')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(latestPayload),
      })
      return
    }

    const summaryMatch = pathname.match(/^\/api\/clx-daily-selection\/batches\/([^/]+)\/summary$/)
    if (summaryMatch) {
      const batchId = decodeURIComponent(summaryMatch[1])
      const batch = knownBatches.get(batchId)
      requestLog.summaryRequests.push(batchId)
      await waitForResponse('summary', batchId)
      await route.fulfill({ status: batch ? 200 : 404, contentType: 'application/json', body: JSON.stringify(batch || {}) })
      return
    }

    const resultsMatch = pathname.match(/^\/api\/clx-daily-selection\/batches\/([^/]+)\/results$/)
    if (resultsMatch) {
      const batchId = decodeURIComponent(resultsMatch[1])
      const batch = knownBatches.get(batchId)
      const query = request.postDataJSON?.() || {}
      requestLog.resultQueries.push(query)
      await waitForResponse('results', batchId)
      const failureKey = String(query.q || '')
      if (Number(resultFailureCounts[failureKey] || 0) > 0) {
        resultFailureCounts[failureKey] -= 1
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ message: '筛选结果更新失败' }),
        })
        return
      }
      const allRows = emptyResultQueries.includes(String(query.q || ''))
        ? []
        : resultRowsByBatch[batchId] || [resultRow]
      const offset = Math.max(0, Number(query.cursor) || 0)
      const limit = Math.max(1, Math.min(200, Number(query.limit) || 100))
      const pageRows = allRows.slice(offset, offset + limit)
      const nextCursor = offset + limit < allRows.length ? String(offset + limit) : ''
      await route.fulfill({
        status: batch ? 200 : 404,
        contentType: 'application/json',
        body: JSON.stringify({
          ...(batch || {}),
          rows: pageRows,
          total: allRows.length,
          next_cursor: nextCursor,
        }),
      })
      return
    }

    const tdxImportMatch = pathname.match(/^\/api\/clx-daily-selection\/batches\/([^/]+)\/results\/sync-selected-to-tdx$/)
    if (tdxImportMatch) {
      const batchId = decodeURIComponent(tdxImportMatch[1])
      requestLog.tdxImports = [...(requestLog.tdxImports || []), {
        batchId,
        payload: request.postDataJSON?.() || {},
      }]
      await waitForResponse('tdxImport', batchId)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(tdxImportPayload),
      })
      return
    }

    if (pathname.endsWith('/statistics')) {
      const batchId = decodeURIComponent(pathname.split('/').at(-2) || '')
      requestLog.statisticsRequests += 1
      requestLog.statisticsScopeIds = [...(requestLog.statisticsScopeIds || []), batchId]
      await waitForResponse('statistics', batchId)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(statisticsPayload) })
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

async function pushClxScopeRoute(page, scopeId) {
  await page.evaluate(async (nextScopeId) => {
    const router = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$router
    if (!router) throw new Error('Vue router is not available')
    await router.push({ path: '/clx-daily-screening', query: { scope_id: nextScopeId } })
  }, scopeId)
}

async function pushDailySelectionNav(page) {
  await page.evaluate(async () => {
    const router = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$router
    if (!router) throw new Error('Vue router is not available')
    await router.push({
      path: '/kline-slim',
      query: { clxScreening: '1', clxWorkbench: '1', period: '1d' },
    })
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

test('legacy entry opens the unified workbench, keeps partial explicit and renders guarded CLX markers', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  await page.setViewportSize({ width: 1600, height: 900 })
  await mockApis(page, requestLog)

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  await expect(page).toHaveURL(/\/kline-slim\?.*clxScreening=1/)
  await expect(page.getByRole('complementary', { name: 'CLX 筛选工作台' })).toBeVisible()
  await expect(page.getByText('暂无正式完整结果；可在上方显式选择部分批次。')).toBeVisible()
  expect(requestLog.resultQueries).toHaveLength(0)

  await page.goto(
    `${DEV_SERVER_URL}/clx-daily-screening?scope_id=${PARTIAL_BATCH_ID}&period=5m`,
    { waitUntil: 'domcontentloaded' },
  )
  await expect(page).toHaveURL(new RegExp(`clxScope=${PARTIAL_BATCH_ID}`))
  await expect(page.locator('.clx-selection-panel__status')).toContainText('部分结果')
  await expect(page.locator('.clx-selection-panel__status')).toContainText('股票已完成')
  await expect(page.locator('.clx-selection-panel__status')).toContainText('ETF运行中')
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  expect(requestLog.statisticsRequests).toBe(0)

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
      y: Number(point.value?.[1]),
      nonTransparentPixels,
    }
  })

  expect(rendered).toMatchObject({ type: 'scatter', count: 1, direction: 'mixed', symbol: 'diamond' })
  expect(Number.isFinite(rendered.y)).toBe(true)
  expect(rendered.y).toBeGreaterThan(0)
  expect(rendered.nonTransparentPixels).toBeGreaterThan(100)

  for (const width of [1200, 1280, 1600]) {
    await page.setViewportSize({ width, height: 900 })
    const layout = await page.evaluate(() => {
      const body = document.querySelector('.kline-slim-body')
      const chart = document.querySelector('.kline-slim-content')
      const workbench = document.querySelector('.kline-slim-clx-workbench')
      const chartRect = chart?.getBoundingClientRect()
      const workbenchRect = workbench?.getBoundingClientRect()
      return {
        chartRight: chartRect?.right,
        workbenchLeft: workbenchRect?.left,
        workbenchPosition: workbench ? window.getComputedStyle(workbench).position : '',
        bodyClientWidth: body?.clientWidth,
        bodyScrollWidth: body?.scrollWidth,
      }
    })
    expect(layout.workbenchPosition).not.toMatch(/^(absolute|fixed)$/)
    expect(layout.chartRight).toBeLessThanOrEqual(layout.workbenchLeft + 1)
    expect(layout.bodyScrollWidth).toBeLessThanOrEqual(layout.bodyClientWidth + 1)
  }
})

test('latest final outside the 30 mixed-scope window remains the complete default', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }

  await page.setViewportSize({ width: 1600, height: 900 })
  await mockApis(page, requestLog, {
    batchItems: buildNewerPartialWindow(),
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    statisticsPayload: finalStatisticsPayload,
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })

  await expect(page.getByText('完整结果', { exact: true })).toBeVisible()
  await expect(page.locator('.clx-selection-panel__controls')).toContainText('2026-02-28')
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  expect(requestLog.resultQueries[0].scope_id).toBe(FINAL_BATCH_ID)
  expect(requestLog.statisticsRequests).toBe(0)
  await expect(page.locator('.kline-slim-clx-workbench')).toContainText('production_v1')
})

test('same-page 每日选股 re-entry restores the default final and first selected symbol', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  await mockApis(page, requestLog, {
    batchItems: buildNewerPartialWindow(),
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect(page).toHaveURL(/clxScope=.*symbol=sz000001/)
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)

  await pushDailySelectionNav(page)

  await expect(page).toHaveURL(new RegExp(`clxScope=${FINAL_BATCH_ID}.*symbol=sz000001`))
  await expect(page.getByRole('button', { name: /平安银行 sz000001/ })).toHaveAttribute('aria-current', 'true')
  await expect.poll(() => requestLog.resultQueries.length).toBe(2)
})

test('a filter changed during initial results loading schedules the current request and clears loading', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    responseDelays: { results: 500 },
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  await page.getByRole('textbox', { name: '搜索代码或名称' }).fill('银行')

  await expect.poll(() => requestLog.resultQueries.length).toBe(2)
  expect(requestLog.resultQueries[1].q).toBe('银行')
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect(page.locator('.clx-selection-panel')).toHaveAttribute('aria-busy', 'false')
})

test('an explicit final scope deep link outside the 30-item window loads all final views', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  await page.setViewportSize({ width: 1600, height: 900 })
  await mockApis(page, requestLog, {
    batchItems: buildNewerPartialWindow(),
    latestPayload: { batch: finalBatch },
    activeBatch: deepLinkedFinalBatch,
    statisticsPayload: finalStatisticsPayload,
  })

  await page.goto(
    `${DEV_SERVER_URL}/clx-daily-screening?scope_id=${encodeURIComponent(DEEP_LINK_BATCH_ID)}`,
    { waitUntil: 'domcontentloaded' },
  )

  await expect(page.getByText('完整结果', { exact: true })).toBeVisible()
  await expect(page.locator('.clx-selection-panel__controls')).toContainText('2026-01-30')
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.summaryRequests).toEqual([DEEP_LINK_BATCH_ID])
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  expect(requestLog.resultQueries[0].scope_id).toBe(DEEP_LINK_BATCH_ID)
  expect(requestLog.statisticsRequests).toBe(0)
  await expect(page).toHaveURL(new RegExp(`clxScope=${DEEP_LINK_BATCH_ID}`))
})

test('a route change during bootstrap invalidates the captured initial scope', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  const scopeA = { ...deepLinkedFinalBatch, batch_id: RACE_SCOPE_A, trade_date: '2026-01-28' }
  const scopeB = { ...deepLinkedFinalBatch, batch_id: RACE_SCOPE_B, trade_date: '2026-01-29' }
  const rowA = { ...resultRow, symbol: 'sz000001', code: '000001', name: '旧导航结果' }
  const rowB = { ...resultRow, symbol: 'sz000002', code: '000002', name: '新导航结果' }

  await mockApis(page, requestLog, {
    batchItems: [scopeA, scopeB],
    activeBatch: scopeA,
    batchPayloads: [scopeB],
    resultRowsByBatch: { [RACE_SCOPE_A]: [rowA], [RACE_SCOPE_B]: [rowB] },
    responseDelays: { batches: 250 },
    statisticsPayload: finalStatisticsPayload,
  })

  await page.goto(
    `${DEV_SERVER_URL}/clx-daily-screening?scope_id=${RACE_SCOPE_A}`,
    { waitUntil: 'domcontentloaded' },
  )
  await expect.poll(() => requestLog.batchRequests || 0).toBeGreaterThan(0)
  await pushClxScopeRoute(page, RACE_SCOPE_B)

  await expect(page).toHaveURL(new RegExp(`clxScope=${RACE_SCOPE_B}`))
  await expect(page.locator('.clx-selection-panel__controls')).toContainText('2026-01-29')
  await expect(page.getByText('新导航结果')).toBeVisible()
  await expect(page.getByText('旧导航结果')).toHaveCount(0)
  await expect.poll(() => requestLog.resultQueries.map((item) => item.scope_id)).toContain(RACE_SCOPE_B)
  expect(requestLog.resultQueries.at(-1).scope_id).toBe(RACE_SCOPE_B)
  expect(requestLog.resultQueries.filter((item) => item.scope_id === RACE_SCOPE_B)).toHaveLength(1)
})

test('a delayed old result cannot overwrite a window-external deep link while its summary loads', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  const scopeA = { ...deepLinkedFinalBatch, batch_id: RACE_SCOPE_A, trade_date: '2026-01-28' }
  const scopeB = { ...deepLinkedFinalBatch, batch_id: RACE_SCOPE_B, trade_date: '2026-01-29' }
  const rowA = { ...resultRow, symbol: 'sz000001', code: '000001', name: '迟到旧结果' }
  const rowB = { ...resultRow, symbol: 'sz000002', code: '000002', name: '权威深链结果' }

  await mockApis(page, requestLog, {
    batchItems: [scopeA],
    latestPayload: { batch: scopeA },
    activeBatch: scopeA,
    batchPayloads: [scopeB],
    resultRowsByBatch: { [RACE_SCOPE_A]: [rowA], [RACE_SCOPE_B]: [rowB] },
    responseDelays: {
      summary: { [RACE_SCOPE_B]: 350 },
      results: { [RACE_SCOPE_A]: 150 },
    },
    statisticsPayload: finalStatisticsPayload,
  })

  await page.goto(
    `${DEV_SERVER_URL}/clx-daily-screening?scope_id=${RACE_SCOPE_A}`,
    { waitUntil: 'domcontentloaded' },
  )
  await expect.poll(() => requestLog.resultQueries.map((item) => item.scope_id)).toContain(RACE_SCOPE_A)
  await pushClxScopeRoute(page, RACE_SCOPE_B)

  await page.waitForTimeout(220)
  await expect(page).toHaveURL(new RegExp(`clxScope=${RACE_SCOPE_B}`))
  await expect(page.getByText('迟到旧结果')).toHaveCount(0)

  await expect(page.locator('.clx-selection-panel__controls')).toContainText('2026-01-29')
  await expect(page.getByText('权威深链结果')).toBeVisible()
  await expect(page.getByText('完整结果', { exact: true })).toBeVisible()
  await expect.poll(() => requestLog.resultQueries.map((item) => item.scope_id)).toEqual([
    RACE_SCOPE_A,
    RACE_SCOPE_B,
  ])
  expect(requestLog.statisticsRequests).toBe(0)
})

test('final published basket uses sibling row actions, dark surfaces and selected-only import once while loading', async ({ page }) => {
  const requestLog = {
    summaryRequests: [],
    resultQueries: [],
    statisticsRequests: 0,
    historyQueries: [],
    tdxImports: [],
  }
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    responseDelays: { tdxImport: 350 },
    tdxImportPayload: { success: true, group_name: 'clx_18', written_count: 1 },
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  const rowItem = page.locator('.clx-selection-panel__row-item').first()
  await expect(rowItem.getByRole('button')).toHaveCount(2)
  const urlBeforeBasketToggle = page.url()
  await rowItem.getByRole('button', { name: '加入通达信 平安银行' }).click()
  await expect(rowItem).toContainText('已加入')
  await expect(page).toHaveURL(urlBeforeBasketToggle)

  const scopeSelect = page.getByRole('combobox', { name: '每日选股结果批次' })
  await expect(scopeSelect).toBeVisible()
  await page.locator('.clx-selection-panel .el-select__wrapper').first().click()
  await expect(page.locator('.el-popper.clx-market-dark-popper[aria-hidden="false"]')).toBeVisible()
  const colors = await page.evaluate(() => {
    const style = (selector) => {
      const element = document.querySelector(selector)
      const computed = element ? window.getComputedStyle(element) : null
      return {
        background: computed?.backgroundColor || '',
        color: computed?.color || '',
      }
    }
    const parseRgb = (value) => (String(value).match(/[\d.]+/g) || []).slice(0, 3).map(Number)
    const luminance = (value) => {
      const channels = parseRgb(value).map((channel) => {
        const normalized = channel / 255
        return normalized <= 0.03928
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4
      })
      return channels.length === 3
        ? 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
        : 0
    }
    const panel = style('.clx-selection-panel')
    const foreground = luminance(panel.color)
    const background = luminance(panel.background)
    const basket = style('.clx-selection-panel__basket-toggle[aria-pressed="true"]')
    const basketForeground = luminance(basket.color)
    const basketBackground = luminance(basket.background)
    return {
      panel,
      row: style('.clx-selection-panel__row-item'),
      input: style('.clx-selection-panel .el-input__wrapper'),
      popper: style('.el-popper.clx-market-dark-popper[aria-hidden="false"]'),
      basket,
      contrast: (Math.max(foreground, background) + 0.05) /
        (Math.min(foreground, background) + 0.05),
      basketContrast: (Math.max(basketForeground, basketBackground) + 0.05) /
        (Math.min(basketForeground, basketBackground) + 0.05),
    }
  })
  await page.keyboard.press('Escape')
  for (const surface of [colors.panel, colors.row, colors.input, colors.popper, colors.basket]) {
    expect(surface.background).not.toBe('rgb(255, 255, 255)')
  }
  expect(colors.contrast).toBeGreaterThan(4.5)
  expect(colors.basketContrast).toBeGreaterThan(4.5)

  const button = page.getByRole('button', { name: '导入通达信（1）', exact: true })
  await expect(button).toBeEnabled()
  await button.click()
  await expect(button).toBeDisabled()
  await button.click({ force: true })
  await expect(page.getByText('已导入通达信分组 clx_18，共 1 只（已覆盖原分组）')).toBeVisible()
  await expect(button).toBeEnabled()
  await expect(rowItem).toContainText('已加入')

  expect(requestLog.tdxImports).toEqual([{
    batchId: FINAL_BATCH_ID,
    payload: {
      items: [{ asset_type: 'stock', symbol: 'sz000001' }],
    },
  }])
})

test('select-all freezes the current filter and unions every result beyond the first 100 rows', async ({ page }) => {
  const requestLog = {
    summaryRequests: [],
    resultQueries: [],
    statisticsRequests: 0,
    historyQueries: [],
    tdxImports: [],
  }
  const allRows = Array.from({ length: 205 }, (_, index) => ({
    ...resultRow,
    asset_type: index % 5 === 0 ? 'etf' : 'stock',
    symbol: String(index + 1).padStart(6, '0'),
    code: String(index + 1).padStart(6, '0'),
    name: `筛选标的${index + 1}`,
  }))
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    resultRowsByBatch: { [FINAL_BATCH_ID]: allRows },
    responseDelays: { results: 120 },
    tdxImportPayload: { success: true, group_name: 'clx_18', written_count: 205 },
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('已加载 100 / 205')).toBeVisible()
  const selectAllQueryStart = requestLog.resultQueries.length
  const selectAll = page.getByRole('button', { name: '全选当前筛选结果' })
  await selectAll.click()
  await expect(selectAll).toBeDisabled()
  await selectAll.dispatchEvent('click')
  await expect(page.getByText('待导入 205 只')).toBeVisible()
  await expect(selectAll).toBeEnabled()

  const fullQueries = requestLog.resultQueries
    .slice(selectAllQueryStart)
    .filter((query) => query.limit === 200)
  expect(fullQueries.map((query) => query.cursor)).toEqual(['', '200'])
  expect(fullQueries.every((query) => query.scope_id === FINAL_BATCH_ID)).toBe(true)

  await page.getByRole('button', { name: '导入通达信（205）', exact: true }).click()
  await expect(page.getByText('已导入通达信分组 clx_18，共 205 只（已覆盖原分组）')).toBeVisible()
  expect(requestLog.tdxImports).toHaveLength(1)
  expect(requestLog.tdxImports[0].payload.items).toHaveLength(205)
})

test('basket remains isolated per batch and restores from session storage after route changes and reload', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  const scopeA = { ...finalBatch, batch_id: RACE_SCOPE_A, trade_date: '2026-01-28' }
  const scopeB = { ...finalBatch, batch_id: RACE_SCOPE_B, trade_date: '2026-01-29' }
  const rowA = { ...resultRow, symbol: '000001', code: '000001', name: '批次A标的' }
  const rowB = { ...resultRow, symbol: '510050', code: '510050', asset_type: 'etf', name: '批次B标的' }
  await mockApis(page, requestLog, {
    batchItems: [scopeA, scopeB],
    latestPayload: { batch: scopeA },
    activeBatch: scopeA,
    resultRowsByBatch: { [RACE_SCOPE_A]: [rowA], [RACE_SCOPE_B]: [rowB] },
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening?scope_id=${RACE_SCOPE_A}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '加入通达信 批次A标的' }).click()
  await expect(page.getByText('待导入 1 只')).toBeVisible()

  await pushClxScopeRoute(page, RACE_SCOPE_B)
  await expect(page.getByText('批次B标的')).toBeVisible()
  await expect(page.getByText('待导入 0 只')).toBeVisible()
  await page.getByRole('button', { name: '加入通达信 批次B标的' }).click()

  await pushClxScopeRoute(page, RACE_SCOPE_A)
  await expect(page.getByText('批次A标的')).toBeVisible()
  await expect(page.getByRole('button', { name: '取消加入通达信 批次A标的' })).toBeVisible()
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: '取消加入通达信 批次A标的' })).toBeVisible()
  await expect(page.getByText('待导入 1 只')).toBeVisible()
})

test('scope navigation aborts select-all and releases its loading state for the new batch', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  const scopeA = { ...finalBatch, batch_id: RACE_SCOPE_A, trade_date: '2026-01-28' }
  const scopeB = { ...finalBatch, batch_id: RACE_SCOPE_B, trade_date: '2026-01-29' }
  const rowsA = Array.from({ length: 205 }, (_, index) => ({
    ...resultRow,
    symbol: String(index + 1).padStart(6, '0'),
    code: String(index + 1).padStart(6, '0'),
    name: `批次A标的${index + 1}`,
  }))
  const rowB = { ...resultRow, symbol: '510050', code: '510050', asset_type: 'etf', name: '批次B标的' }
  await mockApis(page, requestLog, {
    batchItems: [scopeA, scopeB],
    latestPayload: { batch: scopeA },
    activeBatch: scopeA,
    resultRowsByBatch: { [RACE_SCOPE_A]: rowsA, [RACE_SCOPE_B]: [rowB] },
    responseDelays: { results: { [RACE_SCOPE_A]: 350 } },
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening?scope_id=${RACE_SCOPE_A}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('已加载 100 / 205')).toBeVisible()
  const selectAll = page.getByRole('button', { name: '全选当前筛选结果' })
  await selectAll.click()
  await expect(selectAll).toBeDisabled()

  await pushClxScopeRoute(page, RACE_SCOPE_B)
  await expect(page.getByText('批次B标的')).toBeVisible()
  await expect(page.getByRole('button', { name: '全选当前筛选结果' })).toBeEnabled()
  await expect(page.locator('.clx-selection-panel')).toHaveAttribute('aria-busy', 'false')
  await expect(page.getByText('待导入 0 只')).toBeVisible()
})

test('empty filters disable select-all but keep a non-empty basket importable, and partial batches stay ineligible', async ({ page }) => {
  const requestLog = { summaryRequests: [], resultQueries: [], statisticsRequests: 0, historyQueries: [] }
  await mockApis(page, requestLog, {
    batchItems: [finalBatch, partialBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    emptyResultQueries: ['无结果'],
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '加入通达信 平安银行' }).click()
  await page.getByRole('textbox', { name: '搜索代码或名称' }).fill('无结果')
  await expect(page.getByText('当前筛选条件下没有标的。')).toBeVisible()
  await expect(page.getByRole('button', { name: '全选当前筛选结果' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '导入通达信（1）', exact: true })).toBeEnabled()

  await pushClxScopeRoute(page, PARTIAL_BATCH_ID)
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect(page.getByRole('button', { name: '加入通达信 平安银行' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '全选当前筛选结果' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '导入通达信（0）', exact: true })).toBeDisabled()
})

test('filter refresh keeps the last stable list visible and retry replaces it after an error', async ({ page }) => {
  const requestLog = {
    summaryRequests: [],
    resultQueries: [],
    statisticsRequests: 0,
    historyQueries: [],
  }
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    resultFailureCounts: { '银行': 1 },
    responseDelays: { results: 250 },
  })

  await page.goto(`${DEV_SERVER_URL}/clx-daily-screening`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('平安银行')).toBeVisible()

  await page.getByRole('textbox', { name: '搜索代码或名称' }).fill('银行')
  await expect(page.getByText('更新中 · 旧结果保留')).toBeVisible()
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect(page.getByText('筛选结果更新失败')).toBeVisible()
  await expect(page.getByText('平安银行')).toBeVisible()

  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('筛选结果更新失败')).toBeHidden()
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.resultQueries.filter((query) => query.q === '银行').length).toBe(2)

  await page.getByRole('button', { name: '刷新 CLX 筛选批次和结果' }).click()
  await expect(page.getByText('更新中 · 旧结果保留')).toBeVisible()
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect(page.getByText('已加载 1 / 1')).toBeVisible()
})
