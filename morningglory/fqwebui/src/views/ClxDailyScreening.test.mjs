import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('CLX page keeps partial status distinct from final and renders both partitions', async () => {
  const source = await readFile(new URL('./ClxDailyScreening.vue', import.meta.url), 'utf8')

  assert.match(source, /activeScope\?\.isPartial/)
  assert.match(source, /当前是部分结果/)
  assert.match(source, /stockPartitionStatus/)
  assert.match(source, /etfPartitionStatus/)
  assert.match(source, /getLatestBatch\(\{ includePartial: false \}, \{ signal: token\.signal \}\)/)
  assert.match(source, /getBatches\(\{ includePartial: true \}, \{ signal: token\.signal \}\)/)
  assert.match(source, /observedScopes\.value = normalizeClxScopes\(batchesPayload\)/)
  assert.match(source, /getBatchSummary\(\s*initialRoute\.scopeId/)
  assert.match(source, /mergeClxScopes\(batchesPayload, requestedScopePayload, latestFinalPayload\)/)
  assert.match(source, /requested\?\.scopeId \|\| finalScope\?\.scopeId \|\| scopes\.value\.find\(\(item\) => item\.isFinal\)\?\.scopeId \|\| ''/)
  assert.doesNotMatch(source, /scopes\.value\[0\]\?\.scopeId/)
  assert.match(source, /selectObservedPartial/)
  assert.match(source, /routeScopeRequests\.begin\(requestKey\)/)
  assert.match(source, /selectRouteScope\(routeState\.scopeId\)/)
  assert.match(source, /loadScopeData\(\{ prefetchedSummary, navigationId \}\)/)
})

test('CLX page uses backend summary, statistics, result and evidence contracts', async () => {
  const source = await readFile(new URL('./ClxDailyScreening.vue', import.meta.url), 'utf8')

  assert.match(source, /queryBatchResults/)
  assert.match(source, /getBatchSummary/)
  assert.match(source, /getBatchStatistics/)
  assert.match(source, /v-if="activeScope\?\.isFinal" label="统计"/)
  assert.match(source, /scopeIsFinal\s*\?\s*clxDailySelectionApi\.getBatchStatistics/)
  assert.match(source, /conditionEvidence/)
  assert.match(source, /distinctModelCount/)
  assert.match(source, /distinctConditionCount/)
  assert.match(source, /value\.hit_symbol_count \?\? value\.hit_count/)
  assert.match(source, /statistics\.modelCooccurrence/)
  assert.match(source, /statistics\.lineRelations/)
  assert.doesNotMatch(source, /queryResult\.value\.rows\.reduce/)
})

test('CLX page isolates scope and detail requests while preserving partial errors', async () => {
  const source = await readFile(new URL('./ClxDailyScreening.vue', import.meta.url), 'utf8')

  assert.match(source, /createClxRequestChannel/)
  assert.match(source, /scopeRequests\.begin\(scopeId\)/)
  assert.match(source, /detailRequests\.begin\(detailKey\)/)
  assert.match(source, /queryResult\.value = emptyQueryResult\(\)/)
  assert.match(source, /Promise\.allSettled/)
  assert.match(source, /getBatchStatistics[\s\S]*catch/)
  assert.match(source, /v-if="activeScope\?\.isPartial"/)
  assert.match(source, /v-if="pageError"/)
  assert.doesNotMatch(source, /v-else-if="pageError"/)
})

test('CLX page gives each scope navigation exclusive ownership of async responses', async () => {
  const source = await readFile(new URL('./ClxDailyScreening.vue', import.meta.url), 'utf8')

  assert.match(source, /let navigationEpoch = 0/)
  assert.match(source, /const beginScopeNavigation = \(\{ abortBootstrap = true \} = \{\}\) => \{/)
  assert.match(source, /window\.clearTimeout\(queryTimer\)[\s\S]*routeScopeRequests\.abort\(\)[\s\S]*scopeRequests\.abort\(\)[\s\S]*resultRequests\.abort\(\)[\s\S]*detailRequests\.abort\(\)/)
  assert.match(source, /navigationEpoch === activeNavigationId/)
  assert.match(source, /const navigationId = beginScopeNavigation\(\)[\s\S]*selectedScopeId\.value = scopeId[\s\S]*getBatchSummary/)
  assert.match(source, /if \(loading\.bootstrap\) \{[\s\S]*await loadBootstrap\(\)/)
})

test('CLX result navigation carries row asset type into the Kline route', async () => {
  const source = await readFile(new URL('./ClxDailyScreening.vue', import.meta.url), 'utf8')

  assert.match(source, /@click\.stop="openRowInKline\(row\)"/)
  assert.match(source, /const openSelectedInKline = \(\) => openRowInKline\(selectedRow\.value\)/)
  assert.match(source, /path:\s*'\/kline-slim'/)
  assert.match(source, /symbol:\s*row\.symbol/)
  assert.match(source, /clxAssetType:\s*row\.assetType \|\| 'stock'/)
  assert.match(source, /clxWorkbench:\s*'1'/)
})
