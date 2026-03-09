import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildTraceSummaryMeta,
  buildTraceDetail,
  buildHealthCards,
  buildRawLookupFromStep,
  buildTraceQuery,
  filterTraceSteps,
  formatDurationMs,
  groupStepsByComponent,
  pickDefaultTraceStep,
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

test('summarizeTrace and sortTraceSummaries prioritize traces with issues before latest timestamp', () => {
  const rows = sortTraceSummaries([
    summarizeTrace({
      trace_id: 'trc_1',
      steps: [{ node: 'submit_result', ts: '2026-03-09T10:00:02+08:00', status: 'success' }],
    }),
    summarizeTrace({
      trace_id: 'trc_2',
      steps: [{ node: 'queue_consume', ts: '2026-03-09T10:00:03+08:00', status: 'info' }],
    }),
    summarizeTrace({
      trace_id: 'trc_3',
      steps: [{ node: 'decision', ts: '2026-03-09T09:59:00+08:00', status: 'warning' }],
    }),
  ])

  assert.equal(rows[0].trace_id, 'trc_3')
  assert.equal(rows[0].issue_count, 1)
  assert.equal(rows[1].trace_id, 'trc_2')
  assert.equal(rows[2].last_status, 'success')
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

test('buildTraceDetail derives durations, issue steps and step metadata', () => {
  const detail = buildTraceDetail({
    trace_id: 'trc_1',
    intent_ids: ['intent_1'],
    request_ids: ['req_1'],
    internal_order_ids: ['ord_1'],
    steps: [
      {
        component: 'guardian_strategy',
        node: 'receive_signal',
        status: 'info',
        ts: '2026-03-09T10:00:00+08:00',
      },
      {
        component: 'position_gate',
        node: 'decision',
        status: 'skipped',
        ts: '2026-03-09T10:00:00.250+08:00',
        reason_code: 'cooldown_active',
        decision_branch: 'cooldown_block',
        decision_expr: 'cooldown_remaining > 0',
        payload: { quantity: 300 },
      },
    ],
  })

  assert.equal(detail.trace_id, 'trc_1')
  assert.equal(detail.issue_count, 1)
  assert.equal(detail.total_duration_label, '250ms')
  assert.equal(detail.first_issue.node, 'decision')
  assert.equal(detail.steps[1].delta_from_prev_label, '250ms')
  assert.equal(detail.steps[1].is_issue, true)
  assert.deepEqual(
    detail.steps[1].tags.map((item) => item.key),
    ['decision_branch', 'reason_code', 'decision_expr'],
  )
  assert.match(detail.steps[1].payload_text, /"quantity": 300/)
})

test('filterTraceSteps keeps only issue steps when requested', () => {
  const detail = buildTraceDetail({
    steps: [
      { component: 'guardian_strategy', node: 'receive_signal', status: 'info' },
      { component: 'position_gate', node: 'decision', status: 'warning' },
      { component: 'order_submit', node: 'queue_write', status: 'success' },
    ],
  })

  assert.deepEqual(
    filterTraceSteps(detail.steps, { onlyIssues: true }).map((item) => item.node),
    ['decision'],
  )
  assert.equal(formatDurationMs(1520), '1.5s')
})

test('buildTraceSummaryMeta derives issue summary and slowest step metadata', () => {
  const detail = buildTraceDetail({
    steps: [
      { component: 'guardian_strategy', node: 'receive_signal', status: 'info', ts: '2026-03-09T10:00:00+08:00' },
      { component: 'position_gate', node: 'decision', status: 'warning', ts: '2026-03-09T10:00:00.200+08:00' },
      { component: 'order_submit', node: 'queue_write', status: 'success', ts: '2026-03-09T10:00:01.700+08:00' },
      { component: 'broker_gateway', node: 'submit_result', status: 'failed', ts: '2026-03-09T10:00:02+08:00' },
    ],
  })
  const meta = buildTraceSummaryMeta(detail)

  assert.equal(meta.first_issue.node, 'decision')
  assert.equal(meta.last_issue.node, 'submit_result')
  assert.equal(meta.slowest_step.node, 'queue_write')
  assert.equal(meta.slowest_step.delta_from_prev_label, '1.5s')
  assert.deepEqual(meta.affected_components, ['broker_gateway', 'position_gate'])
})

test('groupStepsByComponent and pickDefaultTraceStep keep component groups and choose first issue', () => {
  const detail = buildTraceDetail({
    steps: [
      { component: 'guardian_strategy', node: 'receive_signal', status: 'info', ts: '2026-03-09T10:00:00+08:00' },
      { component: 'guardian_strategy', node: 'decision', status: 'warning', ts: '2026-03-09T10:00:00.100+08:00' },
      { component: 'order_submit', node: 'queue_write', status: 'success', ts: '2026-03-09T10:00:01+08:00' },
    ],
  })

  const groups = groupStepsByComponent(detail.steps)
  assert.deepEqual(groups.map((group) => group.component), ['guardian_strategy', 'order_submit'])
  assert.equal(groups[0].issue_count, 1)
  assert.equal(groups[0].duration_label, '100ms')
  assert.equal(groups[1].duration_label, '900ms')
  assert.equal(pickDefaultTraceStep(detail.steps).node, 'decision')
})
