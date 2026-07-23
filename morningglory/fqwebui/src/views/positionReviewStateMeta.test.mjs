import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getPositionReviewStatusMeta,
  normalizePositionReviewStatus,
  POSITION_REVIEW_FILTER_OPTIONS,
  POSITION_REVIEW_STATUS_META,
} from './positionReviewStateMeta.mjs'

test('position review exposes four explicit verdict states', () => {
  assert.deepEqual(Object.keys(POSITION_REVIEW_STATUS_META), [
    'COMPLIANT',
    'ANOMALY',
    'UNVERIFIABLE',
    'NOT_APPLICABLE',
  ])
  assert.equal(POSITION_REVIEW_FILTER_OPTIONS.length, 5)
  assert.equal(POSITION_REVIEW_FILTER_OPTIONS[0].label, '全部结论')
})

test('backend verdict vocabulary maps to stable frontend verdicts', () => {
  assert.equal(normalizePositionReviewStatus('PASS'), 'COMPLIANT')
  assert.equal(normalizePositionReviewStatus('FAIL'), 'ANOMALY')
  assert.equal(normalizePositionReviewStatus('INSUFFICIENT_EVIDENCE'), 'UNVERIFIABLE')
  assert.equal(normalizePositionReviewStatus('NOT_APPLICABLE'), 'NOT_APPLICABLE')
  assert.equal(normalizePositionReviewStatus(''), 'UNVERIFIABLE')
  assert.equal(getPositionReviewStatusMeta('FAIL').label, '策略异常')
  assert.equal(getPositionReviewStatusMeta('PASS').chipVariant, 'success')
})
