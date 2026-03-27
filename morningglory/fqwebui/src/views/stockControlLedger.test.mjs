import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

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
