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

test('CLX unified entry waits for the screening result instead of selecting an unrelated holding', () => {
  assert.equal(shouldResolveDefaultSymbol({}), true)
  assert.equal(shouldResolveDefaultSymbol({ clxScreening: '1' }), false)
  assert.equal(shouldResolveDefaultSymbol({ clxWorkbench: '1' }), false)
  assert.equal(shouldResolveDefaultSymbol({ symbol: 'sz000001' }), false)
})

test('getKlineSlimEmptyMessage prefers resolving text before generic empty text', () => {
  assert.equal(
    getKlineSlimEmptyMessage({ resolvingDefaultSymbol: true, resolveError: '' }),
    '正在读取持仓，准备默认标的...'
  )
  assert.equal(
    getKlineSlimEmptyMessage({ resolvingDefaultSymbol: false, resolveError: '' }),
    '请在顶部输入代码，或从左侧持仓股/股票池选择标的'
  )
  assert.equal(
    getKlineSlimEmptyMessage({
      resolvingDefaultSymbol: false,
      resolveError: '',
      clxScreening: true
    }),
    '请从左侧 CLX 筛选结果选择标的'
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
