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
      recent_decisions: buildRows(48, (index) => ({
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

function buildPositionManagementSubjectOverview(symbols) {
  return symbols.map((symbol, index) => {
    const positionAmount = 920000 - index * 24000
    return {
      symbol,
      name: `标的${index + 1}`,
      category: index % 2 === 0 ? '银行' : '科技',
      must_pool: {
        category: index % 2 === 0 ? '银行' : '科技',
        stop_loss_price: 9.1 - index * 0.02,
        initial_lot_amount: 90000 - index * 1000,
        lot_amount: 60000 - index * 500,
      },
      guardian: {
        enabled: index % 3 !== 0,
        buy_1: 10.2 - index * 0.03,
        buy_2: 9.9 - index * 0.03,
        buy_3: 9.5 - index * 0.03,
      },
      takeprofit: {
        tiers: [],
      },
      stoploss: {
        active_count: index % 4 === 0 ? 2 : 1,
        open_entry_count: index % 3 === 0 ? 3 : 2,
      },
      runtime: {
        position_quantity: 1200 - index * 30,
        position_amount: positionAmount,
        last_hit_level: index % 2 === 0 ? 'BUY-2' : 'BUY-1',
        last_trigger_time: `2026-03-18T10:${String(index).padStart(2, '0')}:00+08:00`,
      },
      position_limit_summary: {
        market_value: positionAmount,
        default_limit: 800000,
        override_limit: index % 3 === 0 ? 650000 : null,
        effective_limit: index % 3 === 0 ? 650000 : 800000,
        using_override: index % 3 === 0,
        blocked: index % 4 === 0,
      },
    }
  })
}

function buildPositionManagementSubjectDetail(row, index) {
  const entryCount = index === 0 ? 12 : index === 1 ? 8 : 3
  const entries = buildRows(entryCount, (entryIndex) => {
    const baseQuantity = 180 - entryIndex * 8
    const sliceCount = index === 0 ? (entryIndex === 0 ? 2 : 1) : 1
    return {
      entry_id: `${row.symbol}-entry-${entryIndex + 1}`,
      date: `202603${String((entryIndex % 9) + 10).padStart(2, '0')}`,
      time: `09${String((entryIndex % 5) + 30).padStart(2, '0')}00`,
      entry_price: 10.2 - index * 0.04 - entryIndex * 0.02,
      original_quantity: baseQuantity,
      remaining_quantity: Math.max(baseQuantity - 20, 20),
      latest_price: 10.3 - index * 0.04 - entryIndex * 0.02,
      remaining_market_value: (Math.max(baseQuantity - 20, 20)) * (10.3 - index * 0.04 - entryIndex * 0.02),
      stoploss: {
        stop_price: 9.2 - index * 0.03 - entryIndex * 0.01,
        enabled: entryIndex % 2 === 0,
      },
      aggregation_members: [
        {
          order_id: `${row.symbol}-buy-a-${entryIndex + 1}`,
          quantity: Math.max(Math.trunc(baseQuantity / 2), 10),
        },
        {
          order_id: `${row.symbol}-buy-b-${entryIndex + 1}`,
          quantity: Math.max(baseQuantity - Math.trunc(baseQuantity / 2), 10),
        },
      ],
      aggregation_window: {
        started_at: `2026-03-18T09:${String((entryIndex % 5) + 30).padStart(2, '0')}:00+08:00`,
        ended_at: `2026-03-18T10:${String((entryIndex % 5) + 5).padStart(2, '0')}:00+08:00`,
      },
      entry_slices: buildRows(sliceCount, (sliceIndex) => ({
        entry_slice_id: `${row.symbol}-slice-${entryIndex + 1}-${sliceIndex + 1}`,
        slice_seq: sliceIndex + 1,
        guardian_price: 9.85 - sliceIndex * 0.06 - index * 0.02,
        original_quantity: Math.max(Math.trunc(baseQuantity / sliceCount), 10),
        remaining_quantity: Math.max(Math.trunc((baseQuantity - 20) / sliceCount), 10),
        remaining_amount: Math.max(Math.trunc((baseQuantity - 20) / sliceCount), 10) * (10.1 - index * 0.04),
      })),
    }
  })

  return {
    subject: {
      symbol: row.symbol,
      name: row.name,
      category: row.category,
    },
    must_pool: { ...row.must_pool },
    guardian_buy_grid_config: {
      enabled: row.guardian.enabled,
      buy_1: row.guardian.buy_1,
      buy_2: row.guardian.buy_2,
      buy_3: row.guardian.buy_3,
    },
    guardian_buy_grid_state: {
      last_hit_level: row.runtime.last_hit_level,
      last_hit_price: row.guardian.buy_2,
      last_hit_signal_time: row.runtime.last_trigger_time,
    },
    takeprofit: {
      tiers: [],
      state: {},
    },
    entries,
    runtime_summary: {
      position_quantity: row.runtime.position_quantity,
      position_amount: row.runtime.position_amount,
      avg_price: 10.05 - index * 0.03,
      last_trigger_time: row.runtime.last_trigger_time,
      last_trigger_kind: index % 2 === 0 ? 'guardian_buy' : 'takeprofit',
    },
    position_management_summary: {
      effective_state: index % 5 === 0 ? 'HOLDING_ONLY' : 'ALLOW_OPEN',
      allow_open_min_bail: 800000,
      holding_only_min_bail: 100000,
    },
    position_limit_summary: {
      market_value: row.position_limit_summary.market_value,
      default_limit: row.position_limit_summary.default_limit,
      override_limit: row.position_limit_summary.override_limit,
      effective_limit: row.position_limit_summary.effective_limit,
      using_override: row.position_limit_summary.using_override,
      blocked: row.position_limit_summary.blocked,
    },
  }
}

function buildPositionManagementReconciliation(symbols) {
  const rows = symbols.map((symbol, index) => {
    const auditStatus = index % 6 === 0 ? 'ERROR' : index % 4 === 0 ? 'WARN' : 'OK'
    const reconciliationState = auditStatus === 'ERROR'
      ? (index % 2 === 0 ? 'BROKEN' : 'DRIFT')
      : auditStatus === 'WARN'
        ? 'OBSERVING'
        : 'AUTO_RECONCILED'
    const quantityBase = 1200 - index * 18
    const brokerQuantity = quantityBase
    const entryQuantity = auditStatus === 'ERROR'
      ? quantityBase - 120
      : auditStatus === 'WARN'
        ? quantityBase - 40
        : quantityBase
    const sliceQuantity = auditStatus === 'ERROR' ? entryQuantity - 40 : entryQuantity
    const mismatchCodes = []
    if (auditStatus === 'ERROR') mismatchCodes.push('broker_vs_entry_quantity_mismatch')
    if (auditStatus === 'ERROR' && index % 2 === 0) mismatchCodes.push('entry_vs_slice_quantity_mismatch')
    if (auditStatus === 'WARN') mismatchCodes.push('entry_vs_compat_quantity_mismatch')

    const makeSurface = (key, label, quantity, marketValue, source) => ({
      key,
      label,
      quantity,
      market_value: marketValue,
      quantity_source: `${source}.quantity_projection.with_extremely_long_label_for_browser_wrapping_checks.${symbol}`,
      market_value_source: `${source}.market_value_projection.with_extremely_long_label_for_browser_wrapping_checks.${symbol}`,
    })

    const surfaces = [
      makeSurface('broker', '券商', brokerQuantity, brokerQuantity * 95, 'xt_positions'),
      makeSurface('snapshot', 'PM快照', brokerQuantity, brokerQuantity * 95, 'pm_symbol_position_snapshots'),
      makeSurface('entry_ledger', 'Entry账本', entryQuantity, entryQuantity * 94, 'order_management.position_entries'),
      makeSurface('slice_ledger', 'Slice账本', sliceQuantity, sliceQuantity * 93, 'order_management.entry_slices'),
      makeSurface('compat_projection', 'Compat镜像', entryQuantity, entryQuantity * 94, 'stock_fills_compat'),
      makeSurface('stock_fills_projection', 'StockFills投影', entryQuantity, entryQuantity * 94, 'api.stock_fills'),
    ]

    return {
      symbol,
      name: `标的${index + 1}`,
      audit_status: auditStatus,
      latest_resolution_label: auditStatus === 'ERROR' ? 'MANUAL_REVIEW' : auditStatus === 'WARN' ? 'OBSERVE_GAP' : 'AUTO_OPENED',
      mismatch_codes: mismatchCodes,
      broker: { quantity: brokerQuantity, market_value: brokerQuantity * 95 },
      snapshot: { quantity: brokerQuantity, market_value: brokerQuantity * 95 },
      entry_ledger: { quantity: entryQuantity, market_value: entryQuantity * 94 },
      slice_ledger: { quantity: sliceQuantity, market_value: sliceQuantity * 93 },
      compat_projection: { quantity: entryQuantity, market_value: entryQuantity * 94 },
      stock_fills_projection: { quantity: entryQuantity, market_value: entryQuantity * 94 },
      reconciliation: {
        state: reconciliationState,
        signed_gap_quantity: brokerQuantity - entryQuantity,
        open_gap_count: auditStatus === 'ERROR' ? 2 : auditStatus === 'WARN' ? 1 : 0,
      },
      rule_results: {
        R1: { id: 'R1', key: 'broker_snapshot_consistency', label: '券商与PM快照', expected_relation: 'exact_match', status: 'OK', mismatch_codes: [] },
        R2: { id: 'R2', key: 'ledger_internal_consistency', label: 'Entry与Slice账本', expected_relation: 'exact_match', status: auditStatus === 'ERROR' ? 'ERROR' : 'OK', mismatch_codes: mismatchCodes.filter((code) => code === 'entry_vs_slice_quantity_mismatch') },
        R3: { id: 'R3', key: 'compat_projection_consistency', label: '账本与兼容投影', expected_relation: 'projection_match', status: auditStatus === 'WARN' ? 'WARN' : 'OK', mismatch_codes: mismatchCodes.filter((code) => code === 'entry_vs_compat_quantity_mismatch') },
        R4: { id: 'R4', key: 'broker_vs_ledger_consistency', label: '券商与账本解释', expected_relation: 'reconciliation_explained', status: auditStatus, mismatch_codes: mismatchCodes },
      },
      surface_values: Object.fromEntries(surfaces.map((surface) => [surface.key, surface])),
      evidence_sections: {
        surfaces,
        rules: [
          { id: 'R4', label: '券商与账本解释', status: auditStatus, mismatch_codes: mismatchCodes },
        ],
        reconciliation: {
          state: reconciliationState,
          signed_gap_quantity: brokerQuantity - entryQuantity,
          open_gap_count: auditStatus === 'ERROR' ? 2 : auditStatus === 'WARN' ? 1 : 0,
        },
      },
    }
  })

  const auditStatusCounts = rows.reduce((counts, row) => {
    counts[row.audit_status] = (counts[row.audit_status] || 0) + 1
    return counts
  }, { OK: 0, WARN: 0, ERROR: 0 })

  const reconciliationStateCounts = rows.reduce((counts, row) => {
    counts[row.reconciliation.state] = (counts[row.reconciliation.state] || 0) + 1
    return counts
  }, {
    ALIGNED: 0,
    OBSERVING: 0,
    AUTO_RECONCILED: 0,
    BROKEN: 0,
    DRIFT: 0,
  })

  const ruleCounts = rows.reduce((counts, row) => {
    for (const [ruleId, rule] of Object.entries(row.rule_results || {})) {
      counts[ruleId] = counts[ruleId] || { OK: 0, WARN: 0, ERROR: 0 }
      counts[ruleId][rule.status] = (counts[ruleId][rule.status] || 0) + 1
    }
    return counts
  }, {
    R1: { OK: 0, WARN: 0, ERROR: 0 },
    R2: { OK: 0, WARN: 0, ERROR: 0 },
    R3: { OK: 0, WARN: 0, ERROR: 0 },
    R4: { OK: 0, WARN: 0, ERROR: 0 },
  })

  return {
    data: {
      summary: {
        row_count: rows.length,
        audit_status_counts: auditStatusCounts,
        reconciliation_state_counts: reconciliationStateCounts,
        rule_counts: ruleCounts,
      },
      rows,
    },
  }
}

async function setupPositionManagementRoutes(page) {
  const dashboard = buildPositionManagementDashboard()
  const subjectOverview = buildPositionManagementSubjectOverview(dashboard.data.holding_scope.codes)
  const subjectDetailMap = Object.fromEntries(
    subjectOverview.map((row, index) => [row.symbol, buildPositionManagementSubjectDetail(row, index)]),
  )
  const reconciliation = buildPositionManagementReconciliation(dashboard.data.holding_scope.codes)
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
    if (url.pathname === '/api/position-management/reconciliation') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(reconciliation),
      })
      return
    }
    if (url.pathname === '/api/subject-management/overview') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(subjectOverview),
      })
      return
    }
    if (url.pathname.startsWith('/api/subject-management/')) {
      const symbol = decodeURIComponent(url.pathname.replace('/api/subject-management/', '')).trim()
      const detail = subjectDetailMap[symbol]
      await route.fulfill({
        status: detail ? 200 : 404,
        contentType: 'application/json',
        body: JSON.stringify(detail || { error: `${symbol} not mocked` }),
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

test('position-management dense workbench keeps split panels, descending sort, full decision timeline, and entry-slice linkage', async ({ page }) => {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await setupPositionManagementRoutes(page)
  await page.goto(`${DEV_SERVER_URL}/position-management`)
  await expect(page.locator('.position-reconciliation-ledger__row').first()).toBeVisible()
  await expect(page.locator('.position-subject-table .el-table__body-wrapper tbody tr').first()).toBeVisible()
  await expect(page.locator('.position-decision-table .el-table__body-wrapper tbody tr').first()).toBeVisible()
  await expect(page.getByText('选中标的工作区', { exact: true })).toBeVisible()
  await expect(page.locator('.position-selection-entry-table .el-table__body-wrapper tbody tr').first()).toBeVisible()
  await expect(page.locator('.position-selection-slice-table .el-table__body-wrapper tbody tr').first()).toBeVisible()

  const panelHeights = await page.evaluate(() => {
    const getHeight = (selector) => {
      const element = document.querySelector(selector)
      return element ? element.getBoundingClientRect().height : 0
    }
    return {
      leftTop: getHeight('.position-state-panel'),
      leftBottom: getHeight('.position-reconciliation-panel'),
      rightTop: getHeight('.position-selection-panel'),
      rightBottom: getHeight('.position-decision-panel'),
    }
  })
  expect(Math.abs(panelHeights.leftTop - panelHeights.leftBottom)).toBeLessThanOrEqual(8)
  expect(Math.abs(panelHeights.rightTop - panelHeights.rightBottom)).toBeLessThanOrEqual(8)

  const headerTexts = await page.locator('.position-subject-table .el-table__header-wrapper thead th .cell').evaluateAll((nodes) => (
    nodes
      .map((node) => (node.textContent || '').trim())
      .filter(Boolean)
  ))
  expect(headerTexts).toEqual(expect.arrayContaining([
    '标的',
    '持仓',
    '订单状态',
    'Guardian 买入层级',
    '止盈价格层级',
    'Guardian 层级触发',
    '止盈层级触发',
    '单笔止损触发',
    '全仓止损价',
    '单标的仓位上限',
    '保存',
  ]))
  expect(headerTexts).not.toEqual(expect.arrayContaining([
    '分类',
    '止损价',
    '首笔金额',
    '常规金额',
    '活跃止损',
    '首笔买入金额',
    '默认买入金额',
    '持仓股数',
    '持仓市值',
    '活跃单笔止损',
    'Open Entry',
    '门禁',
    '最近TPLS触发',
    'TPLS触发',
    'Guardian 层级买入',
    'Guardian层级触发',
    '止盈价格',
  ]))

  const overviewTableOverflow = await page.locator('.position-subject-table .el-table__body-wrapper').evaluate((node) => ({
    clientWidth: node.clientWidth,
    scrollWidth: node.scrollWidth,
  }))
  expect(
    overviewTableOverflow.scrollWidth,
    'position-management 标的总览在桌面宽度下不应再出现横向滚动',
  ).toBeLessThanOrEqual(overviewTableOverflow.clientWidth + 1)

  const overviewSymbols = await page.locator('.position-subject-table .el-table__body-wrapper tbody tr').evaluateAll((rows) => (
    rows.slice(0, 3).map((row) => ((row.textContent || '').match(/\d{6}/) || [''])[0])
  ))
  expect(overviewSymbols).toEqual(['000001', '000002', '000003'])

  await expect(page.locator('.position-selection-panel .workbench-summary-row')).toContainText('000001')
  await expect(page.locator('.position-selection-slice-table .el-table__body-wrapper tbody tr')).toHaveCount(2)
  await page.locator('.position-subject-table .el-table__body-wrapper tbody tr').nth(1).click()
  await expect(page.locator('.position-selection-panel .workbench-summary-row')).toContainText('000002')
  await expect(page.locator('.position-decision-panel .workbench-summary-row')).toContainText('全部标的')

  const decisionSymbols = await page.locator('.position-decision-table .el-table__body-wrapper tbody tr').evaluateAll((rows) => (
    rows.map((row) => (row.querySelectorAll('td')?.[1]?.textContent || '').trim())
  ))
  expect(decisionSymbols.length).toBeGreaterThan(0)
  expect(new Set(decisionSymbols).size).toBeGreaterThan(1)

  const decisionTimes = await page.locator('.position-decision-table .el-table__body-wrapper tbody tr').evaluateAll((rows) => (
    rows.slice(0, 3).map((row) => (row.querySelectorAll('td')?.[0]?.textContent || '').trim())
  ))
  expect(decisionTimes).toEqual(['2026-03-18 10:47:00', '2026-03-18 10:46:00', '2026-03-18 10:45:00'])

  await page.locator('.position-subject-table .el-table__body-wrapper tbody tr').first().click()
  await expect(page.locator('.position-selection-panel .workbench-summary-row')).toContainText('000001')
  await expect(page.locator('.position-selection-slice-table .el-table__body-wrapper tbody tr')).toHaveCount(2)
  await page.locator('.position-selection-entry-table .el-table__body-wrapper tbody tr').nth(1).evaluate((node) => {
    node.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  })
  await expect(page.locator('.position-selection-slice-table .el-table__body-wrapper tbody tr')).toHaveCount(1)
  await expect(page.locator('.position-selection-slice-table .el-table__body-wrapper tbody tr').first()).toContainText('#2 / ntry-2')
})

test('position-management dense ledgers keep the first row clear and reconciliation evidence expands as tables', async ({ page }) => {
  await page.setViewportSize(DESKTOP_VIEWPORT)
  await setupPositionManagementRoutes(page)
  await page.goto(`${DEV_SERVER_URL}/position-management`)
  await expect(page.locator('.position-reconciliation-ledger__row').first()).toBeVisible()
  await expect(page.locator('.position-decision-table .el-table__body-wrapper tbody tr').first()).toBeVisible()
  const metrics = await Promise.all([
    measureLedger(page.locator('.position-state-panel'), { name: 'position rule ledger', headerSelector: '.runtime-position-rule-ledger .runtime-ledger__header', rowSelector: '.runtime-position-rule-ledger .runtime-ledger__row', viewportSelector: '.position-state-scroll', scrollTop: 220 }),
  ])
  assertNoOverlap(metrics)

  const firstLedgerItem = page.locator('.position-reconciliation-ledger__item').first()
  await firstLedgerItem.getByRole('button', { name: '展开' }).evaluate((element) => {
    element.click()
  })
  await expect(firstLedgerItem.locator('.position-reconciliation-expanded__surface-table .position-reconciliation-expanded__table-row').first()).toBeVisible()
  await expect(firstLedgerItem.locator('.position-reconciliation-expanded__rule-table .position-reconciliation-expanded__table-row').first()).toBeVisible()
  await expect(firstLedgerItem.locator('.position-reconciliation-expanded__reconciliation-table .position-reconciliation-expanded__table-row').first()).toBeVisible()
  await expect(firstLedgerItem.locator('.position-reconciliation-expanded')).toContainText('视图层证据表')
  await expect(firstLedgerItem.locator('.position-reconciliation-expanded')).toContainText('规则检查表')
  await expect(firstLedgerItem.locator('.position-reconciliation-expanded')).toContainText('差异说明表')
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
