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

const READY_BATCH_ID = 'clx-2026-08-07-production_v1-b55928c40a7bdf50'
const RESULT_TIME = '2026-08-07T20:00:00+08:00'
const TRADE_DATE = '2026-08-07'

let devServerProcess = null

const readyRow = {
  asset_type: 'stock',
  symbol: '000001',
  code: '000001',
  name: '平安银行',
  distinct_model_count: 2,
  distinct_condition_count: 2,
  signal_event_count: 2,
  model_keys: ['S0003', 'S0007'],
  condition_keys: ['entrypoint_1', 'entrypoint_2'],
  latest_trigger: '2026-08-07',
}

const etfRow = {
  asset_type: 'etf',
  symbol: '510300',
  code: '510300',
  name: '沪深300ETF',
  distinct_model_count: 1,
  distinct_condition_count: 1,
  signal_event_count: 1,
  model_keys: ['S0003'],
  condition_keys: ['entrypoint_1'],
  latest_trigger: '2026-08-07',
}

function buildOfficialPayload({ rows, cursor = '', limit = 100, total = 0, nextCursor = '' } = {}) {
  return {
    schema_version: '1',
    status: 'ready',
    trade_date: TRADE_DATE,
    batch_id: READY_BATCH_ID,
    generation_id: 'gen-2026-08-07-1',
    generation_order: '1',
    publication_id: 'pub-2026-08-07-1',
    content_hash: '18f75c',
    result_time: RESULT_TIME,
    release_status: 'final',
    is_final: true,
    counts: { pure_buy_total: total, stock: 1, etf: 1 },
    rows,
    total,
    next_cursor: nextCursor || '',
    cursor,
    limit,
  }
}

function buildLatestEvaluationManifest() {
  return {
    tradeDate: TRADE_DATE,
    runId: 'run-2026-08-08-01',
    promotedAt: '2026-08-08T09:00:00+08:00',
    href: '/data/clx-evaluator/clx-eval.v1.json',
  }
}

function buildEvaluationSnapshot() {
  return {
    tradeDate: TRADE_DATE,
    runId: 'run-2026-08-08-01',
    clxBatchId: READY_BATCH_ID,
    officialContentHash: '18f75c',
    review: { generatedAt: '2026-08-08T09:00:00+08:00' },
    summary: {
      stockRows: 1,
      groupCount: 1,
      remainingUnmapped: 0,
      fundamentalEvidenceGap: 0,
      mappedEtfCount: 1,
    },
    groups: [
      {
        groupRank: 1,
        groupName: '银行',
        marketLane: '金融',
        marketFitGrade: 'A',
        themeId: 'banking',
        clxStockCount: 1,
        shortlistCount: 1,
        clxGroupAmountYi: 120,
        fitReason: '主线吻合',
      },
    ],
    members: [
      {
        symbol: '000001',
        name: '平安银行',
        primaryGroup: '银行',
        marketLane: '金融',
        marketFitGrade: 'A',
        fundamentalQualityGrade: 'B+',
        riskFlagGrade: '低',
        shortlistEligible: true,
        globalRank: 1,
        memberRank: 1,
      },
    ],
    diagnostics: { sellDiagnostics: [] },
  }
}

const defaultRequestLog = () => ({
  officialQueries: [],
  evaluationRequests: 0,
  poolListRequests: [],
  stockSyncRequests: [],
  mustSyncRequests: [],
  tdxExports: [],
})

async function mockApis(page, requestLog, {
  officialPayload = buildOfficialPayload({ rows: [readyRow], total: 2 }),
  officialRowsByCursor = null,
  latestManifest = buildLatestEvaluationManifest(),
  poolRows = {},
  syncPayload = {
    code: '0',
    msg: '操作成功',
    data: {
      source_count: 2,
      synced_count: 1,
      removed_count: 1,
      holding_excluded_count: 1,
      invalid_count: 0,
      failed_count: 0,
      failed_codes: [],
    },
  },
  tdxExportPayload = { written_count: 2 },
} = {}) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    const method = request.method()

    if (pathname === '/api/clx-daily-selection/official') {
      const query = Object.fromEntries(url.searchParams.entries())
      requestLog.officialQueries.push(query)
      const cursor = query.cursor || ''
      const payload = officialRowsByCursor
        ? officialRowsByCursor(cursor, query)
        : officialPayload
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload),
      })
      return
    }

    if (pathname === '/api/get_stock_pre_pools_list') {
      requestLog.poolListRequests.push('pre')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(poolRows.pre || []),
      })
      return
    }

    if (pathname === '/api/get_stock_pools_list') {
      requestLog.poolListRequests.push('stock')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(poolRows.stock || []),
      })
      return
    }

    if (pathname === '/api/get_stock_must_pools_list') {
      requestLog.poolListRequests.push('must')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(poolRows.must || []),
      })
      return
    }

    if (pathname === '/api/pools/stock/sync-from-tdx' && method === 'POST') {
      requestLog.stockSyncRequests.push(Object.fromEntries(url.searchParams.entries()))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(syncPayload),
      })
      return
    }

    if (pathname === '/api/pools/must/sync-from-tdx' && method === 'POST') {
      requestLog.mustSyncRequests.push(Object.fromEntries(url.searchParams.entries()))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(syncPayload),
      })
      return
    }

    const tdxExportMatch = pathname.match(/^\/api\/clx-daily-selection\/batches\/([^/]+)\/results\/sync-selected-to-tdx$/)
    if (tdxExportMatch && method === 'POST') {
      requestLog.tdxExports.push({
        batchId: decodeURIComponent(tdxExportMatch[1]),
        payload: request.postDataJSON?.() || {},
      })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(tdxExportPayload),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    })
  })

  await page.route('**/data/clx-evaluator/latest.json', async (route) => {
    requestLog.evaluationRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(latestManifest),
    })
  })

  await page.route('**/data/clx-evaluator/clx-eval.v1.json', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildEvaluationSnapshot()),
    })
  })
}

