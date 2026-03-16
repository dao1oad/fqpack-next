import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
const lineBreak = '\\r?\\n'

test('KlineSlim keeps the price panel on the left edge', () => {
  assert.match(
    source,
    new RegExp(`\\.kline-slim-content\\.has-side-panel \\.kline-slim-chart,\\s*${lineBreak}\\.kline-slim-content\\.has-side-panel \\.kline-slim-empty\\s*${lineBreak}\\s+left 384px`)
  )
  assert.match(
    source,
    new RegExp(`\\.kline-slim-content\\.has-side-panel \\.kline-slim-chanlun-panel\\s*${lineBreak}\\s+left 396px`)
  )
  assert.match(
    source,
    new RegExp(`\\.kline-slim-price-panel\\s*${lineBreak}(?:\\s+.+${lineBreak})*?\\s+left 12px`)
  )
})

test('KlineSlim price panel titles stay horizontal with ellipsis', () => {
  assert.match(
    source,
    new RegExp(`\\.price-panel-row-title\\s*${lineBreak}(?:\\s+.+${lineBreak})*?\\s+white-space nowrap`)
  )
  assert.match(
    source,
    new RegExp(`\\.price-panel-row-title\\s*${lineBreak}(?:\\s+.+${lineBreak})*?\\s+text-overflow ellipsis`)
  )
  assert.match(
    source,
    new RegExp(`\\.price-panel-row-subtitle\\s*${lineBreak}(?:\\s+.+${lineBreak})*?\\s+white-space nowrap`)
  )
  assert.match(
    source,
    new RegExp(`\\.price-panel-row-subtitle\\s*${lineBreak}(?:\\s+.+${lineBreak})*?\\s+text-overflow ellipsis`)
  )
})
