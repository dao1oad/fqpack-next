import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import {
  buildDetailViewModel,
  buildDetailSummaryChips,
  buildDenseConfigRows,
  buildOverviewRows,
  buildTakeprofitDrafts,
  createSubjectManagementActions,
} from './subjectManagement.mjs'

test('buildOverviewRows keeps dense summary columns and default three takeprofit tiers', () => {
  const rows = buildOverviewRows([
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
        active_count: 2,
        open_buy_lot_count: 5,
      },
      runtime: {
        position_quantity: 500,
        position_amount: 123456,
        last_hit_level: 'BUY-2',
        last_trigger_time: '2026-03-16T10:40:00+08:00',
      },
    },
  ])

  assert.equal(rows[0].takeprofitSummary.length, 3)
  assert.equal(rows[0].takeprofitSummary[0].level, 1)
  assert.equal(rows[0].takeprofitSummary[0].priceLabel, '-')
  assert.equal(rows[0].guardianSummaryLabel.includes('B1'), true)
  assert.equal(rows[0].stoplossSummaryLabel, '2 / 5')
  assert.equal(rows[0].runtimeSummaryLabel.includes('12.35 万'), true)
  assert.equal(rows[0].runtimeSummaryLabel.includes('500'), true)
})

test('buildDetailViewModel keeps right-panel fields and at least three takeprofit drafts', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      stop_loss_price: 9.2,
      initial_lot_amount: 80000,
      lot_amount: 50000,
      forever: true,
    },
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 10.2,
      buy_2: 9.9,
      buy_3: 9.5,
    },
    guardian_buy_grid_state: {
      buy_active: [true, false, true],
      last_hit_level: 'BUY-2',
      last_hit_price: 9.88,
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8, enabled: true },
        { level: 3, price: 11.8, enabled: false },
      ],
      state: {
        armed_levels: { 1: true, 2: false, 3: true },
      },
    },
    buy_lots: [
      {
        buy_lot_id: 'lot_1',
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
      position_quantity: 500,
      position_amount: 123456,
      last_trigger_time: '2026-03-16T10:40:00+08:00',
      last_trigger_kind: 'takeprofit',
    },
    position_management_summary: {
      effective_state: 'HOLDING_ONLY',
      allow_open_min_bail: 800000,
      holding_only_min_bail: 100000,
    },
  })

  assert.equal(detail.symbol, '600000')
  assert.equal(detail.guardianConfig.buy_3, 9.5)
  assert.equal(detail.takeprofitDrafts.length, 3)
  assert.equal(detail.takeprofitDrafts[1].level, 2)
  assert.equal(detail.takeprofitDrafts[1].price, null)
  assert.equal(detail.buyLots[0].stoplossLabel, '9.2')
  assert.equal(detail.positionManagementSummary.effective_state, 'HOLDING_ONLY')
})

test('buildDenseConfigRows flattens must-pool and guardian fields into one dense editor table', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      category: '银行',
      stop_loss_price: 9.2,
      initial_lot_amount: 80000,
      lot_amount: 50000,
      forever: true,
    },
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 10.2,
      buy_2: 9.9,
      buy_3: 9.5,
    },
    guardian_buy_grid_state: {
      buy_active: [true, false, true],
      last_hit_level: 'BUY-2',
      last_hit_price: 9.88,
      last_hit_signal_time: '2026-03-16T10:40:00+08:00',
    },
  })

  const rows = buildDenseConfigRows(detail)

  assert.deepEqual(
    rows.map((row) => row.key),
    ['category', 'stop_loss_price', 'initial_lot_amount', 'lot_amount', 'forever', 'guardian_enabled', 'buy_1', 'buy_2', 'buy_3'],
  )
  assert.equal(rows[0].currentLabel, '银行')
  assert.equal(rows[1].group, '基础')
  assert.equal(rows[5].group, 'Guardian')
  assert.equal(rows[6].statusLabel, '当前 B1:开')
  assert.equal(rows[7].statusLabel, '当前 B2:关')
  assert.equal(rows[8].note.includes('BUY-2'), true)
})

test('buildDenseConfigRows keeps category row bound to must-pool category instead of subject category', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      category: '守护池',
    },
  })

  const rows = buildDenseConfigRows(detail)

  assert.equal(detail.category, '银行')
  assert.equal(detail.mustPool.category, '守护池')
  assert.equal(rows[0].currentLabel, '守护池')
})

