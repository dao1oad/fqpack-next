import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

test('StockControl uses must_pools title and includes stock_pools model signals section', async () => {
  const content = await readFile(new URL('../src/views/StockControl.vue', import.meta.url), 'utf8')

  assert.match(content, /must_pools买入信号/)
  assert.match(content, /stock_pools模型信号/)
  assert.match(content, /持仓股信号[\s\S]*stock_pools模型信号[\s\S]*must_pools买入信号/)
  assert.doesNotMatch(content, /持仓监控/)
  assert.doesNotMatch(content, /买入监控/)
  assert.doesNotMatch(content, /模型监控/)
  assert.doesNotMatch(content, /<StockPositionList/)
  assert.match(content, /stock-control-shell/)
  assert.match(content, /stock-control-grid/)
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
  assert.match(content, /close/)
  assert.match(content, /stop_loss_price/)
  assert.match(content, /label="信号时间"/)
  assert.match(content, /label="入库时间"/)
  assert.match(content, /label="标的代码"/)
  assert.match(content, /label="标的名称"/)
  assert.match(content, /label="价格"/)
  assert.match(content, /formatPriceSummary\(row\.close, row\.stop_loss_price\)/)
  assert.match(content, /size:\s*100/)
  assert.match(content, /:page-sizes="\[100, 200, 500\]"/)
  assert.doesNotMatch(content, /label="标的"/)
  assert.doesNotMatch(content, /label="周期"/)
  assert.doesNotMatch(content, /label="模型"/)
  assert.doesNotMatch(content, /label="来源"/)
})

test('SignalList component uses the unified stock-control columns and 100-row pagination', async () => {
  const content = await readFile(new URL('../src/views/SignalList.vue', import.meta.url), 'utf8')

  assert.match(content, /label="信号时间"/)
  assert.match(content, /label="入库时间"/)
  assert.match(content, /label="标的代码"/)
  assert.match(content, /label="标的名称"/)
  assert.match(content, /label="价格"/)
  assert.match(content, /formatPriceSummary\(row\.price, row\.stop_lose_price\)/)
  assert.match(content, /size:\s*100/)
  assert.match(content, /:page-sizes="\[100, 200, 500\]"/)
  assert.doesNotMatch(content, /label="品种"/)
  assert.doesNotMatch(content, /label="买\/卖"/)
  assert.doesNotMatch(content, /label="备注"/)
  assert.doesNotMatch(content, /label="分类"/)
})
