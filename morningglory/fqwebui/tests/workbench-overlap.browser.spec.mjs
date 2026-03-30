import { test, expect } from '@playwright/test'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  startPreviewServer,
  stopDevServer,
  waitForServer,
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18094
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)
const DESKTOP_VIEWPORT = { width: 1600, height: 900 }

let devServerProcess = null

const buildRows = (count, factory) => Array.from({ length: count }, (_, index) => factory(index))

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

async function measureLedger(rootLocator, {
  name,
  headerSelector,
  rowSelector,
  viewportSelector = '',
  scrollTop = 160,
}) {
  await expect(rootLocator, `${name} root should be visible`).toBeVisible()
  return await rootLocator.evaluate(async (root, options) => {
    const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))
    const preferredViewport = options.viewportSelector
      ? root.querySelector(options.viewportSelector)
      : null
    const scroller = preferredViewport &&
      preferredViewport.scrollHeight > preferredViewport.clientHeight
      ? preferredViewport
      : root
    const header = root.querySelector(options.headerSelector)
    const firstRow = root.querySelector(options.rowSelector)
    if (!header || !firstRow) {
      return {
        name: options.name,
        error: 'missing-header-or-row',
      }
    }

    scroller.scrollTop = Math.min(options.scrollTop, Math.max(scroller.scrollHeight - scroller.clientHeight, 0))
    await wait(120)

    const headerRect = header.getBoundingClientRect()
    const scrollerRect = scroller.getBoundingClientRect()
    const rowRect = (() => {
      if (preferredViewport && scroller === preferredViewport) {
        return { top: scrollerRect.top }
      }
      const visibleRow = Array.from(root.querySelectorAll(options.rowSelector)).find((row) => {
        const rect = row.getBoundingClientRect()
        return rect.top >= headerRect.bottom - 1 && rect.top < scrollerRect.bottom
      }) || firstRow
      return visibleRow.getBoundingClientRect()
    })()
    return {
      name: options.name,
      overlap: Number((headerRect.bottom - rowRect.top).toFixed(2)),
      scrollHeight: Number(scroller.scrollHeight || 0),
      clientHeight: Number(scroller.clientHeight || 0),
    }
  }, {
    name,
    headerSelector,
    rowSelector,
    viewportSelector,
    scrollTop,
  })
}

function assertNoOverlap(metrics) {
  expect(metrics.length).toBeGreaterThan(0)
  for (const metric of metrics) {
    expect(metric.error, `${metric.name}: missing nodes`).toBeUndefined()
    expect(
      metric.scrollHeight,
      `${metric.name}: expected scrollable content to exceed viewport height`,
    ).toBeGreaterThan(metric.clientHeight)
    expect(
      metric.overlap,
      `${metric.name}: first row is covered by header after scrolling`,
    ).toBeLessThanOrEqual(1)
  }
}

async function measureTextHorizontalOverflow(rootLocator, {
  name,
  rowSelector,
  detailSelector,
  rowLimit = 6,
}) {
  await expect(rootLocator, `${name} root should be visible`).toBeVisible()
  return await rootLocator.evaluate((root, options) => {
    const rows = Array.from(root.querySelectorAll(options.rowSelector)).slice(0, options.rowLimit)
    const violations = []
    rows.forEach((row, rowIndex) => {
      const details = Array.from(row.querySelectorAll(options.detailSelector))
      details.forEach((detail, detailIndex) => {
        const text = (detail.textContent || '').trim()
        if (!text || text === '-') return
        const parent = detail.parentElement
        const detailRect = detail.getBoundingClientRect()
        const parentRect = parent?.getBoundingClientRect()
        const widthOverflow = detailRect.width - (parentRect?.width || 0)
        const rightOverflow = detailRect.right - (parentRect?.right || 0)
        if (
          widthOverflow > 1 ||
          rightOverflow > 1
        ) {
          violations.push({
            rowIndex,
            detailIndex,
            detailWidth: Number(detailRect.width || 0),
            parentWidth: Number(parentRect?.width || 0),
            rightOverflow: Number(rightOverflow || 0),
            clientWidth: Number(detail.clientWidth || 0),
            scrollWidth: Number(detail.scrollWidth || 0),
            text,
          })
        }
      })
    })
    return {
      name: options.name,
      rowCount: rows.length,
      violations,
    }
  }, {
    name,
    rowSelector,
    detailSelector,
    rowLimit,
  })
}

