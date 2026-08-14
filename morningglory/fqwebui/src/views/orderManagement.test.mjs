import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  ORDER_STATE_FILTER_OPTIONS,
  buildOrderDetailViewModel,
  buildOrderRows,
  buildOrderStats,
  createOrderManagementActions,
  formatLedgerLabel,
  formatOrderPrice,
  formatOrderTimestamp,
  ledgerChipVariant,
  resolveOrderLedgerFromRequest,
} from './orderManagement.mjs'


test('buildOrderRows sorts latest rows first and keeps request-derived fields', () => {
  const rows = buildOrderRows([
    {
      internal_order_id: 'ord_1',
      request_id: 'req_1',
      symbol: '600000',
      name: '浦发银行',
      side: 'buy',
      state: 'FILLED',
      strategy_name: 'Guardian',
      source: 'strategy',
      updated_at: '2026-03-13T09:05:00+08:00',
    },
    {
      internal_order_id: 'ord_2',
      request_id: 'req_2',
      symbol: '000001',
      side: 'sell',
      state: 'QUEUED',
      strategy_name: 'ManualDesk',
      source: 'web',
      updated_at: '2026-03-13T10:05:00+08:00',
    },
  ])

  assert.equal(rows[0].internal_order_id, 'ord_2')
  assert.equal(rows[0].state_label, '已入队')
  assert.equal(rows[0].state_chip_variant, 'info')
  assert.equal(rows[0].summaryLabel, '000001 · sell · 已入队')
  assert.equal(rows[1].name, '浦发银行')
  assert.equal(rows[1].strategy_name, 'Guardian')
  assert.equal(rows[1].source, 'strategy')
})

test('buildOrderRows exposes a fallback lookup id when broker-only rows have no internal_order_id', () => {
  const rows = buildOrderRows([
    {
      broker_order_id: '403701761',
      broker_order_key: '403701761',
      symbol: '600104',
      side: 'sell',
      state: 'FILLED',
    },
  ])

  assert.equal(rows[0].orderLookupId, '403701761')
})

test('buildOrderRows keeps a muted fallback for unknown order states', () => {
  const rows = buildOrderRows([
    {
      internal_order_id: 'ord_unknown',
      symbol: '600000',
      side: 'buy',
      state: 'WAITING_EXTERNAL',
    },
  ])

  assert.equal(rows[0].state_label, 'WAITING_EXTERNAL')
  assert.equal(rows[0].state_chip_variant, 'muted')
  assert.equal(rows[0].state_severity, 'warn')
})

test('order state filter options keep the legacy CANCELLED alias selectable', () => {
  assert.ok(
    ORDER_STATE_FILTER_OPTIONS.some(
      (option) => option.value === 'CANCELLED' && option.label === '已撤单',
    ),
  )

  const rows = buildOrderRows([
    {
      internal_order_id: 'ord_cancelled',
      symbol: '600000',
      side: 'sell',
      state: 'CANCELLED',
    },
  ])

  assert.equal(rows[0].state_label, '已撤单')
  assert.equal(rows[0].state_chip_variant, 'muted')
})

test('order helpers keep instrument name, 3-decimal prices and second-level timestamps', () => {
  assert.equal(formatOrderPrice(null), '-')
  assert.equal(formatOrderPrice(''), '-')
  assert.equal(formatOrderPrice(10.12345), '10.123')
  assert.equal(formatOrderPrice('10.1'), '10.100')
  assert.equal(formatOrderTimestamp('2026-03-13T10:05:00+08:00'), '2026-03-13 10:05:00')
  assert.equal(formatOrderTimestamp('2026-03-13T10:05:00.123+08:00'), '2026-03-13 10:05:00')
  assert.equal(formatOrderTimestamp('2026-03-25T05:46:10+00:00'), '2026-03-25 13:46:10')
  assert.equal(formatOrderTimestamp(1774417570), '2026-03-25 13:46:10')
})





test('buildOrderDetailViewModel and buildOrderStats keep identifiers and distributions', () => {
  const detail = buildOrderDetailViewModel({
    order: {
      internal_order_id: 'ord_1',
      request_id: 'req_1',
      symbol: '600000',
      side: 'buy',
      state: 'FILLED',
      trace_id: 'trc_1',
      intent_id: 'int_1',
      broker_order_id: 'BRK-1',
    },
    request: {
      request_id: 'req_1',
      source: 'strategy',
      strategy_name: 'Guardian',
      scope_type: 'signal',
      scope_ref_id: 'sig_1',
    },
    events: [
      { event_id: 'evt_1', event_type: 'accepted', state: 'ACCEPTED' },
      { event_id: 'evt_2', event_type: 'trade_reported', state: 'FILLED' },
    ],
    trades: [
      { trade_fact_id: 'trade_1', quantity: 100, price: 10.1, trade_time: 1774417570 },
    ],
    identifiers: {
      trace_id: 'trc_1',
      intent_id: 'int_1',
      request_id: 'req_1',
      internal_order_id: 'ord_1',
      broker_order_id: 'BRK-1',
    },
  })
  const stats = buildOrderStats({
    total: 2,
    side_distribution: { buy: 1, sell: 1 },
    state_distribution: { FILLED: 1, QUEUED: 1 },
    missing_broker_order_count: 1,
    latest_updated_at: '2026-03-25T05:46:10+00:00',
  })

  assert.equal(detail.headerTitle, '600000 · ord_1')
  assert.equal(detail.order.state_label, '已成交')
  assert.equal(detail.timelineRows[0].state_label, '已受理')
  assert.equal(detail.requestSummary, 'strategy · Guardian')
  assert.equal(detail.timelineRows[1].event_type, 'trade_reported')
  assert.equal(detail.tradeSummary, '1 笔成交')
  assert.equal(detail.tradeRows[0].trade_time_label, '2026-03-25 13:46:10')
  assert.equal(detail.identifierRows[0].key, 'trace_id')
  assert.equal(stats.total, 2)
  assert.equal(stats.latest_updated_at, '2026-03-25 13:46:10')
  assert.equal(stats.sideCards[0].label, '买单')
  assert.equal(stats.stateCards[0].label, '已成交')
})

