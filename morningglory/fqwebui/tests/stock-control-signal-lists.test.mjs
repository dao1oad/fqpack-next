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

test('stock-control layout gives more width to stock_pools model signals without horizontal overflow', async () => {
  const content = await readFile(new URL('../src/style/stock-control.styl', import.meta.url), 'utf8')

  assert.match(content, /grid-template-columns minmax\(0, 0\.84fr\) minmax\(0, 1\.32fr\) minmax\(0, 0\.84fr\)/)
  assert.match(content, /grid-template-columns minmax\(0, 0\.9fr\) minmax\(0, 1\.1fr\)/)
  assert.match(content, /\.panel-card[\s\S]*min-width 0/)
  assert.match(content, /\.panel-table[\s\S]*min-width 0/)
  assert.match(content, /border-radius 14px/)
  assert.doesNotMatch(content, /grid-template-columns minmax\(0, 0\.95fr\) minmax\(0, 1\.1fr\) minmax\(0, 0\.95fr\)/)
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
  assert.match(content, /source/)
  assert.match(content, /close/)
  assert.match(content, /stop_loss_price/)
  assert.match(content, /stock-control-ledger stock-control-ledger--model/)
  assert.match(content, /stock-control-ledger__header stock-control-model-ledger__grid/)
  assert.match(content, />\s*信号时间\s*</)
  assert.match(content, />\s*入库时间\s*</)
  assert.match(content, />\s*标的代码\s*</)
  assert.match(content, />\s*标的名称\s*</)
  assert.match(content, />\s*周期\s*</)
  assert.match(content, />\s*分组\s*</)
  assert.match(content, />\s*模型\s*</)
  assert.match(content, />\s*来源\s*</)
  assert.match(content, />\s*触发价\/止损价\/止损%\s*</)
  assert.match(content, /formatPriceSummary\(row\.close, row\.stop_loss_price\)/)
  assert.match(content, /formatDateTime\(row\.datetime\)/)
  assert.match(content, /formatDateTime\(row\.created_at\)/)
  assert.match(content, /stock-control-ledger__cell--time/)
  assert.match(content, /grid-template-columns 72px 72px 56px minmax\(0, 1fr\) 80px 100px 120px 46px 160px/)
  assert.match(content, /size:\s*100/)
  assert.match(content, /:page-sizes="\[100, 200, 500\]"/)
  assert.doesNotMatch(content, /<el-table/)
  assert.doesNotMatch(content, /label="标的"/)
})

test('SignalList component uses the unified stock-control columns and 100-row pagination', async () => {
  const content = await readFile(new URL('../src/views/SignalList.vue', import.meta.url), 'utf8')

  assert.match(content, /stock-control-ledger stock-control-ledger--signal/)
  assert.match(content, /stock-control-ledger__header stock-control-signal-ledger__grid/)
  assert.match(content, />\s*信号时间\s*</)
  assert.match(content, />\s*入库时间\s*</)
  assert.match(content, />\s*标的代码\s*</)
  assert.match(content, />\s*标的名称\s*</)
  assert.match(content, />\s*方向\s*</)
  assert.match(content, />\s*类型\s*</)
  assert.match(content, />\s*触发价\/止损价\/止损%\s*</)
  assert.match(content, /formatDateTime\(row\.fire_time\)/)
  assert.match(content, /formatDateTime\(formatCreatedAt\(row\)\)/)
  assert.match(content, /formatDirection\(row\.position\)/)
  assert.match(content, /formatSignalType\(row\)/)
  assert.match(content, /stock-control-ledger__cell--time/)
  assert.match(content, /grid-template-columns 72px 72px 56px minmax\(0, 0\.52fr\) 40px minmax\(0, 1fr\) 160px/)
  assert.match(content, /formatPriceSummary\(row\.price, row\.stop_lose_price\)/)
  assert.match(content, /size:\s*100/)
  assert.match(content, /:page-sizes="\[100, 200, 500\]"/)
  assert.doesNotMatch(content, /<el-table/)
  assert.doesNotMatch(content, /label="品种"/)
  assert.doesNotMatch(content, /label="分类"/)
})
