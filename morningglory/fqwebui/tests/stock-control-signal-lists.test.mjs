import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

test('StockControl uses must_pools title and includes stock_pools model signals section', async () => {
  const content = await readFile(new URL('../src/views/StockControl.vue', import.meta.url), 'utf8')

  assert.match(content, /must_pools买入信号/)
  assert.match(content, /stock_pools模型信号/)
})

test('stockApi exposes stock model signal list endpoint', async () => {
  const content = await readFile(new URL('../src/api/stockApi.js', import.meta.url), 'utf8')

  assert.match(content, /getStockModelSignalList/)
  assert.match(content, /\/api\/get_stock_model_signal_list/)
})

test('ModelSignalList component exists and renders all realtime model signal fields', async () => {
  const componentUrl = new URL('../src/views/ModelSignalList.vue', import.meta.url)
  assert.equal(existsSync(componentUrl), true)

  const content = await readFile(componentUrl, 'utf8')

  assert.match(content, /datetime/)
  assert.match(content, /created_at/)
  assert.match(content, /code/)
  assert.match(content, /name/)
  assert.match(content, /period/)
  assert.match(content, /model/)
  assert.match(content, /close/)
  assert.match(content, /stop_loss_price/)
  assert.match(content, /source/)
})
