import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildPositionReviewDetailKpis,
  buildPositionReviewSummaryKpis,
  formatPositionReviewSignedInteger,
  isPositionReviewFiniteNonZero,
  normalizePositionReviewDetail,
  normalizePositionReviewSummary,
  normalizePositionReviewSymbolRows,
  readPositionReviewPayload,
  resolvePositionReviewSelectedSymbol,
  runPositionReviewCatalogFilter,
  runPositionReviewRefresh,
} from './positionReview.mjs'

test('readPositionReviewPayload accepts interceptor-unwrapped and axios envelope payloads', () => {
  assert.deepEqual(readPositionReviewPayload({ totals: { symbols: 2 } }), {
    totals: { symbols: 2 },
  })
  assert.deepEqual(readPositionReviewPayload({ data: { totals: { symbols: 3 } } }), {
    totals: { symbols: 3 },
  })
  assert.deepEqual(readPositionReviewPayload(null), {})
})

test('normalizePositionReviewSummary keeps insufficient evidence outside pass rate', () => {
  const summary = normalizePositionReviewSummary({
    generated_at: '2026-07-23T10:30:00+08:00',
    totals: {
      symbols: 8,
      requests: 20,
      reviewable: 16,
      anomaly_symbols: 2,
      pass_rate: 0.875,
    },
    verdict_counts: {
      PASS: 14,
      FAIL: 2,
      INSUFFICIENT_EVIDENCE: 3,
      NOT_APPLICABLE: 1,
    },
    data_quality: {
      canonical_trade_source: 'xt_trades',
      warnings: ['legacy aggregate excluded'],
    },
  })

  assert.equal(summary.symbolCount, 8)
  assert.equal(summary.requestCount, 20)
  assert.equal(summary.reviewableCount, 16)
  assert.equal(summary.counts.COMPLIANT, 14)
  assert.equal(summary.counts.ANOMALY, 2)
  assert.equal(summary.counts.UNVERIFIABLE, 3)
  assert.equal(summary.passRateLabel, '87.5%')
  assert.equal(summary.statusDistribution.reduce((sum, item) => sum + item.value, 0), 20)
  assert.equal(summary.dataQuality.canonicalTradeSource, 'xt_trades')
  assert.equal(summary.dataQuality.warningCount, 1)
})

test('structured data quality warnings render readable code and message text', () => {
  const summary = normalizePositionReviewSummary({
    data_quality: {
      canonical_trade_source: 'execution_history_archive_then_current_xt_om_union',
      warnings: [
        {
          code: 'runtime_evidence_unavailable',
          message: 'ClickHouse runtime evidence unavailable',
        },
        {
          code: 'trade_association_degraded',
          broker_trade_id: 'trade-55',
          association_quality: 'low',
        },
        {
          code: 'catalog_data_quality_degraded',
          message: '部分标的数据质量存在告警，请进入详情核查。',
        },
      ],
    },
  })

  assert.deepEqual(summary.dataQuality.warnings, [
    '运行时证据不可用：ClickHouse runtime evidence unavailable',
    '成交关联质量下降（broker_trade_id=trade-55，association_quality=low）',
    '部分标的数据质量存在告警：部分标的数据质量存在告警，请进入详情核查。',
  ])
  assert.equal(summary.dataQuality.canonicalTradeSourceLabel, '历史成交档案 + 当前 XT/OM')
  assert.equal(summary.dataQuality.warningDetails[0].code, 'runtime_evidence_unavailable')
  assert.equal(summary.dataQuality.warnings.some((item) => item.includes('[object Object]')), false)
})

