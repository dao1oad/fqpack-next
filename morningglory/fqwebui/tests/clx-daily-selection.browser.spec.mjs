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
const DEV_SERVER_URL = 'http://127.0.0.1:' + DEV_SERVER_PORT
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
  latest_price: 10.2,
  change_pct: 1.23,
  distinct_model_count: 2,
  distinct_condition_count: 2,
  signal_event_count: 2,
  model_keys: ['S0003', 'S0007'],
  condition_keys: ['entrypoint_1', 'entrypoint_2'],
  latest_trigger: '2026-03-10',
  above_ma250: { state: 'yes', line_value: 10.08, source: 'daily_close_ma250' },
  above_chanlun_line: { state: 'yes' },
  above_reference_line: { state: 'unknown' },
}

function buildKlinePayload(period = '5m') {
  const suffix = period === '1d' ? '' : ' 15:00:00'
  const dates = ['2026-03-09' + suffix, '2026-03-10' + suffix]
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
    updated_at: '2026-03-10:' + period,
  }
}

const buildNewerPartialWindow = () => Array.from({ length: 30 }, (_, index) => ({
  ...partialBatch,
  batch_id: 'partial-window-' + String(index + 1).padStart(2, '0'),
  trade_date: '2026-03-' + String(30 - index).padStart(2, '0'),
  updated_at: '2026-03-' + String(30 - index).padStart(2, '0') + 'T18:00:00+08:00',
}))

const finalStatisticsPayload = {
  counts: { stock: 1, etf: 1, total: 2 },
  by_model: [{ model_key: 'S0003', symbol_count: 1 }],
  by_condition: [{ condition_key: 'entrypoint_1', symbol_count: 1 }],
  resonance_distribution: [{ distinct_model_count: 2, symbol_count: 1 }],
}

const defaultRequestLog = () => ({
  batchRequests: 0,
  summaryRequests: [],
  resultQueries: [],
  statisticsRequests: 0,
  statisticsScopeIds: [],
  historyQueries: [],
  detailRequests: [],
  tdxImports: [],
  stockPoolAppends: [],
})

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
      const limit = Math.max(1, Math.min(200, Number(query.limit) || 50))
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
      requestLog.tdxImports.push({
        batchId,
        payload: request.postDataJSON?.() || {},
      })
      await waitForResponse('tdxImport', batchId)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(tdxImportPayload),
      })
      return
    }

    const detailMatch = pathname.match(/^\/api\/clx-daily-selection\/batches\/([^/]+)\/results\/([^/]+)\/([^/]+)$/)
    if (detailMatch) {
      const batchId = decodeURIComponent(detailMatch[1])
      const assetType = decodeURIComponent(detailMatch[2])
      const symbol = decodeURIComponent(detailMatch[3])
      const row = (resultRowsByBatch[batchId] || [resultRow]).find((item) => (
        item.symbol === symbol || item.code === symbol
      )) || resultRow
      requestLog.detailRequests.push({ batchId, assetType, symbol })
      await waitForResponse('detail', batchId)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          snapshot: row,
          memberships: [{
            model_key: 'S0003',
            condition_key: 'entrypoint_1',
            direction: 'buy',
            trigger_date: row.latest_trigger || '2026-03-10',
            signal_value_raw: 301,
            condition_evidence: [{ key: 'above_ma250', value: 'yes' }],
          }],
        }),
      })
      return
    }

    if (pathname.endsWith('/statistics')) {
      const batchId = decodeURIComponent(pathname.split('/').at(-2) || '')
      requestLog.statisticsRequests += 1
      requestLog.statisticsScopeIds.push(batchId)
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

    if (pathname === '/api/gantt/stocks') {
      requestLog.stockPoolAppends.push(request.postDataJSON?.() || {})
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ appended_count: 1, skipped_count: 0 }),
      })
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
    await router.push({ path: '/daily-screening', query: { tab: 'clx', scope_id: nextScopeId } })
  }, scopeId)
}

async function pushDailySelectionNav(page) {
  await page.evaluate(async () => {
    const router = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$router
    if (!router) throw new Error('Vue router is not available')
    await router.push({ path: '/daily-screening', query: { tab: 'clx' } })
  })
}

