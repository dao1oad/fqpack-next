import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildGuardianPriceGuides,
  buildKlineSubjectPriceDetail,
  buildTakeprofitPriceGuides,
  getPriceGuideLegendName,
  validateGuardianGuideDraft,
  validateTakeprofitDrafts,
} from './subject-price-guides.mjs'

test('buildKlineSubjectPriceDetail keeps guardian, takeprofit and runtime state', () => {
  const detail = buildKlineSubjectPriceDetail({
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 10.2346,
      buy_2: 9.8765,
      buy_3: 9.5434,
    },
    guardian_buy_grid_state: {
      buy_active: [true, false, true],
      last_hit_level: 'BUY-2',
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8765, enabled: true },
        { level: 3, price: 11.8765, enabled: false },
      ],
      state: { armed_levels: { 1: true, 2: false, 3: true } },
    },
  })

  assert.equal(detail.guardianDraft.buy_1, 10.235)
  assert.deepEqual(detail.guardianState.buy_active, [true, false, true])
  assert.equal(detail.takeprofitDrafts.length, 3)
  assert.equal(detail.takeprofitDrafts[0].price, 10.877)
  assert.equal(detail.takeprofitDrafts[1].level, 2)
  assert.equal(detail.takeprofitDrafts[1].price, null)
  assert.deepEqual(detail.takeprofitState.armed_levels, { 1: true, 2: false, 3: true })
  assert.equal(detail.chartPriceGuides.lines.length, 5)
  assert.equal(detail.chartPriceGuides.bands.length, 0)
})

test('buildKlineSubjectPriceDetail adds cost basis and open buy lot guides', () => {
  const detail = buildKlineSubjectPriceDetail({
    runtime_summary: {
      avg_price: 10.0234,
    },
    buy_lots: [
      {
        buy_lot_id: 'lot_1',
        buy_price_real: 10.02,
        remaining_quantity: 200,
      },
      {
        buy_lot_id: 'lot_2',
        buy_price_real: 9.88,
        remaining_quantity: 100,
      },
      {
        buy_lot_id: 'lot_3',
        buy_price_real: null,
        remaining_quantity: 50,
      },
    ],
  })

  const costBasisLine = detail.chartPriceGuides.lines.find((row) => row.group === 'cost_basis')
  const buyLotLines = detail.chartPriceGuides.lines.filter((row) => row.group === 'buy_lot')

  assert.equal(costBasisLine?.price, 10.023)
  assert.equal(costBasisLine?.label, '成本 10.023')
  assert.equal(costBasisLine?.lineStyle, 'solid')
  assert.deepEqual(
    buyLotLines.map((row) => ({
      id: row.id,
      price: row.price,
      label: row.label,
      lineStyle: row.lineStyle,
    })),
    [
      { id: 'buy-lot-lot_1', price: 10.02, label: '买1 10.020 / 200股', lineStyle: 'dotted' },
      { id: 'buy-lot-lot_2', price: 9.88, label: '买2 9.880 / 100股', lineStyle: 'dotted' },
    ],
  )
})

test('getPriceGuideLegendName exposes cost basis and buy lot legend labels', () => {
  assert.equal(getPriceGuideLegendName('cost_basis'), '成本价线')
  assert.equal(getPriceGuideLegendName('buy_lot'), '买入订单线')
})

test('buildGuardianPriceGuides keeps blue red green order from high to low', () => {
  const lines = buildGuardianPriceGuides({
    buy_enabled: [true, false, true],
    buy_1: 10.2,
    buy_2: 9.9,
    buy_3: 9.5,
  }, {
    buy_active: [true, false, true],
  })

  assert.deepEqual(
    lines.map((row) => ({
      key: row.key,
      price: row.price,
      color: row.color,
      active: row.active,
      lineStyle: row.lineStyle,
    })),
    [
      { key: 'buy_1', price: 10.2, color: '#3b82f6', active: true, lineStyle: 'dashed' },
      { key: 'buy_2', price: 9.9, color: '#ef4444', active: false, lineStyle: 'dashed' },
      { key: 'buy_3', price: 9.5, color: '#22c55e', active: true, lineStyle: 'dashed' },
    ],
  )
  assert.equal(lines[0].label, 'G-B1 10.200')
})

