import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { buildDetailViewModel, buildOverviewRows } from './subjectManagement.mjs'
import { createPositionManagementSubjectWorkbenchController } from './positionManagementSubjectWorkbench.mjs'

const makeOverviewRows = () => buildOverviewRows([
  {
    symbol: '600000',
    name: '浦发银行',
    category: '银行',
    must_pool: {
      category: '银行',
      stop_loss_price: 9.2,
      initial_lot_amount: 80000,
      lot_amount: 50000,
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
      open_entry_count: 2,
    },
    runtime: {
      position_quantity: 500,
      position_amount: 501000,
      last_hit_level: 'BUY-2',
      last_trigger_time: '2026-04-02T10:40:00+08:00',
    },
    position_limit_summary: {
      market_value: 501000,
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
      category: '观察',
      stop_loss_price: 8.8,
      initial_lot_amount: 60000,
      lot_amount: 40000,
    },
    guardian: {
      enabled: false,
      buy_1: 9.8,
      buy_2: 9.5,
      buy_3: 9.2,
    },
    takeprofit: {
      tiers: [],
    },
    stoploss: {
      active_count: 0,
      open_entry_count: 0,
    },
    runtime: {
      position_quantity: 0,
      position_amount: 0,
      last_hit_level: null,
      last_trigger_time: null,
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
    category: symbol === '600000' ? '银行' : '观察',
    stop_loss_price: symbol === '600000' ? 9.2 : 8.8,
    initial_lot_amount: symbol === '600000' ? 80000 : 60000,
    lot_amount: symbol === '600000' ? 50000 : 40000,
  },
  guardian_buy_grid_config: {
    enabled: symbol === '600000',
    buy_1: symbol === '600000' ? 10.2 : 9.8,
    buy_2: symbol === '600000' ? 9.9 : 9.5,
    buy_3: symbol === '600000' ? 9.5 : 9.2,
  },
  guardian_buy_grid_state: {
    last_hit_level: symbol === '600000' ? 'BUY-2' : '',
    last_hit_price: symbol === '600000' ? 9.88 : null,
  },
  takeprofit: {
    tiers: [],
    state: {},
  },
  entries: symbol === '600000'
    ? [
      {
        entry_id: '600000-entry-1',
        entry_price: 10.0,
        original_quantity: 300,
        remaining_quantity: 200,
        latest_price: 10.2,
        remaining_market_value: 2040,
        stoploss: {
          stop_price: 9.2,
          enabled: true,
        },
        aggregation_members: [
          { order_id: 'buy-1', quantity: 100 },
          { order_id: 'buy-2', quantity: 200 },
        ],
        aggregation_window: {
          started_at: '2026-04-02T09:30:00+08:00',
          ended_at: '2026-04-02T10:05:00+08:00',
        },
        entry_slices: [
          {
            entry_slice_id: 'slice-1',
            slice_seq: 1,
            guardian_price: 9.9,
            original_quantity: 100,
            remaining_quantity: 80,
            remaining_amount: 816,
          },
          {
            entry_slice_id: 'slice-2',
            slice_seq: 2,
            guardian_price: 9.8,
            original_quantity: 200,
            remaining_quantity: 120,
            remaining_amount: 1224,
          },
        ],
      },
      {
        entry_id: '600000-entry-2',
        entry_price: 10.15,
        original_quantity: 200,
        remaining_quantity: 160,
        latest_price: 10.35,
        remaining_market_value: 1656,
        stoploss: {
          stop_price: 9.05,
          enabled: false,
        },
        aggregation_members: [
          { order_id: 'buy-3', quantity: 120 },
          { order_id: 'buy-4', quantity: 80 },
        ],
        aggregation_window: {
          started_at: '2026-04-02T10:10:00+08:00',
          ended_at: '2026-04-02T10:16:00+08:00',
        },
        entry_slices: [
          {
            entry_slice_id: 'slice-3',
            slice_seq: 1,
            guardian_price: 9.7,
            original_quantity: 200,
            remaining_quantity: 160,
            remaining_amount: 1656,
          },
        ],
      },
    ]
    : [],
  runtime_summary: {
    position_quantity: symbol === '600000' ? 500 : 0,
    position_amount: symbol === '600000' ? 501000 : 0,
    avg_price: symbol === '600000' ? 10.0 : 0,
    last_trigger_time: '2026-04-02T10:40:00+08:00',
    last_trigger_kind: 'takeprofit',
  },
  position_management_summary: {
    effective_state: 'HOLDING_ONLY',
    allow_open_min_bail: 800000,
    holding_only_min_bail: 100000,
  },
  position_limit_summary: {
    market_value: symbol === '600000' ? 501000 : 0,
    default_limit: 800000,
    override_limit: symbol === '600000' ? 500000 : null,
    effective_limit: symbol === '600000' ? 500000 : 800000,
    using_override: symbol === '600000',
    blocked: false,
  },
  ...overrides,
})

test('subject workbench controller refreshes overview and hydrates visible symbols into per-row drafts', async () => {
  const calls = []
  const actions = {
    async loadOverview() {
      calls.push(['loadOverview'])
      return makeOverviewRows()
    },
    async loadSubjectDetail(symbol) {
      calls.push(['loadSubjectDetail', symbol])
      return makeDetail(symbol)
    },
    async saveMustPool() {
      throw new Error('should not save')
    },
    async savePositionLimit() {
      throw new Error('should not save')
    },
    async saveStoploss() {
      throw new Error('should not save')
    },
  }

  const controller = createPositionManagementSubjectWorkbenchController({
    actions,
    notify: {},
  })

  await controller.refreshOverview({
    preloadSymbols: ['600000', '000001'],
  })

  assert.equal(controller.state.overviewRows.length, 2)
  assert.equal(controller.state.detailMap['600000'].symbol, '600000')
  assert.equal(controller.state.detailMap['000001'].symbol, '000001')
  assert.equal(controller.state.mustPoolDrafts['600000'].category, '银行')
  assert.equal(controller.state.positionLimitDrafts['600000'].limit, 500000)
  assert.equal(controller.state.stoplossDrafts['600000']['600000-entry-1'].stop_price, 9.2)
  assert.equal(controller.state.selectedEntryIds['600000'], '600000-entry-1')
  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSubjectDetail', '600000'],
    ['loadSubjectDetail', '000001'],
  ])
})