function assertNoTextHorizontalOverflow(metric) {
  expect(metric.rowCount, `${metric.name}: expected at least one visible row`).toBeGreaterThan(0)
  expect(metric.violations, `${metric.name}: detail text overflowed horizontally`).toEqual([])
}

function buildDailyRows(count = 24) {
  return buildRows(count, (index) => {
    const code = String(index + 1).padStart(6, '0')
    return {
      code,
      name: `样本股票${index + 1}`,
      symbol: `sz${code}`,
      higher_multiple: 1.1 + index * 0.05,
      segment_multiple: 0.8 + index * 0.04,
      bi_gain_percent: 4 + index,
      chanlun_reason: index % 3 === 0 ? 'passed' : 'segment_multiple_exceed',
    }
  })
}

function buildDailyWorkspaceItems(prefix, count) {
  return buildRows(count, (index) => {
    const code = String(300000 + index).padStart(6, '0')
    return {
      code,
      code6: code,
      name: `${prefix}${index + 1}`,
      category: index % 2 === 0 ? '三十涨停Pro预选' : '每日选股交集',
      extra: {
        shouban30_provider: 'daily_screening',
        shouban30_plate_name: '每日选股交集',
        context: `${prefix}-context-${index + 1}`,
      },
    }
  })
}

function buildDailyMustPoolItems(count) {
  return buildRows(count, (index) => {
    const code = String(600000 + index).padStart(6, '0')
    return {
      code,
      code6: code,
      name: `必选股票${index + 1}`,
      category: index % 2 === 0 ? 'must_pool' : '重点观察',
      source: 'daily_screening',
      extra: {
        provider: 'daily_screening',
        plate_name: '每日选股交集',
      },
    }
  })
}

function buildDailyHotReasons(count = 18) {
  return buildRows(count, (index) => ({
    provider: index % 2 === 0 ? 'xgb' : 'jy',
    date: `2026-03-${String((index % 9) + 10).padStart(2, '0')}`,
    time: `14:${String(index).padStart(2, '0')}`,
    plate_name: `热点板块${index + 1}`,
    stock_reason: `个股强度原因 ${index + 1}`,
    plate_reason: `板块共振原因 ${index + 1}`,
  }))
}

async function setupDailyScreeningRoutes(page) {
  const resultRows = buildDailyRows(24)
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const { pathname } = url
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
        body: JSON.stringify({
          scope_id: 'trade_date:2026-03-18',
          condition_keys: ['base:union', 'cls:S0008', 'hot:30d', 'flag:credit_subject'],
          groups: {
            cls_groups: [
              { key: 'cls_group:beichi', label: '背驰', count: 12 },
              { key: 'cls_group:sanmai', label: '三买', count: 8 },
            ],
            cls_models: [
              { key: 'cls:S0008', label: 'S0008', count: 12 },
              { key: 'cls:S0009', label: 'S0009', count: 8 },
            ],
            hot_windows: [
              { key: 'hot:30d', label: '30天热门', count: 16 },
              { key: 'hot:90d', label: '90天热门', count: 10 },
            ],
            market_flags: [
              { key: 'flag:credit_subject', label: '融资标的', count: 18 },
              { key: 'flag:quality_subject', label: '优质标的', count: 14 },
            ],
            chanlun_periods: [
              { key: 'chanlun_period:30m', label: '30m', count: 9 },
            ],
            chanlun_signals: [
              { key: 'chanlun_signal:buy_zs_huila', label: '回拉中枢上涨', count: 9 },
              { key: 'chanlun_signal:sell_zs_huila', label: '回拉中枢下跌', count: 9 },
            ],
          },
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/scopes/trade_date:2026-03-18/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'trade_date:2026-03-18',
          scope: 'trade_date:2026-03-18',
          stock_count: resultRows.length,
          membership_count: resultRows.length * 2,
          stage_counts: {
            'base:union': resultRows.length,
            'cls:S0008': 12,
            'hot:30d': 16,
            'flag:credit_subject': 18,
          },
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/query' && route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'trade_date:2026-03-18',
          scope: 'trade_date:2026-03-18',
          total: resultRows.length,
          rows: resultRows,
        }),
      })
      return
    }

    if (pathname === '/api/daily-screening/stocks/000001/detail') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'trade_date:2026-03-18',
          scope: 'trade_date:2026-03-18',
          snapshot: resultRows[0],
          memberships: [
            { code: '000001', condition_key: 'cls:S0008', name: '样本股票1', symbol: 'sz000001' },
            { code: '000001', condition_key: 'hot:30d', name: '样本股票1', symbol: 'sz000001' },
            { code: '000001', condition_key: 'flag:credit_subject', name: '样本股票1', symbol: 'sz000001' },
          ],
          hot_reasons: buildDailyHotReasons(18),
        }),
      })
      return
    }

    if (pathname === '/api/gantt/shouban30/pre-pool') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { items: buildDailyWorkspaceItems('pre', 18) } }),
      })
      return
    }

    if (pathname === '/api/gantt/shouban30/stock-pool') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { items: buildDailyWorkspaceItems('stock', 16) } }),
      })
      return
    }

    if (pathname === '/api/get_stock_must_pools_list') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildDailyMustPoolItems(14)),
      })
      return
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ error: `${pathname} not mocked` }),
    })
  })
}