test('normalizePositionReviewSymbolRows prioritizes anomalies and keeps cleared symbols', () => {
  const result = normalizePositionReviewSymbolRows({
    rows: [
      {
        symbol: '000001',
        name: '平安银行',
        current_quantity: 0,
        is_holding: false,
        last_trade_at: '2026-07-20T10:00:00+08:00',
        request_count: 2,
        review_counts: { PASS: 2 },
        verdict: 'PASS',
        pass_rate: 1,
      },
      {
        symbol: '002262',
        name: '恩华药业',
        current_quantity: 29300,
        is_holding: true,
        last_trade_at: '2026-07-22T10:00:00+08:00',
        request_count: 15,
        review_counts: { PASS: 14, FAIL: 1 },
        verdict: 'FAIL',
        pass_rate: 14 / 15,
      },
    ],
    total: 2,
    page: 1,
    size: 50,
  })

  assert.deepEqual(result.rows.map((row) => row.symbol), ['002262', '000001'])
  assert.equal(result.rows[0].status, 'ANOMALY')
  assert.equal(result.rows[0].counts.ANOMALY, 1)
  assert.equal(result.rows[1].isHolding, false)
  assert.equal(result.rows[1].currentQuantity, 0)
})

test('normalizePositionReviewDetail reconstructs the full April 29 review contract', () => {
  const detail = normalizePositionReviewDetail({
    symbol: {
      code: '002262',
      name: '恩华药业',
      current_quantity: 29300,
      is_holding: true,
    },
    summary: {
      request_count: 15,
      fill_count: 15,
      buy_quantity: 25500,
      sell_quantity: 20800,
      review_counts: {
        PASS: 14,
        FAIL: 1,
      },
      pass_rate: 14 / 15,
      first_trade_at: '2026-04-13T14:22:00+08:00',
      last_trade_at: '2026-07-22T10:00:00+08:00',
    },
    charts: {
      cumulative_quantity: [
        { time: '2026-04-29T10:14:07+08:00', value: 26800 },
        { time: '2026-04-29T10:33:07+08:00', value: 22300 },
      ],
      traded_amount: [
        { date: '2026-04-29', buy: 0, sell: 151963 },
      ],
      trade_price: [
        {
          time: '2026-04-29T10:14:07+08:00',
          side: 'sell',
          price: 22.41,
          quantity: 2300,
          request_id: 'req-first',
          verdict: 'PASS',
        },
        {
          time: '2026-04-29T10:33:07+08:00',
          side: 'sell',
          price: 22.43,
          quantity: 4500,
          request_id: 'req-second',
          verdict: 'FAIL',
        },
      ],
      request_quantity_compare: [
        {
          time: '2026-04-29T10:14:00+08:00',
          requested: 2300,
          expected: 2300,
          filled: 2300,
          request_id: 'req-first',
          verdict: 'PASS',
        },
        {
          time: '2026-04-29T10:33:00+08:00',
          requested: 4500,
          expected: 0,
          filled: 4500,
          request_id: 'req-second',
          verdict: 'FAIL',
        },
      ],
    },
    reviews: [
      {
        review_id: 'review-first',
        request_id: 'req-first',
        time: '2026-04-29T10:14:00+08:00',
        side: 'sell',
        request: { price: 22.41, quantity: 2300 },
        expected: {
          quantity: 2300,
          threshold_price: 21.5332,
          lowest_guardian_price: 21.32,
          formula: 'floor100(min(2300, 29100))',
          source_entries: [{ entry_id: 'entry-apr23', quantity: 2300 }],
        },
        actual: {
          filled_quantity: 2300,
          avg_filled_price: 22.41,
          fill_count: 1,
        },
        verdict: 'PASS',
        evidence_confidence: 'HIGH',
      },
      {
        review_id: 'review-second',
        request_id: 'req-second',
        internal_order_id: 'ord-second',
        trace_id: 'trc-second',
        time: '2026-04-29T10:33:00+08:00',
        side: 'sell',
        request: { price: 22.43, quantity: 4500 },
        expected: {
          quantity: 0,
          threshold_price: 22.6341,
          lowest_guardian_price: 22.41,
          formula: '22.43 < 22.6341, skip',
        },
        actual: {
          filled_quantity: 4500,
          avg_filled_price: 22.43,
          fill_count: 1,
        },
        verdict: 'FAIL',
        reason_codes: ['SELL_THRESHOLD_NOT_MET'],
        evidence_confidence: 'HIGH',
      },
    ],
    data_quality: {
      canonical_trade_source: 'xt_trades',
    },
  })

  assert.equal(detail.symbol, '002262')
  assert.equal(detail.name, '恩华药业')
  assert.equal(detail.reviews.length, 2)
  assert.equal(detail.reviews[0].status, 'COMPLIANT')
  assert.equal(detail.reviews[0].expectedQuantity, 2300)
  assert.equal(detail.reviews[1].status, 'ANOMALY')
  assert.equal(detail.reviews[1].expectedQuantity, 0)
  assert.equal(detail.reviews[1].actualQuantity, 4500)
  assert.equal(detail.reviews[1].quantityDelta, 4500)
  assert.equal(detail.reviews[1].thresholdPrice, 22.6341)
  assert.equal(detail.counts.COMPLIANT, 14)
  assert.equal(detail.counts.ANOMALY, 1)
  assert.equal(detail.monthlyActivity[0].month, '2026-04')
  assert.equal(detail.positionPoints[1].value, 22300)
  assert.equal(detail.dataQuality.canonicalTradeSource, 'xt_trades')

  const kpis = buildPositionReviewDetailKpis(detail)
  assert.equal(kpis.find((item) => item.key === 'current_quantity').value, '29,300 股')
  assert.equal(kpis.find((item) => item.key === 'anomaly').value, '1')
})

