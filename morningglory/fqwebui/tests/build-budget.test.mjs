import test from 'node:test'
import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { bundleBudget } from '../vite.config.js'
import { runLockedBuild } from './vite-build-lock.mjs'

const projectDir = new URL('..', import.meta.url)
const projectRootPath = fileURLToPath(new URL('../', import.meta.url))
const isolatedOutDir = '.playwright-vite/build-budget-test'
const retainedAsyncRouteChunks = [
  ['StockControl'],
  ['MultiPeriod'],
  ['KlineBig'],
  ['KlineSlim', 'page-kline-slim'],
  ['StockPools'],
  ['PositionManagement'],
  ['SystemSettings'],
  ['ReconciliationWorkbench'],
]

let builtAssetSizesPromise

const loadBuiltAssetSizes = async () => {
  builtAssetSizesPromise ||= (async () => {
    await runLockedBuild(
      () => ({
        command: process.execPath,
        args: ['./node_modules/vite/bin/vite.js', 'build'],
      }),
      projectRootPath,
      { outDir: isolatedOutDir },
    )

    const assetsDir = new URL(`${isolatedOutDir}/assets/`, projectDir)
    const assetNames = await readdir(assetsDir)
    const assetSizes = new Map()

    for (const assetName of assetNames) {
      if (!assetName.endsWith('.js')) continue
      const assetBuffer = await readFile(new URL(assetName, assetsDir))
      assetSizes.set(assetName, assetBuffer.byteLength)
    }

    return assetSizes
  })()

  return builtAssetSizesPromise
}

test('vite config exposes named bundle budgets for fqwebui heavy chunks', () => {
  assert.equal(typeof bundleBudget, 'object')
  assert.equal(typeof bundleBudget.warningLimitKb, 'number')
  assert.equal(typeof bundleBudget.maxChunkSizeBytes, 'object')

  const expectedChunks = [
    'vendor-echarts',
    'vendor-element-plus',
    'vendor-core',
    'index',
  ]

  for (const chunkName of expectedChunks) {
    assert.equal(typeof bundleBudget.maxChunkSizeBytes[chunkName], 'number')
    assert.ok(bundleBudget.maxChunkSizeBytes[chunkName] > 0)
    assert.ok(bundleBudget.maxChunkSizeBytes[chunkName] <= bundleBudget.warningLimitKb * 1024)
  }
})

test('vite config keeps chunkSizeWarningLimit wired to bundleBudget.warningLimitKb', async () => {
  const viteConfigSource = await readFile(new URL('../vite.config.js', import.meta.url), 'utf8')

  assert.match(viteConfigSource.replace(/\r/g, ''), /chunkSizeWarningLimit:\s*bundleBudget\.warningLimitKb/)
})

test('vite dev proxy defaults to the parallel API surface on 15000', async () => {
  const viteConfigSource = await readFile(new URL('../vite.config.js', import.meta.url), 'utf8')

  assert.match(viteConfigSource.replace(/\r/g, ''), /target:\s*env\.VITE_API_BASE_URL\s*\|\|\s*'http:\/\/127\.0\.0\.1:15000'/)
})

test('isolated Vite build emits async route chunks for the retained workbench pages', async () => {
  const assetSizes = await loadBuiltAssetSizes()
  const assetNames = [...assetSizes.keys()]

  for (const chunkNameAliases of retainedAsyncRouteChunks) {
    assert.ok(
      chunkNameAliases.some((chunkName) => (
        assetNames.some((assetName) => assetName === `${chunkName}.js` || assetName.startsWith(`${chunkName}-`))
      )),
      `Missing async route chunk for ${chunkNameAliases.join(' / ')}`,
    )
  }
})

test('isolated Vite build output stays within the named bundle budgets', async () => {
  const assetSizes = await loadBuiltAssetSizes()

  for (const [chunkName, maxSizeBytes] of Object.entries(bundleBudget.maxChunkSizeBytes)) {
    const builtChunkEntry = [...assetSizes.entries()].find(([assetName]) => (
      assetName === `${chunkName}.js` || assetName.startsWith(`${chunkName}-`)
    ))

    assert.ok(builtChunkEntry, `Missing built chunk for ${chunkName}`)
    assert.ok(
      builtChunkEntry[1] <= maxSizeBytes,
      `${chunkName} exceeded budget: ${builtChunkEntry[1]} > ${maxSizeBytes}`,
    )
  }
})
