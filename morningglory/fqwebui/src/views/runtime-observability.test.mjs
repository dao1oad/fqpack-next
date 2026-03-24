import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import * as runtimeObservability from './runtimeObservability.mjs'

import {
  buildEventLedgerRows,
  buildComponentEventEmptyState,
  buildIdentityStrip,
  buildRawSelectionKey,
  buildTodayTimeRange,
  buildTimeRangeQuery,
  buildTraceIdentityLabel,
  applyBoardFilter,
  buildBoardScopedQuery,
  buildComponentBoard,
  buildComponentEventFeed,
  buildComponentSidebarItems,
  createTraceQueryState,
  buildGuardianStepInsight,
  buildGuardianTraceSummary,
  buildTraceListSummary,
  buildTraceKindOptions,
  buildIssuePriorityCards,
  buildIssueSummary,
  buildRawRecordSummary,
  buildRecentTraceFeed,
  filterVisibleTraces,
  filterTracesByIssueComponent,
  buildTraceLedgerRows,
  buildTraceStepLedgerRows,
  buildTraceSummaryMeta,
  buildTraceDetail,
  buildHealthCards,
  readApiPayload,
  buildRawLookupFromStep,
  buildTraceQuery,
  findRawRecordIndex,
  findTraceByRow,
  filterTracesByKind,
  filterTraceSteps,
  formatTimestampLabel,
  formatDurationMs,
  formatTimeRangeLabel,
  groupStepsByComponent,
  hasMatchingRawSelection,
  pickTraceAnchorStep,
  pickDefaultSidebarComponent,
  pickDefaultTraceKind,
  pickDefaultTraceStep,
  sortTraceSummaries,
  summarizeTrace,
  TRACE_QUERY_FIELDS,
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

const makeGuardianTrace = ({
  traceId = 'trc_guardian',
  finalNode = 'finish',
  finalStatus = 'skipped',
  finalOutcome = 'skip',
  reasonCode = 'price_threshold_not_met',
} = {}) => {
  const signalSummary = {
    code: '000001',
    name: 'Ping An Bank',
    position: 'BUY_LONG',
    period: '1m',
    price: 9.8,
    fire_time: '2026-03-09T10:00:00+08:00',
    discover_time: '2026-03-09T10:00:05+08:00',
    remark: 'runtime-test',
    tags: ['must_pool', 'breakout'],
  }
  const thresholdContext = {
    threshold: {
      current_price: 9.8,
      last_fill_price: 10,
      bot_river_price: 9.5,
      top_river_price: 12,
    },
  }
  const steps = [
    {
      component: 'guardian_strategy',
      node: 'receive_signal',
      status: 'info',
      ts: '2026-03-09T10:00:00+08:00',
      symbol: '000001',
      trace_id: traceId,
      signal_summary: signalSummary,
      decision_branch: 'signal_received',
      decision_outcome: { outcome: 'continue' },
    },
    {
      component: 'guardian_strategy',
      node: 'price_threshold_check',
      status: 'skipped',
      ts: '2026-03-09T10:00:01+08:00',
      symbol: '000001',
      trace_id: traceId,
      signal_summary: signalSummary,
      decision_branch: 'holding_add_threshold',
      decision_expr: 'current_price <= bot_river_price',
      reason_code: 'price_threshold_not_met',
      decision_context: thresholdContext,
      decision_outcome: { outcome: 'skip' },
    },
  ]
  steps.push({
    component: 'guardian_strategy',
    node: finalNode,
    status: finalStatus,
    ts: '2026-03-09T10:00:02+08:00',
    symbol: '000001',
    trace_id: traceId,
    signal_summary: signalSummary,
    decision_branch: 'holding_add_threshold',
    decision_expr: 'current_price <= bot_river_price',
    reason_code: reasonCode,
    decision_context: thresholdContext,
    decision_outcome: { outcome: finalOutcome, reason_code: reasonCode },
  })
  return {
    trace_id: traceId,
    trace_key: `trace:${traceId}`,
    request_ids: [`req_${traceId}`],
    internal_order_ids: [],
    intent_ids: [],
    symbol: '000001',
    steps,
  }
}

test('buildTraceQuery trims empty fields', () => {
  assert.deepEqual(
    buildTraceQuery({
      trace_id: ' trc_1 ',
      intent_id: ' int_1 ',
      request_id: '',
      internal_order_id: '   ',
      symbol: '000001',
      runtime_node: ' host:broker ',
    }),
    {
      trace_id: 'trc_1',
      intent_id: 'int_1',
      symbol: '000001',
      runtime_node: 'host:broker',
    },
  )
})

test('buildTraceQuery merges explicit time range bounds', () => {
  assert.deepEqual(
    buildTraceQuery(
      {
        symbol: '000001',
      },
      ['2026-03-18T00:00:00+08:00', '2026-03-18T23:59:59+08:00'],
    ),
    {
      symbol: '000001',
      start_time: '2026-03-18T00:00:00+08:00',
      end_time: '2026-03-18T23:59:59+08:00',
    },
  )
})

test('buildTodayTimeRange returns current Beijing day bounds', () => {
  assert.deepEqual(
    buildTodayTimeRange('2026-03-18T12:34:56+08:00'),
    ['2026-03-18T00:00:00+08:00', '2026-03-18T23:59:59+08:00'],
  )
  assert.deepEqual(
    buildTimeRangeQuery(['2026-03-18T00:00:00+08:00', '2026-03-18T23:59:59+08:00']),
    {
      start_time: '2026-03-18T00:00:00+08:00',
      end_time: '2026-03-18T23:59:59+08:00',
    },
  )
})

test('formatTimeRangeLabel surfaces the selected display range with absolute timestamps', () => {
  assert.equal(
    formatTimeRangeLabel(['2026-03-18T00:00:00+08:00', '2026-03-18T23:59:59+08:00']),
    '2026-03-18 00:00:00 至 2026-03-18 23:59:59',
  )
  assert.equal(formatTimeRangeLabel([]), '')
})

test('buildBoardScopedQuery merges sidebar filter into event query without mutating the base query', () => {
  const baseQuery = {
    symbol: '000001',
    component: '',
  }

  assert.deepEqual(
    buildBoardScopedQuery(baseQuery, {
      component: ' guardian_strategy ',
      runtime_node: ' host:guardian ',
    }),
    {
      symbol: '000001',
      component: 'guardian_strategy',
      runtime_node: 'host:guardian',
    },
  )
  assert.deepEqual(baseQuery, {
    symbol: '000001',
    component: '',
  })
})

test('trace query state includes intent_id for strong-key filtering', () => {
  assert.equal(TRACE_QUERY_FIELDS.includes('intent_id'), true)
  assert.deepEqual(createTraceQueryState(), {
    trace_id: '',
    intent_id: '',
    request_id: '',
    internal_order_id: '',
    symbol: '',
    component: '',
    runtime_node: '',
  })
})

test('buildTraceIdentityLabel falls back to intent before request and order', () => {
  assert.equal(
    buildTraceIdentityLabel({
      trace_key: 'intent:int_1',
      intent_ids: ['int_1'],
      request_ids: ['req_1'],
      internal_order_ids: ['ord_1'],
    }),
    'intent int_1',
  )
})

test('buildTraceDetail reuses hydrated detail objects without rebuilding', () => {
  const detail = buildTraceDetail(
    makeTrace({
      traceId: 'trc_hydrated',
      lastTs: '2026-03-09T10:00:03.000Z',
    }),
  )

  assert.equal(buildTraceDetail(detail), detail)
})

test('buildTraceDetail rehydrates merged trace shells when raw step pages replace hydrated steps', () => {
  const trace = makeTrace({
    traceId: 'trc_trace_detail_merge',
    status: 'failed',
    issueCount: 1,
    lastTs: '2026-03-09T10:00:03.000Z',
  })
  const hydrated = buildTraceDetail(trace)
  const merged = {
    ...hydrated,
    steps: trace.steps,
  }

  const detail = buildTraceDetail(merged)

  assert.notEqual(detail, merged)
  assert.deepEqual(detail.steps.map((item) => item.index), [0, 1, 2])
  assert.equal(detail.steps[2].is_issue, true)
  assert.equal(filterTraceSteps(detail.steps, { onlyIssues: true }).map((item) => item.node).join(','), 'queue_write,submit_result')
  assert.equal(detail.steps[0].ts_label, '2026-03-09 18:00:02')
})

test('filterVisibleTraces keeps issue trace filtering separate from issue step filtering', () => {
  const traces = [
    makeTrace({
      traceId: 'trc_visible_ok',
      status: 'success',
      lastTs: '2026-03-09T10:00:02.000Z',
    }),
    makeTrace({
      traceId: 'trc_visible_failed',
      status: 'failed',
      issueCount: 1,
      component: 'position_gate',
      issueComponent: 'position_gate',
      issueNode: 'decision',
      lastTs: '2026-03-09T10:00:03.000Z',
    }),
  ]

  const issueTraces = filterVisibleTraces(traces, { onlyIssueTraces: true })
  const focusedTraces = filterVisibleTraces(traces, {
    issueComponent: 'position_gate',
    onlyIssueTraces: true,
  })
  const failedTrace = buildTraceDetail(traces[1])

  assert.deepEqual(issueTraces.map((item) => buildTraceDetail(item).trace_id), ['trc_visible_failed'])
  assert.deepEqual(focusedTraces.map((item) => buildTraceDetail(item).trace_id), ['trc_visible_failed'])
  assert.equal(filterTraceSteps(failedTrace.steps, { onlyIssues: false }).length, 3)
  assert.equal(filterTraceSteps(failedTrace.steps, { onlyIssues: true }).length, 2)
})

test('stopPollingTimer clears current timer without arming a new one', () => {
  assert.equal(typeof runtimeObservability.stopPollingTimer, 'function')

  const cleared = []
  const timerHandle = { id: 'overview-1' }
  const nextHandle = runtimeObservability.stopPollingTimer(timerHandle, {
    clearInterval: (handle) => {
      cleared.push(handle)
    },
  })

  assert.deepEqual(cleared, [timerHandle])
  assert.equal(nextHandle, null)
})

test('readApiPayload supports interceptor-unwrapped axios payloads', () => {
  assert.equal(typeof readApiPayload, 'function')

  assert.deepEqual(
    readApiPayload(
      {
        traces: [{ trace_id: 'trc_1' }],
      },
      'traces',
    ),
    [{ trace_id: 'trc_1' }],
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

test('buildRecentTraceFeed accepts a higher limit for expanded recent view', () => {
  const traces = Array.from({ length: 25 }, (_, index) =>
    makeTrace({
      traceId: `trc_expand_${index + 1}`,
      lastTs: `2026-03-09T11:${String(index).padStart(2, '0')}:10+08:00`,
      durationMs: 150 + index * 10,
    }),
  )

  const feed = buildRecentTraceFeed(traces, { limit: 50 })

  assert.equal(feed.length, 25)
  assert.equal(feed[0].trace_id, 'trc_expand_25')
  assert.equal(feed[24].trace_id, 'trc_expand_1')
})

test('buildRecentTraceFeed carries guardian signal summary and conclusion', () => {
  const feed = buildRecentTraceFeed([makeGuardianTrace()])

  assert.equal(feed.length, 1)
  assert.equal(feed[0].guardian_signal.title, '000001 Ping An Bank')
  assert.equal(feed[0].guardian_signal.subtitle, 'BUY_LONG · 1m · 9.8')
  assert.deepEqual(feed[0].guardian_signal.tags, ['must_pool', 'breakout'])
  assert.equal(feed[0].guardian_outcome.label, '跳过')
  assert.equal(feed[0].guardian_outcome.reason_code, 'price_threshold_not_met')
  assert.equal(feed[0].guardian_outcome.node, 'finish')
})

test('buildRecentTraceFeed preserves backend trace metadata for global trace view', () => {
  const feed = buildRecentTraceFeed([
    {
      trace_id: 'trc_trace_meta',
      trace_key: 'trace:trc_trace_meta',
      trace_kind: 'takeprofit',
      trace_status: 'broken',
      break_reason: 'missing_downstream_after_submit_intent',
      first_ts: '2026-03-09T10:00:00+08:00',
      last_ts: '2026-03-09T10:00:03+08:00',
      duration_ms: 3000,
      entry_component: 'tpsl_worker',
      entry_node: 'batch_create',
      exit_component: 'tpsl_worker',
      exit_node: 'submit_intent',
      request_ids: ['req_trace_meta'],
      internal_order_ids: ['ord_trace_meta'],
      steps: [
        {
          component: 'tpsl_worker',
          node: 'batch_create',
          status: 'info',
          ts: '2026-03-09T10:00:00+08:00',
          trace_id: 'trc_trace_meta',
          request_id: 'req_trace_meta',
          internal_order_id: 'ord_trace_meta',
        },
        {
          component: 'tpsl_worker',
          node: 'submit_intent',
          status: 'info',
          ts: '2026-03-09T10:00:03+08:00',
          trace_id: 'trc_trace_meta',
          request_id: 'req_trace_meta',
          internal_order_id: 'ord_trace_meta',
        },
      ],
    },
  ])

  assert.equal(feed[0].trace_kind, 'takeprofit')
  assert.equal(feed[0].trace_status, 'broken')
  assert.equal(feed[0].break_reason, 'missing_downstream_after_submit_intent')
  assert.equal(feed[0].first_ts, '2026-03-09T10:00:00+08:00')
  assert.equal(feed[0].last_ts, '2026-03-09T10:00:03+08:00')
  assert.equal(feed[0].entry_component, 'tpsl_worker')
  assert.equal(feed[0].exit_node, 'submit_intent')
})

test('buildRecentTraceFeed exposes failed trace label for terminal exception traces', () => {
  const feed = buildRecentTraceFeed([
    {
      trace_id: 'trc_failed_meta',
      trace_key: 'trace:trc_failed_meta',
      trace_kind: 'guardian_signal',
      trace_status: 'failed',
      break_reason: 'unexpected_exception@guardian_strategy.timing_check:ValueError',
      first_ts: '2026-03-09T10:00:00+08:00',
      last_ts: '2026-03-09T10:00:02+08:00',
      duration_ms: 2000,
      entry_component: 'guardian_strategy',
      entry_node: 'receive_signal',
      exit_component: 'guardian_strategy',
      exit_node: 'timing_check',
      steps: [
        {
          component: 'guardian_strategy',
          node: 'receive_signal',
          status: 'info',
          ts: '2026-03-09T10:00:00+08:00',
          trace_id: 'trc_failed_meta',
          symbol: '000001',
        },
        {
          component: 'guardian_strategy',
          node: 'timing_check',
          status: 'error',
          reason_code: 'unexpected_exception',
          payload: { error_type: 'ValueError', error_message: 'None None' },
          ts: '2026-03-09T10:00:02+08:00',
          trace_id: 'trc_failed_meta',
          symbol: '000001',
        },
      ],
    },
  ])

  assert.equal(feed[0].trace_status, 'failed')
  assert.equal(feed[0].trace_status_label, '失败')
  assert.equal(
    feed[0].break_reason,
    'unexpected_exception@guardian_strategy.timing_check:ValueError',
  )
})

test('buildComponentEventFeed keeps heartbeat and bootstrap events for component event view', () => {
  const feed = buildComponentEventFeed(
    [
      {
        component: 'xt_producer',
        runtime_node: 'host:xt_producer',
        node: 'bootstrap',
        event_type: 'bootstrap',
        status: 'info',
        ts: '2026-03-09T10:00:00+08:00',
      },
      {
        component: 'xt_producer',
        runtime_node: 'host:xt_producer',
        node: 'heartbeat',
        event_type: 'heartbeat',
        status: 'info',
        metrics: { connected: 1, subscribed_codes: 20 },
        ts: '2026-03-09T10:05:00+08:00',
      },
      {
        component: 'order_submit',
        runtime_node: 'host:rear',
        node: 'tracking_create',
        event_type: 'trace_step',
        status: 'info',
        ts: '2026-03-09T10:04:00+08:00',
      },
    ],
    {
      component: 'xt_producer',
    },
  )

  assert.deepEqual(
    feed.map((item) => ({
      node: item.node,
      event_type: item.event_type,
      runtime_node: item.runtime_node,
    })),
    [
      {
        node: 'heartbeat',
        event_type: 'heartbeat',
        runtime_node: 'host:xt_producer',
      },
      {
        node: 'bootstrap',
        event_type: 'bootstrap',
        runtime_node: 'host:xt_producer',
      },
    ],
  )
  assert.deepEqual(
    feed[0].summary_metrics.find((item) => item.label === '连接'),
    {
      key: 'connected',
      label: '连接',
      value: 1,
      display: 'yes',
    },
  )
})

test('buildComponentEventFeed hydrates event detail fields and guardian insight for component inspector', () => {
  const feed = buildComponentEventFeed(
    [
      {
        component: 'guardian_strategy',
        runtime_node: 'host:guardian',
        node: 'price_threshold_check',
        event_type: 'trace_step',
        status: 'skipped',
        ts: '2026-03-09T10:00:01+08:00',
        trace_id: 'trc_guardian_evt',
        request_id: 'req_guardian_evt',
        intent_id: 'intent_guardian_evt',
        signal_summary: {
          code: '000001',
          name: 'Ping An Bank',
          position: 'BUY_LONG',
          period: '1m',
          price: 9.8,
        },
        decision_branch: 'holding_add_threshold',
        decision_expr: 'current_price <= bot_river_price',
        reason_code: 'price_threshold_not_met',
        decision_context: {
          threshold: {
            current_price: 9.8,
            bot_river_price: 9.5,
          },
        },
        payload: {
          action: 'BUY',
        },
      },
    ],
    {
      component: 'guardian_strategy',
    },
  )

  assert.equal(feed.length, 1)
  assert.equal(feed[0].symbol_display, '000001 / Ping An Bank')
  assert.equal(feed[0].identity, 'trace trc_guardian_evt')
  assert.equal(feed[0].is_issue, true)
  assert.equal(feed[0].guardian_step?.node_label, '价格阈值判断')
  assert.equal(feed[0].guardian_step?.signal?.title, '000001 Ping An Bank')
  assert.equal(feed[0].guardian_step?.outcome?.reason_code, 'price_threshold_not_met')
  assert.deepEqual(
    feed[0].detail_fields.map((item) => [item.key, item.value]),
    [
      ['trace_id', 'trc_guardian_evt'],
      ['intent_id', 'intent_guardian_evt'],
      ['request_id', 'req_guardian_evt'],
      ['symbol', '000001 / Ping An Bank'],
      ['action', 'BUY'],
    ],
  )
})

test('buildComponentEventFeed recovers symbol display from nested payload fields when top-level symbol is absent', () => {
  const feed = buildComponentEventFeed(
    [
      {
        component: 'order_submit',
        runtime_node: 'host:rear',
        node: 'submit_intent',
        event_type: 'trace_step',
        status: 'success',
        ts: '2026-03-09T10:00:02+08:00',
        payload: {
          symbol: '600000',
          symbol_name: '浦发银行',
          quantity: 300,
        },
      },
    ],
    {
      component: 'order_submit',
    },
  )

  assert.equal(feed.length, 1)
  assert.equal(feed[0].symbol, '600000')
  assert.equal(feed[0].symbol_name, '浦发银行')
  assert.equal(feed[0].symbol_display, '600000 / 浦发银行')
})

test('buildComponentEventEmptyState distinguishes issue-filter empty state from missing runtime events', () => {
  const sourceEvents = [
    {
      component: 'broker_gateway',
      runtime_node: 'host:broker',
      node: 'heartbeat',
      event_type: 'heartbeat',
      status: 'info',
      ts: '2026-03-24T10:00:00+08:00',
    },
  ]
  const allEvents = buildComponentEventFeed(sourceEvents, {
    component: 'broker_gateway',
    onlyIssues: false,
  })
  const issueOnlyEvents = buildComponentEventFeed(sourceEvents, {
    component: 'broker_gateway',
    onlyIssues: true,
  })

  assert.deepEqual(
    buildComponentEventEmptyState({
      component: 'broker_gateway',
      allEvents,
      visibleEvents: issueOnlyEvents,
      onlyIssues: true,
    }),
    {
      title: 'broker_gateway 当前没有异常 Event',
      detail: '当前仍有 1 条正常/心跳事件；关闭“仅异常”后可查看完整组件 Event。',
    },
  )
  assert.deepEqual(
    buildComponentEventEmptyState({
      component: 'broker_gateway',
      allEvents: [],
      visibleEvents: [],
      onlyIssues: false,
    }),
    {
      title: 'broker_gateway 当前时间范围内没有任何 Event',
      detail: '请检查 runtime 原始日志目录、runtime indexer 与组件实际运行状态。',
    },
  )
  assert.deepEqual(
    buildComponentEventEmptyState({
      component: 'tpsl_worker',
      allEvents: [],
      visibleEvents: [],
      onlyIssues: false,
    }),
    {
      title: 'tpsl_worker 当前没有真实触发 Event',
      detail: '未命中止盈止损价、空价格和盘后空跑评估默认不会显示；如需查看原始评估日志，请打开 Raw Browser。',
    },
  )
})

test('buildIdentityStrip preserves all strong ids without dropping symbol and trace metadata', () => {
  assert.deepEqual(
    buildIdentityStrip({
      trace_id: 'trc_dense_1',
      intent_ids: ['intent_dense_1', 'intent_dense_2'],
      intent_id: 'intent_dense_2',
      request_ids: ['req_dense_1', 'req_dense_2'],
      request_id: 'req_dense_2',
      internal_order_ids: ['ord_dense_1', 'ord_dense_2'],
      internal_order_id: 'ord_dense_2',
      symbol: '000001',
      trace_kind: 'guardian_signal',
      trace_status: 'failed',
    }),
    {
      primary: 'trace trc_dense_1',
      items: [
        { key: 'trace_id', label: 'Trace', value: 'trc_dense_1', values: ['trc_dense_1'] },
        { key: 'intent_id', label: 'Intent', value: 'intent_dense_1, intent_dense_2', values: ['intent_dense_1', 'intent_dense_2'] },
        { key: 'request_id', label: 'Request', value: 'req_dense_1, req_dense_2', values: ['req_dense_1', 'req_dense_2'] },
        { key: 'internal_order_id', label: 'Order', value: 'ord_dense_1, ord_dense_2', values: ['ord_dense_1', 'ord_dense_2'] },
        { key: 'symbol', label: 'Symbol', value: '000001 / 未知名称', values: ['000001 / 未知名称'] },
        { key: 'trace_kind', label: 'Kind', value: 'guardian_signal', values: ['guardian_signal'] },
        { key: 'trace_status', label: 'Status', value: 'failed', values: ['failed'] },
      ],
    },
  )
})

test('buildRawSelectionKey scopes embedded raw records to the current selection', () => {
  const traceStepA = {
    trace_id: 'trc_dense_1',
    runtime_node: 'host:guardian',
    component: 'guardian_strategy',
    node: 'timing_check',
    ts: '2026-03-09T10:00:03+08:00',
    index: 1,
  }
  const traceStepB = {
    ...traceStepA,
    node: 'submit_intent',
    ts: '2026-03-09T10:00:04+08:00',
    index: 2,
  }
  const eventA = {
    key: 'event_a',
    runtime_node: 'host:guardian',
    component: 'guardian_strategy',
    node: 'timing_check',
    ts: '2026-03-09T10:00:03+08:00',
  }

  const traceSelectionKey = buildRawSelectionKey(traceStepA, 'traces')
  const eventSelectionKey = buildRawSelectionKey(eventA, 'events')

  assert.ok(traceSelectionKey)
  assert.ok(eventSelectionKey)
  assert.notEqual(traceSelectionKey, buildRawSelectionKey(traceStepB, 'traces'))
  assert.notEqual(traceSelectionKey, eventSelectionKey)
  assert.equal(hasMatchingRawSelection(traceSelectionKey, traceStepA, 'traces'), true)
  assert.equal(hasMatchingRawSelection(traceSelectionKey, traceStepB, 'traces'), false)
  assert.equal(hasMatchingRawSelection(traceSelectionKey, eventA, 'events'), false)
})

test('buildTraceLedgerRows returns dense table rows for recent trace list', () => {
  const rows = buildTraceLedgerRows([
    {
      trace_id: 'trc_dense_1',
      trace_key: 'trace:trc_dense_1',
      trace_kind: 'guardian_signal',
      trace_status: 'failed',
      break_reason: 'unexpected_exception@guardian_strategy.timing_check:ValueError',
      first_ts: '2026-03-09T02:00:00Z',
      last_ts: '2026-03-09T02:00:02Z',
      duration_ms: 2000,
      entry_component: 'guardian_strategy',
      entry_node: 'receive_signal',
      exit_component: 'guardian_strategy',
      exit_node: 'timing_check',
      slowest_step: {
        component: 'guardian_strategy',
        node: 'timing_check',
        delta_prev_ms: 1300,
      },
      request_ids: ['req_dense_1'],
      internal_order_ids: ['ord_dense_1'],
      intent_ids: ['intent_dense_1'],
      symbol: '000001',
      steps: [
        {
          component: 'guardian_strategy',
          node: 'receive_signal',
          status: 'info',
          ts: '2026-03-09T02:00:00Z',
          trace_id: 'trc_dense_1',
          symbol: '000001',
          signal_summary: {
            code: '000001',
            name: '平安银行',
          },
        },
        {
          component: 'guardian_strategy',
          node: 'timing_check',
          status: 'error',
          ts: '2026-03-09T02:00:02Z',
          trace_id: 'trc_dense_1',
          symbol: '000001',
          reason_code: 'unexpected_exception',
          payload: {
            error_type: 'ValueError',
            error_message: 'invalid fill time',
          },
        },
      ],
    },
  ])

  assert.equal(rows.length, 1)
  assert.deepEqual(rows[0], {
    trace_key: 'trace:trc_dense_1',
    trace_id: 'trc_dense_1',
    symbol: '000001',
    symbol_name: '平安银行',
    symbol_display: '000001 / 平安银行',
    trace_kind: 'guardian_signal',
    trace_kind_label: 'Guardian 信号',
    trace_status: 'failed',
    trace_status_label: '失败',
    last_ts: '2026-03-09T02:00:02Z',
    last_ts_label: '2026-03-09 10:00:02',
    duration_ms: 2000,
    duration_label: '2s',
    step_count: 2,
    entry_exit_label: '信号接收 -> 时效判断',
    break_reason: 'unexpected_exception@guardian_strategy.timing_check:ValueError',
    has_issue: true,
  })
})

test('buildTraceLedgerRows falls back to unknown name when symbol name is unavailable', () => {
  const rows = buildTraceLedgerRows([
    {
      trace_id: 'trc_symbol_missing_name',
      trace_key: 'trace:trc_symbol_missing_name',
      trace_kind: 'guardian_signal',
      trace_status: 'open',
      first_ts: '2026-03-09T02:00:00Z',
      last_ts: '2026-03-09T02:00:01Z',
      duration_ms: 1000,
      entry_component: 'guardian_strategy',
      entry_node: 'receive_signal',
      exit_component: 'guardian_strategy',
      exit_node: 'finish',
      symbol: '000001',
      steps: [
        {
          component: 'guardian_strategy',
          node: 'receive_signal',
          status: 'info',
          ts: '2026-03-09T02:00:00Z',
          trace_id: 'trc_symbol_missing_name',
          symbol: '000001',
        },
        {
          component: 'guardian_strategy',
          node: 'finish',
          status: 'success',
          ts: '2026-03-09T02:00:01Z',
          trace_id: 'trc_symbol_missing_name',
          symbol: '000001',
        },
      ],
    },
  ])

  assert.equal(rows.length, 1)
  assert.equal(rows[0].symbol_display, '000001 / 未知名称')
})

test('buildTraceStepLedgerRows surfaces branch expr reason outcome context and error columns', () => {
  const detail = buildTraceDetail({
    trace_id: 'trc_step_dense_1',
    symbol: '000001',
    steps: [
      {
        component: 'guardian_strategy',
        node: 'receive_signal',
        status: 'info',
        ts: '2026-03-09T10:00:00+08:00',
      },
      {
        component: 'guardian_strategy',
        node: 'timing_check',
        status: 'error',
        ts: '2026-03-09T10:00:01.300+08:00',
        reason_code: 'unexpected_exception',
        decision_branch: 'holding_sell_timing',
        decision_expr: 'fill_time >= signal_time',
        decision_context: {
          timing: {
            fill_time: '20260315 23:39:42',
            signal_time: '20260315 23:00:00',
          },
        },
        decision_outcome: {
          outcome: 'reject',
          reason_code: 'unexpected_exception',
        },
        payload: {
          error_type: 'ValueError',
          error_message: 'time data None None does not match format',
        },
      },
    ],
  })

  const rows = buildTraceStepLedgerRows(detail)

  assert.equal(rows.length, 2)
  assert.deepEqual(rows[1], {
    index: 1,
    step_key: 'guardian_strategy|timing_check|2026-03-09T10:00:01.300+08:00|1',
    ts: '2026-03-09T10:00:01.300+08:00',
    ts_label: '2026-03-09 10:00:01',
    delta_label: '1.3s',
    component_node: '时效判断',
    status: 'error',
    branch: 'holding_sell_timing',
    expr: 'fill_time >= signal_time',
    reason: 'unexpected_exception',
    outcome: 'reject',
    context_summary: 'timing.fill_time=20260315 23:39:42; timing.signal_time=20260315 23:00:00',
    error_summary: 'ValueError: time data None None does not match format',
    is_issue: true,
  })
})

test('buildEventLedgerRows keeps heartbeat events and extracts summary and metrics columns', () => {
  const rows = buildEventLedgerRows([
    {
      ts: '2026-03-09T02:05:00Z',
      runtime_node: 'host:xt',
      component: 'xt_producer',
      node: 'heartbeat',
      status: 'info',
      symbol: '',
      metrics: {
        rx_age_s: 3,
        tick_count_5m: 48,
        subscribed_codes: 20,
        connected: 1,
      },
    },
    {
      ts: '2026-03-09T02:05:01Z',
      runtime_node: 'host:guardian',
      component: 'guardian_strategy',
      node: 'timing_check',
      status: 'error',
      symbol: '000001',
      symbol_name: '平安银行',
      trace_id: 'trc_event_dense_1',
      payload: {
        error_type: 'ValueError',
        error_message: 'invalid fill time',
      },
      reason_code: 'unexpected_exception',
      decision_expr: 'fill_time >= signal_time',
    },
  ])

  assert.deepEqual(rows, [
    {
      event_key: '2026-03-09T02:05:00Z|host:xt|xt_producer|heartbeat|0',
      ts: '2026-03-09T02:05:00Z',
      ts_label: '2026-03-09 10:05:00',
      runtime_node: 'host:xt',
      runtime_node_label: 'host:xt',
      component: 'xt_producer',
      component_label: 'XT 行情接收',
      node: 'heartbeat',
      node_label: '心跳',
      status: 'info',
      symbol: '',
      symbol_name: '',
      symbol_display: '-',
      summary: 'heartbeat',
      metrics_summary: '收 tick 3s · 5m ticks 48 · 订阅 20 · 连接 yes',
      is_issue: false,
    },
    {
      event_key: '2026-03-09T02:05:01Z|host:guardian|guardian_strategy|timing_check|1',
      ts: '2026-03-09T02:05:01Z',
      ts_label: '2026-03-09 10:05:01',
      runtime_node: 'host:guardian',
      runtime_node_label: 'host:guardian',
      component: 'guardian_strategy',
      component_label: 'Guardian 策略',
      node: 'timing_check',
      node_label: '时效判断',
      status: 'error',
      symbol: '000001',
      symbol_name: '平安银行',
      symbol_display: '000001 / 平安银行',
      summary: 'unexpected_exception · fill_time >= signal_time · ValueError: invalid fill time',
      metrics_summary: '',
      is_issue: true,
    },
  ])
})

test('filterTracesByKind keeps all traces by default and narrows by selected kind', () => {
  const traces = [
    { trace_id: 'trc_guardian', trace_kind: 'guardian_signal', steps: [] },
    { trace_id: 'trc_takeprofit', trace_kind: 'takeprofit', steps: [] },
    { trace_id: 'trc_stoploss', trace_kind: 'stoploss', steps: [] },
  ]

  assert.deepEqual(
    filterTracesByKind(traces, 'all').map((item) => item.trace_id),
    ['trc_guardian', 'trc_takeprofit', 'trc_stoploss'],
  )
  assert.deepEqual(
    filterTracesByKind(traces, 'takeprofit').map((item) => item.trace_id),
    ['trc_takeprofit'],
  )
})

test('buildTraceKindOptions returns chinese labels for available trace kinds', () => {
  const options = buildTraceKindOptions([
    { trace_kind: 'guardian_signal', steps: [] },
    { trace_kind: 'takeprofit', steps: [] },
    { trace_kind: 'guardian_signal', steps: [] },
  ])

  assert.deepEqual(options, [
    { value: 'all', label: '全部链路' },
    { value: 'guardian_signal', label: 'Guardian 信号' },
    { value: 'takeprofit', label: '止盈链路' },
    { value: 'stoploss', label: '止损链路' },
    { value: 'external_reported', label: '外部上报' },
    { value: 'external_inferred', label: '外部推断' },
    { value: 'manual_api_order', label: '手动下单' },
    { value: 'unknown', label: '未知链路' },
  ])
})

test('pickDefaultTraceKind keeps a valid current kind and otherwise falls back to all', () => {
  assert.equal(
    pickDefaultTraceKind([
      { trace_id: 'trc_guardian', trace_kind: 'guardian_signal', steps: [] },
      { trace_id: 'trc_takeprofit', trace_kind: 'takeprofit', steps: [] },
    ], 'takeprofit'),
    'takeprofit',
  )

  assert.equal(
    pickDefaultTraceKind([
      { trace_id: 'trc_guardian', trace_kind: 'guardian_signal', steps: [] },
      { trace_id: 'trc_takeprofit', trace_kind: 'takeprofit', steps: [] },
    ]),
    'all',
  )

  assert.equal(
    pickDefaultTraceKind([
      { trace_id: 'trc_takeprofit', trace_kind: 'takeprofit', steps: [] },
    ], 'stoploss'),
    'stoploss',
  )
})

test('RuntimeObservability.vue reloads traces from the server when a trace-kind button is clicked', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /<div v-if="activeView === 'traces'" class="runtime-trace-kind-actions">[\s\S]*v-for="option in traceKindOptions"[\s\S]*@click="handleTraceKindClick\(option.value\)"/)
  assert.match(content, /const buildTraceRequestParams = \(\) => \(\{[\s\S]*buildTraceQuery\(query,\s*timeRange\.value\)[\s\S]*selectedTraceKind\.value && selectedTraceKind\.value !== 'all'[\s\S]*trace_kind:\s*selectedTraceKind\.value[\s\S]*\}\)/)
  assert.match(content, /const handleTraceKindClick = async \(kind\) => \{[\s\S]*selectedTraceKind\.value = normalizedKind[\s\S]*await loadTraces\(\)/)
  assert.match(content, /if \(chip\.kind === 'trace-kind'\) \{[\s\S]*await handleTraceKindClick\('all'\)/)
})

test('RuntimeObservability.vue uses trace-kind buttons instead of a trace-kind select dropdown', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(content, /<el-select v-model="selectedTraceKind"/)
  assert.doesNotMatch(content, /pickDefaultTraceKind/)
})

test('RuntimeObservability.vue scopes event reloads with the active sidebar component', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const buildEventRequestParams = \(\) => \(\{[\s\S]*buildBoardScopedQuery\(query,\s*boardFilter,\s*timeRange\.value\)[\s\S]*include_symbol_name:\s*1[\s\S]*limit:\s*EVENT_PAGE_SIZE[\s\S]*\}\)/)
  assert.match(content, /const params = \{[\s\S]*buildEventRequestParams\(\)[\s\S]*cursor_ts[\s\S]*cursor_event_id[\s\S]*\}/)
  assert.match(content, /runtimeObservabilityApi\.listEvents\(params\)/)
  assert.match(content, /watch\(\s*\(\) => \[boardFilter\.component,\s*boardFilter\.runtime_node\],/)
  assert.match(content, /if \(activeView\.value !== 'events'\) return/)
  assert.match(content, /watch\(activeView,\s*async \(view,\s*previousView\) => \{/)
  assert.match(content, /lastLoadedEventQueryKey\.value === buildEventRequestKey\(\)/)
})

test('RuntimeObservability.vue switches to component event view when sidebar component is clicked from global trace', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const handleComponentFilter = async \(target\) => \{[\s\S]*await switchToComponentEvents\(/)
})

test('RuntimeObservability.vue keeps trace issue filtering separate from step issue filtering', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const traceOnlyIssues = ref\(false\)/)
  assert.match(content, /const visibleTraces = computed\(\(\) =>[\s\S]*filterVisibleTraces\(hydratedTraces\.value,\s*\{[\s\S]*issueComponent:\s*traceIssueFocus\.component,[\s\S]*onlyIssueTraces:\s*traceOnlyIssues\.value,[\s\S]*\}\)/)
  assert.match(content, /const handleSummaryJump = async \(target\) => \{[\s\S]*traceOnlyIssues\.value = true[\s\S]*onlyIssues\.value = target === 'issue-steps'/)
  assert.match(content, /const handleComponentIssueTraceJump = async \(item\) => \{[\s\S]*traceOnlyIssues\.value = true[\s\S]*onlyIssues\.value = false/)
})

test('RuntimeObservability.vue resets component event issue filtering when clicking a component card', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const handleComponentFilter = async \(target\) => \{[\s\S]*await switchToComponentEvents\(normalizedComponent,\s*\{\s*onlyIssues:\s*false\s*\}\)/)
})

test('RuntimeObservability.vue renders explicit component event empty-state guidance', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /buildComponentEventEmptyState/)
  assert.match(content, /const allComponentEventFeed = computed\(\(\) => \{[\s\S]*onlyIssues: false,[\s\S]*\}\)/)
  assert.match(content, /const componentEventEmptyState = computed\(\(\) => buildComponentEventEmptyState\(\{[\s\S]*component: activeComponent\.value,[\s\S]*allEvents: allComponentEventFeed\.value,[\s\S]*visibleEvents: componentEventFeed\.value,[\s\S]*onlyIssues: onlyIssues\.value,[\s\S]*\}\)\)/)
  assert.match(content, /<strong>{{ componentEventEmptyState\.title }}<\/strong>/)
  assert.match(content, /<p v-if="componentEventEmptyState\.detail">{{ componentEventEmptyState\.detail }}<\/p>/)
})

test('RuntimeObservability.vue keeps explicit sidebar selection sticky and routes component clicks through one event-switch helper', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const userSelectedComponent = ref\(false\)/)
  assert.match(content, /const switchToComponentEvents = async \(component, options = \{\}\) => \{[\s\S]*userSelectedComponent\.value = true[\s\S]*activeView\.value = 'events'[\s\S]*await loadEvents\(\{ suppressError: true \}\)/)
  assert.match(content, /const handleComponentFilter = async \(target\) => \{[\s\S]*await switchToComponentEvents\(/)
  assert.match(content, /watch\(componentSidebarItems, \(items\) => \{[\s\S]*if \(userSelectedComponent\.value && boardFilter\.component\) return/)
})

test('RuntimeObservability.vue keeps toolbar actions in the left title block and exposes a time range picker', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /<div class="runtime-title-main">[\s\S]*<div class="workbench-title-group">[\s\S]*<div class="runtime-title-actions">/)
  assert.match(content, /<el-date-picker[\s\S]*type="datetimerange"/)
  assert.match(content, /buildTraceQuery\(query,\s*timeRange\.value\)/)
  assert.match(content, /buildBoardScopedQuery\(query,\s*boardFilter,\s*timeRange\.value\)/)
})

test('RuntimeObservability.vue defaults to auto refresh and hides the manual auto-refresh switch', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const autoRefresh = ref\(true\)/)
  assert.doesNotMatch(content, /v-model="autoRefresh"/)
  assert.match(content, /onMounted\(\(\) => \{[\s\S]*resetOverviewTimer\(\)[\s\S]*loadOverview\(\)[\s\S]*\}\)/)
})

test('RuntimeObservability.vue lazily requests trace detail and older step pages for the selected trace', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /runtimeObservabilityApi\.getTraceDetail\(/)
  assert.match(content, /runtimeObservabilityApi\.listTraceSteps\(/)
  assert.match(content, /const loadTraceDetail = async \(traceRow/)
  assert.match(content, /const loadMoreTraceSteps = async \(\) => \{/)
  assert.match(content, /const handleTraceClick = async \(row\) => \{[\s\S]*selectedTrace\.value = selected/)
})

test('RuntimeObservability.vue keeps the right detail pane scrollable at full zoom instead of clipping content', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /:deep\(\.workspace-tabs \.el-tabs__content\) \{[\s\S]*flex:\s*1 1 auto;[\s\S]*overflow:\s*hidden;/)
  assert.match(content, /:deep\(\.workspace-tabs \.el-tab-pane\) \{[\s\S]*flex:\s*1 1 auto;[\s\S]*min-height:\s*0;/)
  assert.match(content, /\.runtime-detail-panel--fill \{[\s\S]*overflow:\s*auto;/)
  assert.match(content, /@media \(max-width: 1920px\) \{[\s\S]*\.runtime-browse-layout \{[\s\S]*grid-template-columns:\s*minmax\(220px,\s*0\.72fr\)\s*minmax\(0,\s*1\.28fr\);[\s\S]*\}[\s\S]*\.runtime-browser-panel--detail \{[\s\S]*grid-column:\s*1 \/ -1;/)
  assert.match(content, /\.runtime-detail-panel--steps \{[\s\S]*min-width:\s*0;/)
  assert.match(content, /\.step-inspector \{[\s\S]*overflow:\s*auto;/)
  assert.match(content, /\.detail-pane-grid--step \{[\s\S]*min-width:\s*0;/)
})

test('RuntimeObservability.vue only renders guardian step tables when guardian metadata exists', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /<section v-if="selectedStep\?\.guardian_step && selectedStepGuardianRows.length" class="detail-ledger-section">/)
  assert.match(content, /<section v-if="selectedStep\?\.guardian_step && selectedStepSignalRows.length" class="detail-ledger-section">/)
})

test('RuntimeObservability.vue requests explicit symbol-name enrichment for traces and events', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const buildTraceRequestParams = \(\) => \(\{[\s\S]*buildTraceQuery\(query,\s*timeRange\.value\)[\s\S]*include_symbol_name:\s*1[\s\S]*\}\)/)
  assert.match(content, /const buildEventRequestParams = \(\) => \(\{[\s\S]*buildBoardScopedQuery\(query,\s*boardFilter,\s*timeRange\.value\)[\s\S]*include_symbol_name:\s*1[\s\S]*\}\)/)
  assert.match(content, /value: selectedTraceDetail\.value\.symbol_display/)
  assert.match(content, /value: selectedEvent\.value\?\.symbol_display/)
})

test('RuntimeObservability.vue surfaces the selected time range as a visible summary chip', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /formatTimeRangeLabel/)
  assert.match(content, /const timeRangeDisplayLabel = computed\(\(\) => formatTimeRangeLabel\(timeRange\.value\)\)/)
  assert.match(content, /展示范围 <strong>{{ timeRangeDisplayLabel }}<\/strong>/)
})

test('RuntimeObservability.vue enriches component event detail with decision fields guardian signal and context sections', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /<section class="detail-ledger-section">\s*<div class="detail-ledger-section__title">事件摘要<\/div>/)
  assert.match(content, /<section v-if="eventDecisionRows\.length \|\| eventDetailFieldRows\.length" class="detail-ledger-section">/)
  assert.match(content, /<div class="detail-ledger-section__title">判断与关联字段<\/div>/)
  assert.match(content, /<section v-if="selectedEvent\?\.guardian_step && eventGuardianRows\.length" class="detail-ledger-section">/)
  assert.match(content, /<section v-if="selectedEvent\?\.guardian_step && eventSignalRows\.length" class="detail-ledger-section">/)
  assert.match(content, /<section v-if="eventContextRows\.length" class="detail-ledger-section detail-ledger-section--full">/)
  assert.match(content, /<div class="detail-ledger-section__title">上下文<\/div>/)
  assert.match(content, /<div class="detail-ledger-section__title">Payload \/ Metrics<\/div>/)
})

test('buildRecentTraceFeed exposes flow nodes with guardian decision detail and generic fallback summary', () => {
  const genericTrace = {
    trace_id: 'trc_generic_flow',
    trace_key: 'trace:trc_generic_flow',
    request_ids: ['req_trc_generic_flow'],
    internal_order_ids: ['ord_trc_generic_flow'],
    steps: [
      {
        component: 'order_submit',
        runtime_node: 'host:order_submit',
        node: 'queue_write',
        status: 'warning',
        ts: '2026-03-09T10:03:00+08:00',
        message: 'queue backlog detected',
        payload: { queue_len: 5 },
      },
    ],
  }

  const feed = buildRecentTraceFeed([makeGuardianTrace(), genericTrace], { limit: 50 })

  const guardianRow = feed.find((item) => item.trace_id === 'trc_guardian')
  assert.ok(guardianRow)
  assert.equal(guardianRow.flow_nodes[1].label, '价格阈值判断')
  assert.equal(
    guardianRow.flow_nodes[1].hover_items.find((item) => item.label === '条件')?.value,
    'current_price <= bot_river_price',
  )
  assert.equal(
    guardianRow.flow_nodes[1].hover_items.find((item) => item.label === '结果')?.value,
    '跳过',
  )
  assert.equal(
    guardianRow.flow_nodes[1].hover_items.find((item) => item.label === '原因')?.value,
    'price_threshold_not_met',
  )

  const genericRow = feed.find((item) => item.trace_id === 'trc_generic_flow')
  assert.ok(genericRow)
  assert.equal(genericRow.flow_nodes[0].label, '下单提交流水.队列写入')
  assert.equal(
    genericRow.flow_nodes[0].hover_items.find((item) => item.label === '结果')?.value,
    'warning',
  )
  assert.match(
    genericRow.flow_nodes[0].hover_items.find((item) => item.label === '摘要')?.value || '',
    /queue backlog detected/,
  )
})

test('buildGuardianTraceSummary and buildGuardianStepInsight expose structured guardian detail blocks', () => {
  const detail = buildTraceDetail(makeGuardianTrace())
  const summary = buildGuardianTraceSummary(detail)
  const stepInsight = buildGuardianStepInsight(detail.steps[1])

  assert.equal(summary.signal.title, '000001 Ping An Bank')
  assert.equal(summary.conclusion.node_label, '结束结论')
  assert.equal(summary.conclusion.label, '跳过')
  assert.equal(summary.conclusion.reason_code, 'price_threshold_not_met')

  assert.equal(stepInsight.node_label, '价格阈值判断')
  assert.equal(stepInsight.outcome.label, '跳过')
  assert.equal(stepInsight.outcome.branch, 'holding_add_threshold')
  assert.equal(stepInsight.outcome.expr, 'current_price <= bot_river_price')
  assert.equal(stepInsight.context_blocks[0].label, '阈值上下文')
  assert.ok(
    stepInsight.context_blocks[0].items.some(
      (item) => item.key === 'current_price' && item.value === '9.8',
    ),
  )
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

test('buildComponentBoard splits host and docker cards for the same component and keeps xt producer visible', () => {
  const traces = [
    {
      trace_id: 'trc_host_order_submit',
      request_ids: ['req_host_order_submit'],
      internal_order_ids: ['ord_host_order_submit'],
      steps: [
        {
          component: 'guardian_strategy',
          runtime_node: 'host:guardian',
          node: 'receive_signal',
          status: 'info',
          ts: '2026-03-09T10:00:00+08:00',
        },
        {
          component: 'order_submit',
          runtime_node: 'host:order_submit',
          node: 'tracking_create',
          status: 'warning',
          ts: '2026-03-09T10:00:02+08:00',
          reason_code: 'host_warning',
        },
      ],
    },
    {
      trace_id: 'trc_docker_order_submit',
      request_ids: ['req_docker_order_submit'],
      internal_order_ids: ['ord_docker_order_submit'],
      steps: [
        {
          component: 'guardian_strategy',
          runtime_node: 'docker:guardian',
          node: 'receive_signal',
          status: 'info',
          ts: '2026-03-09T10:01:00+08:00',
        },
        {
          component: 'order_submit',
          runtime_node: 'docker:order_submit',
          node: 'tracking_create',
          status: 'failed',
          ts: '2026-03-09T10:01:03+08:00',
          reason_code: 'docker_failed',
        },
      ],
    },
  ]

  const board = buildComponentBoard(
    traces,
    buildHealthCards([
      {
        component: 'order_submit',
        runtime_node: 'host:order_submit',
        status: 'warning',
        heartbeat_age_s: 4,
        metrics: { queue_len: 1 },
      },
      {
        component: 'order_submit',
        runtime_node: 'docker:order_submit',
        status: 'failed',
        heartbeat_age_s: 9,
        metrics: { queue_len: 5 },
      },
      {
        component: 'xt_producer',
        runtime_node: 'host:xt_producer',
        status: 'info',
        heartbeat_age_s: 2,
        metrics: { connected: 1 },
      },
    ]),
  )

  assert.deepEqual(
    board.cards
      .filter((card) => card.component === 'order_submit')
      .map((card) => ({
        runtime_node: card.runtime_node,
        issue_trace_count: card.issue_trace_count,
      }))
      .sort((left, right) => left.runtime_node.localeCompare(right.runtime_node)),
    [
      {
        runtime_node: 'docker:order_submit',
        issue_trace_count: 1,
      },
      {
        runtime_node: 'host:order_submit',
        issue_trace_count: 1,
      },
    ],
  )
  assert.ok(board.cards.some((card) => card.component === 'xt_producer'))
})

test('buildComponentBoard keeps placeholder core cards visible and prefers trace runtime nodes over placeholder nodes', () => {
  const board = buildComponentBoard(
    [
      {
        trace_id: 'trc_guardian_only_trace',
        steps: [
          {
            component: 'guardian_strategy',
            runtime_node: 'host:guardian',
            node: 'receive_signal',
            status: 'info',
            ts: '2026-03-09T10:00:00+08:00',
          },
        ],
      },
    ],
    buildHealthCards([
      {
        component: 'guardian_strategy',
        runtime_node: 'docker:guardian',
        status: 'unknown',
        heartbeat_age_s: null,
        metrics: {},
        is_placeholder: true,
      },
      {
        component: 'xt_consumer',
        runtime_node: 'host:xt_consumer',
        status: 'unknown',
        heartbeat_age_s: null,
        metrics: {},
        is_placeholder: true,
      },
    ]),
  )

  assert.deepEqual(
    board.cards
      .filter((card) => ['guardian_strategy', 'xt_consumer'].includes(card.component))
      .map((card) => ({
        component: card.component,
        runtime_node: card.runtime_node,
        status: card.status,
      }))
      .sort((left, right) => left.component.localeCompare(right.component)),
    [
      {
        component: 'guardian_strategy',
        runtime_node: 'host:guardian',
        status: 'unknown',
      },
      {
        component: 'xt_consumer',
        runtime_node: 'host:xt_consumer',
        status: 'unknown',
      },
    ],
  )
})

test('buildComponentSidebarItems keeps fixed core order and preserves placeholder components', () => {
  const items = buildComponentSidebarItems(
    [
      {
        trace_id: 'trc_guardian_only_trace',
        trace_key: 'trace:trc_guardian_only_trace',
        request_ids: ['req_guardian_only_trace'],
        internal_order_ids: [],
        steps: [
          {
            component: 'guardian_strategy',
            runtime_node: 'host:guardian',
            node: 'receive_signal',
            status: 'info',
            ts: '2026-03-09T10:00:00+08:00',
          },
          {
            component: 'guardian_strategy',
            runtime_node: 'host:guardian',
            node: 'finish',
            status: 'skipped',
            ts: '2026-03-09T10:00:02+08:00',
            reason_code: 'price_threshold_not_met',
          },
        ],
      },
    ],
    buildHealthCards([
      {
        component: 'xt_producer',
        runtime_node: 'host:xt_producer',
        status: 'info',
        heartbeat_age_s: 2,
        metrics: { connected: 1 },
      },
      {
        component: 'guardian_strategy',
        runtime_node: 'docker:guardian',
        status: 'unknown',
        heartbeat_age_s: null,
        metrics: {},
        is_placeholder: true,
      },
      {
        component: 'xt_consumer',
        runtime_node: 'host:xt_consumer',
        status: 'unknown',
        heartbeat_age_s: null,
        metrics: {},
        is_placeholder: true,
      },
    ]),
  )

  assert.equal(items.length, 10)
  assert.deepEqual(
    items.slice(0, 5).map((item) => item.component),
    ['xt_producer', 'xt_consumer', 'guardian_strategy', 'position_gate', 'order_submit'],
  )
  assert.equal(items[0].heartbeat_label, '2s')
  assert.equal(items[0].runtime_details[0].runtime_node, 'host:xt_producer')

  const guardian = items.find((item) => item.component === 'guardian_strategy')
  assert.ok(guardian)
  assert.equal(guardian.component_label, 'Guardian 策略')
  assert.equal(guardian.issue_trace_count, 1)
  assert.equal(guardian.issue_step_count, 1)
  assert.equal(guardian.runtime_details[0].runtime_node, 'host:guardian')
  assert.match(guardian.runtime_summary_label, /host:guardian/)

  const xtConsumer = items.find((item) => item.component === 'xt_consumer')
  assert.ok(xtConsumer)
  assert.equal(xtConsumer.status, 'unknown')
  assert.equal(xtConsumer.heartbeat_label, 'no data')
})

test('pickDefaultSidebarComponent waits for traced components before auto-selecting the sidebar', () => {
  const healthCards = buildHealthCards([
    {
      component: 'xt_producer',
      runtime_node: 'host:xt_producer',
      status: 'info',
      heartbeat_age_s: 2,
      metrics: { connected: 1 },
    },
  ])

  const emptyItems = buildComponentSidebarItems([], healthCards)
  assert.equal(pickDefaultSidebarComponent(emptyItems, ''), '')

  const tracedItems = buildComponentSidebarItems(
    [
      makeTrace({
        traceId: 'trc_sidebar_auto_select',
        component: 'order_submit',
        issueComponent: 'order_submit',
        status: 'warning',
        issueCount: 0,
        lastTs: '2026-03-09T10:00:10+08:00',
      }),
    ],
    healthCards,
  )

  assert.equal(pickDefaultSidebarComponent(tracedItems, ''), 'guardian_strategy')
  assert.equal(pickDefaultSidebarComponent(tracedItems, 'xt_producer'), 'xt_producer')
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

test('applyBoardFilter narrows traces by selected runtime node and component', () => {
  const traces = [
    {
      trace_id: 'trc_host_order_submit',
      steps: [
        {
          component: 'order_submit',
          runtime_node: 'host:order_submit',
          node: 'tracking_create',
          status: 'warning',
          ts: '2026-03-09T10:00:10+08:00',
        },
      ],
    },
    {
      trace_id: 'trc_docker_order_submit',
      steps: [
        {
          component: 'order_submit',
          runtime_node: 'docker:order_submit',
          node: 'tracking_create',
          status: 'failed',
          ts: '2026-03-09T10:00:12+08:00',
        },
      ],
    },
  ]

  const filtered = applyBoardFilter(traces, {
    component: 'order_submit',
    runtime_node: 'host:order_submit',
  })

  assert.deepEqual(filtered.map((trace) => trace.trace_id), ['trc_host_order_submit'])
})

test('component filter narrows issue cards and recent feed together', () => {
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
  const cards = buildIssuePriorityCards(filtered)
  const feed = buildRecentTraceFeed(filtered)

  assert.deepEqual(cards.map((card) => card.trace_id), ['trc_order_submit'])
  assert.deepEqual(feed.map((item) => item.trace_id), ['trc_order_submit'])
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
        metrics: {
          rx_age_s: 1.2,
          tick_count_5m: 48,
          subscribed_codes: 20,
          connected: 1,
          ignored: 3,
        },
      },
    ]),
    [
      {
        component: 'xt_producer',
        runtime_node: 'host:xt_producer',
        status: 'info',
        heartbeat_age_s: 12,
        heartbeat_label: '12s',
        is_placeholder: false,
        highlights: [
          { key: 'rx_age_s', label: '收 tick', value: 1.2, display: '1.2s' },
          { key: 'tick_count_5m', label: '5m ticks', value: 48, display: '48' },
          { key: 'subscribed_codes', label: '订阅', value: 20, display: '20' },
          { key: 'connected', label: '连接', value: 1, display: 'yes' },
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
        ts: '2026-03-09T02:00:00Z',
      },
      {
        component: 'position_gate',
        node: 'decision',
        status: 'skipped',
        ts: '2026-03-09T02:00:00.250Z',
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
  assert.equal(detail.first_ts_label, '2026-03-09 10:00:00')
  assert.equal(detail.last_ts_label, '2026-03-09 10:00:00')
  assert.equal(detail.first_issue.node, 'decision')
  assert.equal(detail.steps[0].ts_label, '2026-03-09 10:00:00')
  assert.equal(detail.steps[1].ts_label, '2026-03-09 10:00:00')
  assert.equal(detail.steps[1].delta_from_prev_label, '250ms')
  assert.equal(detail.steps[1].is_issue, true)
  assert.deepEqual(
    detail.steps[1].tags.map((item) => item.key),
    ['decision_branch', 'reason_code', 'decision_expr'],
  )
  assert.match(detail.steps[1].payload_text, /"quantity": 300/)
})

test('buildTraceDetail preserves summary counts before steps are lazily loaded', () => {
  const detail = buildTraceDetail({
    trace_key: 'trace__trc_summary_only',
    trace_id: 'trc_summary_only',
    trace_kind: 'guardian_signal',
    trace_status: 'failed',
    break_reason: 'failed@order_submit.queue_payload_build:ValueError',
    first_ts: '2026-03-09T10:00:00+08:00',
    last_ts: '2026-03-09T10:00:02+08:00',
    duration_ms: 2000,
    entry_component: 'guardian_strategy',
    entry_node: 'receive_signal',
    exit_component: 'order_submit',
    exit_node: 'queue_payload_build',
    step_count: 4,
    issue_count: 1,
    symbol: '000001',
    symbol_name: 'Ping An Bank',
    affected_components: ['guardian_strategy', 'order_submit'],
  })

  assert.equal(detail.steps.length, 0)
  assert.equal(detail.step_count, 4)
  assert.equal(detail.issue_count, 1)
  assert.equal(detail.duration_label, '2s')
  assert.deepEqual(detail.affected_components, ['guardian_strategy', 'order_submit'])
})

test('buildTraceListSummary supports summary-only trace rows', () => {
  const summary = buildTraceListSummary([
    {
      trace_key: 'trace__trc_1',
      trace_status: 'failed',
      issue_count: 2,
      step_count: 5,
      exit_component: 'broker_gateway',
      affected_components: ['broker_gateway'],
    },
    {
      trace_key: 'trace__trc_2',
      trace_status: 'completed',
      issue_count: 0,
      step_count: 3,
      exit_component: 'order_submit',
      affected_components: [],
    },
  ])

  assert.equal(summary.trace_count, 2)
  assert.equal(summary.issue_trace_count, 1)
  assert.equal(summary.issue_step_count, 2)
  assert.deepEqual(summary.components, [
    { component: 'broker_gateway', issue_count: 2, trace_count: 1 },
  ])
})

test('buildComponentSidebarItems uses health summary counters without requiring trace steps', () => {
  const items = buildComponentSidebarItems(
    [
      {
        trace_key: 'trace__trc_order_submit',
        trace_status: 'failed',
        issue_count: 1,
        step_count: 4,
        exit_component: 'order_submit',
        affected_components: ['order_submit'],
      },
    ],
    [
      {
        component: 'order_submit',
        runtime_node: 'host:rear',
        status: 'warning',
        heartbeat_age_s: 5,
        issue_trace_count: 3,
        issue_step_count: 4,
        trace_count: 7,
        last_issue_ts: '2026-03-09T10:00:03+08:00',
        metrics: { queue_len: 3 },
      },
    ],
  )

  const card = items.find((item) => item.component === 'order_submit')
  assert.ok(card)
  assert.equal(card.status, 'warning')
  assert.equal(card.issue_trace_count, 3)
  assert.equal(card.issue_step_count, 4)
  assert.equal(card.trace_count, 7)
  assert.equal(card.runtime_details[0].runtime_node, 'host:rear')
})

test('formatTimestampLabel converts timestamps to Beijing time with second precision', () => {
  assert.equal(formatTimestampLabel('2026-03-09T02:05:01.987Z'), '2026-03-09 10:05:01')
  assert.equal(formatTimestampLabel('2026-03-09T10:05:01+08:00'), '2026-03-09 10:05:01')
  assert.equal(formatTimestampLabel(''), '')
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

test('formatDurationMs normalizes rounded minute rollover for heartbeat labels', () => {
  assert.equal(formatDurationMs(119500), '2m')
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
      symbol_name: '浦发银行',
      payload: { quantity: 300 },
    },
  ]

  assert.equal(findRawRecordIndex(records, step), 1)
  assert.deepEqual(buildRawRecordSummary(records[1]), {
    title: 'order_submit.queue_write',
    subtitle: '2026-03-09 10:00:01',
    badges: ['trace trc_1', 'request req_1', 'order ord_1', 'symbol 600000 / 浦发银行'],
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

test('filterTracesByIssueComponent keeps only traces where the target component actually raised issues', () => {
  const traces = [
    {
      trace_id: 'trc_guardian_issue',
      steps: [
        { component: 'guardian_strategy', node: 'receive_signal', status: 'warning' },
        { component: 'order_submit', node: 'queue_write', status: 'success' },
      ],
    },
    {
      trace_id: 'trc_guardian_clean',
      steps: [
        { component: 'guardian_strategy', node: 'receive_signal', status: 'success' },
        { component: 'order_submit', node: 'submit_result', status: 'failed' },
      ],
    },
    {
      trace_id: 'trc_summary_only',
      issue_count: 3,
      affected_components: ['guardian_strategy'],
      steps: [],
    },
  ]

  assert.deepEqual(
    filterTracesByIssueComponent(traces, 'guardian_strategy').map((trace) => trace.trace_id),
    ['trc_guardian_issue', 'trc_summary_only'],
  )
  assert.deepEqual(
    filterTracesByIssueComponent(traces, 'order_submit').map((trace) => trace.trace_id),
    ['trc_guardian_clean'],
  )
})

test('pickTraceAnchorStep locates first previous next issue steps and the slowest step', () => {
  const detail = buildTraceDetail({
    steps: [
      {
        component: 'guardian_strategy',
        node: 'receive_signal',
        status: 'info',
        ts: '2026-03-09T10:00:00+08:00',
      },
      {
        component: 'guardian_strategy',
        node: 'price_threshold_check',
        status: 'warning',
        ts: '2026-03-09T10:00:00.500+08:00',
      },
      {
        component: 'order_submit',
        node: 'queue_write',
        status: 'success',
        ts: '2026-03-09T10:00:01.100+08:00',
      },
      {
        component: 'broker_gateway',
        node: 'submit_result',
        status: 'failed',
        ts: '2026-03-09T10:00:02.500+08:00',
      },
    ],
  })

  assert.equal(pickTraceAnchorStep(detail, null, 'first-issue')?.index, 1)
  assert.equal(pickTraceAnchorStep(detail, detail.steps[2], 'previous-issue')?.index, 1)
  assert.equal(pickTraceAnchorStep(detail, detail.steps[2], 'next-issue')?.index, 3)
  assert.equal(pickTraceAnchorStep(detail, detail.steps[3], 'next-issue'), null)
  assert.equal(pickTraceAnchorStep(detail, detail.steps[0], 'slowest-step')?.index, 3)
})

test('runtime observability trace mode uses dense ledger layout instead of trace feed cards', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /runtime-ledger runtime-trace-ledger/)
  assert.match(content, /<el-tabs v-model="activeTraceDetailTab" class="workspace-tabs trace-detail-tabs"/)
  assert.match(content, /<div class="workspace-tab-label">\s*<span>步骤<\/span>/)
  assert.match(content, /<div class="workspace-tab-label">\s*<span>摘要<\/span>/)
  assert.match(content, /<div class="workspace-tab-label">\s*<span>原始数据<\/span>/)
  assert.match(content, /\.trace-detail-body--stacked \{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\);/)
  assert.match(content, /:deep\(\.workspace-tabs \.el-tabs__content\)/)
  assert.match(content, /detail-pane-grid/)
  assert.match(content, /detail-kv-table/)
  assert.match(content, /trace-summary-ledger/)
  assert.match(content, /embedded-raw-ledger/)
  assert.match(content, /trace-step-ledger/)
  assert.match(content, /<section v-show="activeTraceDetailTab === 'steps'" class="runtime-detail-panel runtime-detail-panel--steps">/)
  assert.match(content, /buildTraceLedgerRows/)
  assert.match(content, /buildTraceStepLedgerRows/)
  assert.match(content, /traceKindOptions/)
  assert.match(content, /handleSummaryJump\('issue-traces'\)/)
  assert.match(content, /handleSummaryJump\('issue-steps'\)/)
  assert.match(content, /handleComponentIssueTraceJump\(item\)/)
  assert.match(content, /handleComponentIssueEventJump\(item\)/)
  assert.match(content, /trace-ledger-toolbar__actions/)
  assert.match(content, /首个异常/)
  assert.match(content, /上一个异常/)
  assert.match(content, /下一个异常/)
  assert.match(content, /最慢节点/)
  assert.match(content, /<span>标的<\/span>/)
  assert.match(content, /row\.symbol_display/)
  assert.match(content, /value: selectedTraceDetail\.value\.symbol_display/)
  assert.match(content, /runtime-ledger__cell--entry-exit/)
  assert.match(content, /runtime-ledger__cell--status/)
  assert.match(content, /component-symbol-list/)
  assert.match(content, /component-symbol-card/)
  assert.match(content, /grid-template-columns:\s*minmax\(200px,\s*0\.58fr\)\s*minmax\(820px,\s*2\.42fr\)\s*minmax\(400px,\s*1\.08fr\)/)
  assert.match(content, /\.runtime-trace-ledger__grid \{[\s\S]*152px[\s\S]*minmax\(220px,\s*1\.15fr\)[\s\S]*104px[\s\S]*102px[\s\S]*minmax\(480px,\s*3\.6fr\)[\s\S]*54px[\s\S]*84px[\s\S]*minmax\(160px,\s*0\.9fr\)/)
  assert.match(content, /步骤/)
  assert.match(content, /摘要/)
  assert.match(content, /原始数据/)
  assert.match(content, /\.runtime-detail-panel--steps \{[\s\S]*display:\s*flex;[\s\S]*flex-direction:\s*column;[\s\S]*flex:\s*1 1 auto;/)
  assert.match(content, /\.trace-step-ledger \{[\s\S]*flex:\s*0 0 auto;[\s\S]*max-height:\s*calc\(var\(--trace-step-ledger-row-height\)\s*\*\s*9/)
  assert.match(content, /\.trace-step-ledger__header,\s*\.trace-step-ledger__row \{[\s\S]*min-height:\s*var\(--trace-step-ledger-row-height\);/)
  assert.match(content, /\.step-inspector \{[\s\S]*flex:\s*1 1 auto;[\s\S]*overflow:\s*auto;/)
  assert.doesNotMatch(content, /trace-feed-row/)
  assert.doesNotMatch(content, /trace-flow-strip/)
  assert.doesNotMatch(content, /trace-group-card/)
  assert.doesNotMatch(content, /trace-summary-card/)
  assert.doesNotMatch(content, /guardian-trace-card/)
  assert.doesNotMatch(content, /guardian-signal-card/)
  assert.doesNotMatch(content, /recentTraceLimit/)
  assert.doesNotMatch(content, /showMoreRecentTraces/)
  assert.doesNotMatch(content, /traceIdentityStrip/)
  assert.doesNotMatch(content, /<span>identity<\/span>/)
  assert.doesNotMatch(content, /<span>slowest<\/span>/)
  assert.doesNotMatch(content, /raw-record-list raw-record-list--embedded/)
  assert.doesNotMatch(content, /<div class="runtime-detail-tabs">[\s\S]*activeTraceDetailTab/)
})

test('runtime observability event mode uses dense ledger layout instead of event feed cards', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /runtime-ledger runtime-event-ledger/)
  assert.match(content, /<el-tabs v-model="activeEventDetailTab" class="workspace-tabs event-detail-tabs"/)
  assert.match(content, /<div class="workspace-tab-label">\s*<span>事件<\/span>/)
  assert.match(content, /<div class="workspace-tab-label">\s*<span>载荷<\/span>/)
  assert.match(content, /<div class="workspace-tab-label">\s*<span>原始数据<\/span>/)
  assert.match(content, /buildEventLedgerRows/)
  assert.match(content, /embeddedRawRecordCards/)
  assert.match(content, /event-detail-ledger/)
  assert.match(content, /detail-kv-table/)
  assert.match(content, /embedded-raw-ledger/)
  assert.match(content, /runtime-ledger__cell--status/)
  assert.match(content, /<span>运行时间<\/span>/)
  assert.match(content, /<span>运行节点<\/span>/)
  assert.match(content, /<span>组件<\/span>/)
  assert.match(content, /<span>节点<\/span>/)
  assert.match(content, /<span>标的<\/span>/)
  assert.match(content, /:deep\(\.workspace-tabs \.el-tabs__content\)/)
  assert.doesNotMatch(content, /event-feed-row/)
  assert.doesNotMatch(content, /<section v-show="activeEventDetailTab === 'payload'" class="runtime-detail-panel">/)
  assert.doesNotMatch(content, /raw-record-list raw-record-list--embedded/)
})

test('RuntimeObservability.vue lets zero-issue chips pass clicks through to the component card', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /\.component-symbol-card__action\.is-disabled\s*\{[\s\S]*pointer-events:\s*none;/)
})

test('RuntimeObservability.vue keeps step and raw DOM registries outside Vue reactivity to avoid render-time update loops', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')

  assert.match(content, /const stepRowRefs = new Map\(\)/)
  assert.match(content, /const rawRecordRefs = new Map\(\)/)
  assert.match(content, /const setStepRowRef = \(element, key\) => \{[\s\S]*stepRowRefs\.set\(key, element \|\| null\)/)
  assert.match(content, /const setRawRecordRef = \(element, index\) => \{[\s\S]*rawRecordRefs\.set\(index, element \|\| null\)/)
  assert.match(content, /stepRowRefs\.get\(key\)\?\.scrollIntoView/)
  assert.match(content, /rawRecordRefs\.get\(rawFocusedIndex\.value\)\?\.scrollIntoView/)
  assert.doesNotMatch(content, /stepRowRefs\.value = \{/)
  assert.doesNotMatch(content, /rawRecordRefs\.value = \{/)
})
