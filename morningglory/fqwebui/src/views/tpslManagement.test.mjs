import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import {
  buildDetailViewModel,
  buildHistoryRows,
  buildOverviewRows,
  createTpslManagementActions,
} from './tpslManagement.mjs'
import { createTpslManagementPageController } from './tpslManagementPage.mjs'

test('buildOverviewRows sorts holding symbols before config-only symbols and keeps latest trigger', () => {
  const rows = buildOverviewRows([
    {
      symbol: '000001',
      name: '平安银行',
      position_quantity: 0,
      takeprofit_configured: true,
      has_active_stoploss: false,
      last_trigger: {
        kind: 'takeprofit',
        created_at: '2026-03-13T01:00:00+00:00',
      },
    },
    {
      symbol: '600000',
      name: '浦发银行',
      position_quantity: 500,
      takeprofit_configured: true,
      has_active_stoploss: true,
      active_stoploss_buy_lot_count: 2,
      last_trigger: {
        kind: 'stoploss',
        created_at: '2026-03-13T02:00:00+00:00',
      },
    },
  ])

  assert.equal(rows[0].symbol, '600000')
  assert.equal(rows[0].badges.join(','), '止盈,止损')
  assert.equal(rows[0].last_trigger_label, 'stoploss')
  assert.equal(rows[0].last_trigger_time, '2026-03-13 10:00:00')
  assert.equal(rows[1].symbol, '000001')
})

test('buildOverviewRows exposes position amount labels in chinese wan with two decimals', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600000',
      name: '浦发银行',
      position_quantity: 500,
      position_amount: 123456.789,
      takeprofit_tiers: [
        { level: 1, price: 10.2, manual_enabled: true },
        { level: 2, price: 10.8, manual_enabled: true },
        { level: 3, price: 11.5, manual_enabled: false },
      ],
    },
  ])

  assert.equal(rows[0].position_amount, 123456.789)
  assert.equal(rows[0].position_amount_label, '12.35 万')
  assert.deepEqual(rows[0].takeprofitSummary, ['L1 10.2', 'L2 10.8', 'L3 11.5'])
})

test('buildDetailViewModel and buildHistoryRows keep tiers, buy lots and downstream order facts', () => {
  const detail = buildDetailViewModel({
    symbol: '600000',
    name: '浦发银行',
    position: {
      quantity: 200,
      amount: 234567,
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.2, manual_enabled: true },
        { level: 2, price: 10.8, manual_enabled: false },
      ],
      state: {
        armed_levels: { 1: true, 2: false },
      },
    },
    buy_lots: [
      {
        buy_lot_id: 'lot_1',
        buy_price_real: 10,
        original_quantity: 300,
        remaining_quantity: 200,
        stoploss: {
          stop_price: 9.2,
          enabled: true,
        },
        sell_history: [{ allocated_quantity: 100 }],
      },
    ],
    stock_fills: [
      {
        date: 20260312,
        time: '09:31:00',
        op: '买',
        quantity: 300,
        price: 10,
        amount: 3000,
        source: 'legacy_stock_fills',
      },
    ],
    history: [
      {
        event_id: 'evt_1',
        kind: 'stoploss',
        event_type: 'stoploss_hit',
        batch_id: 'sl_batch_1',
        buy_lot_ids: ['lot_1'],
        buy_lot_details: [{ buy_lot_id: 'lot_1', stop_price: 9.2, quantity: 200 }],
        created_at: '2026-03-13T02:00:00+00:00',
        order_requests: [{ request_id: 'req_1' }],
        orders: [{ internal_order_id: 'ord_1', state: 'FILLED' }],
        trades: [{ trade_fact_id: 'trade_1', quantity: 200, price: 9.1 }],
      },
    ],
  })

  assert.equal(detail.takeprofitTierCount, 2)
  assert.equal(detail.positionAmountLabel, '23.46 万')
  assert.equal(detail.buyLots[0].stoplossLabel, '9.2')
  assert.equal(detail.buyLots[0].sellHistoryLabel, '1 次卖出分配')
  assert.equal(detail.stockFills[0].op, '买')
  assert.equal(detail.stockFills[0].source, 'legacy_stock_fills')
  assert.equal(detail.historyRows[0].batch_id, 'sl_batch_1')
  assert.equal(detail.historyRows[0].created_at, '2026-03-13 10:00:00')
  assert.equal(detail.historyRows[0].triggerLabel, '9.2')
  assert.equal(detail.historyRows[0].triggerPriceLabel, '9.1')
  assert.equal(detail.historyRows[0].downstreamLabel, '1 request / 1 order / 1 trade')
  assert.equal(buildHistoryRows(detail.historyRows)[0].buy_lot_label, 'lot_1')
})