async function waitForClxWorkbench(page) {
  await expect(page.locator('.clx-screening-page')).toBeVisible()
  await expect(page.getByRole('tab', { name: 'CLX 18 模型' })).toHaveAttribute('aria-selected', 'true')
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

test('legacy entry redirects to daily-screening CLX tab and explicit partial scope stays guarded', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 1600, height: 900 })
  await mockApis(page, requestLog)

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForClxWorkbench(page)
  await expect(page).toHaveURL(/\/daily-screening\?.*tab=clx/)
  await expect(page).not.toHaveURL(/\/kline-slim/)
  await expect(page.getByText('最新运行 2026-03-10')).toBeVisible()
  await expect(page.getByText('查看部分结果')).toBeVisible()
  expect(requestLog.resultQueries).toHaveLength(0)

  await page.goto(
    DEV_SERVER_URL + '/clx-daily-screening?scope_id=' + PARTIAL_BATCH_ID + '&period=5m&clxScreening=1',
    { waitUntil: 'domcontentloaded' },
  )
  await waitForClxWorkbench(page)
  await expect(page).toHaveURL(new RegExp('/daily-screening\\?.*scope_id=' + PARTIAL_BATCH_ID))
  await expect(page).toHaveURL(/tab=clx/)
  await expect(page).not.toHaveURL(/clxScreening|period=5m|clxScope=/)
  await expect(page.locator('.clx-scope-state-row')).toContainText('部分结果')
  await expect(page.locator('.clx-scope-state-row')).toContainText('股票已完成')
  await expect(page.locator('.clx-scope-state-row')).toContainText('ETF运行中')
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  expect(requestLog.resultQueries[0].scope_id).toBe(PARTIAL_BATCH_ID)
  expect(requestLog.statisticsRequests).toBe(0)
})

test('latest final outside the 30 mixed-scope window remains the complete default', async ({ page }) => {
  const requestLog = defaultRequestLog()

  await page.setViewportSize({ width: 1600, height: 900 })
  await mockApis(page, requestLog, {
    batchItems: buildNewerPartialWindow(),
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    statisticsPayload: finalStatisticsPayload,
  })

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForClxWorkbench(page)

  await expect(page).toHaveURL(new RegExp('/daily-screening\\?.*scope_id=' + FINAL_BATCH_ID))
  await expect(page.locator('.clx-scope-state-row')).toContainText('完整结果')
  await expect(page.locator('.clx-screening-header')).toContainText('2026-02-28')
  await expect(page.locator('.clx-results-toolbar')).toContainText('1 条服务端结果')
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  expect(requestLog.resultQueries[0].scope_id).toBe(FINAL_BATCH_ID)
  await expect.poll(() => requestLog.statisticsRequests).toBe(1)
  expect(requestLog.statisticsScopeIds).toEqual([FINAL_BATCH_ID])
})

test('same-page 每日选股 re-entry restores the default final and syncs selected symbol only after row click', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await mockApis(page, requestLog, {
    batchItems: buildNewerPartialWindow(),
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
  })

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForClxWorkbench(page)
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect(page).toHaveURL(new RegExp('scope_id=' + FINAL_BATCH_ID))
  await expect(page).not.toHaveURL(/symbol=sz000001/)
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('tab', { name: '综合交集' })).toHaveAttribute('aria-selected', 'true')
  await pushDailySelectionNav(page)

  await waitForClxWorkbench(page)
  await expect(page).toHaveURL(new RegExp('scope_id=' + FINAL_BATCH_ID))
  await expect(page).not.toHaveURL(/symbol=sz000001/)
  await expect(page.getByText('平安银行')).toBeVisible()
  await page.locator('.clx-results-table-wrap .el-table__body-wrapper tbody tr.el-table__row').first().click({ position: { x: 180, y: 12 } })
  await expect.poll(() => requestLog.detailRequests.length).toBe(1)
  await expect(page).toHaveURL(new RegExp('scope_id=' + FINAL_BATCH_ID + '.*symbol=sz000001'))
  await expect(page.locator('.clx-detail-panel')).toContainText('entrypoint_1')
  expect(requestLog.resultQueries.map((item) => item.scope_id)).toEqual([FINAL_BATCH_ID, FINAL_BATCH_ID])
})

