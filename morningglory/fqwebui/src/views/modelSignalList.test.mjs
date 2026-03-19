import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const modelSignalListSource = readFileSync(new URL('./ModelSignalList.vue', import.meta.url), 'utf8')

test('ModelSignalList uses the unified stock-control columns and single-line price summary', () => {
  assert.match(modelSignalListSource, /label="信号时间"/)
  assert.match(modelSignalListSource, /label="入库时间"/)
  assert.match(modelSignalListSource, /label="标的代码"/)
  assert.match(modelSignalListSource, /label="标的名称"/)
  assert.match(modelSignalListSource, /label="价格" min-width="268"/)
  assert.match(modelSignalListSource, /formatPriceSummary\(row\.close, row\.stop_loss_price\)/)
  assert.match(modelSignalListSource, /return parsed\.toFixed\(3\)/)
  assert.match(modelSignalListSource, /\.price-summary\s+display inline-block\s+white-space nowrap/s)
  assert.doesNotMatch(modelSignalListSource, /label="标的"/)
  assert.doesNotMatch(modelSignalListSource, /label="周期"/)
  assert.doesNotMatch(modelSignalListSource, /label="模型"/)
  assert.doesNotMatch(modelSignalListSource, /label="来源"/)
})