test('buildDetailViewModel labels inferred stock-fills rows instead of leaving direction blank', () => {
  const detail = buildDetailViewModel({
    symbol: '512000',
    stock_fills: [
      {
        date: 20260315,
        time: '23:39:42',
        quantity: 1470300,
        price: 0.569677,
        amount: 837596.09,
        source: 'external_inferred',
        direction_label: '推断持仓',
      },
    ],
  })

  assert.equal(detail.stockFills[0].opLabel, '推断持仓')
  assert.equal(detail.stockFills[0].source, 'external_inferred')
})

test('buildDetailViewModel labels open stock-fills rows as 买入 when the backend omits op fields', () => {
  const detail = buildDetailViewModel({
    symbol: '512600',
    stock_fills: [
      {
        date: 20260323,
        time: '11:05:10',
        quantity: 9900,
        price: 0.633,
        amount: 6266.7,
        source: 'external_reported',
      },
      {
        date: 20260323,
        time: '11:05:10',
        quantity: 69000,
        price: 0.633,
        amount: 43677.0,
        source: 'xtquant',
      },
    ],
  })

  assert.equal(detail.stockFills[0].opLabel, '买入')
  assert.equal(detail.stockFills[1].opLabel, '买入')
})

test('buildHistoryRows derives level and stop price labels for unified timeline cards', () => {
  const rows = buildHistoryRows([
    {
      event_id: 'evt_tp_1',
      kind: 'takeprofit',
      level: 2,
      trigger_price: 10.8,
      batch_id: 'tp_batch_1',
      buy_lot_ids: ['lot_1'],
    },
    {
      event_id: 'evt_sl_1',
      kind: 'stoploss',
      trigger_price: 9.1,
      batch_id: 'sl_batch_1',
      buy_lot_details: [
        { buy_lot_id: 'lot_2', stop_price: 9.2 },
        { buy_lot_id: 'lot_3', stop_price: 9.0 },
      ],
    },
  ])

  assert.equal(rows[0].triggerLabel, 'L2')
  assert.equal(rows[0].triggerPriceLabel, '10.8')
  assert.equal(rows[1].triggerLabel, '9.2, 9.0')
  assert.equal(rows[1].triggerPriceLabel, '9.1')
})

test('createTpslManagementActions calls takeprofit save, stoploss save and history load happy path', async () => {
  const calls = []
  const api = {
    async getManagementOverview() {
      calls.push(['getManagementOverview'])
      return {
        rows: [{ symbol: '600000', name: '浦发银行', position_quantity: 200 }],
      }
    },
    async getManagementDetail(symbol, { historyLimit }) {
      calls.push(['getManagementDetail', symbol, historyLimit])
      return {
        symbol,
        name: '浦发银行',
        position: { quantity: 200 },
        takeprofit: { tiers: [], state: { armed_levels: {} } },
        buy_lots: [],
        history: [],
      }
    },
    async saveTakeprofitProfile(symbol, payload) {
      calls.push(['saveTakeprofitProfile', symbol, payload.tiers.length])
      return { symbol, tiers: payload.tiers }
    },
    async bindStoploss(payload) {
      calls.push(['bindStoploss', payload.buy_lot_id, payload.stop_price, payload.enabled])
      return payload
    },
    async listHistory(filters) {
      calls.push(['listHistory', filters.symbol, filters.kind, filters.limit])
      return {
        rows: [
          {
            event_id: 'evt_1',
            kind: 'takeprofit',
            batch_id: 'tp_batch_1',
            buy_lot_ids: ['lot_1'],
            order_requests: [{ request_id: 'req_1' }],
            orders: [],
            trades: [],
          },
        ],
      }
    },
  }

  const actions = createTpslManagementActions(api)
  const overview = await actions.loadOverview()
  const detail = await actions.loadSymbolDetail('600000', { historyLimit: 30 })
  const savedTakeprofit = await actions.saveTakeprofit('600000', [
    { level: 1, price: 10.2, manual_enabled: true },
  ])
  const savedStoploss = await actions.saveStoploss('lot_1', { stop_price: 9.2, enabled: true })
  const history = await actions.loadHistory({ symbol: '600000', kind: 'takeprofit', limit: 5 })

  assert.equal(overview[0].symbol, '600000')
  assert.equal(detail.symbol, '600000')
  assert.equal(savedTakeprofit.symbol, '600000')
  assert.equal(savedStoploss.buy_lot_id, 'lot_1')
  assert.equal(history[0].batch_id, 'tp_batch_1')
  assert.deepEqual(calls, [
    ['getManagementOverview'],
    ['getManagementDetail', '600000', 30],
    ['saveTakeprofitProfile', '600000', 1],
    ['bindStoploss', 'lot_1', 9.2, true],
    ['listHistory', '600000', 'takeprofit', 5],
  ])
})