function buildPositionManagementDashboard() {
  const symbols = buildRows(18, (index) => String(1 + index).padStart(6, '0'))
  return {
    data: {
      state: {
        effective_state: 'allow_open',
        raw_state: 'allow_open',
        stale: false,
        matched_rule: {
          title: '允许开新仓',
          detail: '账户保证金和单标的门禁均满足条件。',
        },
        available_bail_balance: 1280000,
        available_amount: 2150000,
        fetch_balance: 1640000,
        total_asset: 3650000,
        market_value: 840000,
        total_debt: 0,
        evaluated_at: '2026-03-18T10:20:00+08:00',
        last_query_ok: '2026-03-18T10:19:50+08:00',
        data_source: 'xt_positions',
        account_id: '068000076370',
        snapshot_id: 'snap_001',
      },
      config: {
        updated_at: '2026-03-18T09:45:00+08:00',
        updated_by: 'tester',
        inventory: [
          { key: 'allow_open_min_bail', label: '允许开新仓最低保证金', value: 800000, editable: true, group: 'editable_thresholds', source: 'pm_configs' },
          { key: 'holding_only_min_bail', label: '仅允许持仓内买入最低保证金', value: 100000, editable: true, group: 'editable_thresholds', source: 'pm_configs' },
          { key: 'single_symbol_position_limit', label: '单标的默认持仓上限', value: 800000, editable: true, group: 'editable_thresholds', source: 'pm_configs' },
        ],
      },
      holding_scope: {
        codes: symbols,
        source: 'xt_positions',
        description: '当前券商实时持仓',
      },
      rule_matrix: buildRows(28, (index) => ({
        key: `rule_${index + 1}`,
        label: `门禁规则 ${index + 1}`,
        allowed: index % 4 !== 0,
        reason_code: index % 4 === 0 ? 'limit_blocked' : 'pass',
        reason_text: index % 4 === 0 ? `门禁规则 ${index + 1} 阻断` : `门禁规则 ${index + 1} 通过`,
      })),
      symbol_position_limits: {
        rows: symbols.map((symbol, index) => ({
          symbol,
          name: `标的${index + 1}`,
          is_holding_symbol: true,
          market_value: 920000 - index * 24000,
          broker_position: {
            quantity: 1000 + index * 20,
            market_value: 920000 - index * 24000,
            quantity_source: 'xt_positions',
            market_value_source: 'xt_positions_market_value',
          },
          ledger_position: {
            quantity: (index % 5 === 0 ? 980 : 1000) + index * 20,
            market_value: 915000 - index * 23000,
            quantity_source: 'order_management_position_entries/broker_truth',
            market_value_source: 'order_management_position_entries/broker_truth',
          },
          reconciliation: {
            state: index % 5 === 0 ? 'OBSERVING' : 'AUTO_RECONCILED',
            signed_gap_quantity: index % 5 === 0 ? 20 : 0,
            open_gap_count: 0,
            latest_resolution_type: 'auto_close_allocation',
            ingest_rejection_count: index % 7 === 0 ? 2 : 0,
          },
          position_consistency: { quantity_consistent: index % 5 !== 0 },
          default_limit: 800000,
          override_limit: index % 3 === 0 ? 650000 : null,
          effective_limit: index % 3 === 0 ? 650000 : 800000,
          using_override: index % 3 === 0,
          blocked: index % 4 === 0,
        })),
      },
      recent_decisions: buildRows(20, (index) => ({
        decision_id: `pmd_${index + 1}`,
        strategy_name: index % 2 === 0 ? 'Guardian' : 'Manual',
        action: index % 2 === 0 ? 'buy' : 'sell',
        symbol: symbols[index % symbols.length],
        symbol_name: `标的${(index % symbols.length) + 1}`,
        state: index % 3 === 0 ? 'HOLDING_ONLY' : 'ALLOW_OPEN',
        allowed: index % 4 !== 0,
        reason_code: index % 4 === 0 ? 'symbol_position_limit_blocked' : 'pass',
        reason_text: index % 4 === 0 ? '单标的实时仓位已达到上限' : '门禁允许继续执行',
        source: 'strategy',
        source_module: index % 2 === 0 ? 'Guardian' : 'Manual',
        evaluated_at: `2026-03-18T10:${String(index).padStart(2, '0')}:00+08:00`,
        trace_id: `trc_pm_${index + 1}`,
        intent_id: `intent_pm_${index + 1}`,
        meta: {
          is_holding_symbol: true,
          symbol_position_limit: 800000,
          symbol_market_value: 600000 + index * 5000,
          symbol_market_value_source: 'xt_positions.market_value',
          symbol_quantity_source: 'xt_positions.volume',
        },
      })),
    },
  }
}