test('subject workbench controller defaults to the first entry and exposes slices for the selected entry only', async () => {
  const actions = {
    async loadOverview() {
      return makeOverviewRows()
    },
    async loadSubjectDetail(symbol) {
      return makeDetail(symbol)
    },
    async saveMustPool() {
      throw new Error('should not save')
    },
    async savePositionLimit() {
      throw new Error('should not save')
    },
    async saveStoploss() {
      throw new Error('should not save')
    },
  }

  const controller = createPositionManagementSubjectWorkbenchController({
    actions,
    notify: {},
  })

  await controller.refreshOverview({
    preloadSymbols: ['600000'],
  })

  assert.equal(controller.getSelectedEntryId('600000'), '600000-entry-1')
  assert.deepEqual(
    controller.getSelectedEntrySlices('600000').map((row) => row.entry_slice_id),
    ['slice-1', 'slice-2'],
  )

  controller.selectEntry('600000', '600000-entry-2')

  assert.equal(controller.getSelectedEntryId('600000'), '600000-entry-2')
  assert.equal(controller.getSelectedEntry('600000')?.entry_id, '600000-entry-2')
  assert.deepEqual(
    controller.getSelectedEntrySlices('600000').map((row) => row.entry_slice_id),
    ['slice-3'],
  )
})

test('subject workbench controller deduplicates concurrent detail hydration for the same symbol', async () => {
  const calls = []
  let releaseDetailLoad
  const detailLoadGate = new Promise((resolve) => {
    releaseDetailLoad = resolve
  })
  const actions = {
    async loadOverview() {
      return makeOverviewRows()
    },
    async loadSubjectDetail(symbol) {
      calls.push(['loadSubjectDetail', symbol])
      await detailLoadGate
      return makeDetail(symbol)
    },
    async saveMustPool() {
      throw new Error('should not save')
    },
    async savePositionLimit() {
      throw new Error('should not save')
    },
    async saveStoploss() {
      throw new Error('should not save')
    },
  }

  const controller = createPositionManagementSubjectWorkbenchController({
    actions,
    notify: {},
  })

  const firstHydration = controller.ensureSymbolsHydrated(['600000'])
  const secondHydration = controller.ensureSymbolsHydrated(['600000'])
  assert.equal(controller.state.loadingDetail['600000'], true)

  releaseDetailLoad()
  await Promise.all([firstHydration, secondHydration])

  assert.deepEqual(calls, [
    ['loadSubjectDetail', '600000'],
  ])
  assert.equal(controller.state.detailMap['600000'].symbol, '600000')
  assert.equal(controller.state.loadingDetail['600000'], false)
})

