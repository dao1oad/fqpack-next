import test from 'node:test'
import assert from 'node:assert/strict'

import {
  OPS_KPI_ORDER,
  OPS_SEGMENT_ORDER,
  buildIssueRows,
  buildKpiCards,
  buildRuntimeLogLink,
  buildSegments,
  countDegradedKpis,
  countIssueEvents,
  deriveOverallHealth,
  deriveSessionLabel,
  deriveToneVariant,
  formatAge,
  formatTimestamp
} from './opsConsole.mjs'

test('deriveOverallHealth aggregates worst tone across KPIs', () => {
  assert.equal(deriveOverallHealth({}).tone, 'unknown')
  assert.equal(
    deriveOverallHealth({
      a: { tone: 'ok' },
      b: { tone: 'warn' }
    }).tone,
    'warn'
  )
  assert.equal(
    deriveOverallHealth({
      a: { tone: 'ok' },
      b: { tone: 'warn' },
      c: { tone: 'error' }
    }).tone,
    'error'
  )
  assert.equal(
    deriveOverallHealth({
      a: { tone: 'ok' },
      b: { tone: 'placeholder' }
    }).tone,
    'ok'
  )
})

test('countDegradedKpis counts degraded and error cards only', () => {
  assert.equal(countDegradedKpis({}), 0)
  assert.equal(
    countDegradedKpis({
      a: { status: 'degraded' },
      b: { status: 'error' },
      c: { status: 'ok' },
      d: { status: 'warn' }
    }),
    2
  )
})

test('countIssueEvents sums trace and step issue events', () => {
  assert.equal(countIssueEvents({}), 0)
  assert.equal(countIssueEvents({ issue_trace_count: 3, issue_step_count: 5 }), 8)
})

test('buildKpiCards keeps the documented 8-card order with fallback rows', () => {
  const cards = buildKpiCards({ xtdata_connection: { tone: 'ok', summary: 'connected' } })
  assert.deepEqual(
    cards.map((card) => card.key),
    OPS_KPI_ORDER
  )
  assert.equal(cards.length, 8)
  assert.equal(cards[0].label, 'Supervisor 进程')
  assert.equal(cards[2].summary, 'connected')
  assert.equal(cards[3].tone, 'unknown')
})

test('buildSegments preserves producer -> consumer -> kline_api pipeline order', () => {
  const segments = buildSegments({ consumer: { summary: '停更' } })
  assert.deepEqual(
    segments.map((segment) => segment.key),
    OPS_SEGMENT_ORDER
  )
  assert.equal(segments[0].label, 'producer')
  assert.equal(segments[1].summary, '停更')
  assert.equal(segments[2].label, 'K 线 API')
})

test('deriveSessionLabel maps backend session codes to Chinese labels', () => {
  assert.equal(deriveSessionLabel({ session: 'auction' }), '竞价')
  assert.equal(deriveSessionLabel({ session: 'morning' }), '盘中')
  assert.equal(deriveSessionLabel({ session: 'post_close' }), '盘后')
  assert.equal(deriveSessionLabel({ session: 'non_trade_day' }), '非交易日')
  assert.equal(deriveSessionLabel({}), '时段未知')
})

test('deriveToneVariant maps tones to StatusChip variants', () => {
  assert.equal(deriveToneVariant('ok'), 'success')
  assert.equal(deriveToneVariant('warn'), 'warning')
  assert.equal(deriveToneVariant('degraded'), 'warning')
  assert.equal(deriveToneVariant('error'), 'danger')
  assert.equal(deriveToneVariant('placeholder'), 'skipped')
  assert.equal(deriveToneVariant('unknown'), 'muted')
})

test('formatAge renders seconds, minutes and hours compactly', () => {
  assert.equal(formatAge(null), '-')
  assert.equal(formatAge(undefined), '-')
  assert.equal(formatAge(12), '12s')
  assert.equal(formatAge(90), '2m')
  assert.equal(formatAge(7200), '2.0h')
})

test('formatTimestamp keeps date and minute precision', () => {
  assert.equal(formatTimestamp(null), '-')
  assert.equal(
    formatTimestamp('2026-08-07T16:15:32+08:00'),
    '2026-08-07 16:15'
  )
})

test('buildIssueRows filters by time range and keeps unknown timestamps out', () => {
  const issues = {
    components: [
      {
        component: 'guardian_strategy',
        status: 'warning',
        issue_trace_count: 2,
        issue_step_count: 3,
        last_issue_ts: '2026-08-07T16:15:32+08:00'
      },
      {
        component: 'xt_producer',
        status: 'error',
        issue_trace_count: 1,
        issue_step_count: 1,
        last_issue_ts: '2026-08-07T09:30:00+08:00'
      }
    ]
  }
  assert.equal(buildIssueRows(issues).length, 2)
  assert.equal(
    buildIssueRows(issues, {
      start: '2026-08-07T10:00:00+08:00',
      end: '2026-08-07T23:59:59+08:00'
    }).length,
    1
  )
  assert.deepEqual(
    buildIssueRows({ components: [{ component: 'a', last_issue_ts: null }] }, {
      start: '2026-08-07T00:00:00+08:00',
      end: '2026-08-07T23:59:59+08:00'
    }),
    []
  )
})

test('buildRuntimeLogLink jumps to runtime observability with component filter', () => {
  assert.deepEqual(buildRuntimeLogLink('xt_consumer'), {
    path: '/runtime-observability',
    query: { component: 'xt_consumer' }
  })
  assert.deepEqual(buildRuntimeLogLink(null), {
    path: '/runtime-observability',
    query: {}
  })
})