async function setupPositionManagementRoutes(page) {
  const dashboard = buildPositionManagementDashboard()
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/position-management/dashboard') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dashboard),
      })
      return
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ error: `${url.pathname} not mocked` }),
    })
  })
}

function buildRuntimeTrace(traceId, index) {
  const code = String(index + 1).padStart(6, '0')
  const symbol = `sz${code}`
  const finalStatus = index % 4 === 0 ? 'failed' : (index % 3 === 0 ? 'warning' : 'success')
  const second = String((index + 10) % 60).padStart(2, '0')
  const stepCount = 12
  return {
    trace_id: traceId,
    trace_key: `trace:${traceId}`,
    request_ids: [`req_${traceId}`],
    internal_order_ids: [`ord_${traceId}`],
    intent_ids: [`intent_${traceId}`],
    symbol,
    symbol_name: `运行标的${index + 1}`,
    trace_kind: 'guardian_signal',
    trace_status: finalStatus,
    issue_count: finalStatus === 'success' ? 0 : 1,
    step_count: stepCount,
    duration_ms: 480 + index * 10,
    last_ts: `2026-03-18T10:15:${second}+08:00`,
    break_reason: finalStatus === 'success' ? '' : 'submit_failed',
    steps: [
      { index: 0, component: 'guardian_strategy', runtime_node: 'host:guardian', node: 'receive_signal', status: 'info', ts: `2026-03-18T10:15:${second}+08:00`, symbol, symbol_name: `运行标的${index + 1}`, trace_id: traceId, request_id: `req_${traceId}`, internal_order_id: `ord_${traceId}` },
      ...buildRows(stepCount - 2, (stepIndex) => ({
        index: stepIndex + 1,
        component: stepIndex % 2 === 0 ? 'position_gate' : 'order_submit',
        runtime_node: stepIndex % 2 === 0 ? 'host:position_gate' : 'host:rear',
        node: stepIndex === stepCount - 3 ? 'submit_result' : `step_${stepIndex + 1}`,
        status: stepIndex === stepCount - 3
          ? finalStatus
          : (stepIndex === 0 && index % 5 === 0 ? 'warning' : 'success'),
        ts: `2026-03-18T10:15:${second}+08:00`,
        symbol,
        symbol_name: `运行标的${index + 1}`,
        trace_id: traceId,
        request_id: `req_${traceId}`,
        internal_order_id: `ord_${traceId}`,
        decision_branch: stepIndex % 2 === 0 ? 'allow_open' : '',
        decision_expr: stepIndex % 2 === 0 ? 'cash > threshold' : '',
        reason_code: stepIndex === stepCount - 3 && finalStatus !== 'success' ? 'submit_failed' : '',
        payload: stepIndex === stepCount - 3
          ? (finalStatus === 'success' ? { order_status: 'accepted' } : { error_type: 'BrokerError', error_message: 'submit failed' })
          : undefined,
      })),
    ],
  }
}

