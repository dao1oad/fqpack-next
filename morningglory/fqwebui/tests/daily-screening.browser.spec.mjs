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

function buildFilterCatalog() {
  return {
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['base:union', 'cls:S0008', 'cls:S0009', 'hot:30d', 'flag:credit_subject'],
    groups: {
      cls_models: [
        { key: 'cls:S0008', label: 'S0008', count: 1 },
        { key: 'cls:S0009', label: 'S0009', count: 1 },
      ],
      hot_windows: [
        { key: 'hot:30d', label: '30天热门', count: 1 },
        { key: 'hot:45d', label: '45天热门', count: 0 },
        { key: 'hot:60d', label: '60天热门', count: 0 },
        { key: 'hot:90d', label: '90天热门', count: 1 },
      ],
      market_flags: [
        { key: 'flag:credit_subject', label: '融资标的', count: 1 },
        { key: 'flag:quality_subject', label: '优质标的', count: 1 },
        { key: 'flag:near_long_term_ma', label: '年线附近', count: 0 },
      ],
      chanlun_periods: [
        { key: 'chanlun_period:30m', label: '30m', count: 1 },
        { key: 'chanlun_period:60m', label: '60m', count: 0 },
        { key: 'chanlun_period:1d', label: '1d', count: 0 },
      ],
      chanlun_signals: [
        { key: 'chanlun_signal:buy_zs_huila', label: '回拉中枢上涨', count: 1 },
        { key: 'chanlun_signal:sell_zs_huila', label: '回拉中枢下跌', count: 1 },
        { key: 'chanlun_signal:buy_v_reverse', label: 'V反上涨', count: 0 },
        { key: 'chanlun_signal:sell_v_reverse', label: 'V反下跌', count: 0 },
        { key: 'chanlun_signal:macd_bullish_divergence', label: 'MACD看涨背驰', count: 0 },
        { key: 'chanlun_signal:macd_bearish_divergence', label: 'MACD看跌背驰', count: 0 },
      ],
    },
  }
}

function buildSummaryPayload() {
  return {
    run_id: 'trade_date:2026-03-18',
    scope: 'trade_date:2026-03-18',
    stock_count: 2,
    membership_count: 6,
    stage_counts: {
      'base:union': 2,
      'cls:S0008': 1,
      'hot:30d': 1,
      'hot:90d': 1,
      'flag:credit_subject': 1,
    },
  }
}

function buildQueryPayload({ conditionKeys = [], clxsModels = [] } = {}) {
  const matchedSingle = conditionKeys.length === 1 &&
    conditionKeys.includes('hot:30d') &&
    clxsModels.length === 2 &&
    clxsModels.includes('S0008') &&
    clxsModels.includes('S0009')

  return {
    run_id: 'trade_date:2026-03-18',
    scope: 'trade_date:2026-03-18',
    total: matchedSingle ? 1 : 2,
    rows: [
      {
        code: '000001',
        name: '平安银行',
        symbol: 'sz000001',
        higher_multiple: 1.8,
        segment_multiple: 1.3,
        bi_gain_percent: 9.2,
        chanlun_reason: 'passed',
      },
      ...(
        matchedSingle
          ? []
          : [
              {
                code: '000002',
                name: '万科A',
                symbol: 'sz000002',
                higher_multiple: 2.2,
                segment_multiple: 1.6,
                bi_gain_percent: 12.5,
                chanlun_reason: 'higher_multiple_exceed',
              },
            ]
      ),
    ],
  }
}