test('subject workbench controller saves inline base config and symbol limit per symbol then refreshes overview and detail', async () => {
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
        ? makeDetail(symbol)
        : makeDetail(symbol, {
          must_pool: {
            category: '核心银行',
            stop_loss_price: 9.1,
            initial_lot_amount: 81000,
            lot_amount: 52000,
          },
          position_limit_summary: {
            market_value: 501000,
            default_limit: 800000,
            override_limit: 460000,
            effective_limit: 460000,
            using_override: true,
            blocked: false,
          },
        })
    },
    async saveMustPool(symbol, payload) {
      calls.push(['saveMustPool', symbol, payload.category, payload.stop_loss_price, payload.initial_lot_amount, payload.lot_amount])
      detailVersion = 'saved'
      return { symbol, ...payload }
    },
    async savePositionLimit(symbol, payload) {
      calls.push(['savePositionLimit', symbol, payload.limit ?? null])
      return { symbol, ...payload }
    },
    async saveStoploss() {
      throw new Error('should not save')
    },
  }

  const controller = createPositionManagementSubjectWorkbenchController({
    actions,
    notify: {
      success(message) {
        messages.push(message)
      },
    },
  })

  await controller.refreshOverview({
    preloadSymbols: ['600000'],
  })
  controller.state.mustPoolDrafts['600000'].category = '核心银行'
  controller.state.mustPoolDrafts['600000'].stop_loss_price = 9.1
  controller.state.mustPoolDrafts['600000'].initial_lot_amount = 81000
  controller.state.mustPoolDrafts['600000'].lot_amount = 52000
  controller.state.positionLimitDrafts['600000'].limit = 460000

  await controller.saveConfigBundle('600000')

  assert.equal(controller.state.mustPoolDrafts['600000'].category, '核心银行')
  assert.equal(controller.state.positionLimitDrafts['600000'].limit, 460000)
  assert.deepEqual(messages, ['600000 基础设置与仓位上限已保存'])
  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSubjectDetail', '600000', 'initial'],
    ['saveMustPool', '600000', '核心银行', 9.1, 81000, 52000],
    ['savePositionLimit', '600000', 460000],
    ['loadSubjectDetail', '600000', 'saved'],
    ['loadOverview'],
  ])
})

test('subject workbench controller saves inline entry stoploss and refreshes symbol detail without clearing other drafts', async () => {
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
    async saveMustPool() {
      throw new Error('should not save')
    },
    async savePositionLimit() {
      throw new Error('should not save')
    },
    async saveStoploss(entryId, payload) {
      calls.push(['saveStoploss', entryId, payload.stop_price, payload.enabled])
      return { entryId, ...payload }
    },
  }

  const controller = createPositionManagementSubjectWorkbenchController({
    actions,
    notify: {
      success(message) {
        messages.push(message)
      },
    },
  })

  await controller.refreshOverview({
    preloadSymbols: ['600000', '000001'],
  })
  controller.state.mustPoolDrafts['000001'].category = '观察池'
  controller.state.stoplossDrafts['600000']['600000-entry-1'].stop_price = 9.15
  controller.state.stoplossDrafts['600000']['600000-entry-1'].enabled = true

  await controller.saveStoploss('600000', '600000-entry-1')

  assert.equal(controller.state.mustPoolDrafts['000001'].category, '观察池')
  assert.deepEqual(messages, ['600000 入口止损已保存 600000-entry-1'])
  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadSubjectDetail', '600000'],
    ['loadSubjectDetail', '000001'],
    ['saveStoploss', '600000-entry-1', 9.15, true],
    ['loadSubjectDetail', '600000'],
    ['loadOverview'],
  ])
})

test('PositionSubjectOverviewPanel shows Guardian and takeprofit overview columns alongside inline config editing', () => {
  const source = fs.readFileSync(
    new URL('../components/position-management/PositionSubjectOverviewPanel.vue', import.meta.url),
    'utf8',
  ).replace(/\r/g, '')

  assert.match(source, /<el-table-column label="门禁"/)
  assert.match(source, /<el-table-column label="最近TPLS触发"/)
  assert.match(source, /<el-table-column label="Guardian 层级买入"/)
  assert.match(source, /<el-table-column label="Guardian层级触发"/)
  assert.match(source, /<el-table-column label="止盈价格"/)
  assert.match(source, /<el-table-column label="单标的仓位上限"/)
  assert.match(source, /row\.runtime\?\.last_trigger_kind/)
  assert.match(source, /row\.guardianLevelSummary/)
  assert.match(source, /row\.guardianTrigger\?\.kindLabel/)
  assert.match(source, /row\.takeprofitSummary/)
  assert.match(source, /item\.priceLabel/)
  assert.match(source, /item\.enabledLabel/)
  assert.match(source, /position-subject-summary-line__state/)
  assert.doesNotMatch(source, /<el-table-column label="首笔买入金额"/)
  assert.doesNotMatch(source, /<el-table-column label="默认买入金额"/)
  assert.match(source, /workbench\.state\.positionLimitDrafts\[row\.symbol\]\.limit/)
})