test('filter changes use current scope_id query contract and clear the results loading mask', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    responseDelays: { results: 120 },
  })

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('平安银行')).toBeVisible()
  await page.getByPlaceholder('代码或名称').fill('银行')

  await expect.poll(() => requestLog.resultQueries.length).toBe(2)
  expect(requestLog.resultQueries[1].scope_id).toBe(FINAL_BATCH_ID)
  expect(requestLog.resultQueries[1].q).toBe('银行')
  await expect(page).toHaveURL(new RegExp('scope_id=' + FINAL_BATCH_ID + '.*q='))
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect(page.locator('.clx-results-table-wrap .el-loading-mask')).toHaveCount(0)
})

test('an explicit final scope deep link outside the 30-item window loads summary, statistics and results', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 1600, height: 900 })
  await mockApis(page, requestLog, {
    batchItems: buildNewerPartialWindow(),
    latestPayload: { batch: finalBatch },
    activeBatch: deepLinkedFinalBatch,
    statisticsPayload: finalStatisticsPayload,
  })

  await page.goto(
    DEV_SERVER_URL + '/clx-daily-screening?scope_id=' + encodeURIComponent(DEEP_LINK_BATCH_ID),
    { waitUntil: 'domcontentloaded' },
  )

  await waitForClxWorkbench(page)
  await expect(page).toHaveURL(new RegExp('/daily-screening\\?.*scope_id=' + DEEP_LINK_BATCH_ID))
  await expect(page.locator('.clx-scope-state-row')).toContainText('完整结果')
  await expect(page.locator('.clx-screening-header')).toContainText('2026-01-30')
  await expect(page.getByText('平安银行')).toBeVisible()
  await expect.poll(() => requestLog.summaryRequests).toEqual([DEEP_LINK_BATCH_ID])
  await expect.poll(() => requestLog.resultQueries.length).toBe(1)
  expect(requestLog.resultQueries[0].scope_id).toBe(DEEP_LINK_BATCH_ID)
  await expect.poll(() => requestLog.statisticsRequests).toBe(1)
  expect(requestLog.statisticsScopeIds).toEqual([DEEP_LINK_BATCH_ID])
})

test('a route change during bootstrap invalidates the captured initial scope', async ({ page }) => {
  const requestLog = defaultRequestLog()
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
    DEV_SERVER_URL + '/clx-daily-screening?scope_id=' + RACE_SCOPE_A,
    { waitUntil: 'domcontentloaded' },
  )
  await expect.poll(() => requestLog.batchRequests).toBeGreaterThan(0)
  await pushClxScopeRoute(page, RACE_SCOPE_B)

  await expect(page).toHaveURL(new RegExp('scope_id=' + RACE_SCOPE_B))
  await expect(page.locator('.clx-screening-header')).toContainText('2026-01-29')
  await expect(page.getByText('新导航结果')).toBeVisible()
  await expect(page.getByText('旧导航结果')).toHaveCount(0)
  await expect.poll(() => requestLog.resultQueries.map((item) => item.scope_id)).toContain(RACE_SCOPE_B)
  expect(requestLog.resultQueries.at(-1).scope_id).toBe(RACE_SCOPE_B)
  expect(requestLog.resultQueries.filter((item) => item.scope_id === RACE_SCOPE_B)).toHaveLength(1)
})

test('a delayed old result cannot overwrite a window-external deep link while its summary loads', async ({ page }) => {
  const requestLog = defaultRequestLog()
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
    DEV_SERVER_URL + '/clx-daily-screening?scope_id=' + RACE_SCOPE_A,
    { waitUntil: 'domcontentloaded' },
  )
  await expect.poll(() => requestLog.resultQueries.map((item) => item.scope_id)).toContain(RACE_SCOPE_A)
  await pushClxScopeRoute(page, RACE_SCOPE_B)

  await page.waitForTimeout(220)
  await expect(page).toHaveURL(new RegExp('scope_id=' + RACE_SCOPE_B))
  await expect(page.getByText('迟到旧结果')).toHaveCount(0)

  await expect(page.locator('.clx-screening-header')).toContainText('2026-01-29')
  await expect(page.getByText('权威深链结果')).toBeVisible()
  await expect(page.locator('.clx-scope-state-row')).toContainText('完整结果')
  await expect.poll(() => requestLog.resultQueries.map((item) => item.scope_id)).toEqual([
    RACE_SCOPE_A,
    RACE_SCOPE_B,
  ])
})

