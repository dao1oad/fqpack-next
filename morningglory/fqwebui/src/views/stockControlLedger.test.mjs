import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const stockControlSource = readFileSync(new URL('./StockControl.vue', import.meta.url), 'utf8')
const signalListSource = readFileSync(new URL('./SignalList.vue', import.meta.url), 'utf8')
const modelSignalListSource = readFileSync(new URL('./ModelSignalList.vue', import.meta.url), 'utf8')
const sharedLedgerStyle = readFileSync(new URL('../style/stock-control-ledger.styl', import.meta.url), 'utf8')

test('stock-control ledgers keep headers outside the shared scroll viewport', () => {
  assert.match(signalListSource, /stock-control-ledger__viewport/)
  assert.match(modelSignalListSource, /stock-control-ledger__viewport/)
  assert.match(sharedLedgerStyle, /\.stock-control-ledger\s*[\s\S]*overflow-x auto[\s\S]*overflow-y hidden/)
  assert.match(sharedLedgerStyle, /\.stock-control-ledger__viewport\s*[\s\S]*overflow-y auto[\s\S]*overflow-x visible/)
  assert.match(sharedLedgerStyle, /\.stock-control-ledger__header\s*[\s\S]*flex 0 0 auto/)
  assert.doesNotMatch(sharedLedgerStyle, /\.stock-control-ledger__header\s*[\s\S]*position sticky/)
})

test('stock-control keeps the shared page header summary and three-panel contract', () => {
  assert.match(stockControlSource, /<WorkbenchToolbar class="stock-control-toolbar">/)
  assert.match(stockControlSource, /<WorkbenchSummaryRow class="stock-control-summary">/)
  assert.equal((stockControlSource.match(/<WorkbenchLedgerPanel class="stock-control-panel">/g) || []).length, 3)
  assert.equal((stockControlSource.match(/<div class="workbench-panel__header">/g) || []).length, 3)
  assert.equal((stockControlSource.match(/<div class="stock-control-panel__table">/g) || []).length, 3)
  assert.match(stockControlSource, /<SignalList title="持仓股信号" category="holdings" \/>/)
  assert.match(stockControlSource, /<ModelSignalList title="stock_pools模型信号" \/>/)
  assert.match(stockControlSource, /<SignalList title="must_pools买入信号" category="must_pool_buys" \/>/)
})
