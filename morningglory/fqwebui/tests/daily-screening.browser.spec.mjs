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

function buildSchemaPayload() {
  return {
    models: [
      {
        id: 'all',
        label: '全链路',
        fields: [
          { name: 'days', type: 'number', default: 1 },
          { name: 'code', type: 'text', default: '' },
          { name: 'wave_opt', type: 'number', default: 1560 },
          { name: 'stretch_opt', type: 'number', default: 0 },
          { name: 'trend_opt', type: 'number', default: 1 },
          {
            name: 'clxs_model_opts',
            type: 'select',
            default: [10001, 10002],
            multiple: true,
            options: [
              { value: 10001, label: 'S0001' },
              { value: 10002, label: 'S0002' },
            ],
          },
          {
            name: 'chanlun_signal_types',
            type: 'select',
            default: ['buy_zs_huila', 'macd_bullish_divergence'],
            multiple: true,
            options: [
              { value: 'buy_zs_huila', label: '回拉中枢' },
              { value: 'macd_bullish_divergence', label: 'MACD 看涨背驰' },
            ],
          },
          {
            name: 'chanlun_period_mode',
            type: 'select',
            default: 'all',
            options: [{ value: 'all', label: '30m / 60m / 1d' }],
          },
        ],
      },
      {
        id: 'clxs',
        label: 'CLXS',
        fields: [
          { name: 'days', type: 'number', default: 1 },
          {
            name: 'model_opts',
            type: 'select',
            default: [10001],
            multiple: true,
            options: [{ value: 10001, label: 'S0001' }],
          },
          { name: 'remark', type: 'text', default: 'daily-screening:clxs', readonly: true },
        ],
      },
      {
        id: 'chanlun',
        label: 'chanlun',
        fields: [
          { name: 'days', type: 'number', default: 1 },
          {
            name: 'input_mode',
            type: 'select',
            default: 'all_pre_pools',
            options: [{ value: 'all_pre_pools', label: '全部预选池' }],
          },
          { name: 'remark', type: 'text', default: 'daily-screening:chanlun', readonly: true },
        ],
      },
    ],
    options: {
      pre_pool_categories: ['CLXS_10001'],
      pre_pool_remarks: ['daily-screening:clxs', 'daily-screening:chanlun'],
    },
  }
}

function buildSummaryPayload(runId) {
  return {
    run_id: runId,
    scope: `run:${runId}`,
    membership_count: 6,
    stock_count: 1,
    stage_counts: {
      clxs: 2,
      chanlun: 2,
      shouban30_agg90: 1,
      market_flags: 1,
    },
    stock_codes: ['000001'],
  }
}

function buildRowsPayload(runId) {
  return {
    run_id: runId,
    scope: `run:${runId}`,
    total: 1,
    rows: [
      {
        code: '000001',
        name: '平安银行',
        symbol: 'sz000001',
        selected_by: {
          clxs: true,
          chanlun: true,
          shouban30_agg90: true,
          credit_subject: true,
          near_long_term_ma: true,
          quality_subject: true,
        },
        clxs_models: ['CLXS_10001', 'CLXS_10002'],
        chanlun_variants: [
          { signal_type: 'buy_zs_huila', period: '30m' },
          { signal_type: 'macd_bullish_divergence', period: '1d' },
        ],
        shouban30_providers: ['xgb', 'jygs'],
      },
    ],
    summary: buildSummaryPayload(runId),
  }
}