test('TpslManagement.vue widens quantity summary and renders stock-fill direction from opLabel', () => {
  const source = fs.readFileSync(new URL('./TpslManagement.vue', import.meta.url), 'utf8')

  assert.match(source, /<el-table-column label="原始\/剩余" width="156">/)
  assert.match(source, /<el-table-column label="方向" width="96">[\s\S]*row\.opLabel/)
})

test('page controller runs takeprofit save, stoploss save and history refresh from selected symbol', async () => {
  const calls = []
  const messages = []
  const buildDetail = () => buildDetailViewModel({
    symbol: '600000',
    name: '浦发银行',
    position: { quantity: 200 },
    takeprofit: {
      tiers: [{ level: 1, price: 10.2, manual_enabled: true }],
      state: { armed_levels: { 1: true } },
    },
    buy_lots: [
      {
        buy_lot_id: 'lot_1',
        buy_price_real: 10,
        original_quantity: 300,
        remaining_quantity: 200,
        stoploss: {
          stop_price: 9.2,
          enabled: true,
        },
        sell_history: [],
      },
    ],
    history: [
      {
        event_id: 'evt_1',
        kind: 'takeprofit',
        level: 1,
        trigger_price: 10.2,
        batch_id: 'tp_batch_1',
        buy_lot_ids: ['lot_1'],
        order_requests: [],
        orders: [],
        trades: [],
      },
    ],
  })

  const actions = {
    async loadOverview() {
      calls.push(['loadOverview'])
      return [
        {
          symbol: '600000',
          name: '浦发银行',
          position_quantity: 200,
          has_active_stoploss: true,
          active_stoploss_buy_lot_count: 1,
          badges: ['止盈', '止损'],
          last_trigger_label: 'takeprofit',
          last_trigger_time: '2026-03-13T10:00:00+08:00',
        },
      ]
    },
    async loadSymbolDetail(symbol, options) {
      calls.push(['loadSymbolDetail', symbol, options?.historyLimit ?? 20])
      return buildDetail()
    },
    async saveTakeprofit(symbol, tiers) {
      calls.push(['saveTakeprofit', symbol, tiers.map((row) => row.price)])
      return { symbol, tiers }
    },
    async saveStoploss(buyLotId, payload) {
      calls.push(['saveStoploss', buyLotId, payload.stop_price, payload.enabled])
      return { buyLotId, ...payload }
    },
    async loadHistory(filters) {
      calls.push(['loadHistory', filters.symbol, filters.kind, filters.limit])
      return buildHistoryRows([
        {
          event_id: 'evt_2',
          kind: 'stoploss',
          trigger_price: 9.1,
          batch_id: 'sl_batch_1',
          buy_lot_details: [{ buy_lot_id: 'lot_1', stop_price: 9.2 }],
          order_requests: [{ request_id: 'req_1' }],
          orders: [],
          trades: [],
        },
      ])
    },
  }

  const controller = createTpslManagementPageController({
    actions,
    notify: {
      success(message) {
        messages.push(['success', message])
      },
      warning(message) {
        messages.push(['warning', message])
      },
    },
  })

  await controller.refreshOverview()
  controller.state.takeprofitDrafts[0].price = 10.5
  controller.state.stoplossDrafts.lot_1.stop_price = 9.15

  await controller.handleSaveTakeprofit()
  await controller.handleSaveStoploss('lot_1')
  controller.state.historyKind = 'stoploss'
  await controller.loadHistory()

  assert.equal(controller.state.selectedSymbol, '600000')
  assert.equal(controller.state.detail.historyRows[0].kind, 'stoploss')
  assert.equal(controller.state.detail.historyRows[0].triggerLabel, '9.2')
  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSymbolDetail', '600000', 20],
    ['saveTakeprofit', '600000', [10.5]],
    ['loadSymbolDetail', '600000', 20],
    ['saveStoploss', 'lot_1', 9.15, true],
    ['loadSymbolDetail', '600000', 20],
    ['loadHistory', '600000', 'stoploss', 20],
  ])
  assert.deepEqual(messages, [
    ['success', '止盈层级已保存'],
    ['success', '已更新 lot_1'],
  ])
})

test('TpslManagement view keeps symbol list scrollable inside the fixed viewport shell', () => {
  const filePath = path.resolve(import.meta.dirname, 'TpslManagement.vue')
  const source = fs.readFileSync(filePath, 'utf8')

  assert.ok(!source.includes('标的止盈层次'))
  assert.ok(source.includes('stock_fills 对照视图'))
  assert.match(source, /\.symbol-list,\s*[\r\n]+\s*\.tpsl-main-stack\s*\{/)
  assert.match(source, /\.symbol-list[\s\S]*?overflow:\s*auto;/)
  assert.match(source, /\.symbol-list[\s\S]*?flex:\s*1 1 auto;/)
})