async function waitForWorkbench(page) {
  await expect(page.locator('.clx-workbench-page')).toBeVisible()
  await expect(page.locator('.clx-result-panel')).toBeVisible()
  await expect(page.locator('.clx-eval-panel')).toBeVisible()
  await expect(page.locator('.clx-pools-panel')).toBeVisible()
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

test('legacy entry redirects to the daily-screening workbench with mapped query', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page, requestLog)

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening?scope_id=' + READY_BATCH_ID + '&period=5m&clxScreening=1', {
    waitUntil: 'domcontentloaded',
  })

  await expect(page).toHaveURL(new RegExp('/daily-screening\\?.*tab=clx'))
  await expect(page).toHaveURL(new RegExp('scope_id=' + READY_BATCH_ID))
  await expect(page).not.toHaveURL(/clxScreening|period=5m/)
  await waitForWorkbench(page)
  await expect(page.getByText('每日选股工作台')).toBeVisible()
  await expect.poll(() => requestLog.officialQueries.length).toBeGreaterThan(0)
  expect(requestLog.officialQueries[0].direction_mode).toBe('pure_buy')
})

test('left panel renders the ready generation pure-buy rows and independent result time', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page, requestLog)

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForWorkbench(page)

  await expect(page.locator('.clx-result-panel')).toContainText('CLX pure-buy 结果')
  await expect(page.locator('.clx-result-panel .clx-panel-time')).toContainText('2026-08-07T20:00:00+08:00')
  await expect(page.locator('.clx-result-panel .clx-panel-kpis')).toContainText('pure-buy')
  await expect(page.locator('.clx-result-panel .clx-panel-kpis')).toContainText('Stock')
  await expect(page.locator('.clx-result-panel .clx-panel-kpis')).toContainText('ETF')
  await expect(page.locator('.clx-result-panel .clx-panel-row').first()).toContainText('000001')
  await expect(page.locator('.clx-result-panel .clx-panel-row').first()).toContainText('平安银行')

  expect(requestLog.officialQueries).toHaveLength(1)
  expect(requestLog.officialQueries[0]).toMatchObject({
    direction_mode: 'pure_buy',
    limit: '100',
  })
})

test('left panel search filters rows and load-more follows the cursor contract', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  const allRows = Array.from({ length: 105 }, (_, index) => ({
    ...readyRow,
    asset_type: index % 5 === 0 ? 'etf' : 'stock',
    symbol: String(index + 1).padStart(6, '0'),
    code: String(index + 1).padStart(6, '0'),
    name: '筛选标的' + (index + 1),
  }))
  await mockApis(page, requestLog, {
    officialRowsByCursor: (cursor, query) => {
      const offset = Number(cursor || 0)
      const limit = Number(query.limit || 100)
      const pageRows = allRows.slice(offset, offset + limit)
      const nextCursor = offset + limit < allRows.length ? String(offset + limit) : ''
      return buildOfficialPayload({
        rows: pageRows,
        total: allRows.length,
        nextCursor,
      })
    },
  })

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForWorkbench(page)
  await expect(page.locator('.clx-result-panel .clx-panel-row').first()).toContainText('筛选标的1')

  await page.getByPlaceholder('搜索代码或名称').fill('筛选标的51')
  await expect(page.locator('.clx-result-panel .clx-panel-row')).toHaveCount(1)
  await expect(page.locator('.clx-result-panel .clx-panel-row')).toContainText('筛选标的51')
  await page.getByPlaceholder('搜索代码或名称').fill('')

  const list = page.locator('.clx-result-panel .clx-panel-list')
  await list.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  await expect.poll(() => requestLog.officialQueries.length).toBeGreaterThan(1)
  expect(requestLog.officialQueries.at(-1).cursor).toBe('100')
  await expect(page.locator('.clx-result-panel .clx-panel-row').last()).toContainText('筛选标的105')
})

