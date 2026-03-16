import test from 'node:test'
import assert from 'node:assert/strict'

import { buildDetailViewModel, buildOverviewRows } from './subjectManagement.mjs'
import { createSubjectManagementPageController } from './subjectManagementPage.mjs'

const makeOverviewRows = () => buildOverviewRows([
  {
    symbol: '600000',
    name: '浦发银行',
    category: '银行',
    must_pool: {
      stop_loss_price: 9.2,
      initial_lot_amount: 80000,
      lot_amount: 50000,
      forever: true,
    },
    guardian: {
      enabled: true,
      buy_1: 10.2,
      buy_2: 9.9,
      buy_3: 9.5,
    },
    takeprofit: {
      tiers: [],
    },
    stoploss: {
      active_count: 1,
      open_buy_lot_count: 2,
    },
    runtime: {
      position_quantity: 500,
      last_hit_level: 'BUY-2',
      last_trigger_time: '2026-03-16T10:40:00+08:00',
    },
  },
  {
    symbol: '000001',
    name: '平安银行',
    category: '银行',
    must_pool: {
      stop_loss_price: 8.8,
      initial_lot_amount: 60000,
      lot_amount: 40000,
      forever: false,
    },
    guardian: {
      enabled: false,
      buy_1: 9.8,
      buy_2: 9.5,
      buy_3: 9.2,
    },
    takeprofit: {
      tiers: [{ level: 1, price: 10.2, enabled: true }],
    },
    stoploss: {
      active_count: 0,
      open_buy_lot_count: 0,
    },
    runtime: {
      position_quantity: 0,
      last_hit_level: null,
      last_trigger_time: '-',
    },
  },
])

const makeDetail = (symbol = '600000') => buildDetailViewModel({
  subject: {
    symbol,
    name: symbol === '600000' ? '浦发银行' : '平安银行',
    category: '银行',
  },
  must_pool: {
    stop_loss_price: symbol === '600000' ? 9.2 : 8.8,
    initial_lot_amount: symbol === '600000' ? 80000 : 60000,
    lot_amount: symbol === '600000' ? 50000 : 40000,
    forever: symbol === '600000',
  },
  guardian_buy_grid_config: {
    enabled: symbol === '600000',
    buy_1: symbol === '600000' ? 10.2 : 9.8,
    buy_2: symbol === '600000' ? 9.9 : 9.5,
    buy_3: symbol === '600000' ? 9.5 : 9.2,
  },
  guardian_buy_grid_state: {
    buy_active: [true, false, true],
    last_hit_level: 'BUY-2',
    last_hit_price: 9.88,
  },
  takeprofit: {
    tiers: symbol === '600000'
      ? []
      : [{ level: 1, price: 10.2, enabled: true }],
    state: { armed_levels: { 1: true, 2: false, 3: true } },
  },
  buy_lots: [
    {
      buy_lot_id: `${symbol}-lot-1`,
      buy_price_real: 10.0,
      original_quantity: 300,
      remaining_quantity: 200,
      stoploss: {
        stop_price: 9.2,
        enabled: true,
      },
    },
  ],
  runtime_summary: {
    position_quantity: symbol === '600000' ? 500 : 0,
    position_amount: 5010,
    last_trigger_time: '2026-03-16T10:40:00+08:00',
    last_trigger_kind: 'takeprofit',
  },
  position_management_summary: {
    effective_state: 'HOLDING_ONLY',
    allow_open_min_bail: 800000,
    holding_only_min_bail: 100000,
  },
})

test('page controller loads overview first, then detail, switches rows and refreshes after must-pool save', async () => {
  const calls = []
  const messages = []
  const actions = {
    async loadOverview() {
      calls.push(['loadOverview'])
      return makeOverviewRows()
    },
    async loadSubjectDetail(symbol) {
      calls.push(['loadSubjectDetail', symbol])
      return makeDetail(symbol)
    },
    async saveMustPool(symbol, payload) {
      calls.push(['saveMustPool', symbol, payload.category, payload.stop_loss_price])
      return { symbol, ...payload }
    },
    async saveGuardianBuyGrid(symbol, payload) {
      calls.push(['saveGuardianBuyGrid', symbol, payload.buy_1])
      return { symbol, ...payload }
    },
    async saveTakeprofit(symbol, tiers) {
      calls.push(['saveTakeprofit', symbol, tiers.length])
      return { symbol, tiers }
    },
    async saveStoploss(buyLotId, payload) {
      calls.push(['saveStoploss', buyLotId, payload.stop_price, payload.enabled])
      return { buyLotId, ...payload }
    },
  }

  const controller = createSubjectManagementPageController({
    actions,
    notify: {
      success(message) {
        messages.push(['success', message])
      },
    },
  })

  await controller.refreshOverview()
  assert.equal(controller.state.selectedSymbol, '600000')
  assert.equal(controller.state.takeprofitDrafts.length, 3)
  assert.equal(controller.state.takeprofitDrafts[0].manual_enabled, true)

  await controller.selectSymbol('000001')
  assert.equal(controller.state.selectedSymbol, '000001')

  controller.state.mustPoolDraft.stop_loss_price = 8.6
  await controller.handleSaveMustPool()

  assert.equal(controller.state.selectedSymbol, '000001')
  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSubjectDetail', '600000'],
    ['loadSubjectDetail', '000001'],
    ['saveMustPool', '000001', '银行', 8.6],
    ['loadSubjectDetail', '000001'],
    ['loadOverview'],
  ])
  assert.deepEqual(messages, [['success', '基础设置已保存']])
})

test('page controller saves dense config table via must-pool and guardian apis with one refresh cycle', async () => {
  const calls = []
  const messages = []
  const actions = {
    async loadOverview() {
      calls.push(['loadOverview'])
      return makeOverviewRows()
    },
    async loadSubjectDetail(symbol) {
      calls.push(['loadSubjectDetail', symbol])
      return makeDetail(symbol)
    },
    async saveMustPool(symbol, payload) {
      calls.push(['saveMustPool', symbol, payload.category, payload.stop_loss_price])
      return { symbol, ...payload }
    },
    async saveGuardianBuyGrid(symbol, payload) {
      calls.push(['saveGuardianBuyGrid', symbol, payload.enabled, payload.buy_1])
      return { symbol, ...payload }
    },
    async saveTakeprofit(symbol, tiers) {
      calls.push(['saveTakeprofit', symbol, tiers.length])
      return { symbol, tiers }
    },
    async saveStoploss(buyLotId, payload) {
      calls.push(['saveStoploss', buyLotId, payload.stop_price, payload.enabled])
      return { buyLotId, ...payload }
    },
  }

  const controller = createSubjectManagementPageController({
    actions,
    notify: {
      success(message) {
        messages.push(['success', message])
      },
    },
  })

  await controller.refreshOverview()
  controller.state.mustPoolDraft.category = '核心银行'
  controller.state.mustPoolDraft.stop_loss_price = 9.1
  controller.state.guardianDraft.enabled = false
  controller.state.guardianDraft.buy_1 = 10.1

  await controller.handleSaveConfigBundle()

  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSubjectDetail', '600000'],
    ['saveMustPool', '600000', '核心银行', 9.1],
    ['saveGuardianBuyGrid', '600000', false, 10.1],
    ['loadSubjectDetail', '600000'],
    ['loadOverview'],
  ])
  assert.deepEqual(messages, [['success', '基础与 Guardian 已保存']])
})
