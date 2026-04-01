import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildOrderDetailViewModel,
  buildOrderRows,
  buildOrderStats,
  createOrderManagementActions,
  formatOrderPrice,
  formatOrderTimestamp,
} from './orderManagement.mjs'
import { createOrderManagementPageController } from './orderManagementPage.mjs'

const orderManagementPageSource = readFileSync(new URL('./OrderManagement.vue', import.meta.url), 'utf8')

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
  assert.equal(rows[0].summaryLabel, '000001 · sell · QUEUED')
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

test('OrderManagement table uses Chinese semantics and places 更新时间 after 标的代码', () => {
  assert.match(orderManagementPageSource, /{{ row\.name \|\| '-' }}/)
  assert.match(orderManagementPageSource, /<el-table-column prop="side" label="方向" width="86" \/>/)
  assert.match(orderManagementPageSource, /<el-table-column prop="state" label="订单状态" width="160" \/>/)
  assert.match(orderManagementPageSource, /<el-table-column prop="strategy_name" label="策略" min-width="132" \/>/)
  assert.match(orderManagementPageSource, /<el-table-column prop="source" label="来源" width="148" \/>/)
  assert.match(orderManagementPageSource, /{{ formatOrderPrice\(row\.price\) }} \/ {{ formatOrderQuantity\(row\.quantity\) }}/)
  assert.match(orderManagementPageSource, /{{ formatOrderTimestamp\(row\.updated_at \|\| row\.created_at\) }}/)
  assert.match(orderManagementPageSource, /<el-table-column prop="broker_order_id" label="券商单号" min-width="132" \/>/)

  const symbolColumnIndex = orderManagementPageSource.indexOf('<el-table-column label="标的代码"')
  const updatedColumnIndex = orderManagementPageSource.indexOf('<el-table-column label="更新时间"')
  const sideColumnIndex = orderManagementPageSource.indexOf('<el-table-column prop="side" label="方向"')
  const brokerColumnIndex = orderManagementPageSource.indexOf('<el-table-column prop="broker_order_id" label="券商单号"')

  assert.ok(symbolColumnIndex > -1)
  assert.ok(updatedColumnIndex > -1)
  assert.ok(updatedColumnIndex > symbolColumnIndex)
  assert.ok(sideColumnIndex > updatedColumnIndex)
  assert.ok(brokerColumnIndex > sideColumnIndex)
  assert.doesNotMatch(orderManagementPageSource, /label="Internal Order"/)
  assert.doesNotMatch(orderManagementPageSource, /label="Request"/)
})

test('OrderManagement hides advanced filters behind an explicit toggle', () => {
  assert.match(orderManagementPageSource, /const showAdvancedFilters = ref\(false\)/)
  assert.match(orderManagementPageSource, /const toggleAdvancedFilters = \(\) => \{[\s\S]*showAdvancedFilters\.value = !showAdvancedFilters\.value/)
  assert.match(orderManagementPageSource, /@click="toggleAdvancedFilters"[^>]*>\s*高级筛选\s*</)
  assert.match(orderManagementPageSource, /<div v-if="showAdvancedFilters" class="filter-grid">/)
})

test('OrderManagement keeps the summary panel above the list grid in its own stacking context', () => {
  assert.match(orderManagementPageSource, /\.order-stats-panel\s*\{[\s\S]*position:\s*relative;/)
  assert.match(orderManagementPageSource, /\.order-stats-panel\s*\{[\s\S]*z-index:\s*2;/)
  assert.match(orderManagementPageSource, /\.order-main-grid\s*\{[\s\S]*position:\s*relative;/)
  assert.match(orderManagementPageSource, /\.order-main-grid\s*\{[\s\S]*z-index:\s*1;/)
})

test('OrderManagement.vue routes summary and identifier chips through shared StatusChip', () => {
  assert.match(orderManagementPageSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(orderManagementPageSource, /<StatusChip[\s\S]*v-for="chip in activeFilterChips"/)
  assert.match(orderManagementPageSource, /<StatusChip[\s\S]*v-if="activeFilterChips\.length === 0"[\s\S]*variant="muted"[\s\S]*当前无额外筛选/)
  assert.match(orderManagementPageSource, /<StatusChip>\s*总订单 <strong>\{\{\s*stats\.total\s*\}\}<\/strong>/)
  assert.match(orderManagementPageSource, /<StatusChip variant="warning">\s*缺 broker 单号 <strong>\{\{\s*stats\.missing_broker_order_count\s*\}\}<\/strong>/)
  assert.match(orderManagementPageSource, /<StatusChip variant="success">\s*已成交 \/ 部分成交 <strong>\{\{\s*stats\.filled_count\s*\}\} \/ \{\{\s*stats\.partial_filled_count\s*\}\}<\/strong>/)
  assert.match(orderManagementPageSource, /<StatusChip[\s\S]*v-for="item in stats\.sideCards"/)
  assert.match(orderManagementPageSource, /<StatusChip[\s\S]*v-for="item in detail\.identifierRows"/)
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
  assert.equal(detail.requestSummary, 'strategy · Guardian')
  assert.equal(detail.timelineRows[1].event_type, 'trade_reported')
  assert.equal(detail.tradeSummary, '1 笔成交')
  assert.equal(detail.tradeRows[0].trade_time_label, '2026-03-25 13:46:10')
  assert.equal(detail.identifierRows[0].key, 'trace_id')
  assert.equal(stats.total, 2)
  assert.equal(stats.latest_updated_at, '2026-03-25 13:46:10')
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

test('page controller auto-selects broker-only rows by broker_order fallback id', async () => {
  const calls = []
  const controller = createOrderManagementPageController({
    actions: {
      async loadOrders() {
        return {
          rows: [
            {
              internal_order_id: '',
              broker_order_id: '403701761',
              broker_order_key: '403701761',
              symbol: '600104',
              side: 'sell',
              state: 'FILLED',
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
          state_distribution: { FILLED: 1 },
          missing_broker_order_count: 0,
        }
      },
      async loadOrderDetail(orderId) {
        calls.push(orderId)
        return buildOrderDetailViewModel({
          order: {
            internal_order_id: '',
            broker_order_id: orderId,
            symbol: '600104',
            side: 'sell',
            state: 'FILLED',
          },
          request: {},
          events: [],
          trades: [],
          identifiers: {
            broker_order_id: orderId,
          },
        })
      },
    },
  })

  await controller.refreshAll()

  assert.deepEqual(calls, ['403701761'])
  assert.equal(controller.state.selectedOrderId, '403701761')
  assert.equal(controller.state.detail.order.broker_order_id, '403701761')
})
