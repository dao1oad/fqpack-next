import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CLX_LEGACY_QUERY_KEYS,
  aggregateClxMarkersByBar,
  anchorClxMarkersToBars,
  buildKlineClxQuery,
  buildKlineClxScreeningQuery,
  filterClxMarkers,
  normalizeClxSignalHistory,
  parseKlineClxQuery,
  parseKlineClxScreeningQuery,
  resolveClxAssetType,
} from './kline-slim-clx.mjs'

const markers = [
  { id: 'a', modelKey: 'S0003', conditionKey: 'buy', triggerDate: '2026-07-30', direction: 'buy' },
  { id: 'b', modelKey: 'S0007', conditionKey: 'buy', triggerDate: '2026-07-30', direction: 'buy' },
  { id: 'c', modelKey: 'S0009', conditionKey: 'sell', triggerDate: '2026-07-31', direction: 'sell' },
]

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
  assert.equal(parseKlineClxQuery({}).workbenchOpen, false)
  assert.equal(parseKlineClxQuery({ clxWorkbench: '1' }).workbenchOpen, true)
  assert.equal(parseKlineClxQuery(query).assetType, 'etf')
  assert.equal(resolveClxAssetType('sh520001'), 'etf')
  assert.equal(resolveClxAssetType('sh530001'), 'etf')
  assert.equal(resolveClxAssetType('sz000001'), 'stock')
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

test('screening filters and signal marker visibility use independent URL namespaces', () => {
  const query = {
    clxScreening: '1',
    clxScope: 'scope-20260731',
    clxFilterModels: 'S0001,S0003',
    clxFilterConditions: 'breakout',
    clxModels: 'S0007',
    clxConditions: 'fallback_fractal',
  }

  assert.deepEqual(parseKlineClxScreeningQuery(query).modelKeys, ['S0001', 'S0003'])
  assert.deepEqual(parseKlineClxScreeningQuery(query).conditionKeys, ['breakout'])
  assert.deepEqual(parseKlineClxQuery(query).modelKeys, ['S0007'])
  assert.deepEqual(parseKlineClxQuery(query).conditionKeys, ['fallback_fractal'])

  const screeningQuery = buildKlineClxScreeningQuery(query, {
    screeningOpen: true,
    scopeId: 'scope-20260731',
    modelKeys: ['S0009'],
    conditionKeys: ['trend'],
    lineFlags: {},
  })
  assert.equal(screeningQuery.clxFilterModels, 'S0009')
  assert.equal(screeningQuery.clxFilterConditions, 'trend')
  assert.equal(screeningQuery.clxModels, 'S0007')
  assert.equal(screeningQuery.clxConditions, 'fallback_fractal')
})

test('alias-only Kline signal state survives the screening writer without becoming left filters', () => {
  const legacy = {
    clxScreening: '1',
    clxWorkbench: '1',
    asset_type: 'etf',
    model_keys: 'S7',
    condition_keys: 'fallback_fractal',
  }
  const screeningState = parseKlineClxScreeningQuery(legacy)
  const query = buildKlineClxScreeningQuery(legacy, screeningState)

  assert.deepEqual(screeningState.assetTypes, [])
  assert.deepEqual(screeningState.modelKeys, [])
  assert.deepEqual(screeningState.conditionKeys, [])
  assert.deepEqual(parseKlineClxQuery(query), {
    scopeId: '',
    assetType: 'etf',
    modelKeys: ['S0007'],
    conditionKeys: ['fallback_fractal'],
    markerMode: 'aggregate',
    workbenchOpen: true,
  })
  assert.equal(Object.hasOwn(query, 'asset_type'), false)
  assert.equal(Object.hasOwn(query, 'model_keys'), false)
  assert.equal(Object.hasOwn(query, 'condition_keys'), false)
})