function buildDetailPayload() {
  return {
    run_id: 'trade_date:2026-03-18',
    scope: 'trade_date:2026-03-18',
    snapshot: {
      code: '000001',
      name: '平安银行',
      symbol: 'sz000001',
      higher_multiple: 1.8,
      segment_multiple: 1.3,
      bi_gain_percent: 9.2,
      chanlun_reason: 'passed',
    },
    memberships: [
      { code: '000001', condition_key: 'cls:S0008', name: '平安银行', symbol: 'sz000001' },
      { code: '000001', condition_key: 'hot:30d', name: '平安银行', symbol: 'sz000001' },
      { code: '000001', condition_key: 'hot:90d', name: '平安银行', symbol: 'sz000001' },
      { code: '000001', condition_key: 'flag:credit_subject', name: '平安银行', symbol: 'sz000001' },
      { code: '000001', condition_key: 'chanlun_period:30m', name: '平安银行', symbol: 'sz000001' },
      { code: '000001', condition_key: 'chanlun_signal:buy_zs_huila', name: '平安银行', symbol: 'sz000001' },
      { code: '000001', condition_key: 'chanlun_signal:sell_zs_huila', name: '平安银行', symbol: 'sz000001' },
    ],
    hot_reasons: [
      {
        provider: 'xgb',
        date: '2026-03-18',
        time: '14:55',
        plate_name: '银行',
        stock_reason: '龙头地位明确',
        plate_reason: '板块强势共振',
      },
    ],
  }
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

test('daily-screening workbench only queries Dagster-prepared scopes and intersections', async ({ page }) => {
  const requestLog = {
    queryBodies: [],
    detailRequests: [],
    appendPrePoolBodies: [],
  }

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    const method = route.request().method()
    const body = route.request().postDataJSON?.() || {}

    if (pathname === '/api/daily-screening/scopes') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              run_id: 'trade_date:2026-03-18',
              scope: 'trade_date:2026-03-18',
              label: '正式 2026-03-18',
              is_latest: true,
            },
          ],
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/scopes/latest') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'trade_date:2026-03-18',
          scope: 'trade_date:2026-03-18',
          label: '正式 2026-03-18',
          is_latest: true,
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/filters') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildFilterCatalog()),
      })
      return
    }

    if (pathname === '/api/daily-screening/scopes/trade_date:2026-03-18/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSummaryPayload()),
      })
      return
    }

    if (pathname === '/api/daily-screening/query' && method === 'POST') {
      requestLog.queryBodies.push(body)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildQueryPayload({
          conditionKeys: body.condition_keys || [],
          clxsModels: body.clxs_models || [],
        })),
      })
      return
    }

    if (pathname === '/api/daily-screening/stocks/000001/detail') {
      requestLog.detailRequests.push(url.searchParams.get('scope_id'))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildDetailPayload()),
      })
      return
    }

    if (pathname === '/api/gantt/shouban30/pre-pool' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            items: [
              {
                code: '000333',
                code6: '000333',
                name: '美的集团',
                category: '三十涨停Pro预选',
                extra: {
                  shouban30_provider: 'daily_screening',
                  shouban30_plate_name: '每日选股交集',
                },
              },
            ],
          },
        }),
      })
      return
    }

    if (pathname === '/api/gantt/shouban30/stock-pool' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            items: [
              {
                code: '000651',
                code6: '000651',
                name: '格力电器',
                category: '三十涨停Pro自选',
                extra: {
                  shouban30_provider: 'daily_screening',
                  shouban30_plate_name: '每日选股交集',
                },
              },
            ],
          },
        }),
      })
      return
    }

    if (pathname === '/api/gantt/shouban30/pre-pool/append' && method === 'POST') {
      requestLog.appendPrePoolBodies.push(body)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            appended_count: Array.isArray(body.items) ? body.items.length : 0,
            skipped_count: 0,
          },
        }),
      })
      return
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ error: `${pathname} not mocked` }),
    })
  })

  await page.goto(TARGET_URL)

  await expect(page.locator('.workbench-page-title').getByText('每日选股')).toBeVisible()
  const filterPanelMetrics = await page.locator('.daily-filter-panel').evaluate((element) => ({
    overflowY: window.getComputedStyle(element).overflowY,
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
  }))
  expect(filterPanelMetrics.overflowY).toBe('auto')
  expect(filterPanelMetrics.scrollHeight).toBeGreaterThan(filterPanelMetrics.clientHeight)
  await expect(page.getByText('前端只做组合查询，不再触发运行，不再展示 SSE。')).toBeVisible()
  await expect(page.getByText('上游范围：全市场股票，排除 ST 和北交所')).toBeVisible()
  await expect(page.getByText('基础池：CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成')).toBeVisible()
  await expect(page.getByText('交集规则：用户勾选的条件会在当前结果上继续取交集')).toBeVisible()
  await expect(page.getByText('工作区用途：交集结果可加入 pre_pools，再同步到 stock_pools / must_pools')).toBeVisible()
  await expect(page.getByText('基础池 2')).toBeVisible()
  await expect(page.getByText('当前结果 2')).toBeVisible()
  await expect(page.getByRole('button', { name: '开始扫描' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '全部加入pre_pools' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /pre_pools/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /stock_pools/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '查询结果' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '参与筛选' })).toBeVisible()

  await page.getByRole('button', { name: '查看热门窗口说明' }).hover()
  await expect(page.getByText('来源于 /gantt/shouban30 同口径的热门标的结果，聚合选股通和韭研公式的 30/45/60/90 天窗口命中股票。')).toBeVisible()

  await page.getByRole('button', { name: '背驰', exact: true }).click()
  await page.getByRole('button', { name: '30天热门 · 1' }).click()

  await expect(page.getByText('当前结果 1')).toBeVisible()
  await expect(page.getByText('背驰 ∩ 30天热门')).toBeVisible()
  await expect(page.getByRole('cell', { name: '平安银行' })).toBeVisible()

  const lastQuery = requestLog.queryBodies.at(-1)
  expect(lastQuery).toEqual({
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['hot:30d'],
    clxs_models: ['S0008', 'S0009'],
  })

  await page.getByRole('button', { name: '全部加入pre_pools' }).click()
  await expect(page.getByText('已将当前交集结果 1 条加入 pre_pools')).toBeVisible()
  expect(requestLog.appendPrePoolBodies.at(-1)).toEqual({
    items: [
      {
        code6: '000001',
        name: '平安银行',
        plate_key: 'trade_date:2026-03-18',
        plate_name: '每日选股交集',
        provider: 'daily_screening',
      },
    ],
    replace_scope: 'daily_screening_intersection',
    end_date: '2026-03-18',
    selected_extra_filters: ['cls_group:beichi', 'hot:30d'],
    remark: '背驰 ∩ 30天热门',
  })

  await page.locator('.daily-results-panel .el-table__body-wrapper tbody tr').first().dispatchEvent('click')

  const detailPane = page.locator('.daily-detail-stack')
  await expect(page.getByText('标的详情')).toBeVisible()
  await expect(page.locator('.daily-detail-title').getByText('平安银行')).toBeVisible()
  await expect(detailPane.getByText('融资标的', { exact: true })).toBeVisible()
  await expect(detailPane.getByText('盘整或趋势背驰', { exact: true })).toBeVisible()
  await expect(detailPane.getByText('回拉中枢上涨', { exact: true })).toBeVisible()
  await expect(detailPane.getByText('回拉中枢下跌', { exact: true })).toBeVisible()
  await expect(detailPane.getByText('龙头地位明确')).toBeVisible()
  expect(requestLog.detailRequests).toEqual(['trade_date:2026-03-18'])
})
