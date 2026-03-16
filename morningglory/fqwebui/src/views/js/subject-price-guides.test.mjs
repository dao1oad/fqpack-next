import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildGuardianPriceGuides,
  buildKlineSubjectPriceDetail,
  buildTakeprofitPriceGuides,
  validateGuardianGuideDraft,
  validateTakeprofitDrafts,
} from './subject-price-guides.mjs'

test('buildKlineSubjectPriceDetail keeps guardian, takeprofit and runtime state', () => {
  const detail = buildKlineSubjectPriceDetail({
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 10.2,
      buy_2: 9.9,
      buy_3: 9.5,
    },
    guardian_buy_grid_state: {
      buy_active: [true, false, true],
      last_hit_level: 'BUY-2',
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8, enabled: true },
        { level: 3, price: 11.8, enabled: false },
      ],
      state: { armed_levels: { 1: true, 2: false, 3: true } },
    },
  })

  assert.equal(detail.guardianDraft.buy_1, 10.2)
  assert.deepEqual(detail.guardianState.buy_active, [true, false, true])
  assert.equal(detail.takeprofitDrafts.length, 3)
  assert.equal(detail.takeprofitDrafts[1].level, 2)
  assert.equal(detail.takeprofitDrafts[1].price, null)
  assert.deepEqual(detail.takeprofitState.armed_levels, { 1: true, 2: false, 3: true })
  assert.equal(detail.chartPriceGuides.lines.length, 5)
  assert.equal(detail.chartPriceGuides.bands.length, 0)
})

test('buildGuardianPriceGuides keeps blue red green order from high to low', () => {
  const lines = buildGuardianPriceGuides({
    enabled: true,
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
      { key: 'buy_1', price: 10.2, color: '#3b82f6', active: true, lineStyle: 'solid' },
      { key: 'buy_2', price: 9.9, color: '#ef4444', active: false, lineStyle: 'solid' },
      { key: 'buy_3', price: 9.5, color: '#22c55e', active: true, lineStyle: 'solid' },
    ],
  )
  assert.equal(lines[0].label, 'G-B1 10.20')
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
  assert.equal(lines[2].label, 'TP-L3 11.80')
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
