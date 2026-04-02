import test from 'node:test'
import assert from 'node:assert/strict'

import { buildEventLedgerRows } from './runtimeObservability.mjs'

test('buildEventLedgerRows formats position management state through shared gate labels', () => {
  const rows = buildEventLedgerRows([
    {
      ts: '2026-03-09T02:05:07Z',
      runtime_node: 'host:submit',
      component: 'order_submit',
      node: 'queue_payload_build',
      status: 'info',
      symbol: '000001',
      action: 'buy',
      payload: {
        queue_payload: {
          position_management_state: 'HOLDING_ONLY',
        },
      },
    },
  ])

  assert.equal(rows[0].semantic_value, '仅允许持仓内买入')
})