test('expected quantity null remains unknown and never creates a synthetic zero delta', () => {
  const detail = normalizePositionReviewDetail({
    symbol: { code: '002262', name: '恩华药业' },
    charts: {
      request_quantity_compare: [
        {
          time: '2026-04-29T10:33:00+08:00',
          requested: 4500,
          expected: null,
          expected_quantity: 9999,
          filled: 4500,
          verdict: 'INSUFFICIENT_EVIDENCE',
        },
      ],
    },
    reviews: [
      {
        review_id: 'review-unknown',
        time: '2026-04-29T10:33:00+08:00',
        side: 'sell',
        request: { quantity: 4500 },
        expected: {
          quantity: null,
          expected_quantity: 9999,
        },
        expected_quantity: 9999,
        actual: { filled_quantity: 4500 },
        quantity_delta: 4500,
        verdict: 'INSUFFICIENT_EVIDENCE',
      },
    ],
  })

  assert.equal(detail.reviews[0].expectedQuantity, null)
  assert.equal(detail.reviews[0].quantityDelta, null)
  assert.equal(detail.quantityCompare[0].expected, null)
  assert.equal(formatPositionReviewSignedInteger(null), '—')
  assert.equal(formatPositionReviewSignedInteger(undefined), '—')
  assert.equal(formatPositionReviewSignedInteger(''), '—')
  assert.equal(isPositionReviewFiniteNonZero(null), false)
  assert.equal(isPositionReviewFiniteNonZero(undefined), false)
  assert.equal(isPositionReviewFiniteNonZero(''), false)
  assert.equal(isPositionReviewFiniteNonZero(4500), true)
})

