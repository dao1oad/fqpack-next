import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CONSISTENCY_RECONCILIATION_STATES,
  CONSISTENCY_RULES,
  CONSISTENCY_SURFACES,
  getConsistencyRuleMeta,
  getConsistencySurfaceMeta,
} from './consistencyContract.mjs'

test('consistency contract exposes canonical surface order and labels', () => {
  assert.deepEqual(
    CONSISTENCY_SURFACES.map((item) => item.key),
    ['broker', 'snapshot', 'entry_ledger', 'slice_ledger', 'compat_projection', 'stock_fills_projection'],
  )
  assert.equal(getConsistencySurfaceMeta('broker').label, '券商')
  assert.equal(getConsistencySurfaceMeta('snapshot').label, 'PM快照')
  assert.equal(getConsistencySurfaceMeta('entry_ledger').label, 'Entry账本')
})

test('consistency contract exposes rule ids labels and expected relations', () => {
  assert.deepEqual(
    CONSISTENCY_RULES.map((item) => item.id),
    ['R1', 'R2', 'R3', 'R4'],
  )
  assert.equal(getConsistencyRuleMeta('R1').key, 'broker_snapshot_consistency')
  assert.equal(getConsistencyRuleMeta('R1').label, '券商与PM快照')
  assert.equal(getConsistencyRuleMeta('R3').expectedRelation, 'projection_match')
  assert.equal(getConsistencyRuleMeta('R4').expectedRelation, 'reconciliation_explained')
})

test('consistency contract keeps canonical reconciliation states', () => {
  assert.deepEqual(
    CONSISTENCY_RECONCILIATION_STATES,
    ['ALIGNED', 'OBSERVING', 'AUTO_RECONCILED', 'BROKEN', 'DRIFT'],
  )
})
