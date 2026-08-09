import { test, expect } from '@playwright/test'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  startPreviewServer,
  stopDevServer,
  waitForServer,
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18092
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/daily-screening`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)

let devServerProcess = null

async function runBuild() {
  await runLockedBuild(
    () => ({
      command: process.execPath,
      args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build'],
    }),
    process.cwd(),
    {
      outDir: PREVIEW_ARTIFACTS.outDirRelative,
    },
  )
}

const READY_BATCH_ID = 'clx-2026-08-07-production_v1-b55928c40a7bdf50'
const RESULT_TIME = '2026-08-07T20:00:00+08:00'
const TRADE_DATE = '2026-08-07'

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
  latest_trigger: TRADE_DATE,
}

const requestLog = {
  officialQueries: [],
  evaluationRequests: 0,
  poolListRequests: [],
  legacyDailyScreeningRequests: [],
  shouban30Requests: [],
}

const resetRequestLog = () => {
  requestLog.officialQueries.length = 0
  requestLog.evaluationRequests = 0
  requestLog.poolListRequests.length = 0
  requestLog.legacyDailyScreeningRequests.length = 0
  requestLog.shouban30Requests.length = 0
}

async function mockWorkbenchApis(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname

    if (pathname === '/api/clx-daily-selection/official') {
      requestLog.officialQueries.push(Object.fromEntries(url.searchParams.entries()))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: '1',
          status: 'ready',
          trade_date: TRADE_DATE,
          batch_id: READY_BATCH_ID,
          generation_id: 'gen-2026-08-07-1',
          publication_id: 'pub-2026-08-07-1',
          content_hash: '18f75c',
          result_time: RESULT_TIME,
          release_status: 'final',
          is_final: true,
          counts: { pure_buy_total: 2, stock: 1, etf: 1 },
          rows: [readyRow],
          total: 2,
          next_cursor: '',
        }),
      })
      return
    }

    if (pathname === '/api/get_stock_pre_pools_list') {
      requestLog.poolListRequests.push('pre')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ code: '000001', name: '平安银行', asset_type: 'stock' }]),
      })
      return
    }

    if (pathname === '/api/get_stock_pools_list') {
      requestLog.poolListRequests.push('stock')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ code: '000002', name: '万科A' }]),
      })
      return
    }

    if (pathname === '/api/get_stock_must_pools_list') {
      requestLog.poolListRequests.push('must')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ code: '000003', name: '宁德时代' }]),
      })
      return
    }

    if (
      pathname.startsWith('/api/daily-screening/') ||
      pathname.startsWith('/api/gantt/shouban30/')
    ) {
      if (pathname.startsWith('/api/daily-screening/')) {
        requestLog.legacyDailyScreeningRequests.push(pathname)
      } else {
        requestLog.shouban30Requests.push(pathname)
      }
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ error: `${pathname} retired` }),
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
      body: JSON.stringify({
        tradeDate: TRADE_DATE,
        runId: 'run-2026-08-08-01',
        promotedAt: '2026-08-08T09:00:00+08:00',
        href: '/data/clx-evaluator/clx-eval.v1.json',
      }),
    })
  })

  await page.route('**/data/clx-evaluator/clx-eval.v1.json', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tradeDate: TRADE_DATE,
        runId: 'run-2026-08-08-01',
        clxBatchId: READY_BATCH_ID,
        officialContentHash: '18f75c',
        review: { generatedAt: '2026-08-08T09:00:00+08:00' },
        summary: { stockRows: 1, groupCount: 1, remainingUnmapped: 0, fundamentalEvidenceGap: 0, mappedEtfCount: 1 },
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
      }),
    })
  })
}

test.beforeAll(async () => {
  test.setTimeout(120000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runBuild()
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
})

test('daily-screening workbench renders the fixed three-panel layout without page-level scroll', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockWorkbenchApis(page)

  await page.goto(TARGET_URL)

  await expect(page.locator('.workbench-page-title')).toContainText('每日选股工作台')
  await expect(page.locator('.clx-result-panel')).toBeVisible()
  await expect(page.locator('.clx-eval-panel')).toBeVisible()
  await expect(page.locator('.clx-pools-panel')).toBeVisible()

  await expect(page.locator('.clx-result-panel')).toContainText('CLX pure-buy 结果')
  await expect(page.locator('.clx-eval-panel')).toContainText('最新 CLX 评价')
  await expect(page.locator('.clx-pools-panel')).toContainText('三池工作区')

  await expect(page.locator('.clx-result-panel .clx-panel-row').first()).toContainText('平安银行')
  await expect(page.locator('.clx-eval-group-card').first()).toContainText('银行')
  await expect(page.locator('.clx-pools-panel .clx-pool-row').first()).toContainText('000001')

  const gridColumns = await page.locator('.clx-workbench-grid').evaluate((element) =>
    window.getComputedStyle(element).gridTemplateColumns.split(' ').length,
  )
  expect(gridColumns).toBe(3)

  const viewportFit = await page.evaluate(() => {
    const scrollingElement = document.scrollingElement || document.documentElement
    return {
      innerHeight: window.innerHeight,
      scrollHeight: scrollingElement.scrollHeight,
    }
  })
  expect(viewportFit.scrollHeight).toBeLessThanOrEqual(viewportFit.innerHeight + 4)

  const resultListOverflow = await page.locator('.clx-result-panel .clx-panel-list').evaluate(
    (element) => window.getComputedStyle(element).overflowY,
  )
  expect(resultListOverflow).toBe('auto')
})

test('daily-screening workbench only queries the CLX official, evaluation and pool endpoints', async ({ page }) => {
  resetRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockWorkbenchApis(page)

  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-result-panel .clx-panel-row').first()).toBeVisible()

  expect(requestLog.officialQueries).toHaveLength(1)
  expect(requestLog.officialQueries[0]).toMatchObject({
    direction_mode: 'pure_buy',
  })
  expect(requestLog.evaluationRequests).toBeGreaterThan(0)
  expect(requestLog.poolListRequests).toEqual(expect.arrayContaining(['pre', 'stock', 'must']))

  await page.waitForTimeout(300)
  expect(requestLog.legacyDailyScreeningRequests).toEqual([])
  expect(requestLog.shouban30Requests).toEqual([])
})