function buildRuntimeEvent(index) {
  const code = String(index + 1).padStart(6, '0')
  return {
    ts: `2026-03-18T11:${String(index).padStart(2, '0')}:00+08:00`,
    runtime_node: index % 2 === 0 ? 'host:rear' : 'host:guardian',
    component: index % 2 === 0 ? 'order_submit' : 'guardian_strategy',
    node: index % 2 === 0 ? 'submit_result' : 'receive_signal',
    status: index % 4 === 0 ? 'warning' : 'info',
    symbol: `sz${code}`,
    symbol_name: `事件标的${index + 1}`,
    reason_code: index % 4 === 0 ? 'queue_delay' : '',
    payload: { latency_ms: 120 + index },
    metrics: { queue_len: index % 7 },
  }
}

function buildRuntimeRawRecords(count = 16) {
  return buildRows(count, (index) => ({
    component: 'order_submit',
    node: 'submit_result',
    ts: `2026-03-18T10:15:${String((index + 10) % 60).padStart(2, '0')}+08:00`,
    trace_id: `trc_overlap_${index + 1}`,
    request_id: `req_trc_overlap_${index + 1}`,
    internal_order_id: `ord_trc_overlap_${index + 1}`,
    symbol: `sz${String(index + 1).padStart(6, '0')}`,
    payload: { detail: `raw payload ${index + 1}` },
  }))
}

async function setupRuntimeObservabilityRoutes(page) {
  const traces = buildRows(18, (_, index) => buildRuntimeTrace(`trc_overlap_${index + 1}`, index))
  const events = buildRows(18, (_, index) => buildRuntimeEvent(index))
  const rawRecords = buildRuntimeRawRecords(16)

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const { pathname } = url
    if (pathname === '/api/runtime/health/summary') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { components: [
        { component: 'guardian_strategy', runtime_node: 'host:guardian', status: 'warning', heartbeat_age_s: 4, issue_trace_count: 3, issue_step_count: 4, trace_count: 18, metrics: { queue_len: 2 } },
        { component: 'order_submit', runtime_node: 'host:rear', status: 'warning', heartbeat_age_s: 5, issue_trace_count: 4, issue_step_count: 6, trace_count: 18, metrics: { queue_len: 3 } },
        { component: 'xt_producer', runtime_node: 'host:xt_producer', status: 'info', heartbeat_age_s: 2, issue_trace_count: 0, issue_step_count: 0, trace_count: 7, metrics: { connected: 1 } },
      ] } }) })
      return
    }
    if (pathname === '/api/runtime/traces') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { items: traces, next_cursor: null } }) })
      return
    }
    if (pathname === '/api/runtime/events') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { items: events, next_cursor: null } }) })
      return
    }
    if (pathname === '/api/runtime/raw-files/files') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { files: [{ name: 'host-rear-2026-03-18.jsonl' }] } }) })
      return
    }
    if (pathname === '/api/runtime/raw-files/tail') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { records: rawRecords } }) })
      return
    }
    if (pathname.startsWith('/api/runtime/traces/') && pathname.endsWith('/steps')) {
      const traceKey = pathname.replace('/api/runtime/traces/', '').replace('/steps', '')
      const trace = traces.find((item) => item.trace_key === traceKey || item.trace_id === traceKey)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { items: trace?.steps || [], next_cursor: null } }) })
      return
    }
    if (pathname.startsWith('/api/runtime/traces/')) {
      const traceKey = pathname.replace('/api/runtime/traces/', '')
      const trace = traces.find((item) => item.trace_key === traceKey || item.trace_id === traceKey)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { trace, steps: trace?.steps || [], next_cursor: null } }) })
      return
    }
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: `${pathname} not mocked` }) })
  })
}

function buildStockSignalRows(category, count) {
  return buildRows(count, (index) => ({
    code: String(100000 + index).padStart(6, '0'),
    name: `${category}-${index + 1}`,
    position: index % 2 === 0 ? 'BUY_LONG' : 'SELL_SHORT',
    category,
    remark: `${category}-remark-${index + 1}`,
    fire_time: `2026-03-18T13:${String(index).padStart(2, '0')}:00+08:00`,
    created_at: `2026-03-18T13:${String(index).padStart(2, '0')}:30+08:00`,
    price: 10 + index * 0.1,
    stop_lose_price: 9 + index * 0.08,
  }))
}

