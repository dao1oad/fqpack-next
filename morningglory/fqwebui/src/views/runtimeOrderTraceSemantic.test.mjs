import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildEventLedgerRows,
  buildRecentTraceFeed,
  buildTraceLedgerRows,
  summarizeTrace,
} from './runtimeObservability.mjs'

const completedTrace = {
  trace_id: 'trc_completed',
  trace_key: 'trace:trc_completed',
  trace_kind: 'guardian_signal',
  trace_status: 'completed',
  first_ts: '2026-03-09T10:00:00+08:00',
  last_ts: '2026-03-09T10:00:02+08:00',
  steps: [
    {
      component: 'guardian_strategy',
      node: 'receive_signal',
      status: 'info',
      ts: '2026-03-09T10:00:00+08:00',
      trace_id: 'trc_completed',
      symbol: '000001',
    },
    {
      component: 'order_submit',
      node: 'submit_result',
      status: 'success',
      ts: '2026-03-09T10:00:02+08:00',
      trace_id: 'trc_completed',
      symbol: '000001',
    },
  ],
}

test('buildEventLedgerRows formats latest order states through shared order meta', () => {
  const rows = buildEventLedgerRows([
    {
      ts: '2026-03-09T02:05:07Z',
      runtime_node: 'host:submit',
      component: 'order_submit',
      node: 'submit_result',
      status: 'info',
      symbol: '000001',
      payload: {
        state: 'SUBMITTED',
      },
    },
    {
      ts: '2026-03-09T02:05:08Z',
      runtime_node: 'host:ingest',
      component: 'xt_report_ingest',
      node: 'order_callback',
      status: 'info',
      symbol: '000001',
      payload: {
        report_type: 'order',
        state: 'CANCEL_REQUESTED',
      },
    },
  ])

  assert.equal(rows[0].semantic_value, '已提交')
  assert.equal(rows[1].semantic_value, '订单撤单中')
})

test('summarizeTrace exposes shared trace status meta for runtime trace rows', () => {
  const row = summarizeTrace({
    ...completedTrace,
    trace_status: 'broken',
  })

  assert.equal(row.trace_status, 'broken')
  assert.equal(row.trace_status_label, '断裂')
  assert.equal(row.trace_status_chip_variant, 'danger')
  assert.equal(row.trace_status_severity, 'error')
})

test('buildRecentTraceFeed and buildTraceLedgerRows keep trace chip variants for view reuse', () => {
  const feed = buildRecentTraceFeed([completedTrace])
  const ledgerRows = buildTraceLedgerRows([completedTrace])

  assert.equal(feed[0].trace_status_label, '已完成')
  assert.equal(feed[0].trace_status_chip_variant, 'success')
  assert.equal(feed[0].trace_status_severity, 'ok')
  assert.equal(ledgerRows[0].trace_status_chip_variant, 'success')
  assert.equal(ledgerRows[0].trace_status_severity, 'ok')
})
