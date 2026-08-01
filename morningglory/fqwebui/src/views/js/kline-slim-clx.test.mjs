import test from 'node:test'
import assert from 'node:assert/strict'

import {
  aggregateClxMarkersByBar,
  anchorClxMarkersToBars,
  buildKlineClxQuery,
  filterClxMarkers,
  normalizeClxSignalHistory,
  normalizeClxSidebarItem,
  parseKlineClxQuery,
  resolveClxAssetType,
  sortClxSidebarItems,
} from './kline-slim-clx.mjs'

const markers = [
  { id: 'a', modelKey: 'S0003', conditionKey: 'buy', triggerDate: '2026-07-30', direction: 'buy' },
  { id: 'b', modelKey: 'S0007', conditionKey: 'buy', triggerDate: '2026-07-30', direction: 'buy' },
  { id: 'c', modelKey: 'S0009', conditionKey: 'sell', triggerDate: '2026-07-31', direction: 'sell' },
]

test('CLX sidebar order is distinct models desc, distinct conditions desc, symbol asc', () => {
  const sorted = sortClxSidebarItems([
    { symbol: 'sz000003', distinct_model_count: 2, distinct_condition_count: 5 },
    { symbol: 'sz000002', distinct_model_count: 3, distinct_condition_count: 1 },
    { symbol: 'sz000001', distinct_model_count: 3, distinct_condition_count: 2 },
  ])

  assert.deepEqual(sorted.map((item) => item.symbol), ['sz000001', 'sz000002', 'sz000003'])
})

test('daily markers anchor to the close bar of a minute chart and aggregate same-day signals', () => {
  const anchored = anchorClxMarkersToBars({
    markers,
    dates: [
      '2026-07-30 09:35:00',
      '2026-07-30 15:00:00',
      '2026-07-31 09:35:00',
      '2026-07-31 15:00:00',
    ],
    period: '5m',
  })
  const groups = aggregateClxMarkersByBar(anchored)

  assert.deepEqual(anchored.map((item) => item.barIndex), [1, 1, 3])
  assert.equal(groups[0].count, 2)
  assert.deepEqual(groups[0].modelKeys, ['S0003', 'S0007'])
})

test('daily markers anchor to daily, weekly and monthly chart buckets', () => {
  assert.equal(anchorClxMarkersToBars({
    markers: [markers[0]],
    dates: ['2026-07-29', '2026-07-30', '2026-07-31'],
    period: '1d',
  })[0].barIndex, 1)

  assert.equal(anchorClxMarkersToBars({
    markers: [markers[0]],
    dates: ['2026-07-27', '2026-08-03'],
    period: '1w',
  })[0].barIndex, 0)

  assert.equal(anchorClxMarkersToBars({
    markers: [markers[0]],
    dates: ['2026-07-01', '2026-08-01'],
    period: '1M',
  })[0].barIndex, 0)
})

test('marker filters only change visibility of calculated history facts', () => {
  const visible = filterClxMarkers(markers, {
    modelKeys: ['S0007'],
    conditionKeys: ['buy'],
  })

  assert.deepEqual(visible.map((item) => item.id), ['b'])
  assert.equal(markers.length, 3)
})

test('history normalizer preserves profile and four-layer condition evidence', () => {
  const history = normalizeClxSignalHistory({
    calculation_profile: {
      id: 'production_v1',
      switch_opt: 1,
      algorithm_version: 'clx18-v2',
      data_version: 'daily-bars-v7',
    },
    future_function_guard: { passed: true },
    markers_by_model: {
      S0002: [{
        marker_id: 'm-1',
        trigger_date: '2026-07-30',
        direction: 'sell',
        signal_value_raw: 203,
        model_condition: { code: 'fallback_fractal', label: '普通分型兜底' },
        condition_evidence: [{ key: 'fractal', value: true }],
      }],
    },
  })

  assert.equal(history.profileId, 'production_v1')
  assert.equal(history.switchOpt, 1)
  assert.equal(history.futureFunctionGuard, true)
  assert.equal(history.markers[0].direction, 'sell')
  assert.equal(history.markers[0].conditionKey, 'fallback_fractal')
  assert.deepEqual(history.markers[0].conditionEvidence, [{ key: 'fractal', value: true }])
})

test('history normalizer maps nested line facts and structured guard results', () => {
  const history = normalizeClxSignalHistory({
    future_function_guard: { passed: false },
    markers_by_model: {
      S0002: [{
        marker_id: 'm-line',
        date: '2026-07-31',
        direction: 'buy',
        above_ma250: { line_value: 10.08, source: 'ma250-v1' },
        structural_evidence: { trigger: 'fallback_fractal', status: 'confirmed' },
      }],
    },
  })

  assert.equal(history.futureFunctionGuard, false)
  assert.equal(history.markers[0].lineValue, 10.08)
  assert.equal(history.markers[0].source, 'ma250-v1')
  assert.deepEqual(history.markers[0].conditionEvidence, [{
    key: 'structural_evidence',
    trigger: 'fallback_fractal',
    status: 'confirmed',
  }])
})

test('Kline CLX route keeps explicit asset type and ETF prefix fallback covers 52/53', () => {
  const query = buildKlineClxQuery({ symbol: 'sh520001' }, {
    scopeId: 'scope-etf',
    assetType: 'etf',
    modelKeys: [],
    conditionKeys: [],
    markerMode: 'aggregate',
    workbenchOpen: true,
  })

  assert.equal(query.clxAssetType, 'etf')
  assert.equal(parseKlineClxQuery(query).assetType, 'etf')
  assert.equal(resolveClxAssetType('sh520001'), 'etf')
  assert.equal(resolveClxAssetType('sh530001'), 'etf')
  assert.equal(resolveClxAssetType('sz000001'), 'stock')
  assert.equal(normalizeClxSidebarItem({ symbol: 'sh520001', asset_type: 'etf' }).assetType, 'etf')
})

test('the explicit no-model sentinel stays distinct from S0000 and hides every marker', () => {
  const routeState = parseKlineClxQuery({ clxModels: '__NONE__' })
  const query = buildKlineClxQuery({}, {
    modelKeys: routeState.modelKeys,
    conditionKeys: [],
    markerMode: 'aggregate',
    workbenchOpen: true,
  })

  assert.deepEqual(routeState.modelKeys, ['__NONE__'])
  assert.equal(query.clxModels, '__NONE__')
  assert.deepEqual(filterClxMarkers(markers, { modelKeys: routeState.modelKeys }), [])
  assert.notEqual(query.clxModels, 'S0000')
})
