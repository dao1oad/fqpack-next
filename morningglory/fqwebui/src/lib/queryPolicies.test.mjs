import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { QueryClient } from '@tanstack/vue-query'

const currentDir = path.dirname(fileURLToPath(import.meta.url))
const srcDir = path.dirname(currentDir)

async function importModule(relativePath) {
  try {
    return await import(new URL(relativePath, import.meta.url))
  } catch (error) {
    assert.fail(`expected ${relativePath} to exist and be importable: ${error.message}`)
  }
}

async function readSource(...segments) {
  return readFile(path.join(srcDir, ...segments), 'utf8')
}

test('shared query client exposes unified defaults for stale time, retry, and refetch behavior', async () => {
  const queryClientModule = await importModule('./queryClient.mjs')

  assert.equal(typeof queryClientModule.createQueryClient, 'function')
  assert.ok(queryClientModule.queryClient instanceof QueryClient)
  assert.equal(typeof queryClientModule.QUERY_CLIENT_DEFAULT_OPTIONS, 'object')

  const defaults = queryClientModule.queryClient.getDefaultOptions().queries
  assert.equal(defaults.staleTime, queryClientModule.QUERY_CLIENT_DEFAULT_OPTIONS.queries.staleTime)
  assert.equal(defaults.retry, queryClientModule.QUERY_CLIENT_DEFAULT_OPTIONS.queries.retry)
  assert.equal(defaults.refetchOnWindowFocus, queryClientModule.QUERY_CLIENT_DEFAULT_OPTIONS.queries.refetchOnWindowFocus)
  assert.equal(defaults.refetchOnReconnect, queryClientModule.QUERY_CLIENT_DEFAULT_OPTIONS.queries.refetchOnReconnect)
})

test('named query policies provide the shared 10s, 30s, and 10min refresh cadences', async () => {
  const queryPoliciesModule = await importModule('./queryPolicies.mjs')

  assert.equal(queryPoliciesModule.pollingFast.refetchInterval, 10000)
  assert.equal(queryPoliciesModule.pollingNormal.refetchInterval, 30000)
  assert.equal(queryPoliciesModule.pollingSlow.refetchInterval, 600000)
  assert.equal(queryPoliciesModule.staticLike.refetchInterval ?? false, false)
  assert.equal(queryPoliciesModule.pollingFast.staleTime, queryPoliciesModule.pollingNormal.staleTime)
  assert.equal(queryPoliciesModule.pollingNormal.staleTime, queryPoliciesModule.pollingSlow.staleTime)
  assert.equal(queryPoliciesModule.pollingSlow.staleTime, queryPoliciesModule.staticLike.staleTime)
})

test('main.js registers VueQueryPlugin with the shared queryClient', async () => {
  const content = await readSource('main.js')

  assert.match(content, /import\s+\{\s*queryClient\s*\}\s+from\s+'\.\/lib\/queryClient\.mjs'/)
  assert.match(content, /\.use\(VueQueryPlugin,\s*\{\s*queryClient\s*\}\)/)
})

test('query pages use named policies instead of staleTime and refetch magic numbers', async () => {
  const expectedPoliciesByFile = [
    ['views/SignalList.vue', 'pollingNormal'],
    ['views/ModelSignalList.vue', 'pollingNormal'],
    ['views/StockPositionList.vue', 'pollingNormal'],
    ['views/js/kline-big.js', 'pollingFast'],
    ['views/js/multi-period.js', 'pollingFast'],
    ['components/StockPools.vue', 'pollingSlow'],
    ['components/StockMustPools.vue', 'pollingSlow'],
    ['components/StockCjsd.vue', 'pollingSlow']
  ]

  for (const [filePath, expectedPolicy] of expectedPoliciesByFile) {
    const content = await readSource(...filePath.split('/'))
    assert.match(content, /queryPolicies\.mjs/)
    assert.match(content, new RegExp(`\\.\\.\\.${expectedPolicy}`))
    assert.doesNotMatch(content, /refetchInterval:\s*(10000|30000|600000)/)
    assert.doesNotMatch(content, /staleTime:\s*5000/)
  }
})
