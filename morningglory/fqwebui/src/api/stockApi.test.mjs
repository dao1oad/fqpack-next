import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./stockApi.js', import.meta.url), 'utf8').replace(/\r/g, '')

test('stockApi exposes the single overwrite sync endpoint for stock_pools', () => {
  assert.match(source, /syncStockPoolsFromTdx \(\{ days = 30 \} = \{\}\)/)
  assert.match(source, /url: '\/api\/pools\/stock\/sync-from-tdx'/)
  assert.match(source, /method: 'post'/)
  assert.match(source, /params: \{ days \}/)
})

test('stockApi exposes the single overwrite sync endpoint for must_pool', () => {
  assert.match(source, /syncMustPoolFromTdx \(\{ days = 30, allowEmpty = false \} = \{\}\)/)
  assert.match(source, /url: '\/api\/pools\/must\/sync-from-tdx'/)
  assert.match(source, /method: 'post'/)
  assert.match(source, /params: \{/)
  // #589：allowEmpty 显式确认后透传 allow_empty=1
  assert.match(source, /\.\.\.\(allowEmpty \? \{ allow_empty: 1 \} : \{\}\)/)
})

test('stockApi no longer exposes web direct-write endpoints', () => {
  assert.doesNotMatch(source, /add_to_stock_pools_by_code/)
  assert.doesNotMatch(source, /delete_from_stock_pools_by_code/)
  assert.doesNotMatch(source, /add_to_must_pool_by_code/)
  assert.doesNotMatch(source, /delete_from_must_pool_by_code/)
  assert.doesNotMatch(source, /add_to_stock_pools_by_stock/)
})
