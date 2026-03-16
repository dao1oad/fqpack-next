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

test('KlineSlim keeps price guide and chanlun panels on the chart overlay instead of shrinking the chart area', () => {
  const source = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(source, /has-side-panel/)
  assert.match(source, /class="kline-slim-price-panel kline-slim-overlay-panel"/)
  assert.match(source, /class="kline-slim-chanlun-panel kline-slim-overlay-panel"/)
})

test('KlineSlim toolbar toggles both price guide and chanlun panels from the same buttons', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /@click="togglePriceGuidePanel"/)
  assert.match(viewSource, /@click="toggleChanlunStructurePanel"/)
  assert.match(viewSource, /:type="showChanlunStructurePanel \? 'primary' : 'default'"/)

  assert.match(scriptSource, /togglePriceGuidePanel\(\)/)
  assert.match(scriptSource, /toggleChanlunStructurePanel\(\)/)
  assert.match(scriptSource, /this\.showPriceGuidePanel = false/)
  assert.match(scriptSource, /this\.showChanlunStructurePanel = false/)
})
