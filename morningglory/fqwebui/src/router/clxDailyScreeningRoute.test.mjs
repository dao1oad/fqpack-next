import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  getHeaderNavTarget,
  resolveRouteMetaTitle,
} from './pageMeta.mjs'
import { buildClxDailyScreeningRedirect } from './clxDailyScreeningRedirect.mjs'

test('CLX daily screening navigation opens the unified Kline workbench', () => {
  assert.deepEqual(getHeaderNavTarget('clxDailyScreening'), {
    label: '每日选股',
    path: '/kline-slim',
    query: {
      clxScreening: '1',
      clxWorkbench: '1',
      period: '1d',
      tabTitle: '每日选股',
    },
  })
  assert.equal(resolveRouteMetaTitle('clx-daily-screening'), '每日选股')
})

test('legacy CLX daily screening route redirects instead of loading a second page', async () => {
  const source = await readFile(new URL('./index.js', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /import\('\.\.\/views\/ClxDailyScreening\.vue'\)/)
  assert.match(source, /path: '\/clx-daily-screening',[\s\S]*name: 'clx-daily-screening',[\s\S]*redirect: buildClxDailyScreeningRedirect/)
})

test('legacy redirect migrates every screening field and never re-emits aliases', () => {
  const redirected = buildClxDailyScreeningRedirect({
    query: {
      scope_id: 'scope-20260731',
      q: '半导体',
      asset_types: 'stock,etf',
      clxModels: 'S1,S0003',
      clxConditions: 'breakout,fallback_fractal',
      directions: 'buy,sell',
      min_model_count: '2',
      above_chanlun_line: 'yes',
      line_flags: '{"above_ma250":"no","above_reference_line":"unknown"}',
      asset_type: 'etf',
      symbol: 'sz159577',
      endDate: '2026-07-31',
      tabTitle: '旧收藏',
      period: '1w',
    },
    hash: '#signals',
  })

  assert.equal(redirected.path, '/kline-slim')
  assert.equal(redirected.hash, '#signals')
  assert.deepEqual(redirected.query, {
    symbol: 'sz159577',
    endDate: '2026-07-31',
    tabTitle: '旧收藏',
    period: '1w',
    clxScreening: '1',
    clxScope: 'scope-20260731',
    clxFilterQ: '半导体',
    clxFilterAssets: 'stock,etf',
    clxFilterModels: 'S0001,S0003',
    clxFilterConditions: 'breakout,fallback_fractal',
    clxFilterDirections: 'buy,sell',
    clxFilterMinModels: '2',
    clxFilterAboveChanlun: 'yes',
    clxFilterAboveMa250: 'no',
    clxFilterAboveReference: 'unknown',
    clxAssetType: 'etf',
    clxWorkbench: '1',
  })
  ;[
    'scope_id', 'asset_type', 'asset_types', 'clxAssets', 'model_keys',
    'condition_keys', 'directions', 'clxDirections', 'min_model_count',
    'clxMinModels', 'q', 'line_flags', 'above_chanlun_line', 'above_ma250',
    'above_reference_line', 'clxModels', 'clxConditions',
  ].forEach((key) => assert.equal(Object.hasOwn(redirected.query, key), false, key))

  assert.equal(buildClxDailyScreeningRedirect({ query: {} }).query.period, '1d')
})
