import test from 'node:test'
import assert from 'node:assert/strict'

import { getPositionGateStateMeta } from './positionGateStateMeta.mjs'

test('getPositionGateStateMeta exposes canonical position gate labels and chip variants', () => {
  assert.deepEqual(getPositionGateStateMeta('ALLOW_OPEN'), {
    key: 'ALLOW_OPEN',
    label: '允许开新仓',
    chipVariant: 'success',
    tone: 'allow',
  })
  assert.deepEqual(getPositionGateStateMeta('holding_only'), {
    key: 'HOLDING_ONLY',
    label: '仅允许持仓内买入',
    chipVariant: 'warning',
    tone: 'hold',
  })
  assert.deepEqual(getPositionGateStateMeta('FORCE_PROFIT_REDUCE'), {
    key: 'FORCE_PROFIT_REDUCE',
    label: '强制盈利减仓',
    chipVariant: 'danger',
    tone: 'reduce',
  })
})

test('getPositionGateStateMeta preserves unknown raw keys as fallback labels', () => {
  assert.deepEqual(getPositionGateStateMeta('custom_state'), {
    key: 'CUSTOM_STATE',
    label: 'CUSTOM_STATE',
    chipVariant: 'muted',
    tone: 'neutral',
  })
})