test('buildDetailSummaryChips compresses subject, runtime and pm state into header chips', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      forever: true,
    },
    guardian_buy_grid_config: {
      enabled: true,
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8, enabled: true },
        { level: 2, price: 11.2, enabled: false },
      ],
      state: { armed_levels: { 1: true } },
    },
    buy_lots: [
      { buy_lot_id: 'lot-1', stoploss: { enabled: true } },
      { buy_lot_id: 'lot-2', stoploss: { enabled: false } },
    ],
    runtime_summary: {
      position_quantity: 500,
      position_amount: 123456,
    },
    position_management_summary: {
      effective_state: 'HOLDING_ONLY',
    },
  })

  const chips = buildDetailSummaryChips(detail)

  assert.deepEqual(
    chips.map((chip) => chip.key),
    ['category', 'must_pool', 'position_quantity', 'guardian_enabled', 'takeprofit_enabled_count', 'stoploss_active_count', 'pm_state'],
  )
  assert.equal(chips[1].value, '永久跟踪')
  assert.equal(chips[2].value, '500 股 / 12.35 万')
  assert.equal(chips[4].value, '1 / 3')
  assert.equal(chips[5].value, '1 / 2')
})

test('buildTakeprofitDrafts preserves existing tiers beyond level 3 while keeping first three visible', () => {
  const rows = buildTakeprofitDrafts([
    { level: 2, price: 10.8, enabled: false },
    { level: 4, price: 12.2, enabled: true },
  ])

  assert.deepEqual(
    rows.map((row) => ({ level: row.level, price: row.price, enabled: row.manual_enabled })),
    [
      { level: 1, price: null, enabled: true },
      { level: 2, price: 10.8, enabled: false },
      { level: 3, price: null, enabled: true },
      { level: 4, price: 12.2, enabled: true },
    ],
  )
})

test('createSubjectManagementActions calls subject, guardian, takeprofit and stoploss apis', async () => {
  const calls = []
  const api = {
    async getOverview() {
      calls.push(['getOverview'])
      return {
        rows: [{ symbol: '600000', name: '浦发银行', runtime: { position_quantity: 500 } }],
      }
    },
    async getDetail(symbol) {
      calls.push(['getDetail', symbol])
      return {
        subject: { symbol, name: '浦发银行' },
        must_pool: {},
        guardian_buy_grid_config: {},
        guardian_buy_grid_state: {},
        takeprofit: { tiers: [], state: { armed_levels: {} } },
        buy_lots: [],
        runtime_summary: {},
        position_management_summary: {},
      }
    },
    async saveMustPool(symbol, payload) {
      calls.push(['saveMustPool', symbol, payload.category])
      return { symbol, ...payload }
    },
    async saveGuardianBuyGrid(symbol, payload) {
      calls.push(['saveGuardianBuyGrid', symbol, payload.buy_1])
      return { symbol, ...payload }
    },
    async saveTakeprofitProfile(symbol, payload) {
      calls.push(['saveTakeprofitProfile', symbol, payload.tiers.length])
      return { symbol, tiers: payload.tiers }
    },
    async bindStoploss(payload) {
      calls.push(['bindStoploss', payload.buy_lot_id, payload.stop_price, payload.enabled])
      return payload
    },
  }

  const actions = createSubjectManagementActions(api)
  const overview = await actions.loadOverview()
  const detail = await actions.loadSubjectDetail('600000')
  const mustPool = await actions.saveMustPool('600000', { category: '银行' })
  const guardian = await actions.saveGuardianBuyGrid('600000', { buy_1: 10.2 })
  const takeprofit = await actions.saveTakeprofit('600000', [
    { level: 1, price: 10.8, manual_enabled: true },
  ])
  const stoploss = await actions.saveStoploss('lot_1', { stop_price: 9.2, enabled: true })

  assert.equal(overview[0].symbol, '600000')
  assert.equal(detail.symbol, '600000')
  assert.equal(mustPool.category, '银行')
  assert.equal(guardian.buy_1, 10.2)
  assert.equal(takeprofit.symbol, '600000')
  assert.equal(stoploss.buy_lot_id, 'lot_1')
  assert.deepEqual(calls, [
    ['getOverview'],
    ['getDetail', '600000'],
    ['saveMustPool', '600000', '银行'],
    ['saveGuardianBuyGrid', '600000', 10.2],
    ['saveTakeprofitProfile', '600000', 1],
    ['bindStoploss', 'lot_1', 9.2, true],
  ])
})

test('SubjectManagement view uses dense table editor layout instead of form blocks', () => {
  const source = fs.readFileSync(new URL('./SubjectManagement.vue', import.meta.url), 'utf8')

  assert.match(source, /subject-editor-summarybar/)
  assert.match(source, /subject-editor-table-panel/)
  assert.match(source, /subject-editor-config-table/)
  assert.match(source, /subject-editor-stoploss-table/)
  assert.doesNotMatch(source, /subject-form-grid/)
  assert.doesNotMatch(source, /subject-runtime-grid/)
})
