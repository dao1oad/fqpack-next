import test from 'node:test'
import assert from 'node:assert/strict'

import {
  applyBoardFilter,
  buildComponentBoard,
  buildTraceListSummary,
  buildIssuePriorityCards,
  buildIssueSummary,
  buildRawRecordSummary,
  buildRecentTraceFeed,
  buildTraceSummaryMeta,
  buildTraceDetail,
  buildHealthCards,
  buildRawLookupFromStep,
  buildTraceQuery,
  findRawRecordIndex,
  findTraceByRow,
  filterTraceSteps,
  formatDurationMs,
  groupStepsByComponent,
  pickDefaultTraceStep,
  sortTraceSummaries,
  summarizeTrace,
} from './runtimeObservability.mjs'

const makeTrace = ({
  traceId,
  symbol = 'sh510050',
  status = 'success',
  component = 'order_submit',
  issueComponent = component,
  node = 'submit_result',
  issueNode = node,
  stepCount = 3,
  durationMs = 500,
  issueCount = status === 'success' ? 0 : 1,
  lastTs,
}) => {
  const baseTs = Date.parse(lastTs) - durationMs
  const steps = [
    {
      component: 'guardian_strategy',
      node: 'receive_signal',
      status: 'info',
      ts: new Date(baseTs).toISOString(),
      symbol,
      trace_id: traceId,
      request_id: `req_${traceId}`,
      internal_order_id: `ord_${traceId}`,
    },
  ]

  for (let index = 0; index < Math.max(stepCount - 2, 0); index += 1) {
    steps.push({
      component,
      node: index === 0 ? 'queue_write' : `${node}_${index}`,
      status: issueCount > 0 && index < issueCount ? status : 'success',
      ts: new Date(baseTs + 100 + index * 100).toISOString(),
      symbol,
      trace_id: traceId,
      request_id: `req_${traceId}`,
      internal_order_id: `ord_${traceId}`,
      reason_code: issueCount > 0 && index < issueCount ? `${status}_reason` : '',
    })
  }

  steps.push({
    component: issueComponent,
    node: issueNode,
    status,
    ts: new Date(Date.parse(lastTs)).toISOString(),
    symbol,
    trace_id: traceId,
    request_id: `req_${traceId}`,
    internal_order_id: `ord_${traceId}`,
    reason_code: status === 'success' ? '' : `${status}_reason`,
  })

  return {
    trace_id: traceId,
    trace_key: `trace:${traceId}`,
    request_ids: [`req_${traceId}`],
    internal_order_ids: [`ord_${traceId}`],
    intent_ids: [`intent_${traceId}`],
    symbol,
    steps,
  }
}

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

test('buildIssuePriorityCards prioritizes failed traces before warnings', () => {
  const cards = buildIssuePriorityCards([
    makeTrace({
      traceId: 'trc_warn',
      status: 'warning',
      issueComponent: 'position_gate',
      issueNode: 'guard_reject',
      issueCount: 0,
      durationMs: 800,
      lastTs: '2026-03-09T10:00:02+08:00',
    }),
    makeTrace({
      traceId: 'trc_fail',
      status: 'failed',
      issueComponent: 'broker_gateway',
      issueNode: 'submit_result',
      issueCount: 0,
      durationMs: 1200,
      lastTs: '2026-03-09T10:00:03+08:00',
    }),
  ])

  assert.equal(cards.length, 2)
  assert.equal(cards[0].trace_id, 'trc_fail')
  assert.equal(cards[0].status, 'failed')
  assert.match(cards[0].headline, /broker_gateway\.submit_result/)
})

test('buildRecentTraceFeed returns latest 20 rows by default', () => {
  const traces = Array.from({ length: 25 }, (_, index) =>
    makeTrace({
      traceId: `trc_${index + 1}`,
      lastTs: `2026-03-09T10:${String(index).padStart(2, '0')}:20+08:00`,
      durationMs: 200 + index * 10,
    }),
  )

  const feed = buildRecentTraceFeed(traces)

  assert.equal(feed.length, 20)
  assert.equal(feed[0].trace_id, 'trc_25')
  assert.equal(feed[19].trace_id, 'trc_6')
})

test('buildComponentBoard summarizes core component issue counts', () => {
  const board = buildComponentBoard(
    [
      makeTrace({
        traceId: 'trc_order_submit_1',
        component: 'order_submit',
        issueComponent: 'order_submit',
        status: 'failed',
        issueCount: 0,
        lastTs: '2026-03-09T10:00:10+08:00',
      }),
      makeTrace({
        traceId: 'trc_order_submit_2',
        component: 'order_submit',
        issueComponent: 'order_submit',
        status: 'warning',
        issueCount: 0,
        lastTs: '2026-03-09T10:00:12+08:00',
      }),
      makeTrace({
        traceId: 'trc_position_gate',
        component: 'position_gate',
        issueComponent: 'position_gate',
        status: 'warning',
        issueCount: 0,
        lastTs: '2026-03-09T10:00:14+08:00',
      }),
    ],
    buildHealthCards([
      {
        component: 'order_submit',
        runtime_node: 'host:order_submit',
        status: 'warning',
        heartbeat_age_s: 3,
        metrics: { queue_len: 2 },
      },
      {
        component: 'position_gate',
        runtime_node: 'host:position_gate',
        status: 'info',
        heartbeat_age_s: 1,
        metrics: { queue_len: 0 },
      },
    ]),
  )

  assert.equal(board.cards[0].component, 'order_submit')
  assert.equal(board.cards[0].issue_trace_count, 2)
  assert.equal(board.distribution[0].component, 'order_submit')
})