test('screening query round-trips canonical filters and removes every legacy alias', () => {
  const legacy = {
    scope_id: 'legacy-scope',
    asset_type: 'etf',
    asset_types: 'stock,etf',
    clxAssets: 'stock',
    model_keys: 'S1',
    condition_keys: 'legacy-condition',
    directions: 'buy',
    clxDirections: 'sell',
    min_model_count: '3',
    clxMinModels: '4',
    q: 'legacy query',
    line_flags: '{"above_ma250":"no"}',
    above_chanlun_line: 'yes',
    above_ma250: 'no',
    above_reference_line: 'unknown',
    clxModels: 'S0017',
    clxConditions: 'visible-marker',
  }
  const query = buildKlineClxScreeningQuery(legacy, {
    screeningOpen: true,
    scopeId: 'canonical-scope',
    q: '中证',
    assetTypes: ['stock', 'etf', 'stock'],
    modelKeys: ['s2'],
    conditionKeys: ['breakout'],
    directions: ['BUY'],
    minModelCount: 2,
    lineFlags: {
      above_chanlun_line: 'yes',
      above_ma250: 'no',
      above_reference_line: 'unknown',
    },
  })

  assert.deepEqual(parseKlineClxScreeningQuery(query), {
    screeningOpen: true,
    scopeId: 'canonical-scope',
    q: '中证',
    assetTypes: ['stock', 'etf'],
    modelKeys: ['S0002'],
    conditionKeys: ['breakout'],
    directions: ['buy'],
    minModelCount: 2,
    lineFlags: {
      above_chanlun_line: 'yes',
      above_ma250: 'no',
      above_reference_line: 'unknown',
    },
  })
  assert.equal(query.clxModels, 'S0017')
  assert.equal(query.clxConditions, 'visible-marker')
  ;[
    'scope_id', 'asset_type', 'asset_types', 'clxAssets', 'model_keys',
    'condition_keys', 'directions', 'clxDirections', 'min_model_count',
    'clxMinModels', 'q', 'line_flags', 'above_chanlun_line', 'above_ma250',
    'above_reference_line',
  ].forEach((key) => assert.equal(Object.hasOwn(query, key), false, key))
})

test('signal query writer consumes aliases once without letting them rebound', () => {
  const query = buildKlineClxQuery({
    scope_id: 'legacy-scope',
    asset_type: 'stock',
    model_keys: 'S0001',
    condition_keys: 'legacy-condition',
    q: 'legacy query',
    clxFilterModels: 'S0003',
  }, {
    scopeId: 'canonical-scope',
    assetType: 'etf',
    modelKeys: ['S0007'],
    conditionKeys: ['visible-marker'],
    markerMode: 'aggregate',
    workbenchOpen: true,
  })

  assert.equal(query.clxScope, 'canonical-scope')
  assert.equal(query.clxAssetType, 'etf')
  assert.equal(query.clxModels, 'S0007')
  assert.equal(query.clxConditions, 'visible-marker')
  assert.equal(query.clxFilterModels, 'S0003')
  assert.equal(query.clxFilterQ, 'legacy query')
  assert.equal(Object.hasOwn(query, 'scope_id'), false)
  assert.equal(Object.hasOwn(query, 'asset_type'), false)
  assert.equal(Object.hasOwn(query, 'model_keys'), false)
  assert.equal(Object.hasOwn(query, 'condition_keys'), false)
  assert.equal(Object.hasOwn(query, 'q'), false)
})

test('signal query writer preserves unambiguous legacy left filters while promoting ambiguous aliases right', () => {
  const legacy = {
    clxScreening: '1',
    clxWorkbench: '1',
    scope_id: 'legacy-scope',
    q: '银行',
    asset_types: 'stock,etf',
    directions: 'buy',
    min_model_count: '3',
    line_flags: '{"above_ma250":"yes"}',
    asset_type: 'etf',
    model_keys: 'S7',
    condition_keys: 'fallback_fractal',
  }
  const query = buildKlineClxQuery(legacy, parseKlineClxQuery(legacy))

  assert.equal(query.clxScope, 'legacy-scope')
  assert.equal(query.clxFilterQ, '银行')
  assert.equal(query.clxFilterAssets, 'stock,etf')
  assert.equal(query.clxFilterDirections, 'buy')
  assert.equal(query.clxFilterMinModels, '3')
  assert.equal(query.clxFilterAboveMa250, 'yes')
  assert.equal(query.clxAssetType, 'etf')
  assert.equal(query.clxModels, 'S0007')
  assert.equal(query.clxConditions, 'fallback_fractal')
  CLX_LEGACY_QUERY_KEYS.forEach((key) => assert.equal(Object.hasOwn(query, key), false, key))
})
