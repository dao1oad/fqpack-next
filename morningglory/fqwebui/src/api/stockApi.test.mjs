import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./stockApi.js', import.meta.url), 'utf8').replace(/\r/g, '')

test('stockApi sends add_to_stock_pools_by_code through params with direct CLX options', () => {
  assert.match(source, /addToStockPoolsByCode \(code, days, options = \{\}\)/)
  assert.match(source, /url: '\/api\/add_to_stock_pools_by_code'/)
  assert.match(source, /params = \{ code, days \}/)
  assert.match(source, /params\.allow_direct = allowDirect \? 1 : 0/)
  assert.match(source, /params\.category = options\.category/)
  assert.match(source, /params\.source = options\.source/)
  assert.match(source, /params\.remark = options\.remark/)
})

test('stockApi exposes must_pool TDX 待买 group sync endpoint', () => {
  assert.match(source, /syncMustPoolFromTdxSelfSelect \(\{ days = 30 \} = \{\}\)/)
  assert.match(source, /url: '\/api\/sync_must_pool_from_tdx_self_select'/)
  assert.match(source, /method: 'post'/)
  assert.match(source, /params: \{ days \}/)
})