test('detail keeps every canonical execution and flags unassociated fills without a verdict', () => {
  const executions = Array.from({ length: 55 }, (_, index) => ({
    broker_trade_id: `trade-${index + 1}`,
    broker_order_id: `broker-order-${index + 1}`,
    time: `2026-04-29T10:${String(index).padStart(2, '0')}:00+08:00`,
    side: index % 2 ? 'sell' : 'buy',
    price: 22 + index / 100,
    quantity: 100,
    request_id: index === 54 ? null : `request-${index + 1}`,
    internal_order_id: index === 54 ? null : `order-${index + 1}`,
    execution_fill_id: `fill-${index + 1}`,
    trade_fact_id: `fact-${index + 1}`,
    association_quality: index === 54 ? 'low' : 'high',
    association_method: index === 54 ? 'order_composite' : 'execution_fill',
    account_id: 'sensitive-account-id',
    account_partition: index % 2 ? 'partition-b' : 'partition-a',
    source: 'execution_history_archive',
  }))
  const detail = normalizePositionReviewDetail({
    symbol: { code: '002262', name: '恩华药业' },
    summary: { fill_count: 55 },
    executions,
    reviews: [],
  })

  assert.equal(detail.executions.length, 55)
  assert.equal(detail.fillCount, 55)
  assert.equal(detail.unassociatedExecutionCount, 1)
  assert.equal(detail.executions[0].brokerTradeId, 'trade-1')
  assert.equal(detail.executions[0].associationLabel, '高质量关联')
  assert.equal(detail.executions[54].isAssociated, false)
  assert.equal(detail.executions[54].associationLabel, '未关联请求')
  assert.equal('status' in detail.executions[54], false)
  assert.equal(detail.executions[0].accountPartition, 'partition-a')
  assert.equal(detail.executions[0].source, 'execution_history_archive')
  assert.equal('account_id' in detail.executions[0].raw, false)
})

test('reused broker trade ids still produce unique execution rows and timeline points', () => {
  const detail = normalizePositionReviewDetail({
    executions: [
      {
        broker_trade_id: 'reused-trade-id',
        time: '2026-04-29T10:14:01+08:00',
        side: 'sell',
        price: 22.41,
        quantity: 100,
      },
      {
        broker_trade_id: 'reused-trade-id',
        time: '2026-04-29T10:14:02+08:00',
        side: 'sell',
        price: 22.42,
        quantity: 200,
      },
    ],
    charts: {
      trade_price: [
        {
          broker_trade_id: 'reused-trade-id',
          time: '2026-04-29T10:14:01+08:00',
          side: 'sell',
          price: 22.41,
          quantity: 100,
        },
        {
          broker_trade_id: 'reused-trade-id',
          time: '2026-04-29T10:14:02+08:00',
          side: 'sell',
          price: 22.42,
          quantity: 200,
        },
      ],
    },
    timeline: [
      {
        id: 'fill:reused-trade-id',
        time: '2026-04-29T10:14:01+08:00',
        type: 'fill',
        side: 'sell',
        price: 22.41,
        quantity: 100,
      },
      {
        id: 'fill:reused-trade-id',
        time: '2026-04-29T10:14:02+08:00',
        type: 'fill',
        side: 'sell',
        price: 22.42,
        quantity: 200,
      },
    ],
  })

  assert.equal(new Set(detail.executions.map((item) => item.id)).size, 2)
  assert.equal(new Set(detail.pricePoints.map((item) => item.pointId)).size, 2)
  assert.equal(new Set(detail.timeline.map((item) => item.id)).size, 2)
})

test('detail exposes derived opening position and its explicit chart starting point', () => {
  const detail = normalizePositionReviewDetail({
    symbol: { code: '002262', current_quantity: 29300 },
    summary: {
      initial_position_quantity: 24600,
      initial_position_source: 'derived_from_current_and_canonical_trades',
    },
    charts: {
      cumulative_quantity: [
        {
          time: '2026-04-13T14:21:59+08:00',
          value: 24600,
          point_type: 'derived_initial',
          assumption: true,
        },
        {
          time: '2026-04-13T14:22:00+08:00',
          value: 25100,
        },
      ],
    },
    data_quality: {
      initial_position_quantity: 24600,
      initial_position_source: 'derived_from_current_and_canonical_trades',
      initial_position_formula: 'current_quantity - buy_quantity + sell_quantity',
      initial_position_assumption: true,
    },
  })

  assert.equal(detail.initialPositionQuantity, 24600)
  assert.equal(detail.initialPositionSource, 'derived_from_current_and_canonical_trades')
  assert.equal(detail.initialPositionAssumption, true)
  assert.equal(detail.positionPoints[0].point_type, 'derived_initial')
  assert.equal(
    buildPositionReviewDetailKpis(detail).find((item) => item.key === 'initial_position').value,
    '24,600 股',
  )
})

