import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  applyClxPanelScopeDate,
  appendClxPanelRows,
  assertClxTdxSelectionProgress,
  buildClxPanelRequestKey,
  buildClxTdxBasketKey,
  buildClxTdxSelectionPagePayload,
  buildClxTdxSelectedPayload,
  freezeClxTdxSelectionPayload,
  formatClxTdxImportErrorMessage,
  formatClxTdxImportSuccessMessage,
  isClxTdxBasketEligible,
  isClxTdxImportEnabled,
  isClxTdxSelectAllEnabled,
  isSameClxPanelSymbol,
  mergeClxTdxBasketItems,
  readClxTdxBasket,
  resolveClxPanelAutoSelection,
  resolveClxPanelRouteEntry,
  toggleClxTdxBasketItem,
  writeClxTdxBasket,
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

test('TDX basket uses asset_type:symbol identity and stable union/toggle semantics', () => {
  const stock = { assetType: 'stock', symbol: 'sz000001' }
  const etf = { asset_type: 'etf', symbol: '510050' }

  assert.equal(buildClxTdxBasketKey(stock), 'stock:sz000001')
  assert.deepEqual(
    mergeClxTdxBasketItems([stock], [stock, etf]),
    [
      { asset_type: 'etf', symbol: '510050' },
      { asset_type: 'stock', symbol: 'sz000001' },
    ],
  )
  assert.deepEqual(toggleClxTdxBasketItem([stock], stock), [])
  assert.deepEqual(
    toggleClxTdxBasketItem([stock], etf),
    [
      { asset_type: 'etf', symbol: '510050' },
      { asset_type: 'stock', symbol: 'sz000001' },
    ],
  )
})

test('TDX baskets persist and restore independently for each batch in session storage', () => {
  const values = new Map()
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }

  writeClxTdxBasket(storage, 'batch-a', [{ assetType: 'stock', symbol: '000001' }])
  writeClxTdxBasket(storage, 'batch-b', [{ assetType: 'etf', symbol: '510050' }])

  assert.deepEqual(readClxTdxBasket(storage, 'batch-a'), [
    { asset_type: 'stock', symbol: '000001' },
  ])
  assert.deepEqual(readClxTdxBasket(storage, 'batch-b'), [
    { asset_type: 'etf', symbol: '510050' },
  ])
  assert.deepEqual(readClxTdxBasket(storage, 'missing'), [])
})

test('TDX select-all freezes all filters and pages the existing result API at limit 200', () => {
  const source = {
    scope_id: 'scope-a',
    q: '银行',
    asset_types: ['stock', 'etf'],
    model_keys: ['S0003'],
    condition_keys: ['entrypoint_1'],
    directions: ['buy'],
    min_model_count: 3,
    line_flags: { above_ma250: 'yes' },
    sort: 'distinct_model_count_desc,symbol_asc',
    cursor: 'old',
    limit: 100,
  }
  const frozen = freezeClxTdxSelectionPayload(source)
  source.asset_types.push('changed')
  source.line_flags.above_ma250 = 'no'

  assert.deepEqual(
    buildClxTdxSelectionPagePayload(frozen, '200'),
    {
      scope_id: 'scope-a',
      q: '银行',
      asset_types: ['stock', 'etf'],
      model_keys: ['S0003'],
      condition_keys: ['entrypoint_1'],
      directions: ['buy'],
      min_model_count: 3,
      line_flags: { above_ma250: 'yes' },
      sort: 'distinct_model_count_desc,symbol_asc',
      cursor: '200',
      limit: 200,
    },
  )
})

test('TDX select-all rejects pagination drift and incomplete deduplicated results', () => {
  assert.equal(assertClxTdxSelectionProgress({
    expectedTotal: 205,
    responseTotal: 205,
    selectedCount: 200,
    nextCursor: '200',
  }), true)
  assert.equal(assertClxTdxSelectionProgress({
    expectedTotal: 205,
    responseTotal: 205,
    selectedCount: 205,
    nextCursor: '',
  }), true)

  assert.throws(
    () => assertClxTdxSelectionProgress({
      expectedTotal: 205,
      responseTotal: 206,
      selectedCount: 200,
      nextCursor: '200',
    }),
    /总数在分页期间发生变化/,
  )
  assert.throws(
    () => assertClxTdxSelectionProgress({
      expectedTotal: 205,
      responseTotal: 205,
      selectedCount: 200,
      nextCursor: '',
    }),
    /分页提前结束/,
  )
  assert.throws(
    () => assertClxTdxSelectionProgress({
      expectedTotal: 205,
      responseTotal: 205,
      selectedCount: 204,
      nextCursor: '',
    }),
    /分页提前结束/,
  )
})

