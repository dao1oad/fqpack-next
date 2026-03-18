import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDailyScreeningQueryPayload,
  buildDailyScreeningWorkbenchState,
  normalizeDailyScreeningFilterCatalog,
  normalizeDailyScreeningScopeItems,
  readDailyScreeningPayload,
} from './dailyScreeningPage.mjs'

test('readDailyScreeningPayload supports both axios envelopes and interceptor-unwrapped payloads', () => {
  assert.deepEqual(
    readDailyScreeningPayload({
      data: {
        scope_id: 'trade_date:2026-03-18',
      },
    }),
    {
      scope_id: 'trade_date:2026-03-18',
    },
  )

  assert.deepEqual(
    readDailyScreeningPayload({
      scope_id: 'trade_date:2026-03-19',
    }),
    {
      scope_id: 'trade_date:2026-03-19',
    },
  )

  assert.deepEqual(readDailyScreeningPayload(null), {})
})

test('buildDailyScreeningWorkbenchState defaults to base-union query mode', () => {
  const state = buildDailyScreeningWorkbenchState({
    run_id: 'trade_date:2026-03-18',
    scope: 'trade_date:2026-03-18',
    label: '正式 2026-03-18',
  })

  assert.equal(state.scopeId, 'trade_date:2026-03-18')
  assert.equal(state.selectedRunId, 'trade_date:2026-03-18')
  assert.deepEqual(state.conditionKeys, [])
  assert.deepEqual(state.metricFilters, {
    higherMultipleLte: null,
    segmentMultipleLte: null,
    biGainPercentLte: null,
  })
})

test('normalizeDailyScreeningScopeItems preserves scope identity and latest marker', () => {
  const items = normalizeDailyScreeningScopeItems({
    items: [
      {
        run_id: 'trade_date:2026-03-18',
        scope: 'trade_date:2026-03-18',
        label: '正式 2026-03-18',
        is_latest: true,
      },
    ],
  })

  assert.deepEqual(items, [
    {
      scopeId: 'trade_date:2026-03-18',
      runId: 'trade_date:2026-03-18',
      scope: 'trade_date:2026-03-18',
      label: '正式 2026-03-18',
      isLatest: true,
    },
  ])
})

test('normalizeDailyScreeningFilterCatalog exposes grouped condition options', () => {
  const catalog = normalizeDailyScreeningFilterCatalog({
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['hot:30d', 'flag:quality_subject'],
    groups: {
      hot_windows: [{ key: 'hot:30d', label: '30天热门', count: 12 }],
      market_flags: [{ key: 'flag:quality_subject', label: '优质标的', count: 8 }],
      chanlun_periods: [{ key: 'chanlun_period:30m', label: '30m', count: 6 }],
    },
  })

  assert.equal(catalog.scopeId, 'trade_date:2026-03-18')
  assert.deepEqual(catalog.conditionKeys, ['hot:30d', 'flag:quality_subject'])
  assert.deepEqual(catalog.groups.hotWindows, [
    { key: 'hot:30d', label: '30天热门', count: 12 },
  ])
  assert.deepEqual(catalog.groups.marketFlags, [
    { key: 'flag:quality_subject', label: '优质标的', count: 8 },
  ])
  assert.deepEqual(catalog.groups.chanlunPeriods, [
    { key: 'chanlun_period:30m', label: '30m', count: 6 },
  ])
})

test('buildDailyScreeningQueryPayload emits condition_keys and metric_filters', () => {
  const payload = buildDailyScreeningQueryPayload({
    scopeId: 'trade_date:2026-03-18',
    conditionKeys: ['hot:30d', 'flag:quality_subject'],
    metricFilters: {
      higherMultipleLte: 2.5,
      segmentMultipleLte: null,
      biGainPercentLte: 30,
    },
  })

  assert.deepEqual(payload, {
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['hot:30d', 'flag:quality_subject'],
    metric_filters: {
      higher_multiple_lte: 2.5,
      bi_gain_percent_lte: 30,
    },
  })
})
