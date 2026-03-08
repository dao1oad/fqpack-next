import test from 'node:test'
import assert from 'node:assert/strict'

import {
  aggregatePlateRows,
  aggregateStockRows,
  buildViewStats,
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
        plate_name: '机器人',
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
        plate_name: '机器人',
        seg_to: '2026-03-06',
        appear_days_30: 2,
        hit_trade_dates_30: ['2026-03-05', '2026-03-06'],
        reason_text: 'jygs reason',
      },
      {
        provider: 'jygs',
        plate_key: 'chip',
        plate_name: '芯片',
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
    view_key: 'agg|机器人',
    provider: 'agg',
    plate_key: 'agg|机器人',
    plate_name: '机器人',
    appear_days_30: 3,
    last_up_date: '2026-03-06',
    seg_to: '2026-03-06',
    stocks_count: 3,
    reason_text: 'jygs reason',
    providers: ['xgb', 'jygs'],
    source_plate_keys: {
      xgb: '11',
      jygs: 'robot',
    },
    hit_trade_dates_30: ['2026-03-04', '2026-03-05', '2026-03-06'],
  })
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