test('final published visible rows import once while loading and keeps the current URL unchanged', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    responseDelays: { tdxImport: 350 },
    tdxImportPayload: { success: true, group_name: 'clx_18', written_count: 1 },
  })

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('平安银行')).toBeVisible()
  const button = page.getByRole('button', { name: '导入通达信', exact: true })
  const urlBeforeImport = page.url()

  await expect(button).toBeEnabled()
  await button.click()
  await expect(button).toBeDisabled()
  await button.click({ force: true })
  await expect(page.getByText('已导入通达信 clx_18：1 条')).toBeVisible()
  await expect(button).toBeEnabled()
  await expect(page).toHaveURL(urlBeforeImport)

  expect(requestLog.tdxImports).toEqual([{
    batchId: FINAL_BATCH_ID,
    payload: {
      items: [{ asset_type: 'stock', symbol: 'sz000001' }],
    },
  }])
})

test('pagination imports only the currently visible server page', async ({ page }) => {
  const requestLog = defaultRequestLog()
  const allRows = Array.from({ length: 105 }, (_, index) => ({
    ...resultRow,
    asset_type: index % 5 === 0 ? 'etf' : 'stock',
    symbol: String(index + 1).padStart(6, '0'),
    code: String(index + 1).padStart(6, '0'),
    name: '筛选标的' + (index + 1),
  }))
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
    resultRowsByBatch: { [FINAL_BATCH_ID]: allRows },
    tdxImportPayload: { success: true, group_name: 'clx_18', written_count: 50 },
  })

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.clx-results-toolbar')).toContainText('105 条服务端结果')
  await expect(page.getByText('筛选标的1', { exact: true })).toBeVisible()
  await expect(page.getByText('筛选标的51', { exact: true })).toHaveCount(0)
  expect(requestLog.resultQueries[0]).toMatchObject({ scope_id: FINAL_BATCH_ID, cursor: '', limit: 50 })

  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByText('筛选标的51', { exact: true })).toBeVisible()
  await expect(page.getByText('筛选标的1', { exact: true })).toHaveCount(0)
  expect(requestLog.resultQueries.at(-1)).toMatchObject({ scope_id: FINAL_BATCH_ID, cursor: '50', limit: 50 })

  await page.getByRole('button', { name: '导入通达信', exact: true }).click()
  await expect(page.getByText('已导入通达信 clx_18：50 条')).toBeVisible()
  expect(requestLog.tdxImports).toHaveLength(1)
  expect(requestLog.tdxImports[0].payload.items).toHaveLength(50)
  expect(requestLog.tdxImports[0].payload.items[0]).toEqual({ asset_type: 'etf', symbol: '000051' })
})

test('explicit row chart action keeps Kline legacy query compatibility', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await mockApis(page, requestLog, {
    batchItems: [finalBatch],
    latestPayload: { batch: finalBatch },
    activeBatch: finalBatch,
  })

  await page.goto(
    DEV_SERVER_URL + '/clx-daily-screening?scope_id=' + FINAL_BATCH_ID + '&model_keys=S0003&condition_keys=entrypoint_1',
    { waitUntil: 'domcontentloaded' },
  )
  await expect(page.getByText('平安银行')).toBeVisible()

  await page.getByRole('button', { name: '看图' }).first().click()
  await expect(page).toHaveURL(/\/kline-slim\?/)
  await expect(page).toHaveURL(/symbol=sz000001/)
  await expect(page).toHaveURL(/period=1d/)
  await expect(page).toHaveURL(new RegExp('clxScope=' + FINAL_BATCH_ID))
  await expect(page).toHaveURL(/clxWorkbench=1/)
  await expect(page).toHaveURL(/clxModels=S0003/)
  await expect(page).toHaveURL(/clxConditions=entrypoint_1/)
  await expect.poll(() => requestLog.historyQueries.length).toBeGreaterThan(0)
  expect(requestLog.historyQueries.at(-1).includeRaw).toBe('1')
})