test('reason codes are translated for users while raw codes remain on the review', () => {
  const detail = normalizePositionReviewDetail({
    reviews: [
      {
        review_id: 'review-reasons',
        expected: {
          quantity: 0,
          formula: 'price >= replayed percent/ATR historical threshold; sum contiguous profitable slices; floor to board lot',
        },
        actual: { filled_quantity: 4500 },
        reason_codes: [
          'threshold_not_met',
          'requested_quantity_mismatch',
          'historical_threshold_mode_ambiguous',
          'UNKNOWN_REASON',
        ],
        verdict: 'FAIL',
      },
    ],
  })

  assert.equal(
    detail.reviews[0].reasonText,
    '未达到卖出阈值；请求数量与策略应有量不一致；历史阈值模式无法确定（百分比/ATR结果不一致）；UNKNOWN_REASON',
  )
  assert.deepEqual(
    detail.reviews[0].reasonCodes,
    [
      'threshold_not_met',
      'requested_quantity_mismatch',
      'historical_threshold_mode_ambiguous',
      'UNKNOWN_REASON',
    ],
  )
  assert.deepEqual(
    detail.reviews[0].reasonLabels,
    [
      '未达到卖出阈值',
      '请求数量与策略应有量不一致',
      '历史阈值模式无法确定（百分比/ATR结果不一致）',
      'UNKNOWN_REASON',
    ],
  )
  assert.equal(
    detail.reviews[0].formula,
    '信号价达到历史百分比/ATR阈值后，汇总连续可盈利持仓切片，并向下取整到 100 股',
  )
  assert.equal(
    detail.reviews[0].rawFormula,
    'price >= replayed percent/ATR historical threshold; sum contiguous profitable slices; floor to board lot',
  )
})

test('refresh orchestration warms summary cache before loading symbols', async () => {
  const calls = []
  await runPositionReviewRefresh({
    loadSummary: async (options) => {
      calls.push(['summary', options])
    },
    loadSymbols: async () => {
      calls.push(['symbols'])
    },
  })

  assert.deepEqual(calls, [
    ['summary', { refresh: true }],
    ['symbols'],
  ])
})

test('catalog filtering only loads symbols and never refreshes the summary replay', async () => {
  const calls = []
  await runPositionReviewCatalogFilter({
    loadSymbols: async () => {
      calls.push('symbols')
    },
  })

  assert.deepEqual(calls, ['symbols'])
})

test('deep-linked symbol remains selected even when absent from the current catalog page', () => {
  assert.equal(resolvePositionReviewSelectedSymbol({
    selectedSymbol: '',
    routeSymbol: '002262',
    rows: [{ symbol: '000001' }],
  }), '002262')
  assert.equal(resolvePositionReviewSelectedSymbol({
    selectedSymbol: '002262',
    routeSymbol: '002262',
    rows: [],
  }), '002262')
  assert.equal(resolvePositionReviewSelectedSymbol({
    rows: [{ symbol: '000001' }],
  }), '000001')
})

test('summary and detail KPI sets expose actual fill counts', () => {
  const summaryKpis = buildPositionReviewSummaryKpis({
    requestCount: 15,
    fillCount: 55,
    counts: {},
  })
  const detailKpis = buildPositionReviewDetailKpis({
    requestCount: 15,
    fillCount: 55,
    counts: {},
  })

  assert.equal(summaryKpis.find((item) => item.key === 'fills').value, '55')
  assert.equal(detailKpis.find((item) => item.key === 'fill_count').value, '55')
})
