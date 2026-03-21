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
      position_amount: 5010,
      last_hit_level: 'BUY-2',
      last_trigger_time: '2026-03-16T10:40:00+08:00',
    },
    position_limit_summary: {
      market_value: 5010,
      default_limit: 800000,
      override_limit: 500000,
      effective_limit: 500000,
      using_override: true,
      blocked: false,
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
      position_amount: 0,
      last_hit_level: null,
      last_trigger_time: '-',
    },
    position_limit_summary: {
      market_value: 0,
      default_limit: 800000,
      override_limit: null,
      effective_limit: 800000,
      using_override: false,
      blocked: false,
    },
  },
])

const makeDetail = (symbol = '600000', overrides = {}) => buildDetailViewModel({
  subject: {
    symbol,
    name: symbol === '600000' ? '浦发银行' : '平安银行',
    category: '银行',
  },
  must_pool: {
    category: '银行',
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
  position_limit_summary: {
    market_value: 5010,
    default_limit: 800000,
    override_limit: symbol === '600000' ? 500000 : null,
    effective_limit: symbol === '600000' ? 500000 : 800000,
    using_override: symbol === '600000',
    blocked: false,
  },
  ...overrides,
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
    async savePositionLimit(symbol, payload) {
      calls.push(['savePositionLimit', symbol, payload.limit ?? null, !!payload.use_default])
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

test('page controller saves dense config table via must-pool and symbol-limit apis with one refresh cycle', async () => {
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
    async savePositionLimit(symbol, payload) {
      calls.push(['savePositionLimit', symbol, payload.limit ?? null, !!payload.use_default])
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
  controller.state.positionLimitDraft.use_default = false
  controller.state.positionLimitDraft.limit = 460000

  await controller.handleSaveConfigBundle()

  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSubjectDetail', '600000'],
    ['saveMustPool', '600000', '核心银行', 9.1],
    ['savePositionLimit', '600000', 460000, false],
    ['loadSubjectDetail', '600000'],
    ['loadOverview'],
  ])
  assert.deepEqual(messages, [['success', '基础设置与仓位上限已保存']])
})

test('page controller uses must-pool category draft instead of subject category fallback', async () => {
  const actions = {
    async loadOverview() {
      return makeOverviewRows()
    },
    async loadSubjectDetail(symbol) {
      return makeDetail(symbol, {
        subject: {
          symbol,
          name: '浦发银行',
          category: '银行',
        },
        must_pool: {
          category: '守护池',
          stop_loss_price: 9.2,
          initial_lot_amount: 80000,
          lot_amount: 50000,
          forever: true,
        },
      })
    },
    async saveMustPool() {
      throw new Error('should not save')
    },
    async savePositionLimit() {
      throw new Error('should not save')
    },
    async saveTakeprofit() {
      throw new Error('should not save')
    },
    async saveStoploss() {
      throw new Error('should not save')
    },
  }

  const controller = createSubjectManagementPageController({ actions, notify: {} })

  await controller.refreshOverview()

  assert.equal(controller.state.detail.category, '银行')
  assert.equal(controller.state.detail.mustPool.category, '守护池')
  assert.equal(controller.state.mustPoolDraft.category, '守护池')
})

test('page controller reloads persisted state and warns when position-limit save fails after must-pool save', async () => {
  const calls = []
  const messages = []
  let detailVersion = 'initial'
  const actions = {
    async loadOverview() {
      calls.push(['loadOverview'])
      return makeOverviewRows()
    },
    async loadSubjectDetail(symbol) {
      calls.push(['loadSubjectDetail', symbol, detailVersion])
      return detailVersion === 'initial'
        ? makeDetail(symbol, {
          must_pool: {
            category: '银行',
            stop_loss_price: 9.2,
            initial_lot_amount: 80000,
            lot_amount: 50000,
            forever: true,
          },
          position_limit_summary: {
            market_value: 5010,
            default_limit: 800000,
            override_limit: 500000,
            effective_limit: 500000,
            using_override: true,
            blocked: false,
          },
        })
        : makeDetail(symbol, {
          must_pool: {
            category: '核心银行',
            stop_loss_price: 9.1,
            initial_lot_amount: 80000,
            lot_amount: 50000,
            forever: true,
          },
          position_limit_summary: {
            market_value: 5010,
            default_limit: 800000,
            override_limit: 500000,
            effective_limit: 500000,
            using_override: true,
            blocked: false,
          },
        })
    },
    async saveMustPool(symbol, payload) {
      calls.push(['saveMustPool', symbol, payload.category, payload.stop_loss_price])
      detailVersion = 'must-pool-saved'
      return { symbol, ...payload }
    },
    async savePositionLimit(symbol, payload) {
      calls.push(['savePositionLimit', symbol, payload.limit ?? null, !!payload.use_default])
      throw new Error('position limit failed')
    },
    async saveTakeprofit() {
      throw new Error('should not save')
    },
    async saveStoploss() {
      throw new Error('should not save')
    },
  }

  const controller = createSubjectManagementPageController({
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
  controller.state.mustPoolDraft.category = '核心银行'
  controller.state.mustPoolDraft.stop_loss_price = 9.1
  controller.state.positionLimitDraft.use_default = false
  controller.state.positionLimitDraft.limit = 460000

  await controller.handleSaveConfigBundle()

  assert.equal(controller.state.mustPoolDraft.category, '核心银行')
  assert.equal(controller.state.mustPoolDraft.stop_loss_price, 9.1)
  assert.equal(controller.state.positionLimitDraft.use_default, false)
  assert.equal(controller.state.positionLimitDraft.limit, 460000)
  assert.equal(controller.state.pageError, 'position limit failed')
  assert.deepEqual(messages, [['warning', '基础设置已保存，仓位上限保存失败']])
  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSubjectDetail', '600000', 'initial'],
    ['saveMustPool', '600000', '核心银行', 9.1],
    ['savePositionLimit', '600000', 460000, false],
    ['loadSubjectDetail', '600000', 'must-pool-saved'],
    ['loadOverview'],
  ])
})
