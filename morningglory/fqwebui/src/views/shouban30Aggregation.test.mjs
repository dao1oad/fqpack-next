import test from 'node:test'
import assert from 'node:assert/strict'

import {
  aggregatePlateRows,
  aggregateStockRows,
  buildViewStats,
  formatProviderLoadErrors,
  loadProvidersIndependently,
  normalizeSourcePlateRefs,
  sortStockRows,
  sortPlateRows,
} from './shouban30Aggregation.mjs'

test('sortPlateRows sorts by last up date desc then appear days desc then name asc', () => {
  const rows = [
    {
      plate_name: 'Beta',
      seg_to: '2026-03-05',
      appear_days_30: 1,
    },
    {
      plate_name: 'Alpha',
      seg_to: '2026-03-06',
      appear_days_30: 2,
    },
    {
      plate_name: 'Gamma',
      seg_to: '2026-03-06',
      appear_days_30: 1,
    },
  ]

  const sorted = sortPlateRows(rows)

  assert.deepEqual(
    sorted.map((item) => item.plate_name),
    ['Alpha', 'Gamma', 'Beta'],
  )
  assert.deepEqual(
    sorted.map((item) => item.last_up_date),
    ['2026-03-06', '2026-03-06', '2026-03-05'],
  )
})

test('aggregatePlateRows merges same-name plates and deduplicates stock codes', () => {
  const rows = aggregatePlateRows({
    xgbPlates: [
      {
        provider: 'xgb',
        plate_key: '11',
        plate_name: 'robotics',
        seg_to: '2026-03-05',
        appear_days_30: 2,
        hit_trade_dates_30: ['2026-03-04', '2026-03-05'],
        reason_text: 'xgb reason',
      },
    ],
    jygsPlates: [
      {
        provider: 'jygs',
        plate_key: 'robot',
        plate_name: 'robotics',
        seg_to: '2026-03-06',
        appear_days_30: 2,
        hit_trade_dates_30: ['2026-03-05', '2026-03-06'],
        reason_text: 'jygs reason',
      },
      {
        provider: 'jygs',
        plate_key: 'chip',
        plate_name: 'chips',
        seg_to: '2026-03-03',
        appear_days_30: 1,
        hit_trade_dates_30: ['2026-03-03'],
        reason_text: 'chip reason',
      },
    ],
    stockRowsByProvider: {
      xgb: {
        '11': [{ code6: '000001' }, { code6: '000002' }],
      },
      jygs: {
        robot: [{ code6: '000002' }, { code6: '000003' }],
        chip: [{ code6: '000004' }],
      },
    },
  })

  assert.equal(rows.length, 2)
  assert.deepEqual(rows[0], {
    view_key: 'agg|robotics',
    provider: 'agg',
    plate_key: 'agg|robotics',
    plate_name: 'robotics',
    appear_days_30: 3,
    last_up_date: '2026-03-06',
    seg_to: '2026-03-06',
    stocks_count: 3,
    reason_text: 'jygs reason',
    providers: ['xgb', 'jygs'],
    source_plate_refs: [
      { provider: 'xgb', plate_key: '11' },
      { provider: 'jygs', plate_key: 'robot' },
    ],
    hit_trade_dates_30: ['2026-03-04', '2026-03-05', '2026-03-06'],
  })
})

test('aggregatePlateRows uses only chanlun-passed stocks and drops zero-count plates', () => {
  const rows = aggregatePlateRows({
    xgbPlates: [
      {
        provider: 'xgb',
        plate_key: '11',
        plate_name: 'robotics',
        seg_to: '2026-03-05',
        appear_days_30: 2,
        hit_trade_dates_30: ['2026-03-04', '2026-03-05'],
        reason_text: 'xgb reason',
      },
      {
        provider: 'xgb',
        plate_key: '22',
        plate_name: 'chips',
        seg_to: '2026-03-04',
        appear_days_30: 1,
        hit_trade_dates_30: ['2026-03-04'],
        reason_text: 'chip reason',
      },
    ],
    jygsPlates: [],
    stockRowsByProvider: {
      xgb: {
        '11': [
          { code6: '000001', chanlun_passed: true },
          { code6: '000002', chanlun_passed: false },
        ],
        '22': [
          { code6: '000003', chanlun_passed: false },
        ],
      },
      jygs: {},
    },
  })

  assert.equal(rows.length, 1)
  assert.equal(rows[0].plate_name, 'robotics')
  assert.equal(rows[0].stocks_count, 1)
})

test('aggregatePlateRows keeps all source plate refs for same provider and same name', () => {
  const rows = aggregatePlateRows({
    xgbPlates: [
      {
        provider: 'xgb',
        plate_key: 'robot-a',
        plate_name: 'robotics',
        seg_to: '2026-03-05',
        appear_days_30: 1,
        hit_trade_dates_30: ['2026-03-05'],
        reason_text: 'xgb a',
      },
      {
        provider: 'xgb',
        plate_key: 'robot-b',
        plate_name: 'robotics',
        seg_to: '2026-03-06',
        appear_days_30: 1,
        hit_trade_dates_30: ['2026-03-06'],
        reason_text: 'xgb b',
      },
    ],
    jygsPlates: [],
    stockRowsByProvider: {
      xgb: {
        'robot-a': [{ code6: '000001' }],
        'robot-b': [{ code6: '000002' }, { code6: '000003' }],
      },
      jygs: {},
    },
  })

  assert.equal(rows.length, 1)
  assert.deepEqual(rows[0].source_plate_refs, [
    { provider: 'xgb', plate_key: 'robot-a' },
    { provider: 'xgb', plate_key: 'robot-b' },
  ])
  assert.equal(rows[0].stocks_count, 3)
  assert.equal(rows[0].last_up_date, '2026-03-06')
})

