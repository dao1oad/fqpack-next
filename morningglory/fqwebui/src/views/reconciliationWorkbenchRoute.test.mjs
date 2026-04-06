import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const routerSource = readSource('../router/index.js')
const pageMetaSource = readSource('../router/pageMeta.mjs')
test('router removes standalone /reconciliation and keeps retired pages removed', () => {
  assert.doesNotMatch(routerSource, /path:\s*'\/reconciliation'/)
  assert.doesNotMatch(routerSource, /name:\s*'reconciliation'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/order-management'/)
  assert.doesNotMatch(routerSource, /name:\s*'order-management'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/tpsl'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/futures-control'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/stock-cjsd'/)
})

test('header nav removes 对账中心 and keeps retired pages removed', () => {
  assert.doesNotMatch(pageMetaSource, /label:\s*'对账中心'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/reconciliation'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'订单管理'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/order-management'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'TPSL'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/tpsl'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'期货'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/futures-control'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'超级赛道'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/stock-cjsd'/)
})

test('route title mapping no longer includes reconciliation or order management', () => {
  assert.doesNotMatch(pageMetaSource, /'reconciliation':\s*'对账中心'/)
  assert.doesNotMatch(pageMetaSource, /'order-management':\s*'订单管理'/)
})