test('export current result posts the ready batch items to CLX_18', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page, requestLog, {
    officialPayload: buildOfficialPayload({ rows: [readyRow, etfRow], total: 2 }),
    tdxExportPayload: { written_count: 2 },
  })

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForWorkbench(page)
  await expect(page.locator('.clx-result-panel .clx-panel-row').first()).toBeVisible()

  await page.getByRole('button', { name: '导出当前结果到 CLX_18' }).click()
  await expect(page.getByText('已导出当前结果到 CLX_18：2 只')).toBeVisible()
  expect(requestLog.tdxExports).toHaveLength(1)
  expect(requestLog.tdxExports[0].batchId).toBe(READY_BATCH_ID)
  expect(requestLog.tdxExports[0].payload.items).toEqual([
    { asset_type: 'stock', symbol: '000001' },
    { asset_type: 'etf', symbol: '510300' },
  ])
})

test('evaluation panel shows evaluation time and evaluated object time independently', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page, requestLog)

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForWorkbench(page)

  await expect(page.locator('.clx-eval-panel')).toContainText('最新 CLX 评价')
  await expect(page.locator('.clx-eval-panel .clx-panel-time').first()).toContainText('评价结果时间')
  await expect(page.locator('.clx-eval-panel .clx-panel-time').first()).toContainText('2026-08-08T09:00:00+08:00')
  await expect(page.locator('.clx-eval-panel .clx-panel-time').nth(1)).toContainText('评价对象时间')
  await expect(page.locator('.clx-eval-panel .clx-panel-time').nth(1)).toContainText('2026-08-07')
  await expect(page.locator('.clx-eval-group-card').first()).toContainText('银行')
  await expect(page.locator('.clx-eval-table-wrap')).toContainText('平安银行')
  await expect.poll(() => requestLog.evaluationRequests).toBeGreaterThan(0)
})

test('pools panel loads pre/stock/must lists and offers TDX overwrite sync for stock and must only', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page, requestLog, {
    poolRows: {
      pre: [{
        code: '000001',
        name: '平安银行',
        asset_type: 'stock',
        sources: ['clx_daily_selection'],
      }],
      stock: [{ code: '000002', name: '万科A' }],
      must: [{ code: '000003', name: '宁德时代' }],
    },
  })

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForWorkbench(page)

  await expect(page.locator('.clx-pools-panel')).toContainText('三池工作区')
  await expect(page.locator('.clx-pools-panel .clx-pool-row').first()).toContainText('000001')
  await expect(page.locator('.clx-pools-panel')).toContainText('预选池由 CLX 正式结果自动生成，只读展示')
  await expect(page.getByRole('button', { name: '同步自选股' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '同步待买组' })).toHaveCount(0)
  expect(requestLog.poolListRequests).toEqual(expect.arrayContaining(['pre', 'stock', 'must']))

  await page.locator('.clx-pool-tab', { hasText: '监控池' }).click()
  await expect(page.getByRole('button', { name: '同步自选股' })).toBeVisible()
  await page.locator('.clx-pool-tab', { hasText: '待买池' }).click()
  await expect(page.getByRole('button', { name: '同步待买组' })).toBeVisible()
})

test('stock and must TDX sync require confirmation and post to the overwrite endpoints', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page, requestLog)

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await waitForWorkbench(page)

  await page.locator('.clx-pool-tab', { hasText: '监控池' }).click()
  await page.getByRole('button', { name: '同步自选股' }).click()
  await expect(page.getByText('将使用通达信“自选股”覆盖当前监控池，并自动排除持仓股。是否继续？')).toBeVisible()
  await page.getByRole('button', { name: '继续' }).click()
  await expect.poll(() => requestLog.stockSyncRequests.length).toBe(1)
  expect(requestLog.stockSyncRequests[0].days).toBe('30')
  await expect(page.locator('.clx-pool-sync-summary')).toContainText('源 2 个代码')

  await page.locator('.clx-pool-tab', { hasText: '待买池' }).click()
  await page.getByRole('button', { name: '同步待买组' }).click()
  await expect(page.getByText('将使用通达信“待买组”覆盖当前待买池，并自动排除持仓股；新代码自动使用系统默认参数。是否继续？')).toBeVisible()
  await page.getByRole('button', { name: '继续' }).click()
  await expect.poll(() => requestLog.mustSyncRequests.length).toBe(1)
  expect(requestLog.mustSyncRequests[0].days).toBe('30')
})

test('clx-evaluation legacy route redirects to the daily-screening workbench', async ({ page }) => {
  const requestLog = defaultRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page, requestLog)

  await page.goto(DEV_SERVER_URL + '/clx-evaluation', { waitUntil: 'domcontentloaded' })
  await expect(page).toHaveURL(/\/daily-screening$/)
  await waitForWorkbench(page)
  await expect(page.locator('.clx-eval-panel')).toBeVisible()
})
