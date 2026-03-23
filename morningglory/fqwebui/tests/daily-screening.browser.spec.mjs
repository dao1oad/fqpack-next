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
      cls_groups: [
        { key: 'cls_group:erbai', label: '二买', count: 0 },
        { key: 'cls_group:sanmai', label: '三买', count: 0 },
        { key: 'cls_group:yali_support', label: '压力支撑', count: 0 },
        { key: 'cls_group:beichi', label: '背驰', count: 2 },
        { key: 'cls_group:break_pullback', label: '突破回调', count: 0 },
      ],
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
    stock_count: 12,
    membership_count: 18,
    stage_counts: {
      'base:union': 12,
      'cls:S0008': 1,
      'hot:30d': 1,
      'hot:90d': 1,
      'flag:credit_subject': 1,
    },
  }
}

function buildQueryPayload({ conditionKeys = [], clxsModels = [], metricFilters = null } = {}) {
  const matchedSingle = conditionKeys.length === 2 &&
    conditionKeys.includes('flag:credit_subject') &&
    conditionKeys.includes('hot:30d') &&
    clxsModels.length === 2 &&
    clxsModels.includes('S0008') &&
    clxsModels.includes('S0009') &&
    Boolean(metricFilters)

  const baseRows = [
    {
      code: '000001',
      name: '平安银行',
      symbol: 'sz000001',
      higher_multiple: 1.8,
      segment_multiple: 1.3,
      bi_gain_percent: 9.2,
      chanlun_reason: 'passed',
    },
    {
      code: '000002',
      name: '万科A',
      symbol: 'sz000002',
      higher_multiple: 2.2,
      segment_multiple: 1.6,
      bi_gain_percent: 12.5,
      chanlun_reason: 'higher_multiple_exceed',
    },
    ...Array.from({ length: 10 }, (_, index) => ({
      code: String(index + 3).padStart(6, '0'),
      name: `样本股票${index + 3}`,
      symbol: `sz${String(index + 3).padStart(6, '0')}`,
      higher_multiple: 1.2 + index * 0.1,
      segment_multiple: 0.9 + index * 0.1,
      bi_gain_percent: 6 + index,
      chanlun_reason: index % 2 === 0 ? 'passed' : 'segment_multiple_exceed',
    })),
  ]

  return {
    run_id: 'trade_date:2026-03-18',
    scope: 'trade_date:2026-03-18',
    total: matchedSingle ? 1 : baseRows.length,
    rows: matchedSingle ? baseRows.slice(0, 1) : baseRows,
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

  await page.setViewportSize({ width: 1600, height: 900 })

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
          metricFilters: body.metric_filters || null,
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
  await expect(page.locator('.workbench-toolbar .daily-toolbar-guide')).toBeVisible()
  await expect(page.locator('.daily-toolbar-scope')).toBeVisible()
  await expect(page.getByText('筛选工作台')).toHaveCount(0)
  await expect(page.getByText('前端只做组合查询，不再触发运行，不再展示 SSE。')).toHaveCount(0)
  const filterPanelMetrics = await page.locator('.daily-filter-panel').evaluate((element) => ({
    overflowY: window.getComputedStyle(element).overflowY,
  }))
  expect(filterPanelMetrics.overflowY).toBe('auto')
  await expect(page.getByText('上游：全市场，排除 ST / 北交所')).toBeVisible()
  await expect(page.getByText('基础池：CLS 分组 + 热门窗口先取并集')).toBeVisible()
  await expect(page.getByText('交集：其他条件在基础池结果上继续收敛')).toBeVisible()
  await expect(page.getByText('工作区：结果可加入 pre_pools / stock_pools / must_pools')).toBeVisible()
  await expect(page.getByText('基础池 12')).toBeVisible()
  await expect(page.getByText('当前结果 12')).toBeVisible()
  await expect(page.getByRole('button', { name: '开始扫描' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '全部加入pre_pools' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /pre_pools/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /stock_pools/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '查询结果' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /参与筛选/ })).toBeVisible()
  await expect(page.locator('.daily-results-pagination')).toBeVisible()
  await expect(page.locator('.daily-results-panel .runtime-ledger__row')).toHaveCount(8)

  const viewportFit = await page.evaluate(() => {
    const scrollingElement = document.scrollingElement || document.documentElement
    return {
      innerHeight: window.innerHeight,
      scrollHeight: scrollingElement.scrollHeight,
    }
  })
  expect(viewportFit.scrollHeight).toBeLessThanOrEqual(viewportFit.innerHeight + 4)

  const workspaceBox = await page.locator('.daily-workspace-panel').boundingBox()
  expect(workspaceBox).toBeTruthy()
  expect(workspaceBox.y + workspaceBox.height).toBeLessThanOrEqual(900)

  await page.getByRole('button', { name: '查看热门窗口说明' }).dispatchEvent('mouseenter')
  await expect(page.getByText('来源于 /gantt/shouban30 同口径的热门标的结果，聚合选股通和韭研公式的 30/45/60/90 天窗口命中股票。')).toBeVisible()
  await page.getByRole('button', { name: '查看CLS 模型分组说明' }).dispatchEvent('mouseenter')
  await expect(page.getByText('分组内多个 CLS 模型取并集；不同 CLS 分组之间多选也取并集；CLS 分组结果与热门窗口、市场属性、chanlun、日线缠论涨幅等其他条件之间再取交集。')).toBeVisible()
  await page.mouse.move(8, 8)
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: '背驰 · 2', exact: true }).click()
  await page.getByRole('button', { name: '30天热门 · 1' }).click()

  await expect(page.getByText('当前结果 1')).toBeVisible()
  await expect(page.getByText('CLS 分组并集（背驰） ∩ 融资标的 ∩ 30天热门 ∩ 日线缠论涨幅（高级段倍数 <= 3 / 段倍数 <= 2 / 笔涨幅% <= 20）')).toBeVisible()
  await expect(page.locator('.daily-results-panel .runtime-ledger__row').first()).toContainText('平安银行')

  const lastQuery = requestLog.queryBodies.at(-1)
  expect(lastQuery).toEqual({
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['flag:credit_subject', 'hot:30d'],
    clxs_models: ['S0008', 'S0009'],
    metric_filters: {
      higher_multiple_lte: 3,
      segment_multiple_lte: 2,
      bi_gain_percent_lte: 20,
    },
  })

  await page.getByRole('button', { name: '全部加入pre_pools' }).evaluate((element) => {
    element.click()
  })
  await expect.poll(() => requestLog.appendPrePoolBodies.length).toBe(1)
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
    selected_extra_filters: ['cls_group:beichi', 'flag:credit_subject', 'hot:30d', 'metric:daily_chanlun'],
    remark: 'CLS 分组并集（背驰） ∩ 融资标的 ∩ 30天热门 ∩ 日线缠论涨幅（高级段倍数 <= 3 / 段倍数 <= 2 / 笔涨幅% <= 20）',
  })

  await page.locator('.daily-results-panel .runtime-ledger__row').first().evaluate((element) => {
    element.click()
  })
  await expect.poll(() => requestLog.detailRequests.length).toBe(1)

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