test('buildGuardianPriceGuides respects per-level switches instead of a single global switch', () => {
  const lines = buildGuardianPriceGuides({
    enabled: true,
    buy_enabled: [true, false, true],
    buy_1: 10.2,
    buy_2: 9.9,
    buy_3: 9.5,
  }, {
    buy_active: [true, true, true],
  })

  assert.deepEqual(
    lines.map((row) => ({
      key: row.key,
      active: row.active,
      manual_enabled: row.manual_enabled,
    })),
    [
      { key: 'buy_1', active: true, manual_enabled: true },
      { key: 'buy_2', active: false, manual_enabled: false },
      { key: 'buy_3', active: true, manual_enabled: true },
    ],
  )
})

test('buildTakeprofitPriceGuides keeps blue red green order from low to high', () => {
  const lines = buildTakeprofitPriceGuides([
    { level: 1, price: 10.8, manual_enabled: true },
    { level: 2, price: 11.2, manual_enabled: false },
    { level: 3, price: 11.8, manual_enabled: true },
  ], {
    armed_levels: { 1: true, 2: false, 3: true },
  })

  assert.deepEqual(
    lines.map((row) => ({
      level: row.level,
      price: row.price,
      color: row.color,
      active: row.active,
      lineStyle: row.lineStyle,
    })),
    [
      { level: 1, price: 10.8, color: '#3b82f6', active: true, lineStyle: 'dashed' },
      { level: 2, price: 11.2, color: '#ef4444', active: false, lineStyle: 'dashed' },
      { level: 3, price: 11.8, color: '#22c55e', active: true, lineStyle: 'dashed' },
    ],
  )
  assert.equal(lines[2].label, 'TP-L3 11.800')
})

test('validateGuardianGuideDraft rejects invalid prices and wrong order', () => {
  assert.deepEqual(
    validateGuardianGuideDraft({
      enabled: true,
      buy_1: 10.2,
      buy_2: null,
      buy_3: 9.5,
    }),
    {
      valid: false,
      message: '请先填写完整的 Guardian 三层价格',
    },
  )

  assert.deepEqual(
    validateGuardianGuideDraft({
      enabled: true,
      buy_1: 9.8,
      buy_2: 9.9,
      buy_3: 9.5,
    }),
    {
      valid: false,
      message: 'Guardian 价格必须满足 buy_1 > buy_2 > buy_3',
    },
  )
})

test('validateTakeprofitDrafts rejects invalid prices and wrong order', () => {
  assert.deepEqual(
    validateTakeprofitDrafts([
      { level: 1, price: 10.8, manual_enabled: true },
      { level: 2, price: null, manual_enabled: true },
      { level: 3, price: 11.8, manual_enabled: true },
    ]),
    {
      valid: false,
      message: '请先填写完整的止盈三层价格',
    },
  )

  assert.deepEqual(
    validateTakeprofitDrafts([
      { level: 1, price: 10.8, manual_enabled: true },
      { level: 2, price: 10.7, manual_enabled: true },
      { level: 3, price: 11.8, manual_enabled: true },
    ]),
    {
      valid: false,
      message: '止盈价格必须满足 L1 < L2 < L3',
    },
  )

  assert.deepEqual(
    validateTakeprofitDrafts([
      { level: 1, price: 10.8, manual_enabled: true },
      { level: 2, price: 11.2, manual_enabled: false },
      { level: 3, price: 11.8, manual_enabled: true },
    ]),
    {
      valid: true,
      message: '',
    },
  )
})