test('TDX actions require a final published dual-complete batch while empty filters only disable select-all', () => {
  const ready = {
    isFinal: true,
    releaseStatus: 'final',
    publicationLifecycleStatus: 'published',
    partitions: {
      stock: { isComplete: true },
      etf: { isComplete: true },
    },
  }
  const selectAllState = { scope: ready, hasLoaded: true, total: 923, loading: {}, pageError: '' }

  assert.equal(isClxTdxBasketEligible(ready), true)
  assert.equal(isClxTdxSelectAllEnabled(selectAllState), true)
  assert.equal(isClxTdxSelectAllEnabled({ ...selectAllState, total: 0 }), false)
  assert.equal(isClxTdxSelectAllEnabled({ ...selectAllState, loading: { selectAll: true } }), false)
  assert.equal(isClxTdxImportEnabled({ scope: ready, basketCount: 1, loading: { results: true } }), true)
  assert.equal(isClxTdxImportEnabled({ scope: ready, basketCount: 0, loading: {} }), false)
  assert.equal(isClxTdxImportEnabled({ scope: ready, basketCount: 1, loading: { importToTdx: true } }), false)
  assert.equal(isClxTdxBasketEligible({ ...ready, isFinal: false }), false)
  assert.equal(isClxTdxBasketEligible({ ...ready, publicationLifecycleStatus: 'pending' }), false)
})

test('TDX selected import payload contains only normalized basket items', () => {
  assert.deepEqual(
    buildClxTdxSelectedPayload([
      { assetType: 'stock', symbol: '000001', name: '平安银行' },
      { asset_type: 'etf', symbol: '510050', q: 'ignored' },
    ]),
    {
      items: [
        { asset_type: 'etf', symbol: '510050' },
        { asset_type: 'stock', symbol: '000001' },
      ],
    },
  )
})

test('TDX import messages expose overwrite count and preserve-old failure contract', () => {
  assert.equal(
    formatClxTdxImportSuccessMessage(923),
    '已导入通达信分组 clx_18，共 923 只（已覆盖原分组）',
  )
  assert.equal(
    formatClxTdxImportErrorMessage('磁盘写入失败'),
    '磁盘写入失败；旧分组已保留',
  )
  assert.equal(
    formatClxTdxImportErrorMessage('导入失败；旧分组已保留'),
    '导入失败；旧分组已保留',
  )
})

test('panel renders one two-stage basket action before the result heading', async () => {
  const source = await readFile(new URL('./ClxSelectionPanel.vue', import.meta.url), 'utf8')
  const buttonIndex = source.indexOf('全选当前筛选结果')
  const resultsHeadIndex = source.indexOf('clx-selection-panel__results-head')

  assert.ok(buttonIndex > 0)
  assert.ok(resultsHeadIndex > buttonIndex)
  assert.match(source, /待导入 \{\{ basketCount \}\} 只/)
  assert.match(source, /导入通达信（\{\{ basketCount \}\}）/)
  assert.match(source, /清空已选/)
  assert.match(source, /:disabled="!canSelectAllToBasket"/)
  assert.match(source, /:disabled="!canImportToTdx"/)
  assert.match(source, /:loading="loading\.importToTdx"/)
  assert.match(source, /syncSelectedBatchResultsToTdx/)
  assert.match(source, /window\.sessionStorage/)
  assert.match(source, /const expectedTotal = Number\(total\.value\)/)
  assert.match(source, /assertClxTdxSelectionProgress/)
  assert.match(source, /selectAllLoadingOwner === token\.id/)
  assert.match(source, /if \(scopeId !== previousScopeId\) cancelSelectAll\(\)/)
  assert.match(source, /@click\.stop="toggleBasketRow\(row\)"/)
})

test('each result row exposes sibling navigation and basket buttons without nesting', async () => {
  const source = await readFile(new URL('./ClxSelectionPanel.vue', import.meta.url), 'utf8')
  const rowItem = source.match(/<li[\s\S]*?v-for="row in rows"[\s\S]*?<\/li>/)?.[0] || ''
  const navigationEnd = rowItem.indexOf('</button>')
  const basketButton = rowItem.indexOf('加入通达信')

  assert.ok(navigationEnd > 0)
  assert.ok(basketButton > navigationEnd)
  assert.match(rowItem, /:aria-pressed="isRowInBasket\(row\)"/)
  assert.match(rowItem, /isRowInBasket\(row\) \? '已加入' : '加入通达信'/)
  assert.doesNotMatch(rowItem.slice(0, navigationEnd), /加入通达信|已加入/)
})

test('panel keeps stable rows during filter refresh and exposes accessible dark controls', async () => {
  const source = await readFile(new URL('./ClxSelectionPanel.vue', import.meta.url), 'utf8')

  assert.match(source, /每日选股 · 结果筛选/)
  assert.match(source, /改变标的集合/)
  assert.match(source, /popper-class="clx-market-dark-popper"/)
  assert.match(source, /<ul[\s\S]*aria-label="CLX 标的列表"/)
  assert.match(source, /<li[\s\S]*v-for="row in rows"/)
  assert.match(source, /\(loading\.bootstrap \|\| loading\.results\) && rows\.length/)
  assert.match(source, /preserveExisting/)
  assert.match(source, /retryResults/)
  assert.match(source, /loadBootstrap\(\{ preserveExisting: true \}\)/)
  assert.match(source, /preserveScopeResults/)
  assert.doesNotMatch(
    source,
    /const scheduleResultReload = \(\) => \{[\s\S]*?clearResults\(\)[\s\S]*?window\.setTimeout/,
  )
})
