import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildHealthCards,
  buildRawLookupFromStep,
  buildTraceQuery,
  sortTraceSummaries,
  summarizeTrace,
} from './runtimeObservability.mjs'

test('buildTraceQuery trims empty fields', () => {
  assert.deepEqual(
    buildTraceQuery({
      trace_id: ' trc_1 ',
      request_id: '',
      internal_order_id: '   ',
      symbol: '000001',
    }),
    {
      trace_id: 'trc_1',
      symbol: '000001',
    },
  )
})

test('summarizeTrace and sortTraceSummaries derive latest node and sort by latest timestamp desc', () => {
  const rows = sortTraceSummaries([
    summarizeTrace({
      trace_id: 'trc_1',
      steps: [{ node: 'submit_result', ts: '2026-03-09T10:00:02+08:00', status: 'success' }],
    }),
    summarizeTrace({
      trace_id: 'trc_2',
      steps: [{ node: 'queue_consume', ts: '2026-03-09T10:00:03+08:00', status: 'info' }],
    }),
  ])

  assert.equal(rows[0].trace_id, 'trc_2')
  assert.equal(rows[0].last_node, 'queue_consume')
  assert.equal(rows[1].last_status, 'success')
})

test('buildHealthCards and buildRawLookupFromStep normalize view data', () => {
  assert.deepEqual(
    buildHealthCards([
      {
        component: 'xt_producer',
        runtime_node: 'host:xt_producer',
        status: 'info',
        heartbeat_age_s: 12,
        metrics: { rx_age_s: 1.2, connected: 1, ignored: 3 },
      },
    ]),
    [
      {
        component: 'xt_producer',
        runtime_node: 'host:xt_producer',
        status: 'info',
        heartbeat_age_s: 12,
        highlights: [
          { key: 'rx_age_s', value: 1.2 },
          { key: 'connected', value: 1 },
        ],
      },
    ],
  )

  assert.deepEqual(
    buildRawLookupFromStep({
      runtime_node: 'host:guardian',
      component: 'guardian_strategy',
      ts: '2026-03-09T10:00:03+08:00',
    }),
    {
      runtime_node: 'host:guardian',
      component: 'guardian_strategy',
      date: '2026-03-09',
    },
  )
})
