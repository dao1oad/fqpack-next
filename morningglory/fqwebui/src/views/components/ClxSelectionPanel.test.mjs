import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  applyClxPanelScopeDate,
  appendClxPanelRows,
  buildClxPanelRequestKey,
  isSameClxPanelSymbol,
  resolveClxPanelAutoSelection,
  resolveClxPanelRouteEntry,
} from './clxSelectionPanel.mjs'

const request = (overrides = {}) => buildClxPanelRequestKey({
  phase: 'results',
  scopeId: 'scope-a',
  payload: {
    q: '银行',
    asset_types: ['stock'],
    model_keys: ['S0003'],
    condition_keys: ['buy'],
    directions: ['buy'],
    line_flags: { above_ma250: 'yes' },
    min_model_count: 3,
    cursor: '',
    limit: 100,
    ...overrides,
  },
})

test('request ownership key covers every filter and cursor while ignoring object key order', () => {
  assert.equal(request(), request({ line_flags: { above_ma250: 'yes' } }))
  assert.notEqual(request(), request({ q: '证券' }))
  assert.notEqual(request(), request({ asset_types: ['etf'] }))
  assert.notEqual(request(), request({ model_keys: ['S0004'] }))
  assert.notEqual(request(), request({ condition_keys: ['sell'] }))
  assert.notEqual(request(), request({ directions: ['sell'] }))
  assert.notEqual(request(), request({ line_flags: { above_ma250: 'no' } }))
  assert.notEqual(request(), request({ min_model_count: 4 }))
  assert.notEqual(request(), request({ cursor: 'next-100' }))
})

test('load-more appends in server order and removes cross-page duplicates', () => {
  const first = { symbol: 'sz000001', assetType: 'stock' }
  const duplicate = { symbol: '000001', assetType: 'stock' }
  const second = { symbol: 'sh510050', assetType: 'etf' }

  assert.deepEqual(appendClxPanelRows([first], [duplicate, second]), [first, second])
  assert.equal(isSameClxPanelSymbol('SZ000001', '000001'), true)
  assert.equal(isSameClxPanelSymbol('sz000001', 'sh510050'), false)
  assert.equal(isSameClxPanelSymbol('sz000001', 'sh000001'), false)
})

test('scope date hydration fills missing dates, preserves manual dates and forces a new scope date', () => {
  assert.deepEqual(
    applyClxPanelScopeDate({ symbol: '159577' }, { tradeDate: '2026-07-31' }),
    { symbol: '159577', endDate: '2026-07-31' },
  )
  assert.deepEqual(
    applyClxPanelScopeDate(
      { symbol: '159577', endDate: '2026-07-30' },
      { tradeDate: '2026-07-31' },
    ),
    { symbol: '159577', endDate: '2026-07-30' },
  )
  assert.deepEqual(
    applyClxPanelScopeDate(
      { symbol: '159577', endDate: '2026-07-30' },
      { tradeDate: '2026-07-31', force: true },
    ),
    { symbol: '159577', endDate: '2026-07-31' },
  )
})

test('automatic first-row selection belongs only to the current non-append request without a symbol', () => {
  const row = { symbol: 'sz000001' }
  const key = request()
  const input = {
    rows: [row],
    requestKey: key,
    currentRequestKey: key,
  }

  assert.equal(resolveClxPanelAutoSelection(input), row)
  assert.equal(resolveClxPanelAutoSelection({ ...input, append: true }), null)
  assert.equal(resolveClxPanelAutoSelection({ ...input, activeSymbol: 'sh510050' }), null)
  assert.equal(resolveClxPanelAutoSelection({ ...input, currentRequestKey: request({ q: '证券' }) }), null)
  assert.equal(resolveClxPanelAutoSelection({ ...input, selectedRequestKey: key }), null)
})

test('same-page 每日选股 re-entry bootstraps the default scope and starts a fresh first-row selection', () => {
  const entry = resolveClxPanelRouteEntry(
    { screeningOpen: true, scopeId: '' },
    { clxScreening: '1', clxWorkbench: '1', period: '1d' },
  )
  const key = request()
  const row = { symbol: 'sz000001' }

  assert.deepEqual(entry, { shouldBootstrap: true, resetAutoSelection: true })
  assert.equal(resolveClxPanelAutoSelection({
    rows: [row],
    requestKey: key,
    currentRequestKey: key,
    selectedRequestKey: entry.resetAutoSelection ? '' : key,
  }), row)
  assert.deepEqual(
    resolveClxPanelRouteEntry(
      { screeningOpen: true, scopeId: 'scope-a' },
      { symbol: 'sz000001' },
    ),
    { shouldBootstrap: false, resetAutoSelection: false },
  )
})

test('panel owns the compact bootstrap, 100-row cursor and parent selection contracts', async () => {
  const source = await readFile(new URL('./ClxSelectionPanel.vue', import.meta.url), 'utf8')

  assert.match(source, /getBatches\(\s*\{ limit: 30, includePartial: true \}/)
  assert.match(source, /getLatestBatch\(\s*\{ includePartial: false \}/)
  assert.match(source, /getBatchSummary\(\s*requestedState\.scopeId/)
  assert.match(source, /limit: 100/)
  assert.match(source, /appendClxPanelRows/)
  assert.match(source, /resultRequests\.isCurrent/)
  assert.match(source, /emit\('select', \{ row, scope: activeScope\.value \}\)/)
  assert.match(source, /buildKlineClxScreeningQuery/)
  assert.match(source, /syncRoute\(\{ forceScopeDate: true \}\)/)
  assert.match(source, /applyClxPanelScopeDate/)
  assert.match(source, /:aria-current="isActiveRow\(row\) \? 'true' : undefined"/)
})
