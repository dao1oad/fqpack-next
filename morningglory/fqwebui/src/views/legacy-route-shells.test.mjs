import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('legacy pages use viewport shells instead of browser scrolling', async () => {
  const [futures, stockPools, stockCjsd] = await Promise.all([
    readFile(new URL('./FuturesControl.vue', import.meta.url), 'utf8'),
    readFile(new URL('../components/StockPools.vue', import.meta.url), 'utf8'),
    readFile(new URL('../components/StockCjsd.vue', import.meta.url), 'utf8'),
  ])

  assert.match(futures, /future-control-shell/)
  assert.match(futures, /future-control-body/)

  assert.match(stockPools, /stock-pool-shell/)
  assert.match(stockPools, /stock-pool-body/)
  assert.match(stockPools, /stock-pool-panel__table/)

  assert.match(stockCjsd, /stock-cjsd-shell/)
  assert.match(stockCjsd, /stock-cjsd-panel__table/)
})

test('stock pool subviews expose dedicated table scroll containers', async () => {
  const [prePools, mustPools] = await Promise.all([
    readFile(new URL('../components/StockPrePools.vue', import.meta.url), 'utf8'),
    readFile(new URL('../components/StockMustPools.vue', import.meta.url), 'utf8'),
  ])

  assert.match(prePools, /stock-pool-subview__table/)
  assert.match(mustPools, /stock-pool-subview__table/)
})
