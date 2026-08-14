import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { buildDetailViewModel } from './tpslManagement.mjs'

test('buildDetailViewModel normalizes reconciliation state to canonical shared meta', () => {
  const aligned = buildDetailViewModel({
    symbol: '600000',
    reconciliation: {
      state: 'aligned',
      signed_gap_quantity: 0,
      open_gap_count: 0,
      latest_resolution_type: '',
    },
  })
  const drift = buildDetailViewModel({
    symbol: '300001',
    reconciliation: {
      state: 'drift',
      signed_gap_quantity: 50,
      open_gap_count: 0,
      latest_resolution_type: '',
    },
  })

  assert.equal(aligned.reconciliation.state, 'ALIGNED')
  assert.equal(aligned.reconciliation.state_label, '已对齐')
  assert.equal(aligned.reconciliation.state_chip_variant, 'success')
  assert.equal(drift.reconciliation.state, 'DRIFT')
  assert.equal(drift.reconciliation.state_label, '漂移')
  assert.equal(drift.reconciliation.state_chip_variant, 'danger')
})
