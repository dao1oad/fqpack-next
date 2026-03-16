import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

test('KlineSlim view exposes price guide toolbar entry and side panel layout', () => {
  const source = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(source, /价格层级/)
  assert.match(source, /kline-slim-price-panel/)
  assert.match(source, /Guardian 倍量价格/)
  assert.match(source, /止盈价格/)
  assert.match(source, /price-guide-badge--guardian/)
  assert.match(source, /price-guide-badge--takeprofit/)
})
