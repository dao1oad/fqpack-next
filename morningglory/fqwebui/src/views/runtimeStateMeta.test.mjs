import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getTraceStatusMeta,
  getOrderStateMeta,
} from './runtimeStateMeta.mjs'
import {
  ORDER_STATE_META,
  getOrderStateMeta as getOrderStateMetaFromDomain,
} from './orderStateMeta.mjs'
import {
  TRACE_STATUS_META,
  getTraceStatusMeta as getTraceStatusMetaFromDomain,
} from './traceStatusMeta.mjs'

test('traceStatusMeta exposes canonical trace semantics and runtimeStateMeta keeps compatibility re-export', () => {
  const broken = getTraceStatusMetaFromDomain('broken')
  const open = getTraceStatusMeta('OPEN')

  assert.equal(TRACE_STATUS_META.completed.label, '已完成')
  assert.equal(broken.key, 'broken')
  assert.equal(broken.label, '断裂')
  assert.equal(broken.chipVariant, 'danger')
  assert.equal(broken.severity, 'error')

  assert.equal(open.key, 'open')
  assert.equal(open.label, '进行中')
  assert.equal(open.chipVariant, 'info')
  assert.equal(open.severity, 'info')
})

test('orderStateMeta covers latest order management states and runtimeStateMeta re-exports the same semantics', () => {
  assert.equal(ORDER_STATE_META.SUBMITTED.label, '已提交')
  assert.equal(getOrderStateMetaFromDomain('BROKER_BYPASSED').label, '已绕过券商')
  assert.equal(getOrderStateMeta('CANCEL_REQUESTED').label, '撤单中')
  assert.equal(ORDER_STATE_META.CANCELLED.key, 'CANCELLED')
  assert.equal(getOrderStateMeta('CANCELLED').label, '已撤单')
  assert.equal(getOrderStateMetaFromDomain('CANCELLED').chipVariant, 'muted')
  assert.equal(getOrderStateMetaFromDomain('OPEN').label, '未完成')
  assert.equal(getOrderStateMeta('FAILED').chipVariant, 'danger')
  assert.equal(getOrderStateMetaFromDomain('FILLED').chipVariant, 'success')
})
