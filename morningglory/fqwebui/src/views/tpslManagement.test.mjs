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
      active_stoploss_entry_count: 2,
      open_entry_count: 2,
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

test('buildDetailViewModel and buildHistoryRows keep tiers, entries and downstream order facts', () => {
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
    entries: [
      {
        entry_id: 'entry_1',
        entry_price: 10,
        original_quantity: 300,
        remaining_quantity: 200,
        stoploss: {
          stop_price: 9.2,
          enabled: true,
        },
        sell_history: [{ allocated_quantity: 100 }],
      },
    ],
    entry_slices: [
      {
        entry_slice_id: 'slice_1',
        entry_id: 'entry_1',
        guardian_price: 10.8,
        original_quantity: 100,
        remaining_quantity: 100,
        status: 'OPEN',
      },
    ],
    reconciliation: {
      state: 'aligned',
      signed_gap_quantity: 0,
      open_gap_count: 0,
      rejected_gap_count: 0,
      latest_resolution_type: '',
    },
    history: [
      {
        event_id: 'evt_1',
        kind: 'stoploss',
        event_type: 'stoploss_hit',
        batch_id: 'sl_batch_1',
        entry_ids: ['entry_1'],
        entry_details: [{ entry_id: 'entry_1', stop_price: 9.2, quantity: 200 }],
        created_at: '2026-03-13T02:00:00+00:00',
        order_requests: [{ request_id: 'req_1' }],
        orders: [{ internal_order_id: 'ord_1', state: 'FILLED' }],
        trades: [{ trade_fact_id: 'trade_1', quantity: 200, price: 9.1 }],
      },
    ],
  })

  assert.equal(detail.takeprofitTierCount, 2)
  assert.equal(detail.positionAmountLabel, '23.46 万')
  assert.equal(detail.entries[0].stoplossLabel, '9.2')
  assert.equal(detail.entries[0].entry_price_label, '10.0')
  assert.equal(detail.entries[0].sellHistoryLabel, '1 次卖出分配')
  assert.equal(detail.entrySlices[0].entry_slice_id, 'slice_1')
  assert.equal(detail.reconciliation.state, 'ALIGNED')
  assert.equal(detail.reconciliation.state_label, '已对齐')
  assert.equal(detail.reconciliation.state_chip_variant, 'success')
  assert.equal(detail.historyRows[0].batch_id, 'sl_batch_1')
  assert.equal(detail.historyRows[0].created_at, '2026-03-13 10:00:00')
  assert.equal(detail.historyRows[0].triggerLabel, '9.2')
  assert.equal(detail.historyRows[0].triggerPriceLabel, '9.1')
  assert.equal(detail.historyRows[0].downstreamLabel, '1 request / 1 order / 1 trade')
  assert.equal(buildHistoryRows(detail.historyRows)[0].entry_label, 'entry_1')
})

test('buildDetailViewModel normalizes drift reconciliation state with shared semantics', () => {
  const detail = buildDetailViewModel({
    symbol: '300001',
    reconciliation: {
      state: 'drift',
      signed_gap_quantity: 50,
      open_gap_count: 0,
      latest_resolution_type: '',
    },
  })

  assert.equal(detail.reconciliation.state, 'DRIFT')
  assert.equal(detail.reconciliation.state_label, '漂移')
  assert.equal(detail.reconciliation.state_chip_variant, 'danger')
})

