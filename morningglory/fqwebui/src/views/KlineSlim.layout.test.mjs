import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
const lineBreak = '\\r?\\n'
const mediumLayoutStart = source.indexOf('@media (max-width: 1200px)')
const mediumLayoutEnd = source.indexOf('@media (max-width: 900px)')
const mediumLayoutBlock = source.slice(mediumLayoutStart, mediumLayoutEnd)

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

test('KlineSlim responsive side-panel offsets stay left-based below 1200px', () => {
  assert.match(
    mediumLayoutBlock,
    new RegExp(`\\.kline-slim-content\\.has-side-panel \\.kline-slim-chart,\\s*${lineBreak}\\s+\\.kline-slim-content\\.has-side-panel \\.kline-slim-empty\\s*${lineBreak}\\s+left 344px`)
  )
  assert.match(
    mediumLayoutBlock,
    new RegExp(`\\.kline-slim-content\\.has-side-panel \\.kline-slim-chanlun-panel\\s*${lineBreak}\\s+left 356px`)
  )
  assert.doesNotMatch(
    mediumLayoutBlock,
    /\.kline-slim-content\.has-side-panel \.kline-slim-chart,[\s\S]*?\s+right 344px/
  )
  assert.doesNotMatch(
    mediumLayoutBlock,
    /\.kline-slim-content\.has-side-panel \.kline-slim-chanlun-panel[\s\S]*?\s+right 356px/
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