test('applyBoardFilter narrows traces by selected component', () => {
  const traces = [
    makeTrace({
      traceId: 'trc_order_submit',
      component: 'order_submit',
      issueComponent: 'order_submit',
      status: 'warning',
      issueCount: 0,
      lastTs: '2026-03-09T10:00:10+08:00',
    }),
    makeTrace({
      traceId: 'trc_broker',
      component: 'broker_gateway',
      issueComponent: 'broker_gateway',
      status: 'failed',
      issueCount: 0,
      lastTs: '2026-03-09T10:00:12+08:00',
    }),
  ]

  const filtered = applyBoardFilter(traces, { component: 'order_submit' })

  assert.deepEqual(filtered.map((trace) => trace.trace_id), ['trc_order_submit'])
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

test('summarizeTrace preserves trace_key for traces without trace_id', () => {
  const row = summarizeTrace({
    trace_key: 'request:req_1',
    request_ids: ['req_1'],
    internal_order_ids: ['ord_1'],
    steps: [
      { node: 'queue_write', ts: '2026-03-09T10:00:03+08:00', status: 'info' },
    ],
  })

  assert.equal(row.trace_key, 'request:req_1')
  assert.equal(row.trace_id, null)
  assert.deepEqual(row.request_ids, ['req_1'])
})

test('findTraceByRow resolves request-key traces without trace_id', () => {
  const traces = [
    {
      trace_key: 'request:req_1',
      trace_id: null,
      request_ids: ['req_1'],
      internal_order_ids: ['ord_1'],
      steps: [{ component: 'order_submit', node: 'queue_write', status: 'info' }],
    },
  ]

  const row = summarizeTrace(traces[0])

  assert.equal(findTraceByRow(traces, row), traces[0])
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

test('buildIssueSummary aggregates reason labels into readable headline', () => {
  const detail = buildTraceDetail({
    steps: [
      { component: 'guardian_strategy', node: 'decision', status: 'warning', reason_code: 'cooldown_active' },
      { component: 'broker_gateway', node: 'submit_result', status: 'failed', reason_code: 'broker_rejected' },
      { component: 'broker_gateway', node: 'submit_result', status: 'failed', reason_code: 'broker_rejected' },
    ],
  })
  const summary = buildIssueSummary(detail)

  assert.match(summary.headline, /3 个异常节点/)
  assert.deepEqual(summary.items, [
    { label: 'broker_rejected', count: 2 },
    { label: 'cooldown_active', count: 1 },
  ])
})

test('findRawRecordIndex matches the current step and buildRawRecordSummary marks key fields', () => {
  const step = buildTraceDetail({
    steps: [
      {
        component: 'order_submit',
        node: 'queue_write',
        status: 'success',
        ts: '2026-03-09T10:00:01+08:00',
        trace_id: 'trc_1',
        request_id: 'req_1',
        internal_order_id: 'ord_1',
        symbol: '600000',
      },
    ],
  }).steps[0]

  const records = [
    { component: 'guardian_strategy', node: 'receive_signal', ts: '2026-03-09T10:00:00+08:00' },
    {
      component: 'order_submit',
      node: 'queue_write',
      ts: '2026-03-09T10:00:01+08:00',
      trace_id: 'trc_1',
      request_id: 'req_1',
      internal_order_id: 'ord_1',
      symbol: '600000',
      payload: { quantity: 300 },
    },
  ]

  assert.equal(findRawRecordIndex(records, step), 1)
  assert.deepEqual(buildRawRecordSummary(records[1]), {
    title: 'order_submit.queue_write',
    subtitle: '2026-03-09T10:00:01+08:00',
    badges: ['trace trc_1', 'request req_1', 'order ord_1', 'symbol 600000'],
    body: '{\n  "quantity": 300\n}',
  })
})

test('buildTraceListSummary aggregates visible traces and issue components', () => {
  const summary = buildTraceListSummary([
    {
      trace_id: 'trc_1',
      steps: [
        { component: 'guardian_strategy', node: 'decision', status: 'warning' },
        { component: 'order_submit', node: 'queue_write', status: 'success' },
      ],
    },
    {
      trace_id: 'trc_2',
      steps: [
        { component: 'broker_gateway', node: 'submit_result', status: 'failed' },
        { component: 'broker_gateway', node: 'order_callback', status: 'warning' },
      ],
    },
    {
      trace_id: 'trc_3',
      steps: [
        { component: 'order_submit', node: 'queue_write', status: 'success' },
      ],
    },
  ])

  assert.equal(summary.trace_count, 3)
  assert.equal(summary.issue_trace_count, 2)
  assert.equal(summary.issue_step_count, 3)
  assert.deepEqual(summary.components, [
    { component: 'broker_gateway', issue_count: 2, trace_count: 1 },
    { component: 'guardian_strategy', issue_count: 1, trace_count: 1 },
  ])
})

test('buildTraceListSummary respects already filtered component slices', () => {
  const summary = buildTraceListSummary([
    {
      trace_id: 'trc_1',
      steps: [
        { component: 'order_submit', node: 'queue_write', status: 'warning' },
        { component: 'order_submit', node: 'submit_result', status: 'failed' },
      ],
    },
  ])

  assert.equal(summary.trace_count, 1)
  assert.equal(summary.issue_trace_count, 1)
  assert.equal(summary.issue_step_count, 2)
  assert.deepEqual(summary.components, [
    { component: 'order_submit', issue_count: 2, trace_count: 1 },
  ])
})