function buildDetailPayload(runId) {
  return {
    run_id: runId,
    scope: `run:${runId}`,
    snapshot: buildRowsPayload(runId).rows[0],
    clxs_memberships: [
      {
        model_label: 'S0001',
        signal_type: 'CLXS_10001',
        fire_time: '2026-03-18T15:00:00',
        stop_loss_price: 9.8,
      },
    ],
    chanlun_memberships: [
      {
        signal_type: 'buy_zs_huila',
        period: '30m',
        fire_time: '2026-03-18T14:30:00',
        stop_loss_price: 9.7,
      },
    ],
    agg90_memberships: [
      {
        providers: ['xgb', 'jygs'],
        plate_refs: ['xgb:plate-a', 'jygs:plate-b'],
      },
    ],
    market_flag_memberships: [
      { signal_type: 'credit_subject', remark: '融资标的' },
      { signal_type: 'quality_subject', remark: '优质标的' },
      { signal_type: 'near_long_term_ma', remark: '均线附近 MA250' },
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

test('daily-screening workbench supports intersection query, detail view, SSE run, and pre-pool actions', async ({ page }) => {
  const requestLog = {
    queries: [],
    addBatchPayloads: [],
    addSinglePayloads: [],
    startedRuns: [],
  }

  await page.addInitScript(() => {
    window.__dailyScreeningEventSources = []

    class MockEventSource {
      constructor(url) {
        this.url = url
        this.listeners = new Map()
        this.closed = false
        window.__dailyScreeningEventSources.push(url)

        const emit = (eventName, payload) => {
          if (this.closed) return
          const entries = this.listeners.get(eventName) || []
          const event = {
            data: JSON.stringify(payload),
          }
          for (const listener of entries) {
            listener(event)
          }
        }

        setTimeout(() => {
          emit('run_started', {
            seq: 1,
            ts: '2026-03-18T19:00:01',
            data: { run_id: 'run-2', status: 'running', model: 'all' },
          })
          emit('stage_started', {
            seq: 2,
            ts: '2026-03-18T19:00:02',
            data: { stage: 'clxs', label: 'CLXS 全模型' },
          })
          emit('stage_progress', {
            seq: 3,
            ts: '2026-03-18T19:00:03',
            data: { stage: 'clxs', kind: 'accepted', code: '000001', signal_type: 'CLXS_10001' },
          })
          emit('run_completed', {
            seq: 4,
            ts: '2026-03-18T19:00:04',
            data: {
              run_id: 'run-2',
              status: 'completed',
              summary: { accepted_count: 6, persisted_count: 6 },
              stage_summaries: {},
            },
          })
        }, 100)
      }

      addEventListener(eventName, listener) {
        const entries = this.listeners.get(eventName) || []
        entries.push(listener)
        this.listeners.set(eventName, entries)
      }

      close() {
        this.closed = true
      }
    }

    window.EventSource = MockEventSource
  })

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    const method = route.request().method()
    const postDataText = route.request().postData() || ''
    const body = postDataText ? JSON.parse(postDataText) : {}

    if (pathname === '/api/daily-screening/schema') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSchemaPayload()),
      })
      return
    }

    if (pathname === '/api/daily-screening/scopes') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            { run_id: 'run-1', scope: 'run:run-1', label: 'run-1', is_latest: true },
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
          run_id: 'run-1',
          scope: 'run:run-1',
          label: 'run-1',
          is_latest: true,
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/scopes/run-1/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSummaryPayload('run-1')),
      })
      return
    }

    if (pathname === '/api/daily-screening/scopes/run-2/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSummaryPayload('run-2')),
      })
      return
    }

    if (pathname === '/api/daily-screening/query' && method === 'POST') {
      requestLog.queries.push(body)
      const runId = body.run_id || 'run-1'
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildRowsPayload(runId)),
      })
      return
    }

    if (pathname === '/api/daily-screening/stocks/000001/detail') {
      const runId = url.searchParams.get('run_id') || 'run-1'
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildDetailPayload(runId)),
      })
      return
    }

    if (pathname === '/api/daily-screening/runs' && method === 'POST') {
      requestLog.startedRuns.push(body)
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          run: {
            id: 'run-2',
            run_id: 'run-2',
            status: 'queued',
          },
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/runs/run-2') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run: {
            id: 'run-2',
            run_id: 'run-2',
            status: 'completed',
            summary: { accepted_count: 6, persisted_count: 6 },
            stage_summaries: {},
          },
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/actions/add-batch-to-pre-pool' && method === 'POST') {
      requestLog.addBatchPayloads.push(body)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ created_count: 1, codes: ['000001'] }),
      })
      return
    }

    if (pathname === '/api/daily-screening/actions/add-to-pre-pool' && method === 'POST') {
      requestLog.addSinglePayloads.push(body)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: '000001',
          category: 'CLXS_10001',
          remark: 'daily-screening:clxs',
        }),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    })
  })

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.daily-screening-page')

  await expect(page.getByText('交集筛选')).toBeVisible()
  await expect(page.locator('.daily-results-panel').getByText('CLXS 命中模型')).toBeVisible()
  await expect(page.locator('.daily-results-panel').getByText('chanlun 命中信号')).toBeVisible()
  await expect(page.locator('.daily-detail-stack').getByText('历史热门理由')).toBeVisible()
  await page.getByRole('button', { name: '查询结果' }).evaluate((node) => node.click())
  await expect.poll(() => requestLog.queries.length >= 1).toBe(true)
  await expect(page.locator('.daily-results-panel')).toContainText('平安银行')
  await expect(page.locator('.daily-detail-stack')).toContainText('龙头地位明确')

  await page
    .locator('.daily-set-grid')
    .getByRole('button', { name: /90天聚合/ })
    .evaluate((node) => node.click())
  await page
    .locator('.daily-filter-groups article')
    .first()
    .getByRole('button', { name: 'S0001' })
    .evaluate((node) => node.click())
  await page
    .locator('.daily-filter-actions')
    .getByRole('button', { name: '查询结果' })
    .evaluate((node) => node.click())

  await expect.poll(() => requestLog.queries.length >= 2).toBe(true)
  await expect
    .poll(() => requestLog.queries[requestLog.queries.length - 1])
    .toMatchObject({
      run_id: 'run-1',
      selected_sets: ['clxs', 'chanlun', 'shouban30_agg90'],
      clxs_models: ['CLXS_10001'],
    })

  await page.getByRole('button', { name: '开始扫描' }).evaluate((node) => node.click())

  await expect.poll(async () => {
    return page.evaluate(() => window.__dailyScreeningEventSources.slice())
  }).toEqual(['/api/daily-screening/runs/run-2/stream'])
  await expect(page.locator('.daily-stream-list')).toContainText('run_completed')
  await expect(page.locator('.workbench-summary-row')).toContainText('run-2')

  await page
    .getByRole('button', { name: '当前交集加入 pre_pools' })
    .evaluate((node) => node.click())
  await expect.poll(() => requestLog.addBatchPayloads.length).toBe(1)
  await expect(requestLog.addBatchPayloads[0]).toMatchObject({
    run_id: 'run-2',
    selected_sets: ['clxs', 'chanlun', 'shouban30_agg90'],
  })

  await page
    .locator('.daily-detail-stack')
    .getByRole('button', { name: '加入 pre_pools' })
    .evaluate((node) => node.click())
  await expect.poll(() => requestLog.addSinglePayloads.length).toBe(1)
  await expect(requestLog.addSinglePayloads[0]).toEqual({
    run_id: 'run-2',
    code: '000001',
  })
})
