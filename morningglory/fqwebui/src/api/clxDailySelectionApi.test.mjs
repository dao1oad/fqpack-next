import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('CLX API uses fixed batch result path and raw history camelCase contract', async () => {
  const source = await readFile(new URL('./clxDailySelectionApi.js', import.meta.url), 'utf8')

  assert.match(source, /batches\/\$\{encodePath\(batchId\)\}\/results`/)
  assert.match(source, /assetType,/)
  assert.match(source, /conditionKeys:/)
  assert.match(source, /includeRaw: includeRaw \? 1 : 0/)
  assert.match(source, /batches\/\$\{encodePath\(batchId\)\}\/results\/sync-selected-to-tdx`/)
})

test('Kline requests unfiltered raw history and passes an abort signal', async () => {
  const source = await readFile(new URL('../views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(source, /modelKeys: \[\]/)
  assert.match(source, /conditionKeys: \[\]/)
  assert.match(source, /includeRaw: true/)
  assert.match(source, /\{ signal: abortController\.signal \}/)
  assert.match(source, /futureFunctionGuard === true/)
  assert.match(source, /futureFunctionGuard !== true/)
})

test('CLX batch and detail API methods forward AbortController config', async () => {
  const source = await readFile(new URL('./clxDailySelectionApi.js', import.meta.url), 'utf8')

  assert.match(source, /getBatchSummary \(batchId, config = \{\}\)/)
  assert.match(source, /queryBatchResults \(batchId, data, config = \{\}\)/)
  assert.match(source, /getBatchResultDetail \(batchId, assetType, symbol, config = \{\}\)/)
  assert.match(source, /getBatchStatistics \(batchId, config = \{\}\)/)
  assert.match(source, /\.\.\.config/)
})
