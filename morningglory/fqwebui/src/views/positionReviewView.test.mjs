import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const viewPath = new URL('./PositionReview.vue', import.meta.url)
const chartPath = new URL('../components/position-review/PositionReviewChart.vue', import.meta.url)

test('position review view keeps canonical executions and strategy reviews as separate ledgers', async () => {
  const source = await readFile(viewPath, 'utf8')

  assert.match(source, /成交明细（真实成交）/)
  assert.match(source, /:data="selectedDetail\.executions"/)
  assert.match(source, /逐单策略复盘/)
  assert.match(source, /:data="selectedDetail\.reviews"/)
  assert.match(source, /未关联/)
  assert.match(source, /不会为它伪造策略结论/)
})

test('position review view renders unknown expected quantity without a zero delta', async () => {
  const source = await readFile(viewPath, 'utf8')

  assert.match(source, /row\.expectedQuantity !== null/)
  assert.match(source, /证据不足/)
  assert.match(source, /isFiniteNonZero\(row\.quantityDelta\)/)
  assert.doesNotMatch(source, /row\.quantityDelta !== 0/)
})

test('position review refreshes summary before symbols and requests shared-cache refresh', async () => {
  const source = await readFile(viewPath, 'utf8')

  assert.match(source, /runPositionReviewRefresh/)
  assert.match(source, /refresh: refresh \? 1 : undefined/)
  assert.doesNotMatch(source, /Promise\.all\(\[loadSummary\(\), loadSymbols\(\)\]\)/)
})

test('catalog search status and reset do not trigger a full replay refresh', async () => {
  const source = await readFile(viewPath, 'utf8')
  const filterBlock = source.slice(
    source.indexOf('const applyCatalogFilters'),
    source.indexOf('const resetFilters'),
  )
  const initialLoadBlock = source.slice(
    source.indexOf('const loadInitialData'),
    source.indexOf('const selectSymbol'),
  )

  assert.match(source, /@keyup\.enter="applyCatalogFilters"/)
  assert.match(source, /@change="applyCatalogFilters"/)
  assert.match(source, /@click="refreshData"/)
  assert.match(filterBlock, /runPositionReviewCatalogFilter/)
  assert.doesNotMatch(filterBlock, /loadSummary/)
  assert.doesNotMatch(filterBlock, /runPositionReviewRefresh/)
  assert.match(initialLoadBlock, /await loadSummary\(\)/)
  assert.doesNotMatch(initialLoadBlock, /refresh: true/)
})

test('load errors are scoped and a successful symbol switch clears stale detail errors', async () => {
  const source = await readFile(viewPath, 'utf8')

  assert.match(source, /const loadErrors = reactive\(\{\s*summary: '',\s*symbols: '',\s*detail: '',/s)
  assert.match(source, /loading\.detail = true\s*loadErrors\.detail = ''/)
  assert.match(source, /selectedDetail\.value = normalizePositionReviewDetail\(response\)\s*loadErrors\.detail = ''/)
  assert.match(source, /const retryLoadError = async/)
  assert.doesNotMatch(source, /pageError/)
})

test('mobile toolbar clears the desktop flex basis so filters do not create a tall blank area', async () => {
  const source = await readFile(viewPath, 'utf8')
  const mobileBlock = source.slice(source.indexOf('@media (max-width: 960px)'))

  assert.match(
    mobileBlock,
    /\.position-review-filter-actions\s*\{\s*flex:\s*0 0 auto;\s*justify-content:\s*flex-start;\s*width:\s*100%;/s,
  )
})

test('chart initialization waits for a measurable container', async () => {
  const source = await readFile(chartPath, 'utf8')

  assert.match(source, /clientWidth > 0/)
  assert.match(source, /clientHeight > 0/)
  assert.match(source, /if \(!hasRenderableSize\(\)\) return null/)
})

test('data quality alert does not collapse inside the fixed-height workbench', async () => {
  const source = await readFile(viewPath, 'utf8')

  assert.match(source, /\.position-review-quality-alert\s*\{\s*flex:\s*0 0 auto;/s)
})
