import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const modelSignalListSource = readFileSync(new URL('./ModelSignalList.vue', import.meta.url), 'utf8')

test('ModelSignalList widens price column and keeps 3-decimal aligned price labels', () => {
  assert.match(modelSignalListSource, /<el-table-column label="价格" width="160">/)
  assert.match(modelSignalListSource, /class="price-cell-line">触发价: \{\{ formatPrice\(row\.close\) \}\}<\/div>/)
  assert.match(modelSignalListSource, /class="price-cell-line">止损价: \{\{ formatPrice\(row\.stop_loss_price\) \}\}<\/div>/)
  assert.match(modelSignalListSource, /return parsed\.toFixed\(3\)/)
  assert.match(modelSignalListSource, /\.price-cell-line \{\s*white-space: nowrap/s)
  assert.doesNotMatch(modelSignalListSource, />close: \{\{ formatPrice\(row\.close\) \}\}</)
  assert.doesNotMatch(modelSignalListSource, />stop: \{\{ formatPrice\(row\.stop_loss_price\) \}\}</)
})