test('buildHistoryRows derives level and stop price labels for unified timeline cards', () => {
  const rows = buildHistoryRows([
    {
      event_id: 'evt_tp_1',
      kind: 'takeprofit',
      level: 2,
      trigger_price: 10.8,
      batch_id: 'tp_batch_1',
      entry_ids: ['entry_1'],
    },
    {
      event_id: 'evt_sl_1',
      kind: 'stoploss',
      trigger_price: 9.1,
      batch_id: 'sl_batch_1',
      entry_details: [
        { entry_id: 'entry_2', stop_price: 9.2 },
        { entry_id: 'entry_3', stop_price: 9.0 },
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
        entries: [],
        history: [],
      }
    },
    async saveTakeprofitProfile(symbol, payload) {
      calls.push(['saveTakeprofitProfile', symbol, payload.tiers.length])
      return { symbol, tiers: payload.tiers }
    },
    async bindStoploss(payload) {
      calls.push(['bindStoploss', payload.entry_id, payload.stop_price, payload.enabled])
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
            entry_ids: ['entry_1'],
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
  const savedStoploss = await actions.saveStoploss('entry_1', { stop_price: 9.2, enabled: true })
  const history = await actions.loadHistory({ symbol: '600000', kind: 'takeprofit', limit: 5 })

  assert.equal(overview[0].symbol, '600000')
  assert.equal(detail.symbol, '600000')
  assert.equal(savedTakeprofit.symbol, '600000')
  assert.equal(savedStoploss.entry_id, 'entry_1')
  assert.equal(history[0].batch_id, 'tp_batch_1')
  assert.deepEqual(calls, [
    ['getManagementOverview'],
    ['getManagementDetail', '600000', 30],
    ['saveTakeprofitProfile', '600000', 1],
    ['bindStoploss', 'entry_1', 9.2, true],
    ['listHistory', '600000', 'takeprofit', 5],
  ])
})

test('TpslManagement.vue renders entry ledger and reconciliation sections', () => {
  const source = fs.readFileSync(new URL('./TpslManagement.vue', import.meta.url), 'utf8')

  assert.match(source, /<el-table-column label="原始\/剩余" width="156">/)
  assert.match(source, /Entry Slice Ledger/)
  assert.match(source, /对账状态/)
  assert.match(source, /detail\.reconciliation\.state_label/)
  assert.match(source, /detail\.reconciliation\.state_chip_variant/)
  assert.match(source, /<StatusChip v-if="detail" :variant="detail\.reconciliation\.state_chip_variant">/)
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
    entries: [
      {
        entry_id: 'entry_1',
        entry_price: 10,
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
        entry_ids: ['entry_1'],
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
          active_stoploss_entry_count: 1,
          open_entry_count: 1,
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
    async saveStoploss(entryId, payload) {
      calls.push(['saveStoploss', entryId, payload.stop_price, payload.enabled])
      return { entryId, ...payload }
    },
    async loadHistory(filters) {
      calls.push(['loadHistory', filters.symbol, filters.kind, filters.limit])
      return buildHistoryRows([
        {
          event_id: 'evt_2',
          kind: 'stoploss',
          trigger_price: 9.1,
          batch_id: 'sl_batch_1',
          entry_details: [{ entry_id: 'entry_1', stop_price: 9.2 }],
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
  controller.state.stoplossDrafts.entry_1.stop_price = 9.15

  await controller.handleSaveTakeprofit()
  await controller.handleSaveStoploss('entry_1')
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
    ['saveStoploss', 'entry_1', 9.15, true],
    ['loadSymbolDetail', '600000', 20],
    ['loadHistory', '600000', 'stoploss', 20],
  ])
  assert.deepEqual(messages, [
    ['success', '止盈层级已保存'],
    ['success', '已更新 entry_1'],
  ])
})

test('TpslManagement view keeps symbol list scrollable inside the fixed viewport shell', () => {
  const filePath = path.resolve(import.meta.dirname, 'TpslManagement.vue')
  const source = fs.readFileSync(filePath, 'utf8')

  assert.ok(!source.includes('标的止盈层次'))
  assert.ok(source.includes('Entry Slice Ledger'))
  assert.match(source, /\.symbol-list,\s*[\r\n]+\s*\.tpsl-main-stack\s*\{/)
  assert.match(source, /\.symbol-list[\s\S]*?overflow:\s*auto;/)
  assert.match(source, /\.symbol-list[\s\S]*?flex:\s*1 1 auto;/)
})

test('TpslManagement.vue routes toolbar and symbol-list chips through shared StatusChip', () => {
  const filePath = path.resolve(import.meta.dirname, 'TpslManagement.vue')
  const source = fs.readFileSync(filePath, 'utf8')

  assert.match(source, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(source, /<StatusChip>\s*标的数 <strong>\{\{\s*overviewRows\.length\s*\}\}<\/strong>/)
  assert.match(source, /<StatusChip variant="success">\s*持仓中 <strong>\{\{\s*holdingCount\s*\}\}<\/strong>/)
  assert.match(source, /<StatusChip variant="warning">\s*活跃止损 <strong>\{\{\s*activeStoplossCount\s*\}\}<\/strong>/)
  assert.match(source, /<StatusChip variant="muted">\s*\{\{\s*row\.position_amount_label\s*\}\}\s*<\/StatusChip>/)
  assert.match(source, /<StatusChip[\s\S]*v-for="badge in row\.badges"/)
  assert.match(source, /<StatusChip[\s\S]*v-for="tierLabel in row\.takeprofitSummary"/)
})
