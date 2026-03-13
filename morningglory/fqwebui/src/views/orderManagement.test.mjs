import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildOrderDetailViewModel,
  buildOrderRows,
  buildOrderStats,
  createOrderManagementActions,
} from './orderManagement.mjs'
import { createOrderManagementPageController } from './orderManagementPage.mjs'

test('buildOrderRows sorts latest rows first and keeps request-derived fields', () => {
  const rows = buildOrderRows([
    {
      internal_order_id: 'ord_1',
      request_id: 'req_1',
      symbol: '600000',
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
  assert.equal(rows[0].summaryLabel, '000001 · sell · QUEUED')
  assert.equal(rows[1].strategy_name, 'Guardian')
  assert.equal(rows[1].source, 'strategy')
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
      { trade_fact_id: 'trade_1', quantity: 100, price: 10.1 },
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
    latest_updated_at: '2026-03-13T10:05:00+08:00',
  })

  assert.equal(detail.headerTitle, '600000 · ord_1')
  assert.equal(detail.requestSummary, 'strategy · Guardian')
  assert.equal(detail.timelineRows[1].event_type, 'trade_reported')
  assert.equal(detail.tradeSummary, '1 笔成交')
  assert.equal(detail.identifierRows[0].key, 'trace_id')
  assert.equal(stats.total, 2)
  assert.equal(stats.sideCards[0].label, '买单')
  assert.equal(stats.stateCards[0].label, 'FILLED')
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

test('page controller refreshes list and auto-selects the first order detail', async () => {
  const calls = []
  const controller = createOrderManagementPageController({
    actions: {
      async loadOrders(filters) {
        calls.push(['loadOrders', filters.symbol || '', filters.page, filters.size])
        return {
          rows: [
            {
              internal_order_id: 'ord_2',
              request_id: 'req_2',
              symbol: filters.symbol || '000001',
              side: 'sell',
              state: 'QUEUED',
              updated_at: '2026-03-13T10:05:00+08:00',
            },
          ],
          total: 1,
          page: filters.page,
          size: filters.size,
        }
      },
      async loadStats(filters) {
        calls.push(['loadStats', filters.symbol || ''])
        return {
          total: 1,
          side_distribution: { buy: 0, sell: 1 },
          state_distribution: { QUEUED: 1 },
          missing_broker_order_count: 1,
        }
      },
      async loadOrderDetail(internalOrderId) {
        calls.push(['loadOrderDetail', internalOrderId])
        return buildOrderDetailViewModel({
          order: {
            internal_order_id: internalOrderId,
            request_id: 'req_2',
            symbol: '000001',
            side: 'sell',
            state: 'QUEUED',
          },
          request: {
            request_id: 'req_2',
            source: 'web',
            strategy_name: 'ManualDesk',
          },
          events: [],
          trades: [],
          identifiers: {},
        })
      },
    },
  })

  controller.state.filters.symbol = '000001'
  await controller.refreshAll()

  assert.equal(controller.state.selectedOrderId, 'ord_2')
  assert.equal(controller.state.detail.order.internal_order_id, 'ord_2')
  assert.equal(controller.state.stats.total, 1)
  assert.deepEqual(calls, [
    ['loadOrders', '000001', 1, 20],
    ['loadStats', '000001'],
    ['loadOrderDetail', 'ord_2'],
  ])
})

test('page controller keeps list error visible when stats still succeed', async () => {
  const controller = createOrderManagementPageController({
    actions: {
      async loadOrders() {
        throw new Error('orders failed')
      },
      async loadStats() {
        return {
          total: 3,
          side_distribution: { buy: 2, sell: 1 },
          state_distribution: { QUEUED: 3 },
          missing_broker_order_count: 0,
        }
      },
      async loadOrderDetail() {
        throw new Error('detail should not load without rows')
      },
    },
  })

  await controller.refreshAll()

  assert.equal(controller.state.pageError, 'orders failed')
  assert.equal(controller.state.rows.length, 0)
  assert.equal(controller.state.total, 0)
  assert.equal(controller.state.detail, null)
  assert.equal(controller.state.stats.total, 3)
})

test('page controller clears stale detail when detail loading fails', async () => {
  const controller = createOrderManagementPageController({
    actions: {
      async loadOrders() {
        return {
          rows: [
            {
              internal_order_id: 'ord_2',
              request_id: 'req_2',
              symbol: '000001',
              side: 'sell',
              state: 'QUEUED',
              updated_at: '2026-03-13T10:05:00+08:00',
            },
          ],
          total: 1,
          page: 1,
          size: 20,
        }
      },
      async loadStats() {
        return {
          total: 1,
          side_distribution: { buy: 0, sell: 1 },
          state_distribution: { QUEUED: 1 },
          missing_broker_order_count: 0,
        }
      },
      async loadOrderDetail(internalOrderId) {
        if (internalOrderId === 'ord_1') {
          return buildOrderDetailViewModel({
            order: {
              internal_order_id: internalOrderId,
              symbol: '600000',
              side: 'buy',
              state: 'FILLED',
            },
            request: {},
            events: [],
            trades: [],
            identifiers: {},
          })
        }
        throw new Error('detail failed')
      },
    },
  })

  controller.state.detail = buildOrderDetailViewModel({
    order: {
      internal_order_id: 'ord_1',
      symbol: '600000',
      side: 'buy',
      state: 'FILLED',
    },
    request: {},
    events: [],
    trades: [],
    identifiers: {},
  })
  controller.state.selectedOrderId = 'ord_1'

  await controller.selectOrder('ord_2')

  assert.equal(controller.state.pageError, 'detail failed')
  assert.equal(controller.state.detail, null)
  assert.equal(controller.state.selectedOrderId, 'ord_1')
})