test('createOrderManagementActions calls order list, detail and stats APIs', async () => {
  const calls = []
  const api = {
    async listOrders(params) {
      calls.push(['listOrders', params.symbol, params.page, params.size])
      return {
        rows: [{ internal_order_id: 'ord_1', symbol: '600000', side: 'buy', state: 'FILLED' }],
        total: 1,
        page: params.page,
        size: params.size,
      }
    },
    async getOrderDetail(internalOrderId) {
      calls.push(['getOrderDetail', internalOrderId])
      return {
        order: { internal_order_id: internalOrderId, symbol: '600000', side: 'buy', state: 'FILLED' },
        request: { request_id: 'req_1', source: 'strategy', strategy_name: 'Guardian' },
        events: [],
        trades: [],
        identifiers: {},
      }
    },
    async getStats(params) {
      calls.push(['getStats', params.symbol])
      return {
        total: 1,
        side_distribution: { buy: 1, sell: 0 },
        state_distribution: { FILLED: 1 },
        missing_broker_order_count: 0,
      }
    },
  }

  const actions = createOrderManagementActions(api)
  const rowsPayload = await actions.loadOrders({ symbol: '600000', page: 2, size: 5 })
  const detail = await actions.loadOrderDetail('ord_1')
  const stats = await actions.loadStats({ symbol: '600000' })

  assert.equal(rowsPayload.rows[0].internal_order_id, 'ord_1')
  assert.equal(detail.order.internal_order_id, 'ord_1')
  assert.equal(stats.total, 1)
  assert.deepEqual(calls, [
    ['listOrders', '600000', 2, 5],
    ['getOrderDetail', 'ord_1'],
    ['getStats', '600000'],
  ])
})





test('#549 buildOrderRows passes ledger fields through', () => {
  const rows = buildOrderRows([
    {
      internal_order_id: 'ord_ledger_1',
      request_id: 'req_ledger_1',
      symbol: '600000',
      side: 'buy',
      state: 'FILLED',
      ledger: 'base',
      position_type: 'base',
    },
    {
      internal_order_id: 'ord_ledger_2',
      request_id: 'req_ledger_2',
      symbol: '600000',
      side: 'sell',
      state: 'FILLED',
      ledger: '-',
      position_type: '',
    },
  ])

  assert.equal(rows[1].ledger, 'base')
  assert.equal(rows[1].position_type, 'base')
  assert.equal(rows[0].ledger, '-')
  assert.equal(rows[0].position_type, '')
})

test('#571 resolveOrderLedgerFromRequest reads ledger_intent only (no legacy fields)', () => {
  assert.equal(resolveOrderLedgerFromRequest('buy', { ledger_intent: 'base' }), 'base')
  assert.equal(resolveOrderLedgerFromRequest('buy', { ledger_intent: 't' }), 't')
  // 缺失/未知 intent 不再用旧字段推断
  assert.equal(resolveOrderLedgerFromRequest('buy', {}), '')
  assert.equal(
    resolveOrderLedgerFromRequest('buy', {
      ledger_intent: '',
      strategy_context: { guardian_buy_grid: { grid_level: 'BUY-3' } },
    }),
    '',
  )
  assert.equal(resolveOrderLedgerFromRequest('sell', { ledger_intent: 'base' }), 'base')
  assert.equal(resolveOrderLedgerFromRequest('sell', { ledger_intent: 't' }), 't')
  assert.equal(resolveOrderLedgerFromRequest('sell', { ledger_intent: 'mixed' }), 'mixed')
  assert.equal(resolveOrderLedgerFromRequest('sell', { ledger_intent: '-' }), '-')
  assert.equal(resolveOrderLedgerFromRequest('sell', {}), '')
})

test('#571 buildOrderDetailViewModel exposes ledger with request fallback', () => {
  const detail = buildOrderDetailViewModel({
    order: {
      internal_order_id: 'ord_detail_1',
      symbol: '600000',
      side: 'buy',
      state: 'FILLED',
    },
    request: {
      ledger_intent: 't',
    },
    events: [],
    trades: [],
    identifiers: {},
  })

  assert.equal(detail.order.ledger, 't')
  assert.equal(detail.order.ledger_label, '做T')

  const withBackendLedger = buildOrderDetailViewModel({
    order: {
      internal_order_id: 'ord_detail_2',
      symbol: '600000',
      side: 'sell',
      state: 'FILLED',
      ledger: '-',
    },
    request: { strategy_context: {} },
    events: [],
    trades: [],
    identifiers: {},
  })
  assert.equal(withBackendLedger.order.ledger, '-')
  assert.equal(withBackendLedger.order.ledger_label, '-')
})

test('#571 formatLedgerLabel and ledgerChipVariant map base/t/mixed/-', () => {
  assert.equal(formatLedgerLabel('base'), '底仓')
  assert.equal(formatLedgerLabel('t'), '做T')
  assert.equal(formatLedgerLabel('mixed'), '分摊')
  assert.equal(formatLedgerLabel('-'), '-')
  assert.equal(formatLedgerLabel(''), '-')
  assert.equal(ledgerChipVariant('base'), 'info')
  assert.equal(ledgerChipVariant('t'), 'warning')
  assert.equal(ledgerChipVariant('mixed'), 'warning')
  assert.equal(ledgerChipVariant('-'), 'muted')
})
