import test from 'node:test'
import assert from 'node:assert/strict'

import { aggregatePlateRows } from './shouban30Aggregation.mjs'
import {
  EXTRA_FILTER_OPTIONS,
  filterStockRowsByPlate,
  filterStocksByExtraFlags,
  rebuildPlatesFromFilteredStocks,
  toggleExtraFilter,
} from './shouban30StockFilters.mjs'

test('EXTRA_FILTER_OPTIONS keeps stable order and labels', () => {
  assert.deepEqual(EXTRA_FILTER_OPTIONS, [
    { key: 'credit', label: '融资标的' },
    { key: 'near_long_term_ma', label: '均线附近' },
    { key: 'quality', label: '优质标的' },
  ])
})

test('toggleExtraFilter supports add and remove while keeping stable option order', () => {
  assert.deepEqual(toggleExtraFilter([], 'quality'), ['quality'])
  assert.deepEqual(toggleExtraFilter(['quality'], 'credit'), ['credit', 'quality'])
  assert.deepEqual(
    toggleExtraFilter(['credit', 'near_long_term_ma', 'quality'], 'near_long_term_ma'),
    ['credit', 'quality'],
  )
  assert.deepEqual(toggleExtraFilter(['credit'], 'credit'), [])
})

test('filterStocksByExtraFlags returns chanlun-passed rows and applies selected filters by intersection', () => {
  const rows = [
    {
      code6: '000001',
      chanlun_passed: true,
      is_credit_subject: true,
      near_long_term_ma_passed: true,
      is_quality_subject: true,
    },
    {
      code6: '000002',
      chanlun_passed: true,
      is_credit_subject: true,
      near_long_term_ma_passed: false,
      is_quality_subject: true,
    },
    {
      code6: '000003',
      chanlun_passed: true,
      is_credit_subject: false,
      near_long_term_ma_passed: true,
      is_quality_subject: true,
    },
    {
      code6: '000004',
      chanlun_passed: false,
      is_credit_subject: true,
      near_long_term_ma_passed: true,
      is_quality_subject: true,
    },
  ]

  assert.deepEqual(
    filterStocksByExtraFlags(rows, []).map((row) => row.code6),
    ['000001', '000002', '000003'],
  )
  assert.deepEqual(
    filterStocksByExtraFlags(rows, ['credit']).map((row) => row.code6),
    ['000001', '000002'],
  )
  assert.deepEqual(
    filterStocksByExtraFlags(rows, ['credit', 'quality']).map((row) => row.code6),
    ['000001', '000002'],
  )
  assert.deepEqual(
    filterStocksByExtraFlags(rows, ['credit', 'near_long_term_ma', 'quality']).map((row) => row.code6),
    ['000001'],
  )
})

test('filterStockRowsByPlate keeps plate keys and filters each plate independently', () => {
  const rowsByPlate = filterStockRowsByPlate({
    plateA: [
      { code6: '000001', chanlun_passed: true, is_credit_subject: true },
      { code6: '000002', chanlun_passed: true, is_credit_subject: false },
    ],
    plateB: [
      { code6: '000003', chanlun_passed: true, is_credit_subject: true },
    ],
  }, ['credit'])

  assert.deepEqual(
    Object.fromEntries(
      Object.entries(rowsByPlate).map(([plateKey, rows]) => [plateKey, rows.map((row) => row.code6)]),
    ),
    {
      plateA: ['000001'],
      plateB: ['000003'],
    },
  )
})

test('rebuildPlatesFromFilteredStocks rewrites counts and drops empty plates', () => {
  const rows = rebuildPlatesFromFilteredStocks({
    plates: [
      {
        provider: 'xgb',
        plate_key: 'robot',
        plate_name: '机器人',
        seg_to: '2026-03-09',
        appear_days_30: 2,
      },
      {
        provider: 'xgb',
        plate_key: 'chip',
        plate_name: '芯片',
        seg_to: '2026-03-08',
        appear_days_30: 1,
      },
    ],
    stockRowsByPlate: {
      robot: [
        { code6: '000001', chanlun_passed: true, is_credit_subject: true },
        { code6: '000002', chanlun_passed: true, is_credit_subject: true },
      ],
      chip: [],
    },
  })

  assert.deepEqual(rows, [
    {
      provider: 'xgb',
      plate_key: 'robot',
      plate_name: '机器人',
      seg_to: '2026-03-09',
      appear_days_30: 2,
      stocks_count: 2,
      last_up_date: '2026-03-09',
      view_key: 'xgb|robot',
    },
  ])
})

test('aggregate view can rebuild plate counts from filtered stock rows', () => {
  const xgbPlates = [
    {
      provider: 'xgb',
      plate_key: 'robot-a',
      plate_name: '机器人',
      seg_to: '2026-03-08',
      appear_days_30: 2,
      hit_trade_dates_30: ['2026-03-07', '2026-03-08'],
      reason_text: 'xgb reason',
    },
  ]
  const jygsPlates = [
    {
      provider: 'jygs',
      plate_key: 'robot-b',
      plate_name: '机器人',
      seg_to: '2026-03-09',
      appear_days_30: 2,
      hit_trade_dates_30: ['2026-03-08', '2026-03-09'],
      reason_text: 'jygs reason',
    },
  ]

  const rows = aggregatePlateRows({
    xgbPlates,
    jygsPlates,
    stockRowsByProvider: {
      xgb: {
        'robot-a': [
          { code6: '000001', chanlun_passed: true, is_quality_subject: true },
          { code6: '000002', chanlun_passed: true, is_quality_subject: false },
        ],
      },
      jygs: {
        'robot-b': [
          { code6: '000001', chanlun_passed: true, is_quality_subject: true },
          { code6: '000003', chanlun_passed: true, is_quality_subject: false },
        ],
      },
    },
  })

  assert.equal(rows.length, 1)
  assert.equal(rows[0].stocks_count, 3)

  const filteredRows = aggregatePlateRows({
    xgbPlates: [
      xgbPlates[0],
    ],
    jygsPlates: [
      jygsPlates[0],
    ],
    stockRowsByProvider: {
      xgb: filterStockRowsByPlate(
        {
          'robot-a': [
            { code6: '000001', chanlun_passed: true, is_quality_subject: true },
            { code6: '000002', chanlun_passed: true, is_quality_subject: false },
          ],
        },
        ['quality'],
      ),
      jygs: filterStockRowsByPlate(
        {
          'robot-b': [
            { code6: '000001', chanlun_passed: true, is_quality_subject: true },
            { code6: '000003', chanlun_passed: true, is_quality_subject: false },
          ],
        },
        ['quality'],
      ),
    },
  })

  assert.equal(filteredRows.length, 1)
  assert.equal(filteredRows[0].stocks_count, 1)
})
