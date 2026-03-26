import test from 'node:test'
import assert from 'node:assert/strict'

import { pickFirstHoldingSymbol } from './kline-slim-default-symbol.mjs'

test('pickFirstHoldingSymbol prefers the largest holding amount so default symbol matches the sidebar top item', () => {
  const symbol = pickFirstHoldingSymbol([
    { symbol: 'sz000001', amount: 100000 },
    { symbol: 'sh600036', position_amount: 300000 },
    { symbol: 'sh601398', market_value: 300000 },
    { symbol: 'sz300750', amount: 'not-a-number' }
  ])

  assert.equal(symbol, 'sh600036')
})
