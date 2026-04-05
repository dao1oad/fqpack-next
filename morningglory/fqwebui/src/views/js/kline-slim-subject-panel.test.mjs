import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildInitialKlineSlimSubjectPanelState,
  createKlineSlimSubjectPanelActions,
  normalizeKlineSlimSubjectPanelDetail,
} from './kline-slim-subject-panel.mjs'

test('normalizeKlineSlimSubjectPanelDetail keeps must-pool, position limit and stoploss data together', () => {
  const detail = normalizeKlineSlimSubjectPanelDetail({
    subject: { symbol: '600000', name: '浦发银行' },
    must_pool: { category: '银行', stop_loss_price: 9.2, lot_amount: 50000 },
    position_limit_summary: {
      default_limit: 800000,
      override_limit: 500000,
      effective_limit: 500000,
      using_override: true,
      blocked: false,
    },
    entries: [
      {
        entry_id: 'entry_c47155b437de422db9ea2eec0b316d2a',
        date: 20260316,
        time: '10:31:00',
        entry_price: 10.0,
        original_quantity: 300,
        remaining_quantity: 200,
        latest_price: 10.88,
        latest_price_source: 'xt_positions_last_price',
        remaining_market_value: 2176,
        remaining_market_value_source: 'latest_price_x_remaining_quantity',
        aggregation_members: [
          { broker_order_key: 'buy_ord_a', quantity: 100, entry_price: 10.0, time: '10:31:00' },
          { broker_order_key: 'buy_ord_b', quantity: 200, entry_price: 10.03, time: '10:33:00' },
        ],
        entry_slices: [
          { entry_slice_id: 'slice_1', slice_seq: 1, guardian_price: 9.8, remaining_quantity: 80 },
          { entry_slice_id: 'slice_2', slice_seq: 2, guardian_price: 9.6, remaining_quantity: 120 },
        ],
        stoploss: { stop_price: 9.2, enabled: true },
      },
    ],
    runtime_summary: {
      position_quantity: 500,
      position_amount: 123456.0,
      avg_price: 10.023,
    },
  })

  assert.equal(detail.symbol, '600000')
  assert.equal(detail.positionLimit.limit, 500000)
  assert.equal(detail.positionLimit.using_override, true)
  assert.equal(detail.runtimeSummary.avg_price, 10.023)
  assert.equal(detail.entries[0].stoploss.enabled, true)
  assert.equal(detail.entries[0].entryDisplayLabel, '第 1 笔持仓入口')
  assert.equal(detail.entries[0].entryIdLabel, 'ID 尾号 316d2a')
  assert.deepEqual(detail.entries[0].entrySummaryDisplay, {
    entryPriceLabel: '10.000',
    originalQuantityLabel: '300 股',
    remainingQuantityLabel: '200 股',
    remainingPercentLabel: '66.67%',
    remainingPositionLabel: '200 股 / 66.67%',
    entryDateTimeLabel: '2026-03-16 10:31:00',
    remainingMarketValueLabel: '0.22 万',
  })
  assert.deepEqual(detail.entries[0].entrySummaryLines, [
    '买入价：10.000；买入300 股 剩 200 股 / 66.67%',
    '买入时间：2026-03-16 10:31:00；剩余市值：0.22 万',
  ])
  assert.equal(
    detail.entries[0].entryMetaLabel,
    '买入价：10.000；买入300 股 剩 200 股 / 66.67% · 买入时间：2026-03-16 10:31:00；剩余市值：0.22 万'
  )
  assert.equal(detail.entries[0].latest_price, 10.88)
  assert.equal(detail.entries[0].aggregation_members.length, 2)
  assert.equal(detail.entries[0].entry_slices.length, 2)
  assert.equal(Object.hasOwn(detail.mustPool, 'forever'), false)
  assert.equal(Object.hasOwn(detail.positionLimit, 'use_default'), false)
})

test('normalizeKlineSlimSubjectPanelDetail ignores zero latest-price market values and falls back to avg-price labels', () => {
  const detail = normalizeKlineSlimSubjectPanelDetail({
    subject: { symbol: '600104', name: '上汽集团' },
    entries: [
      {
        entry_id: 'entry_zero_price',
        date: 20260401,
        time: '14:44:27',
        entry_price: 14.44,
        original_quantity: 3400,
        remaining_quantity: 3200,
        latest_price: 0,
        remaining_market_value: 0,
      },
    ],
    runtime_summary: {
      avg_price: 14.884353,
    },
  })

  assert.equal(detail.entries[0].entrySummaryDisplay.remainingMarketValueLabel, '4.76 万')
})

test('createKlineSlimSubjectPanelActions routes subject and position-limit writes to separate apis', async () => {
  const calls = []
  const actions = createKlineSlimSubjectPanelActions({
    async getDetail(symbol) {
      calls.push(['getDetail', symbol])
      return { subject: { symbol } }
    },
    async saveMustPool(symbol, payload) {
      calls.push(['saveMustPool', symbol, payload.category])
      return { symbol, ...payload }
    },
    async saveSymbolPositionLimit(symbol, payload) {
      calls.push(['saveSymbolPositionLimit', symbol, payload.limit ?? null])
      return { symbol, ...payload }
    },
    async bindStoploss(payload) {
      calls.push(['bindStoploss', payload.entry_id, payload.stop_price, payload.enabled])
      return payload
    },
  })

  await actions.loadSubjectDetail('600000')
  await actions.saveMustPool('600000', { category: '银行' })
  await actions.savePositionLimit('600000', { limit: 500000 })
  await actions.saveStoploss('entry-1', { stop_price: 9.2, enabled: true })

  assert.deepEqual(calls, [
    ['getDetail', '600000'],
    ['saveMustPool', '600000', '银行'],
    ['saveSymbolPositionLimit', '600000', 500000],
    ['bindStoploss', 'entry-1', 9.2, true],
  ])
})

test('buildInitialKlineSlimSubjectPanelState starts closed and idle', () => {
  const state = buildInitialKlineSlimSubjectPanelState()

  assert.equal(state.showSubjectPanel, false)
  assert.equal(state.subjectDetailLoading, false)
  assert.equal(state.savingSubjectConfigBundle, false)
  assert.equal(state.subjectPanelDetail, null)
  assert.equal(Object.hasOwn(state.mustPoolDraft, 'forever'), false)
  assert.equal(Object.hasOwn(state.positionLimitDraft, 'use_default'), false)
  assert.deepEqual(state.positionLimitDraft, { limit: null })
})
