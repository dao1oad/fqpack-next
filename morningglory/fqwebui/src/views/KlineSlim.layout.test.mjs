import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

test('KlineSlim keeps the price panel on the left edge', () => {
  assert.match(
    source,
    /\.kline-slim-content\.has-side-panel \.kline-slim-chart,\s*\n\.kline-slim-content\.has-side-panel \.kline-slim-empty\s*\n\s+left 384px/
  )
  assert.match(
    source,
    /\.kline-slim-content\.has-side-panel \.kline-slim-chanlun-panel\s*\n\s+left 396px/
  )
  assert.match(
    source,
    /\.kline-slim-price-panel\s*\n(?:\s+.+\n)*?\s+left 12px/
  )
})

test('KlineSlim price panel titles stay horizontal with ellipsis', () => {
  assert.match(
    source,
    /\.price-panel-row-title\s*\n(?:\s+.+\n)*?\s+white-space nowrap/
  )
  assert.match(
    source,
    /\.price-panel-row-title\s*\n(?:\s+.+\n)*?\s+text-overflow ellipsis/
  )
  assert.match(
    source,
    /\.price-panel-row-subtitle\s*\n(?:\s+.+\n)*?\s+white-space nowrap/
  )
  assert.match(
    source,
    /\.price-panel-row-subtitle\s*\n(?:\s+.+\n)*?\s+text-overflow ellipsis/
  )
})