function buildStockModelRows(count) {
  return buildRows(count, (index) => ({
    code: String(200000 + index).padStart(6, '0'),
    name: `模型标的${index + 1}`,
    datetime: `2026-03-18T14:${String(index).padStart(2, '0')}:00+08:00`,
    created_at: `2026-03-18T14:${String(index).padStart(2, '0')}:30+08:00`,
    period: index % 2 === 0 ? '30m' : '1d',
    model: index % 2 === 0 ? 'S0008' : 'S0009',
    source: index % 2 === 0 ? 'stock_pools' : 'must_pools',
    close: 12 + index * 0.1,
    stop_loss_price: 11 + index * 0.08,
  }))
}

async function setupStockControlRoutes(page) {
  const signalRows = { holdings: buildStockSignalRows('holdings', 48), must_pool_buys: buildStockSignalRows('must_pool_buys', 46) }
  const modelRows = buildStockModelRows(52)
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/get_stock_signal_list') {
      const category = url.searchParams.get('category') || 'holdings'
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(signalRows[category] || []) })
      return
    }
    if (url.pathname === '/api/get_stock_model_signal_list') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(modelRows) })
      return
    }
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: `${url.pathname} not mocked` }) })
  })
}

test.beforeAll(async () => {
  test.setTimeout(120000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runBuild()
  devServerProcess = startPreviewServer({ port: DEV_SERVER_PORT, cwd: process.cwd(), outDir: PREVIEW_ARTIFACTS.outDirRelative })
  await waitForServer(DEV_SERVER_URL)
})

test.afterAll(async () => {
  await stopDevServer(devServerProcess)
  devServerProcess = null
})

test('daily-screening ledgers keep the first row clear of the header after scrolling', async ({ page }) => {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await setupDailyScreeningRoutes(page)
  await page.goto(`${DEV_SERVER_URL}/daily-screening`)
  await expect(page.locator('.daily-results-ledger .runtime-ledger__row').first()).toBeVisible()
  await page.locator('.daily-results-ledger .runtime-ledger__row').first().click()
  await expect(page.locator('.daily-history-ledger .runtime-ledger__row').first()).toBeVisible()
  const resultsMetric = await measureLedger(page.locator('.daily-results-ledger'), { name: 'daily results ledger', headerSelector: '.runtime-ledger__header', rowSelector: '.runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport' })
  await page.getByRole('tab', { name: /must_pools/ }).click()
  const workspaceMetric = await measureLedger(page.getByRole('tabpanel', { name: /must_pools/ }).locator('.daily-workspace-ledger'), { name: 'daily workspace must_pools ledger', headerSelector: '.runtime-ledger__header', rowSelector: '.runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport' })
  const historyMetric = await measureLedger(page.locator('.daily-history-ledger'), { name: 'daily history ledger', headerSelector: '.runtime-ledger__header', rowSelector: '.runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport' })
  assertNoOverlap([resultsMetric, workspaceMetric, historyMetric])
})

test('position-management ledgers keep the first row clear of the header after scrolling', async ({ page }) => {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await setupPositionManagementRoutes(page)
  await page.goto(`${DEV_SERVER_URL}/position-management`)
  await expect(page.locator('.runtime-position-symbol-limit-ledger .runtime-ledger__row').first()).toBeVisible()
  await expect(page.locator('.runtime-position-decision-ledger .runtime-ledger__row').first()).toBeVisible()
  const metrics = await Promise.all([
    measureLedger(page.locator('.position-state-scroll'), { name: 'position rule ledger', headerSelector: '.runtime-position-rule-ledger .runtime-ledger__header', rowSelector: '.runtime-position-rule-ledger .runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport', scrollTop: 220 }),
    measureLedger(page.locator('.runtime-position-symbol-limit-ledger'), { name: 'position symbol-limit ledger', headerSelector: '.runtime-ledger__header', rowSelector: '.runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport' }),
    measureLedger(page.locator('.runtime-position-decision-ledger'), { name: 'position decision ledger', headerSelector: '.runtime-ledger__header', rowSelector: '.runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport' }),
  ])
  assertNoOverlap(metrics)
})

test('position-management symbol-limit detail text stays inside each cell with long source labels', async ({ page }) => {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await setupPositionManagementRoutes(page)
  await page.goto(`${DEV_SERVER_URL}/position-management`)
  const metric = await measureTextHorizontalOverflow(
    page.locator('.runtime-position-symbol-limit-ledger'),
    {
      name: 'position symbol-limit detail text',
      rowSelector: '.runtime-ledger__row',
      detailSelector: '.position-source-cell > span',
    },
  )
  assertNoTextHorizontalOverflow(metric)
})

test('runtime-observability ledgers keep the first row clear of the header after scrolling', async ({ page }) => {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await setupRuntimeObservabilityRoutes(page)
  await page.goto(`${DEV_SERVER_URL}/runtime-observability`)
  await expect(page.locator('.runtime-trace-ledger .runtime-ledger__row').first()).toBeVisible()
  await page.locator('.runtime-trace-ledger .runtime-ledger__row').first().click()
  await expect(page.locator('.trace-step-ledger .trace-step-ledger__row').first()).toBeVisible()
  const traceMetric = await measureLedger(page.locator('.runtime-trace-ledger-scroll'), { name: 'runtime trace ledger', headerSelector: '.runtime-ledger__header', rowSelector: '.runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport' })
  const stepMetric = await measureLedger(page.locator('.trace-step-ledger'), { name: 'runtime trace-step ledger', headerSelector: '.trace-step-ledger__header', rowSelector: '.trace-step-ledger__row', viewportSelector: '.trace-step-ledger__viewport' })
  await page.locator('.trace-detail-tabs').getByRole('tab', { name: /原始数据/ }).click()
  await page.getByRole('button', { name: '打开 Raw Browser' }).click()
  const rawDrawer = page.locator('.el-overlay.is-drawer').filter({ hasText: /Raw Records/ }).last()
  await expect(rawDrawer).toBeVisible()
  await expect(page.locator('.embedded-raw-ledger .embedded-raw-ledger__entry').first()).toBeVisible()
  const rawMetric = await measureLedger(page.locator('.embedded-raw-ledger'), { name: 'runtime embedded raw ledger', headerSelector: '.embedded-raw-ledger__header', rowSelector: '.embedded-raw-ledger__entry', viewportSelector: '.embedded-raw-ledger__viewport' })
  await page.keyboard.press('Escape')
  await expect(rawDrawer).toBeHidden()
  await page.getByRole('radio', { name: '组件 Event' }).check({ force: true })
  await expect(page.locator('.runtime-event-ledger .runtime-ledger__row').first()).toBeVisible()
  const eventMetric = await measureLedger(page.locator('.runtime-event-ledger'), { name: 'runtime event ledger', headerSelector: '.runtime-ledger__header', rowSelector: '.runtime-ledger__row', viewportSelector: '.runtime-ledger__viewport' })
  assertNoOverlap([traceMetric, stepMetric, rawMetric, eventMetric])
})

test('stock-control ledgers keep the first row clear of the header after scrolling', async ({ page }) => {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await setupStockControlRoutes(page)
  await page.goto(`${DEV_SERVER_URL}/stock-control`)
  await expect(page.locator('.stock-control-ledger--signal .stock-control-ledger__row').first()).toBeVisible()
  await expect(page.locator('.stock-control-ledger--model .stock-control-ledger__row').first()).toBeVisible()
  const metrics = await Promise.all([
    measureLedger(page.locator('.stock-control-ledger--signal').nth(0), { name: 'stock-control holdings signal ledger', headerSelector: '.stock-control-ledger__header', rowSelector: '.stock-control-ledger__row', viewportSelector: '.stock-control-ledger__viewport' }),
    measureLedger(page.locator('.stock-control-ledger--model'), { name: 'stock-control model signal ledger', headerSelector: '.stock-control-ledger__header', rowSelector: '.stock-control-ledger__row', viewportSelector: '.stock-control-ledger__viewport' }),
    measureLedger(page.locator('.stock-control-ledger--signal').nth(1), { name: 'stock-control must-pool signal ledger', headerSelector: '.stock-control-ledger__header', rowSelector: '.stock-control-ledger__row', viewportSelector: '.stock-control-ledger__viewport' }),
  ])
  assertNoOverlap(metrics)
})
