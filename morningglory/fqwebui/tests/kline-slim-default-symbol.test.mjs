import test from 'node:test'
import assert from 'node:assert/strict'

import {
  shouldResolveDefaultSymbol,
  pickFirstHoldingSymbol,
  buildResolvedKlineSlimQuery,
  canApplyResolvedKlineSlimRoute,
  getKlineSlimEmptyMessage
} from '../src/views/js/kline-slim-default-symbol.mjs'

test('shouldResolveDefaultSymbol only when symbol is missing', () => {
  assert.equal(shouldResolveDefaultSymbol({ symbol: '' }), true)
  assert.equal(shouldResolveDefaultSymbol({}), true)
  assert.equal(shouldResolveDefaultSymbol({ symbol: 'sh510050' }), false)
})

test('pickFirstHoldingSymbol returns first truthy symbol', () => {
  assert.equal(
    pickFirstHoldingSymbol([{ symbol: 'sh600000' }, { symbol: 'sz000001' }]),
    'sh600000'
  )
  assert.equal(pickFirstHoldingSymbol([]), '')
  assert.equal(pickFirstHoldingSymbol([{ symbol: '' }]), '')
})

test('buildResolvedKlineSlimQuery keeps existing query and injects defaults', () => {
  assert.deepEqual(
    buildResolvedKlineSlimQuery({
      currentQuery: { endDate: '2026-03-07' },
      symbol: 'sh600000',
      period: '5m'
    }),
    { endDate: '2026-03-07', symbol: 'sh600000', period: '5m' }
  )
})

test('canApplyResolvedKlineSlimRoute rejects stale or inactive routes', () => {
  assert.equal(
    canApplyResolvedKlineSlimRoute({
      token: 3,
      routeToken: 3,
      routePath: '/kline-slim'
    }),
    true
  )
  assert.equal(
    canApplyResolvedKlineSlimRoute({
      token: 3,
      routeToken: 4,
      routePath: '/kline-slim'
    }),
    false
  )
  assert.equal(
    canApplyResolvedKlineSlimRoute({
      token: 3,
      routeToken: 3,
      routePath: '/stock-control'
    }),
    false
  )
})

test('getKlineSlimEmptyMessage prefers resolving text before generic empty text', () => {
  assert.equal(
    getKlineSlimEmptyMessage({ resolvingDefaultSymbol: true, resolveError: '' }),
    '正在读取持仓，准备默认标的...'
  )
  assert.equal(
    getKlineSlimEmptyMessage({ resolvingDefaultSymbol: false, resolveError: '' }),
    '请输入或通过 query 传入 `symbol`，例如 `/kline-slim?symbol=sh510050`'
  )
  assert.equal(
    getKlineSlimEmptyMessage({
      resolvingDefaultSymbol: false,
      resolveError: '默认持仓解析失败'
    }),
    '默认持仓解析失败'
  )
})

// Manual checklist:
// 1. /kline-slim -> auto replace to first holding symbol when positions exist
// 2. /kline-slim with empty holdings -> stay on empty state
// 3. /kline-slim?symbol=sh510050 -> unchanged behavior