test('aggregateStockRows merges same code6 and keeps latest reason', () => {
  const rows = aggregateStockRows([
    {
      provider: 'xgb',
      code6: '000001',
      name: 'Alpha',
      latest_trade_date: '2026-03-05',
      latest_reason: 'xgb latest',
      hit_count_window: 2,
      hit_trade_dates_window: ['2026-03-04', '2026-03-05'],
    },
    {
      provider: 'jygs',
      code6: '000001',
      name: 'Alpha',
      latest_trade_date: '2026-03-06',
      latest_reason: 'jygs latest',
      hit_count_window: 1,
      hit_trade_dates_window: ['2026-03-06'],
    },
    {
      provider: 'xgb',
      code6: '000002',
      name: 'Beta',
      latest_trade_date: '2026-03-06',
      latest_reason: 'beta latest',
      hit_count_window: 1,
      hit_trade_dates_window: ['2026-03-06'],
    },
  ])

  assert.deepEqual(rows, [
    {
      code6: '000001',
      name: 'Alpha',
      hit_count_window: 3,
      latest_trade_date: '2026-03-06',
      latest_reason: 'jygs latest',
      providers: ['xgb', 'jygs'],
      hit_trade_dates_window: ['2026-03-04', '2026-03-05', '2026-03-06'],
    },
    {
      code6: '000002',
      name: 'Beta',
      hit_count_window: 1,
      latest_trade_date: '2026-03-06',
      latest_reason: 'beta latest',
      providers: ['xgb'],
      hit_trade_dates_window: ['2026-03-06'],
    },
  ])
})

test('aggregateStockRows drops chanlun-failed rows before dedupe', () => {
  const rows = aggregateStockRows([
    {
      provider: 'xgb',
      code6: '000001',
      name: 'Alpha',
      latest_trade_date: '2026-03-05',
      latest_reason: 'xgb latest',
      hit_count_window: 2,
      hit_trade_dates_window: ['2026-03-04', '2026-03-05'],
      chanlun_passed: false,
    },
    {
      provider: 'jygs',
      code6: '000001',
      name: 'Alpha',
      latest_trade_date: '2026-03-06',
      latest_reason: 'jygs latest',
      hit_count_window: 1,
      hit_trade_dates_window: ['2026-03-06'],
      chanlun_passed: true,
    },
  ])

  assert.deepEqual(rows, [
    {
      code6: '000001',
      name: 'Alpha',
      hit_count_window: 1,
      latest_trade_date: '2026-03-06',
      latest_reason: 'jygs latest',
      providers: ['jygs'],
      hit_trade_dates_window: ['2026-03-06'],
    },
  ])
})

test('sortStockRows sorts by latest trade date desc then hit count desc then code6 asc', () => {
  const rows = sortStockRows([
    {
      code6: '000003',
      latest_trade_date: '2026-03-05',
      hit_count_window: 1,
    },
    {
      code6: '000001',
      latest_trade_date: '2026-03-06',
      hit_count_window: 1,
    },
    {
      code6: '000002',
      latest_trade_date: '2026-03-06',
      hit_count_window: 2,
    },
  ])

  assert.deepEqual(
    rows.map((item) => item.code6),
    ['000002', '000001', '000003'],
  )
})

test('buildViewStats counts unique stocks by code6', () => {
  const stats = buildViewStats({
    plates: [{ plate_key: 'a' }, { plate_key: 'b' }],
    stockRowsByPlate: {
      a: [{ code6: '000001' }, { code6: '000002' }],
      b: [{ code6: '000002' }, { code6: '000003' }],
    },
  })

  assert.deepEqual(stats, {
    plate_count: 2,
    stock_count: 3,
  })
})

test('normalizeSourcePlateRefs supports legacy object shape and new array shape', () => {
  assert.deepEqual(normalizeSourcePlateRefs({
    xgb: 'robot-a',
    jygs: 'robot',
  }), [
    { provider: 'xgb', plate_key: 'robot-a' },
    { provider: 'jygs', plate_key: 'robot' },
  ])

  assert.deepEqual(normalizeSourcePlateRefs([
    { provider: 'xgb', plate_key: 'robot-a' },
    { provider: 'xgb', plate_key: 'robot-a' },
    { provider: 'jygs', plate_key: 'robot' },
  ]), [
    { provider: 'xgb', plate_key: 'robot-a' },
    { provider: 'jygs', plate_key: 'robot' },
  ])
})

test('loadProvidersIndependently keeps successful provider data when peer fails', async () => {
  const result = await loadProvidersIndependently({
    providers: ['xgb', 'jygs'],
    fetcher: async (provider) => {
      if (provider === 'jygs') throw new Error('timeout')
      return { items: ['ok'] }
    },
    emptyValueFactory: () => ({ items: [] }),
  })

  assert.deepEqual(result.valuesByProvider, {
    xgb: { items: ['ok'] },
    jygs: { items: [] },
  })
  assert.equal(result.errors.length, 1)
  assert.equal(result.errors[0].provider, 'jygs')
  assert.equal(result.errors[0].error.message, 'timeout')
})

test('formatProviderLoadErrors includes provider labels and messages', () => {
  const message = formatProviderLoadErrors({
    errors: [
      { provider: 'jygs', error: new Error('timeout') },
      { provider: 'xgb', error: { response: { data: { message: '500' } } } },
    ],
    targetLabel: '首板板块',
  })

  assert.equal(message, 'JYGS首板板块加载失败: timeout；XGB首板板块加载失败: 500')
})
