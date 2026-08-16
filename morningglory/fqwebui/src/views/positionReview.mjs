import {
  getPositionReviewStatusMeta,
  normalizePositionReviewStatus,
  POSITION_REVIEW_STATUS_META,
} from './positionReviewStateMeta.mjs'
import {
  formatBeijingDate,
  formatBeijingTimestamp,
  parseTimestampMs,
} from '../tool/beijingTime.mjs'

const integerFormatter = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 0,
})

const amountFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const priceFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
})

const toText = (value) => String(value ?? '').trim()
const toArray = (value) => (Array.isArray(value) ? value : [])

const toFiniteNumber = (value, fallback = null) => {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const toInteger = (value, fallback = 0) => {
  const parsed = toFiniteNumber(value)
  return parsed === null ? fallback : Math.trunc(parsed)
}

const toNullableInteger = (value) => {
  const parsed = toFiniteNumber(value)
  return parsed === null ? null : Math.trunc(parsed)
}

const pickFirst = (...values) => values.find((value) => (
  value !== null && value !== undefined && value !== ''
))

const hasOwn = (source, key) => (
  source !== null &&
  typeof source === 'object' &&
  Object.prototype.hasOwnProperty.call(source, key)
)

const pickNullableField = (source, primaryKey, ...fallbackValues) => (
  hasOwn(source, primaryKey)
    ? source[primaryKey]
    : pickFirst(...fallbackValues)
)

const normalizeRatePercent = (value) => {
  const parsed = toFiniteNumber(value)
  if (parsed === null) return null
  if (parsed >= 0 && parsed <= 1) return parsed * 100
  return parsed
}

const readReviewCounts = (source = {}) => {
  const counts = source?.review_counts || source?.verdict_counts || source?.status_counts || source || {}
  return {
    COMPLIANT: toInteger(pickFirst(counts.PASS, counts.pass, counts.COMPLIANT, counts.compliant)),
    ANOMALY: toInteger(pickFirst(counts.FAIL, counts.fail, counts.ANOMALY, counts.anomaly)),
    UNVERIFIABLE: toInteger(pickFirst(
      counts.INSUFFICIENT_EVIDENCE,
      counts.insufficient_evidence,
      counts.UNVERIFIABLE,
      counts.unverifiable,
    )),
    NOT_APPLICABLE: toInteger(pickFirst(
      counts.NOT_APPLICABLE,
      counts.not_applicable,
      counts.SKIPPED,
      counts.skipped,
    )),
  }
}

const buildStatusDistribution = (counts = {}) => (
  Object.values(POSITION_REVIEW_STATUS_META).map((meta) => ({
    key: meta.key,
    name: meta.label,
    value: toInteger(counts[meta.key]),
    chipVariant: meta.chipVariant,
  }))
)

const WARNING_CODE_LABELS = Object.freeze({
  runtime_evidence_unavailable: '运行时证据不可用',
  runtime_evidence_truncated: '运行时证据已截断',
  current_position_snapshot_missing: '当前持仓快照缺失',
  negative_derived_initial_position: '推导期初仓为负',
  trade_association_degraded: '成交关联质量下降',
  broker_trade_id_evidence_mismatch: '成交证据匹配失败',
  execution_side_conflict: 'XT 与 OM 成交方向冲突',
  ambiguous_execution_account_evidence: '成交证据的账户归属不明确',
  duplicate_canonical_execution_row: '重复的规范成交记录',
  multiple_account_partitions: '存在多个匿名账户分区',
  multiple_execution_accounts: '历史成交跨越多个匿名账户分区',
  unknown_execution_account: '成交账户分区未知',
  execution_account_unknown: '成交账户分区未知',
  unknown_xt_side: '真实成交方向未知',
  historical_threshold_unavailable: '历史卖出阈值缺失',
  historical_threshold_mode_ambiguous: '历史阈值模式不明确',
  catalog_data_quality_degraded: '部分标的数据质量存在告警',
  unassociated_canonical_trades: '存在未关联策略请求的真实成交',
})

const CANONICAL_TRADE_SOURCE_LABELS = Object.freeze({
  xt_trades: 'XT 真实成交',
  current_order_ledger_only: '当前订单账本（重建 + 真实订单）',
})

const normalizeWarning = (warning) => {
  if (typeof warning === 'string' || typeof warning === 'number') {
    const text = toText(warning)
    return { code: '', label: '', message: text, text }
  }
  if (!warning || typeof warning !== 'object') {
    return { code: '', label: '', message: '', text: '' }
  }

  const code = toText(warning.code)
  const label = WARNING_CODE_LABELS[code] || code
  const message = toText(warning.message || warning.detail || warning.description)
  const context = Object.entries(warning)
    .filter(([key, value]) => (
      !['code', 'message', 'detail', 'description'].includes(key) &&
      value !== null &&
      value !== undefined &&
      value !== ''
    ))
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : value}`)
    .join('，')
  const text = label && message
    ? `${label}：${message}`
    : message || (label && context ? `${label}（${context}）` : label || context)
  return { code, label, message, context, text }
}

const normalizeDataQuality = (source = {}, fallback = {}) => {
  const quality = source?.data_quality || source?.dataQuality || source || {}
  const warningDetails = toArray(quality.warnings || fallback.warnings)
    .map(normalizeWarning)
    .filter((item) => item.text)
  const warnings = warningDetails.map((item) => item.text)
  const canonicalTradeSource = toText(
    pickFirst(
      quality.canonical_trade_source,
      quality.canonicalTradeSource,
      fallback.canonical_trade_source,
      fallback.canonicalTradeSource,
    ),
  )
  const canonicalTradeSourceLabel = toText(pickFirst(
    quality.canonical_trade_source_label,
    quality.canonicalTradeSourceLabel,
    fallback.canonical_trade_source_label,
    fallback.canonicalTradeSourceLabel,
    CANONICAL_TRADE_SOURCE_LABELS[canonicalTradeSource],
    canonicalTradeSource,
  ))
  return {
    canonicalTradeSource: canonicalTradeSource || 'xt_trades',
    canonicalTradeSourceLabel: canonicalTradeSourceLabel || 'XT 真实成交',
    strategyVersion: toText(pickFirst(
      quality.strategy_version,
      quality.strategyVersion,
      fallback.strategy_version,
      fallback.strategyVersion,
    )),
    reviewEngineVersion: toText(pickFirst(
      quality.review_engine_version,
      quality.reviewEngineVersion,
      fallback.review_engine_version,
      fallback.reviewEngineVersion,
    )),
    generatedAt: toText(pickFirst(
      quality.generated_at,
      quality.generatedAt,
      fallback.generated_at,
      fallback.generatedAt,
    )),
    dataWatermark: toText(pickFirst(
      quality.data_watermark,
      quality.dataWatermark,
      fallback.data_watermark,
      fallback.dataWatermark,
    )),
    initialPositionQuantity: toNullableInteger(pickNullableField(
      quality,
      'initial_position_quantity',
      quality.initialPositionQuantity,
      fallback.initial_position_quantity,
      fallback.initialPositionQuantity,
    )),
    initialPositionSource: toText(pickFirst(
      quality.initial_position_source,
      quality.initialPositionSource,
      fallback.initial_position_source,
      fallback.initialPositionSource,
    )),
    initialPositionFormula: toText(pickFirst(
      quality.initial_position_formula,
      quality.initialPositionFormula,
      fallback.initial_position_formula,
      fallback.initialPositionFormula,
    )),
    initialPositionAssumption: pickFirst(
      quality.initial_position_assumption,
      quality.initialPositionAssumption,
      fallback.initial_position_assumption,
      fallback.initialPositionAssumption,
    ) ?? '',
    initialPositionIsObserved: Boolean(pickFirst(
      quality.initial_position_is_observed,
      quality.initialPositionIsObserved,
      fallback.initial_position_is_observed,
      fallback.initialPositionIsObserved,
      false,
    )),
    accountPartitions: toArray(
      quality.account_partitions || quality.accountPartitions,
    ).map(toText).filter(Boolean),
    multipleAccountPartitions: Boolean(pickFirst(
      quality.multiple_account_partitions,
      quality.multipleAccountPartitions,
      false,
    )),
    accountPartitionCount: toInteger(pickFirst(
      quality.account_partition_count,
      quality.accountPartitionCount,
    )),
    unknownExecutionAccountCount: toInteger(pickFirst(
      quality.unknown_execution_account_count,
      quality.unknownExecutionAccountCount,
    )),
    warnings,
    warningDetails,
    warningCount: warnings.length,
  }
}

export const readPositionReviewPayload = (response, fallback = {}) => {
  if (!response || typeof response !== 'object') return fallback
  if (
    response.data &&
    typeof response.data === 'object' &&
    !Array.isArray(response.data)
  ) {
    return response.data
  }
  return response
}

export const formatPositionReviewInteger = (value, fallback = '-') => {
  const parsed = toFiniteNumber(value)
  return parsed === null ? fallback : integerFormatter.format(Math.trunc(parsed))
}

export const isPositionReviewFiniteNonZero = (value) => {
  if (value === null || value === undefined || value === '') return false
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed !== 0
}

export const formatPositionReviewSignedInteger = (value, fallback = '—') => {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  if (parsed === 0) return '0'
  return `${parsed > 0 ? '+' : ''}${formatPositionReviewInteger(parsed, fallback)}`
}

export const formatPositionReviewAmount = (value, fallback = '-') => {
  const parsed = toFiniteNumber(value)
  return parsed === null ? fallback : amountFormatter.format(parsed)
}

export const formatPositionReviewPrice = (value, fallback = '-') => {
  const parsed = toFiniteNumber(value)
  return parsed === null ? fallback : priceFormatter.format(parsed)
}

export const formatPositionReviewRate = (value, fallback = '-') => {
  const parsed = normalizeRatePercent(value)
  return parsed === null ? fallback : `${parsed.toFixed(1)}%`
}

export const normalizePositionReviewSummary = (response = {}) => {
  const payload = readPositionReviewPayload(response)
  const totals = payload.totals || payload.summary || payload
  const counts = readReviewCounts(payload.verdict_counts || totals.review_counts || totals)
  const reviewable = toInteger(pickFirst(
    totals.reviewable,
    totals.reviewable_count,
    counts.COMPLIANT + counts.ANOMALY,
  ))
  const computedPassRate = reviewable > 0 ? (counts.COMPLIANT / reviewable) * 100 : null
  const passRate = normalizeRatePercent(pickFirst(
    totals.pass_rate,
    totals.compliance_rate,
    totals.compliant_rate,
    computedPassRate,
  ))
  const generatedAt = toText(pickFirst(payload.generated_at, payload.as_of))
  const dataQuality = normalizeDataQuality(payload.data_quality || {}, {
    ...payload,
    generated_at: generatedAt,
  })

  return {
    generatedAt,
    generatedAtLabel: generatedAt ? formatBeijingTimestamp(generatedAt) : '-',
    symbolCount: toInteger(pickFirst(totals.symbols, totals.symbol_count, totals.traded_symbols)),
    requestCount: toInteger(pickFirst(totals.requests, totals.request_count, totals.orders)),
    fillCount: toInteger(pickFirst(totals.fills, totals.fill_count, totals.trades)),
    reviewableCount: reviewable,
    anomalySymbolCount: toInteger(pickFirst(
      totals.anomaly_symbols,
      totals.anomaly_symbol_count,
    )),
    counts,
    passRate,
    passRateLabel: formatPositionReviewRate(passRate),
    statusDistribution: buildStatusDistribution(counts),
    dataQuality,
  }
}

const resolveSymbolName = (row = {}) => toText(pickFirst(
  row.name,
  row.symbol_name,
  row.stock_name,
))

const resolveSymbolCode = (row = {}) => toText(pickFirst(
  row.symbol,
  row.code,
  row.stock_code,
))

const resolvePrimaryStatus = (row = {}, counts = readReviewCounts(row)) => {
  const explicit = pickFirst(row.verdict, row.review_status, row.status)
  if (explicit) return normalizePositionReviewStatus(explicit)
  if (counts.ANOMALY > 0) return 'ANOMALY'
  if (counts.UNVERIFIABLE > 0) return 'UNVERIFIABLE'
  if (counts.COMPLIANT > 0) return 'COMPLIANT'
  return 'NOT_APPLICABLE'
}

export const normalizePositionReviewSymbolRows = (response = {}) => {
  const payload = readPositionReviewPayload(response)
  const rawRows = toArray(payload.rows || payload.items || payload.symbols)
  const rows = rawRows
    .map((row) => {
      const counts = readReviewCounts(row)
      const noExecutionHistory = Boolean(pickFirst(row.no_execution_history, row.noExecutionHistory))
      const explicitVerdict = pickFirst(row.verdict, row.review_status, row.status)
      const status = noExecutionHistory && !explicitVerdict
        ? 'NO_EXECUTION'
        : resolvePrimaryStatus(row, counts)
      const statusMeta = status === 'NO_EXECUTION'
        ? { label: '暂无成交记录', chipVariant: 'muted' }
        : getPositionReviewStatusMeta(status)
      const reviewable = counts.COMPLIANT + counts.ANOMALY
      const computedPassRate = reviewable > 0 ? (counts.COMPLIANT / reviewable) * 100 : null
      const passRate = normalizeRatePercent(pickFirst(row.pass_rate, row.compliance_rate, computedPassRate))
      const firstTradeAt = toText(pickFirst(row.first_trade_at, row.firstTradeAt))
      const lastTradeAt = toText(pickFirst(row.last_trade_at, row.lastTradeAt))
      return {
        ...row,
        symbol: resolveSymbolCode(row),
        name: resolveSymbolName(row),
        currentQuantity: toInteger(pickFirst(row.current_quantity, row.currentQuantity)),
        isHolding: Boolean(pickFirst(row.is_holding, row.isHolding, toInteger(row.current_quantity) > 0)),
        noExecutionHistory,
        firstTradeAt,
        firstTradeAtLabel: firstTradeAt ? formatBeijingTimestamp(firstTradeAt) : '-',
        lastTradeAt,
        lastTradeAtLabel: lastTradeAt ? formatBeijingTimestamp(lastTradeAt) : '-',
        requestCount: toInteger(pickFirst(row.request_count, row.requests)),
        fillCount: toInteger(pickFirst(row.fill_count, row.trade_count, row.trades)),
        buyQuantity: toInteger(pickFirst(row.buy_quantity, row.buy_qty)),
        sellQuantity: toInteger(pickFirst(row.sell_quantity, row.sell_qty)),
        buyAmount: toFiniteNumber(pickFirst(row.buy_amount, row.buy_value), 0),
        sellAmount: toFiniteNumber(pickFirst(row.sell_amount, row.sell_value), 0),
        counts,
        status,
        statusLabel: statusMeta.label,
        statusChipVariant: statusMeta.chipVariant,
        passRate,
        passRateLabel: formatPositionReviewRate(passRate),
      }
    })
    .filter((row) => row.symbol)
    .sort((left, right) => {
      const severityOrder = { ANOMALY: 0, UNVERIFIABLE: 1, COMPLIANT: 2, NOT_APPLICABLE: 3, NO_EXECUTION: 4 }
      const statusDiff = (severityOrder[left.status] ?? 4) - (severityOrder[right.status] ?? 4)
      if (statusDiff !== 0) return statusDiff
      return (parseTimestampMs(right.lastTradeAt) || 0) - (parseTimestampMs(left.lastTradeAt) || 0)
    })

  return {
    rows,
    total: toInteger(pickFirst(payload.total, rows.length)),
    page: Math.max(1, toInteger(payload.page, 1)),
    size: Math.max(1, toInteger(payload.size, rows.length || 50)),
  }
}

const normalizeSide = (value) => {
  const text = toText(value).toLowerCase()
  if (['buy', 'b', '1', 'long'].includes(text)) return 'buy'
  if (['sell', 's', '2', 'short'].includes(text)) return 'sell'
  return text
}

export const POSITION_REVIEW_REASON_LABELS = Object.freeze({
  non_guardian_request: '非守护策略请求，无需进行守护策略判断',
  filled_quantity_exceeds_request: '实际成交数量超过请求数量',
  canonical_trade_missing: '未找到对应的真实成交',
  buy_snapshot_incomplete: '买入计算所需的历史快照不完整',
  requested_quantity_mismatch: '请求数量与策略应有量不一致',
  quantity_capacity_based: '请求数量按阶段容量规则执行（与公式量不同）',
  capacity_snapshot_conflict: '容量快照量与独立复算结果不一致',
  capacity_evidence_incomplete: '容量证据不足，无法独立复算容量量',
  inventory_evidence_missing: '缺少可卖持仓来源证据',
  historical_threshold_unavailable: '缺少当时的卖出阈值证据',
  historical_threshold_mode_ambiguous: '历史阈值模式无法确定（百分比/ATR结果不一致）',
  signal_price_missing: '缺少当时的信号价格',
  threshold_not_met: '未达到卖出阈值',
  sell_threshold_not_met: '未达到卖出阈值',
  sellable_volume_from_request_snapshot: '可卖数量采用请求快照推导',
  historical_sellable_volume_unavailable: '缺少当时可卖数量证据',
  duplicate_source_entry: '卖出来源持仓存在重复',
  state_replay_divergence: '历史状态重放结果与记录不一致',
  inventory_history_uncertain: '期初持仓来源无法完整还原',
})

const reasonCodeLabel = (code) => {
  const text = toText(code)
  return POSITION_REVIEW_REASON_LABELS[text.toLowerCase()] || text
}

const POSITION_REVIEW_FORMULA_LABELS = Object.freeze({
  'floor(initial_amount / source_price / 100) * 100':
    '向下取整（初始投入金额 ÷ 信号价格 ÷ 100）× 100',
  'floor(base_amount * multiplier / source_price / 100) * 100':
    '向下取整（基础投入金额 × 网格倍数 ÷ 信号价格 ÷ 100）× 100',
  'percent and ATR threshold models diverge for reconstructed inventory':
    '按百分比阈值与 ATR 阈值分别重放后数量不一致，因此不作确定判断',
  'price >= replayed historical threshold; sellable-volume cap unavailable':
    '信号价达到历史阈值，但缺少当时可卖数量上限，无法确定策略应有量',
  'price >= replayed percent/ATR historical threshold; sum contiguous profitable slices; floor to board lot':
    '信号价达到历史百分比/ATR阈值后，汇总连续可盈利持仓切片，并向下取整到 100 股',
})

const formulaLabel = (formula) => {
  const text = toText(formula)
  return POSITION_REVIEW_FORMULA_LABELS[text] || text
}

const buildReasonText = (review = {}) => {
  const explicit = toText(pickFirst(review.reason_text, review.reason, review.description))
  if (explicit) return explicit
  const reasonCodes = toArray(review.reason_codes || review.reasonCodes).map(toText).filter(Boolean)
  return reasonCodes.map(reasonCodeLabel).join('；') || '-'
}

const normalizeReviewRow = (review = {}, index = 0) => {
  const request = review.request || {}
  const expected = review.expected || {}
  const actual = review.actual || {}
  const status = normalizePositionReviewStatus(pickFirst(
    review.verdict,
    review.review_status,
    review.status,
  ))
  const statusMeta = getPositionReviewStatusMeta(status)
  const time = toText(pickFirst(
    review.time,
    review.trade_time,
    review.signal_time,
    request.created_at,
  ))
  const side = normalizeSide(pickFirst(review.side, request.side))
  const expectedQuantity = toNullableInteger(pickNullableField(
    expected,
    'quantity',
    expected.expected_quantity,
    review.expected_quantity,
  ))
  const actualQuantity = toInteger(pickFirst(
    actual.filled_quantity,
    actual.quantity,
    review.actual_quantity,
    review.filled_quantity,
  ))
  const requestQuantity = toInteger(pickFirst(
    request.quantity,
    review.request_quantity,
    review.requested_quantity,
  ))
  const quantityDelta = expectedQuantity === null
    ? null
    : toInteger(pickFirst(
        review.quantity_delta,
        actualQuantity - expectedQuantity,
      ))
  const reviewId = toText(pickFirst(review.review_id, review.id))
  const requestId = toText(pickFirst(review.request_id, request.request_id))
  const id = reviewId || requestId || `${time || 'review'}-${index}`
  const reasonCodes = toArray(review.reason_codes || review.reasonCodes).map(toText).filter(Boolean)
  const rawFormula = toText(pickFirst(expected.formula, review.formula))
  const evidence = review.evidence && typeof review.evidence === 'object' ? review.evidence : {}
  const sourceEntries = toArray(expected.source_entries || expected.entries || review.source_entries)
  const signal = review.signal && typeof review.signal === 'object' ? review.signal : {}
  const conditionsPayload = (
    review.conditions && typeof review.conditions === 'object'
      ? review.conditions
      : {}
  )
  const conditions = toArray(conditionsPayload.conditions).map((condition) => ({
    key: toText(condition.condition_key || condition.key),
    label: toText(condition.label || condition.condition_key),
    actualDisplay: toText(condition.actual_display),
    operator: toText(condition.operator),
    thresholdDisplay: toText(condition.threshold_display),
    thresholdMissing: condition.threshold_value === null || condition.threshold_value === undefined,
    passed: condition.passed,
    source: toText(condition.source),
  }))
  const conditionPassedCount = toInteger(conditionsPayload.passed_count, conditions.filter((item) => item.passed === true).length)
  const conditionFailedCount = toInteger(conditionsPayload.failed_count, conditions.filter((item) => item.passed === false).length)
  const conditionMissingCount = toInteger(conditionsPayload.missing_count, conditions.filter((item) => item.passed === null).length)

  return {
    ...review,
    id,
    reviewId,
    requestId,
    internalOrderId: toText(pickFirst(review.internal_order_id, review.order_id)),
    traceId: toText(review.trace_id),
    intentId: toText(review.intent_id),
    time,
    timeLabel: time ? formatBeijingTimestamp(time) : '-',
    tradeDate: time ? formatBeijingDate(time) : '',
    side,
    sideLabel: side === 'buy' ? '买入' : side === 'sell' ? '卖出' : toText(side) || '-',
    requestPrice: toFiniteNumber(pickFirst(request.price, review.request_price)),
    requestQuantity,
    expectedQuantity,
    actualQuantity,
    quantityDelta,
    thresholdPrice: toFiniteNumber(pickFirst(
      expected.threshold_price,
      expected.top_river_price,
      review.threshold_price,
    )),
    thresholdMode: toText(expected.threshold_mode),
    thresholdRatio: toFiniteNumber(expected.threshold_ratio),
    thresholdDelta: toFiniteNumber(expected.threshold_delta),
    rawQuantity: toNullableInteger(expected.raw_quantity),
    canUseVolume: toNullableInteger(expected.can_use_volume),
    tracedRawQuantity: toNullableInteger(expected.traced_raw_quantity),
    perSliceThresholds: toArray(expected.per_slice_thresholds),
    lowestGuardianPrice: toFiniteNumber(pickFirst(
      expected.lowest_guardian_price,
      expected.guardian_price,
      review.lowest_guardian_price,
    )),
    signal: {
      type: toText(signal.type),
      family: toText(signal.family),
      label: toText(signal.label),
      side: toText(signal.side),
      price: toFiniteNumber(signal.price),
      quantity: toNullableInteger(signal.quantity),
      time: toText(signal.time),
      strategy: toText(signal.strategy),
      remark: toText(signal.remark),
    },
    conditions,
    conditionPassedCount,
    conditionFailedCount,
    conditionMissingCount,
    conditionSnapshotStatus: toText(conditionsPayload.condition_snapshot_status),
    conditionExpression: toText(conditionsPayload.expression),
    formula: formulaLabel(rawFormula),
    rawFormula,
    actualPrice: toFiniteNumber(pickFirst(
      actual.avg_filled_price,
      actual.price,
      review.actual_price,
      review.avg_filled_price,
    )),
    fillCount: toInteger(pickFirst(actual.fill_count, review.fill_count)),
    status,
    statusLabel: statusMeta.label,
    statusChipVariant: statusMeta.chipVariant,
    reasonCodes,
    reasonLabels: reasonCodes.map(reasonCodeLabel),
    reasonText: buildReasonText(review),
    confidence: toText(pickFirst(review.evidence_confidence, review.confidence)).toUpperCase() || 'LOW',
    evidence,
    sourceEntries,
    raw: review,
  }
}

const ASSOCIATION_QUALITY_META = Object.freeze({
  high: { label: '高质量关联', chipVariant: 'success' },
  medium: { label: '中等关联', chipVariant: 'info' },
  low: { label: '低质量关联', chipVariant: 'warning' },
  ambiguous: { label: '关联有歧义', chipVariant: 'danger' },
})

const normalizeExecutionRow = (execution = {}, index = 0) => {
  const safeRaw = Object.fromEntries(
    Object.entries(execution).filter(([key]) => (
      !['account_id', 'accountid'].includes(key.toLowerCase())
    )),
  )
  const executionId = toText(pickFirst(
    execution.execution_id,
    execution.id,
    execution.execution_key,
  ))
  const brokerTradeId = toText(pickFirst(
    execution.broker_trade_id,
    execution.trade_id,
    execution.traded_id,
  ))
  const executionFillId = toText(pickFirst(
    execution.execution_fill_id,
    execution.fill_id,
  ))
  const requestId = toText(execution.request_id)
  const rawTime = pickFirst(
    execution.time,
    execution.trade_time,
    execution.traded_time,
    execution.created_at,
  )
  const time = rawTime === null || rawTime === undefined ? '' : String(rawTime).trim()
  const side = normalizeSide(execution.side)
  const price = toFiniteNumber(pickFirst(execution.price, execution.traded_price))
  const quantity = toInteger(pickFirst(execution.quantity, execution.traded_volume))
  const quality = toText(
    execution.association_quality || execution.associationQuality,
  ).toLowerCase() || 'low'
  const qualityMeta = ASSOCIATION_QUALITY_META[quality] || {
    label: quality || '未知',
    chipVariant: 'muted',
  }
  const isAssociated = Boolean(requestId)

  return {
    ...execution,
    id: executionId || [
        'canonical-execution',
        brokerTradeId || 'no-trade-id',
        executionFillId || 'no-fill-id',
        time || 'no-time',
        side || 'no-side',
        quantity,
        price ?? 'no-price',
        index,
      ].join(':'),
    executionId,
    brokerTradeId,
    brokerOrderId: toText(pickFirst(execution.broker_order_id, execution.order_id)),
    executionFillId,
    tradeFactId: toText(execution.trade_fact_id),
    accountPartition: toText(
      execution.account_partition || execution.accountPartition,
    ),
    source: toText(execution.source),
    requestId,
    internalOrderId: toText(execution.internal_order_id),
    time,
    timeLabel: time ? formatBeijingTimestamp(rawTime) : '-',
    side,
    sideLabel: side === 'buy' ? '买入' : side === 'sell' ? '卖出' : toText(side) || '-',
    price,
    quantity,
    associationQuality: quality,
    associationMethod: toText(
      execution.association_method || execution.associationMethod,
    ),
    associationLabel: isAssociated ? qualityMeta.label : '未关联请求',
    associationChipVariant: isAssociated ? qualityMeta.chipVariant : 'danger',
    isAssociated,
    raw: safeRaw,
  }
}

const normalizePoint = (point = {}, {
  timeKeys = ['time', 'date', 'ts'],
  valueKeys = ['value'],
} = {}) => {
  const time = toText(pickFirst(...timeKeys.map((key) => point[key])))
  const value = toFiniteNumber(pickFirst(...valueKeys.map((key) => point[key])))
  return {
    ...point,
    time,
    value,
  }
}

const aggregateMonthlyActivity = (items = []) => {
  const monthMap = new Map()
  for (const item of items) {
    const rawDate = toText(pickFirst(item.date, item.time, item.month))
    if (!rawDate) continue
    const date = formatBeijingDate(rawDate, rawDate.slice(0, 10))
    const month = toText(item.month) || date.slice(0, 7)
    if (!month) continue
    const current = monthMap.get(month) || {
      month,
      buy: 0,
      sell: 0,
      buyAmount: 0,
      sellAmount: 0,
      tradeCount: 0,
    }
    current.buy += toFiniteNumber(pickFirst(item.buy, item.buy_quantity), 0)
    current.sell += toFiniteNumber(pickFirst(item.sell, item.sell_quantity), 0)
    current.buyAmount += toFiniteNumber(pickFirst(item.buy_amount, item.buyAmount, item.buy), 0)
    current.sellAmount += toFiniteNumber(pickFirst(item.sell_amount, item.sellAmount, item.sell), 0)
    current.tradeCount += toInteger(pickFirst(item.trade_count, item.count), 1)
    monthMap.set(month, current)
  }
  return [...monthMap.values()].sort((left, right) => left.month.localeCompare(right.month))
}

export const normalizePositionReviewDetail = (response = {}) => {
  const payload = readPositionReviewPayload(response)
  const symbolPayload = (
    payload.symbol && typeof payload.symbol === 'object'
      ? payload.symbol
      : payload
  )
  const summaryPayload = payload.summary || {}
  const charts = payload.charts || {}
  const reviews = toArray(payload.reviews || payload.orders || payload.events)
    .map(normalizeReviewRow)
    .sort((left, right) => (parseTimestampMs(left.time) || 0) - (parseTimestampMs(right.time) || 0))
  const executions = toArray(
    payload.executions ||
    payload.canonical_executions ||
    payload.canonical_trades ||
    payload.fills,
  )
    .map(normalizeExecutionRow)
    .sort((left, right) => (parseTimestampMs(left.time) || 0) - (parseTimestampMs(right.time) || 0))
  const counts = readReviewCounts(summaryPayload.review_counts || payload.verdict_counts || reviews.reduce(
    (accumulator, item) => {
      accumulator[item.status] = (accumulator[item.status] || 0) + 1
      return accumulator
    },
    {},
  ))
  const reviewable = counts.COMPLIANT + counts.ANOMALY
  const computedPassRate = reviewable > 0 ? (counts.COMPLIANT / reviewable) * 100 : null
  const passRate = normalizeRatePercent(pickFirst(
    summaryPayload.pass_rate,
    summaryPayload.compliance_rate,
    computedPassRate,
  ))
  const currentQuantity = toInteger(pickFirst(
    symbolPayload.current_quantity,
    symbolPayload.currentQuantity,
    summaryPayload.current_quantity,
  ))
  const positionPoints = toArray(
    charts.cumulative_quantity ||
    charts.position_quantity ||
    payload.position_series,
  ).map((point) => normalizePoint(point, {
    valueKeys: ['value', 'quantity', 'position_quantity'],
  }))
  const pricePoints = toArray(
    charts.trade_price ||
    charts.price_series ||
    payload.price_series,
  ).map((point, index) => {
    const normalized = normalizePoint(point, {
      valueKeys: ['price', 'value', 'avg_filled_price'],
    })
    const status = normalizePositionReviewStatus(point.verdict || point.status)
    return {
      ...normalized,
      side: normalizeSide(point.side),
      quantity: toInteger(point.quantity),
      requestId: toText(point.request_id),
      status,
      eventId: toText(point.review_id || point.event_id || point.request_id),
      pointId: toText(point.execution_id) || [
        'trade-price',
        toText(point.broker_trade_id) || 'no-trade-id',
        normalized.time || 'no-time',
        normalizeSide(point.side) || 'no-side',
        toInteger(point.quantity),
        normalized.value ?? 'no-price',
        index,
      ].join(':'),
    }
  })
  const quantityCompare = toArray(
    charts.request_quantity_compare ||
    charts.quantity_compare,
  ).map((point, index) => {
    const time = toText(point.time || point.date)
    return {
      ...point,
      time,
      requestId: toText(point.request_id),
      eventId: toText(point.review_id || point.event_id || point.request_id) || reviews[index]?.id || '',
      requested: toInteger(pickFirst(point.requested, point.request_quantity)),
      expected: toNullableInteger(pickNullableField(
        point,
        'expected',
        point.expected_quantity,
      )),
      filled: toInteger(pickFirst(point.filled, point.actual, point.filled_quantity)),
      status: normalizePositionReviewStatus(point.verdict || point.status),
    }
  })
  const fallbackQuantityCompare = reviews.map((item) => ({
    time: item.time,
    requestId: item.requestId,
    eventId: item.id,
    requested: item.requestQuantity,
    expected: item.expectedQuantity,
    filled: item.actualQuantity,
    status: item.status,
  }))
  const monthlyActivity = aggregateMonthlyActivity(
    charts.traded_amount ||
    charts.monthly_activity ||
    payload.monthly_activity ||
    reviews.map((item) => ({
      date: item.tradeDate,
      buy_amount: item.side === 'buy' ? (item.actualPrice || item.requestPrice || 0) * item.actualQuantity : 0,
      sell_amount: item.side === 'sell' ? (item.actualPrice || item.requestPrice || 0) * item.actualQuantity : 0,
      buy: item.side === 'buy' ? item.actualQuantity : 0,
      sell: item.side === 'sell' ? item.actualQuantity : 0,
      trade_count: item.actualQuantity > 0 ? 1 : 0,
    })),
  )
  const dataQuality = normalizeDataQuality(payload.data_quality || {}, payload)
  const initialPositionQuantity = toNullableInteger(pickNullableField(
    summaryPayload,
    'initial_position_quantity',
    summaryPayload.initialPositionQuantity,
    dataQuality.initialPositionQuantity,
  ))
  const initialPositionSource = toText(pickFirst(
    summaryPayload.initial_position_source,
    summaryPayload.initialPositionSource,
    dataQuality.initialPositionSource,
  ))
  const symbol = resolveSymbolCode(symbolPayload)
  const name = resolveSymbolName(symbolPayload)

  return {
    ...payload,
    symbol,
    name,
    displayName: [name, symbol].filter(Boolean).join(' · ') || '-',
    currentQuantity,
    isHolding: Boolean(pickFirst(symbolPayload.is_holding, currentQuantity > 0)),
    firstTradeAt: toText(summaryPayload.first_trade_at),
    lastTradeAt: toText(summaryPayload.last_trade_at),
    requestCount: toInteger(pickFirst(summaryPayload.request_count, reviews.length)),
    fillCount: toInteger(pickFirst(summaryPayload.fill_count, executions.length)),
    buyQuantity: toInteger(summaryPayload.buy_quantity),
    sellQuantity: toInteger(summaryPayload.sell_quantity),
    buyAmount: toFiniteNumber(summaryPayload.buy_amount, 0),
    sellAmount: toFiniteNumber(summaryPayload.sell_amount, 0),
    counts,
    passRate,
    passRateLabel: formatPositionReviewRate(passRate),
    statusDistribution: buildStatusDistribution(counts),
    reviews,
    executions,
    unassociatedExecutionCount: executions.filter((item) => !item.isAssociated).length,
    initialPositionQuantity,
    initialPositionSource,
    initialPositionFormula: dataQuality.initialPositionFormula,
    initialPositionAssumption: dataQuality.initialPositionAssumption,
    positionPoints,
    pricePoints,
    quantityCompare: quantityCompare.length ? quantityCompare : fallbackQuantityCompare,
    monthlyActivity,
    dataQuality,
  }
}

export const buildPositionReviewSummaryKpis = (summary = {}) => ([
  {
    key: 'symbols',
    label: '历史交易标的',
    value: formatPositionReviewInteger(summary.symbolCount),
    tone: 'info',
  },
  {
    key: 'requests',
    label: '策略请求',
    value: formatPositionReviewInteger(summary.requestCount),
    tone: 'muted',
  },
  {
    key: 'fills',
    label: '实际成交笔数',
    value: formatPositionReviewInteger(summary.fillCount),
    tone: 'info',
  },
  {
    key: 'pass_rate',
    label: '可复盘符合率',
    value: summary.passRateLabel || '-',
    tone: 'success',
  },
  {
    key: 'anomaly',
    label: '异常请求',
    value: formatPositionReviewInteger(summary.counts?.ANOMALY),
    tone: 'danger',
  },
  {
    key: 'unverifiable',
    label: '证据不足',
    value: formatPositionReviewInteger(summary.counts?.UNVERIFIABLE),
    tone: 'warning',
  },
  {
    key: 'anomaly_symbols',
    label: '异常标的',
    value: formatPositionReviewInteger(summary.anomalySymbolCount),
    tone: 'danger',
  },
])

export const buildPositionReviewDetailKpis = (detail = {}) => ([
  {
    key: 'request_count',
    label: '策略请求',
    value: formatPositionReviewInteger(detail.requestCount),
    tone: 'muted',
  },
  {
    key: 'fill_count',
    label: '实际成交笔数',
    value: formatPositionReviewInteger(detail.fillCount),
    tone: 'info',
  },
  {
    key: 'buy_quantity',
    label: '累计买入',
    value: `${formatPositionReviewInteger(detail.buyQuantity)} 股`,
    tone: 'danger',
  },
  {
    key: 'sell_quantity',
    label: '累计卖出',
    value: `${formatPositionReviewInteger(detail.sellQuantity)} 股`,
    tone: 'success',
  },
  {
    key: 'initial_position',
    label: '期初仓（推导）',
    value: detail.initialPositionQuantity === null || detail.initialPositionQuantity === undefined
      ? '—'
      : `${formatPositionReviewInteger(detail.initialPositionQuantity)} 股`,
    tone: 'warning',
  },
  {
    key: 'current_quantity',
    label: '当前数量',
    value: `${formatPositionReviewInteger(detail.currentQuantity)} 股`,
    tone: detail.isHolding ? 'info' : 'muted',
  },
  {
    key: 'pass_rate',
    label: '可复盘符合率',
    value: detail.passRateLabel || '-',
    tone: 'success',
  },
  {
    key: 'anomaly',
    label: '异常请求',
    value: formatPositionReviewInteger(detail.counts?.ANOMALY),
    tone: 'danger',
  },
])

export const runPositionReviewRefresh = async ({
  loadSummary,
  loadSymbols,
} = {}) => {
  if (typeof loadSummary !== 'function' || typeof loadSymbols !== 'function') {
    throw new TypeError('loadSummary and loadSymbols must be functions')
  }
  await loadSummary({ refresh: true })
  await loadSymbols()
}

export const runPositionReviewCatalogFilter = async ({
  loadSymbols,
} = {}) => {
  if (typeof loadSymbols !== 'function') {
    throw new TypeError('loadSymbols must be a function')
  }
  await loadSymbols()
}

export const resolvePositionReviewSelectedSymbol = ({
  selectedSymbol,
  routeSymbol,
  rows,
} = {}) => {
  const selected = toText(selectedSymbol)
  const fromRoute = toText(routeSymbol)
  if (selected) return selected
  if (fromRoute) return fromRoute
  return toText(toArray(rows)[0]?.symbol)
}


// Read-model helpers for the position-review refactor.
// Pure functions: portfolio normalization, equity/contribution projections,
// symbol review chart option building and condition normalization.

const prtoText = (value) => String(value ?? '').trim()

const prtoArray = (value) => (Array.isArray(value) ? value : [])

const prtoFiniteNumber = (value) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const prtoInteger = (value, fallback = 0) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.trunc(numeric) : fallback
}

const prround2 = (value) => {
  const numeric = prtoFiniteNumber(value)
  return numeric === null ? null : Math.round(numeric * 100) / 100
}

const prVERDICT_ORDER = Object.freeze([
  'PASS',
  'FAIL',
  'INSUFFICIENT_EVIDENCE',
  'NOT_APPLICABLE',
])

const prSIGNAL_TYPE_LABELS = Object.freeze({
  buy_v_reverse: '反转买点',
  buy_zs_huila: '回拉买点',
  macd_bullish_divergence: 'MACD 底背离',
  sell_takeprofit: '止盈卖点',
  manual: '人工/外部',
  unknown: '证据缺失',
})

export const positionReviewChartColors = Object.freeze({
  buy: '#ef4444',
  sell: '#22c55e',
  cost: '#f59e0b',
  equity: '#2563eb',
  estimated: '#f59e0b',
  up: '#ef232a',
  down: '#14b143',
  grid: 'rgba(15,23,42,0.08)',
  text: '#606266',
})

export const normalizePortfolioSummary = (payload = {}) => {
  const kpisRaw = payload.kpis || {}
  const dataQuality = payload.data_quality || {}
  const verdictCounts = payload.verdict_counts || {}
  const signalTypeCounts = payload.signal_type_counts || {}
  const kpis = [
    { key: 'totalAsset', label: '总资产', value: prround2(kpisRaw.total_asset), kind: 'amount' },
    { key: 'netValue', label: '账户净资产', value: prround2(kpisRaw.net_value), kind: 'amount' },
    { key: 'marketValue', label: '持仓市值', value: prround2(kpisRaw.market_value), kind: 'amount' },
    { key: 'remainingCost', label: '持仓成本', value: prround2(kpisRaw.remaining_cost), kind: 'amount' },
    { key: 'floatingPnl', label: '浮动盈亏', value: prround2(kpisRaw.floating_pnl), kind: 'signedAmount' },
    { key: 'realizedPnl', label: '已实现盈亏', value: prround2(kpisRaw.realized_pnl), kind: 'signedAmount' },
    { key: 'positionRatio', label: '持仓比例', value: kpisRaw.position_ratio, kind: 'ratio' },
    { key: 'cash', label: '现金', value: prround2(kpisRaw.cash), kind: 'amount' },
  ]
  return {
    kpis,
    monthly: prtoArray(payload.monthly_turnover).map((item) => ({
      month: prtoText(item.month),
      buy: prround2(item.buy),
      sell: prround2(item.sell),
    })),
    verdictDistribution: prVERDICT_ORDER.map((verdict) => ({
      name: verdict,
      value: prtoInteger(verdictCounts[verdict]),
    })),
    signalTypeDistribution: Object.entries(signalTypeCounts).map(([type, value]) => ({
      type,
      label: prSIGNAL_TYPE_LABELS[type] || type,
      value: prtoInteger(value),
    })),
    reviewable: prtoInteger(payload.reviewable),
    passRate: prtoFiniteNumber(payload.pass_rate),
    equityBasis: prtoText(dataQuality.equity_basis),
    costBasis: prtoText(dataQuality.cost_basis),
    warnings: prtoArray(dataQuality.warnings),
  }
}

const prnetValueOf = (point) => (
  prtoFiniteNumber(point?.net_value)
  ?? prtoFiniteNumber(point?.estimated_equity)
  ?? prtoFiniteNumber(point?.total_equity)
)

const prformatPeriodTick = (label, period) => {
  const text = prtoText(label)
  if (!text) return ''
  // 所有窗口统一按日采样，标签为 YYYY-MM-DD（交易日），横轴显示 MM-DD。
  return text.length >= 10 ? text.slice(5) : text
}

const prtradeSideText = (side) => (side === 'sell' ? '卖出' : '买入')

export const PR_TOOLTIP_CSS = (
  'max-width:560px;max-height:420px;overflow:auto;'
  + 'background:#0f172a;border:1px solid #334155;border-radius:10px;'
  + 'box-shadow:0 8px 24px rgba(0,0,0,0.45);padding:10px 12px;'
)

const prfmtAmount = (value) => (
  value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
)

const prfmtSigned = (value) => (
  value == null
    ? '—'
    : `${value >= 0 ? '+' : ''}${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
)

const prfmtPctText = (value) => (
  value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
)

export const buildPortfolioTradeTooltip = (point = {}) => {
  return `<div class="prt">${prbuildTradesCardHtml(point)}</div>`
}

const prbuildTradesCardHtml = (point = {}) => {
  const trades = prtoArray(point.trades)
  if (!trades.length) return '<div class="prt-muted">该周期内没有交易</div>'
  // 按订单（标的 × 请求 × 方向）聚合：一笔订单可能有多笔成交，只展示
  // 最终成交聚合（数量/加权均价/金额/笔数）+ 触发信号详情。
  const orders = new Map()
  for (const trade of trades) {
    const side = trade.side === 'sell' ? 'sell' : 'buy'
    const hasOrderId = Boolean(trade.request_id || trade.broker_trade_id)
    // 请求/券商委托 ID 双空的成交不可跨成交合并（可能属不同订单），
    // 按成交自身分键，避免信号串行与过度聚合。
    const key = hasOrderId
      ? `${trade.symbol}|${trade.request_id || trade.broker_trade_id}|${side}`
      : `${trade.symbol}|${side}|fill:${prtoText(trade.time)}:${prtoText(trade.broker_trade_id)}:${trades.indexOf(trade)}`
    if (!orders.has(key)) {
      orders.set(key, { side, list: [] })
    }
    orders.get(key).list.push(trade)
  }
  const orderList = [...orders.values()].map(({ side, list }) => {
    const first = list[0] || {}
    const quantity = list.reduce((sum, trade) => sum + (Number(trade.quantity) || 0), 0)
    const amount = list.reduce((sum, trade) => sum + (Number(trade.amount) || 0), 0)
    const prhasPrice = (trade) => (
      trade.price != null && trade.price !== '' && Number.isFinite(Number(trade.price))
    )
    const pricedQuantity = list
      .filter(prhasPrice)
      .reduce((sum, trade) => sum + (Number(trade.quantity) || 0), 0)
    const costSum = list.reduce(
      (sum, trade) => sum + (Number(trade.price) || 0) * (Number(trade.quantity) || 0),
      0,
    )
    const times = list.map((trade) => prtoText(trade.time)).filter(Boolean).sort()
    return {
      side,
      symbol: prtoText(first.symbol),
      name: prtoText(first.name) || prtoText(first.symbol),
      request_id: prtoText(first.request_id),
      fill_count: list.length,
      quantity,
      amount,
      weighted_price: pricedQuantity ? costSum / pricedQuantity : null,
      time: times[0] || '',
      signal_label: prtoText(
        list.find((trade) => prtoText(trade.signal_label))?.signal_label,
      ),
      association_quality: prtoText(first.association_quality),
      account_partition: prtoText(first.account_partition),
    }
  }).sort((left, right) => left.time.localeCompare(right.time))

  const buys = orderList.filter((order) => order.side === 'buy')
  const sells = orderList.filter((order) => order.side === 'sell')
  const sumOf = (ordersList, field) => (
    ordersList.reduce((sum, order) => sum + (Number(order[field]) || 0), 0)
  )
  const buyAmount = sumOf(buys, 'amount')
  const sellAmount = sumOf(sells, 'amount')
  const buyQuantity = sumOf(buys, 'quantity')
  const sellQuantity = sumOf(sells, 'quantity')

  const rows = orderList.map((order) => {
    const timeText = prtoText(order.time)
    const timeOfDay = timeText.length >= 16 ? timeText.slice(11, 16) : timeText
    const meta = [
      order.request_id ? `请求 ${order.request_id}` : null,
      order.signal_label ? `信号 ${order.signal_label}` : null,
      order.association_quality ? `关联 ${order.association_quality}` : null,
      order.account_partition && order.account_partition !== 'unknown'
        ? `分区 ${order.account_partition}`
        : null,
    ].filter(Boolean).join(' · ')
    return `<div class="prt-row prt-trade-row">
      <span class="prt-label">${prescapeTooltipHtml(timeOfDay || '—')}</span>
      <span class="prt-value">
        <span class="prt-side prt-side-${order.side === 'sell' ? 'sell' : 'buy'}">${prtradeSideText(order.side)}</span>
        ${prescapeTooltipHtml(order.name)} ${prescapeTooltipHtml(order.symbol)}
        · 成交 ${prfmtAmount(order.quantity)} 股
        · 均价 ${prfmtAmount(order.weighted_price)} 元
        · 金额 ${prfmtAmount(order.amount)} 元
        · ${order.fill_count} 笔
        <span class="prt-meta">${prescapeTooltipHtml(meta)}</span>
      </span>
    </div>`
  }).join('')
  const header = `<div class="prt-header">
    <span class="prt-side prt-side-buy">交易</span>
    <span class="prt-id">${prescapeTooltipHtml(point.period_label || point.time || '')} · ${orderList.length} 笔订单</span>
  </div>`
  const summary = `<div class="prt-row">
    <span class="prt-label">当日汇总</span>
    <span class="prt-value">
      买入 ${buys.length} 笔订单 · 合计 ${prfmtAmount(buyAmount)} 元（${prfmtAmount(buyQuantity)} 股）
      <br>卖出 ${sells.length} 笔订单 · 合计 ${prfmtAmount(sellAmount)} 元（${prfmtAmount(sellQuantity)} 股）
    </span>
  </div>`
  return `${header}${summary}${rows}`
}

const prfirstFinite = (values) => values.find((value) => value != null)

const prlastFinite = (values) => {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index] != null) return values[index]
  }
  return null
}

const prpreviousFinite = (values, index) => {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (values[cursor] != null) return values[cursor]
  }
  return null
}

const prwindowPct = (value, base) => (
  value == null || !base ? null : (value / base - 1) * 100
)

const prportfolioBenchmarkTooltip = (
  params,
  labels,
  accountName,
  accountData,
  benchmarkName,
  benchmarkData,
  series,
  equityBasis,
) => {
  const items = Array.isArray(params) ? params : [params]
  const index = items.find((item) => item && item.dataIndex != null)?.dataIndex ?? 0
  const label = labels[index] || ''
  const point = series[index] || {}
  const accountValue = accountData[index]
  const benchmarkValue = benchmarkData[index]
  const accountBase = prfirstFinite(accountData)
  const benchmarkBase = prfirstFinite(benchmarkData)
  const accountPct = prwindowPct(accountValue, accountBase)
  const benchmarkPct = prwindowPct(benchmarkValue, benchmarkBase)
  const spread = accountPct == null || benchmarkPct == null
    ? null
    : accountPct - benchmarkPct
  const prevAccount = prpreviousFinite(accountData, index)
  const dayDelta = accountValue != null && prevAccount != null
    ? accountValue - prevAccount
    : null
  const dayPct = dayDelta != null && prevAccount ? (dayDelta / prevAccount) * 100 : null
  const rows = [
    [accountName, `${prfmtAmount(accountValue)}（区间 ${prfmtPctText(accountPct)}）`],
    ['较前一交易日', `${prfmtSigned(dayDelta)}（${prfmtPctText(dayPct)}）`],
    ['持仓市值', prfmtAmount(prtoFiniteNumber(point.market_value))],
    ['现金', prfmtAmount(prtoFiniteNumber(point.cash))],
    // 券商总资产口径无负债字段：不展示"总负债"行，避免恒为 —。
    ...(equityBasis === 'broker_total_asset'
      ? []
      : [['总负债', prfmtAmount(prtoFiniteNumber(point.total_debt))]]),
    [benchmarkName, `${prfmtAmount(benchmarkValue)}（区间 ${prfmtPctText(benchmarkPct)}）`],
    ['相对基准', spread == null
      ? '—'
      : `<span class="prt-spread-${spread >= 0 ? 'up' : 'down'}">${spread >= 0 ? '+' : ''}${spread.toFixed(2)}pp ${spread >= 0 ? '跑赢' : '跑输'}</span>`],
  ]
  const tradesSection = (prtoArray(point.trades).length)
    ? `<div class="prt-section"><div class="prt-section-title">当日成交明细</div>${prbuildTradesCardHtml(point)}</div>`
    : ''
  return `<div class="prt">
    <div class="prt-header"><span class="prt-id">${prescapeTooltipHtml(label)}</span></div>
    ${rows.map(([label, value]) => `
      <div class="prt-row">
        <span class="prt-label">${prescapeTooltipHtml(label)}</span>
        <span class="prt-value">${value}</span>
      </div>`).join('')}
    ${tradesSection}
  </div>`
}

const prportfolioAccountTooltip = (
  params,
  labels,
  accountName,
  accountData,
  series,
  equityBasis,
) => {
  const items = Array.isArray(params) ? params : [params]
  const index = items.find((item) => item && item.dataIndex != null)?.dataIndex ?? 0
  const label = labels[index] || ''
  const point = series[index] || {}
  const accountValue = accountData[index]
  const accountBase = prfirstFinite(accountData)
  const accountPct = prwindowPct(accountValue, accountBase)
  const prevAccount = prpreviousFinite(accountData, index)
  const dayDelta = accountValue != null && prevAccount != null
    ? accountValue - prevAccount
    : null
  const dayPct = dayDelta != null && prevAccount ? (dayDelta / prevAccount) * 100 : null
  const rows = [
    [accountName, `${prfmtAmount(accountValue)}（区间 ${prfmtPctText(accountPct)}）`],
    ['较前一交易日', `${prfmtSigned(dayDelta)}（${prfmtPctText(dayPct)}）`],
    ['持仓市值', prfmtAmount(prtoFiniteNumber(point.market_value))],
    ['现金', prfmtAmount(prtoFiniteNumber(point.cash))],
    ...(equityBasis === 'broker_total_asset'
      ? []
      : [['总负债', prfmtAmount(prtoFiniteNumber(point.total_debt))]]),
  ]
  const tradesSection = (prtoArray(point.trades).length)
    ? `<div class="prt-section"><div class="prt-section-title">当日成交明细</div>${prbuildTradesCardHtml(point)}</div>`
    : ''
  return `<div class="prt">
    <div class="prt-header"><span class="prt-id">${prescapeTooltipHtml(label)}</span></div>
    ${rows.map(([label, value]) => `
      <div class="prt-row">
        <span class="prt-label">${prescapeTooltipHtml(label)}</span>
        <span class="prt-value">${value}</span>
      </div>`).join('')}
    ${tradesSection}
  </div>`
}

export const buildPortfolioBenchmarkSummary = (payload = {}, mode = 'net') => {
  const series = prtoArray(payload.series)
  const benchmarkSeries = prtoArray(payload.benchmark?.series)
  if (!series.length || !benchmarkSeries.length) return null
  const accountValues = series.map((item) => (
    mode === 'asset'
      ? prtoFiniteNumber(item.total_equity)
      : (prtoFiniteNumber(item.net_value) ?? prtoFiniteNumber(item.estimated_equity))
  ))
  const benchmarkValues = benchmarkSeries.map((item) => prtoFiniteNumber(item.close))
  const accountBase = prfirstFinite(accountValues)
  const benchmarkBase = prfirstFinite(benchmarkValues)
  const accountLast = prlastFinite(accountValues)
  const benchmarkLast = prlastFinite(benchmarkValues)
  if (!accountBase || !benchmarkBase || accountLast == null || benchmarkLast == null) {
    return null
  }
  const accountPct = (accountLast / accountBase - 1) * 100
  const benchmarkPct = (benchmarkLast / benchmarkBase - 1) * 100
  const spread = accountPct - benchmarkPct
  return {
    accountPct,
    benchmarkPct,
    spread,
    beat: spread >= 0,
    benchmarkName: prtoText(payload.benchmark?.name) || '上证综指ETF',
  }
}

export const buildPortfolioEquityOption = (
  payload = {},
  mode = 'net',
  options = {},
) => {
  const series = prtoArray(payload.series)
  if (!series.length) {
    return null
  }
  const period = prtoText(payload.period) || 'day'
  const equityMode = mode === 'asset' ? 'asset' : 'net'
  const equityBasis = prtoText(payload.equity_basis)
  const tooltipEnabled = options.tooltipEnabled !== false
  const labels = series.map((item) => prformatPeriodTick(item.period_label || item.time, period))
  const primarySeries = []
  const primaryData = []
  if (equityMode === 'asset') {
    const data = series.map((item) => item.total_equity)
    primaryData.push(...data)
    primarySeries.push({
      name: '总资产',
      type: 'line',
      showSymbol: false,
      smooth: false,
      sampling: 'lttb',
      lineStyle: { color: positionReviewChartColors.equity, width: 1.8 },
      data,
    })
  } else {
    const data = series.map((item) => (
      prtoFiniteNumber(item.net_value) ?? prtoFiniteNumber(item.estimated_equity)
    ))
    primaryData.push(...data)
    primarySeries.push({
      name: '账户净资产',
      type: 'line',
      showSymbol: false,
      smooth: false,
      sampling: 'lttb',
      lineStyle: { color: positionReviewChartColors.equity, width: 1.8 },
      data,
    })
  }
  const benchmarkPayload = payload.benchmark || {}
  const benchmarkName = prtoText(benchmarkPayload.name) || '上证综指ETF'
  const benchmarkData = prtoArray(benchmarkPayload.series).map((item) => (
    prtoFiniteNumber(item.close)
  ))
  const hasBenchmark = benchmarkData.some((value) => value != null)
  const accountBase = prfirstFinite(primaryData)
  const benchmarkBase = prfirstFinite(benchmarkData)
  const prnormalizeTo100 = (value, base) => (
    value == null || !base ? null : Number(((value / base) * 100).toFixed(4))
  )
  const tradeSeriesData = equityMode === 'net'
    ? series
        .map((point, index) => {
          const trades = prtoArray(point.trades)
          if (!trades.length) return null
          return {
            value: [
              index,
              hasBenchmark
                ? prnormalizeTo100(prnetValueOf(point), accountBase)
                : prnetValueOf(point),
            ],
            point,
            trades,
            count: trades.length,
          }
        })
        .filter(Boolean)
    : []
  const tradeSeries = tradeSeriesData.length
    ? [{
        id: 'position-review-portfolio-trades',
        name: '交易点',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'circle',
        symbolSize: (value, params) => 5 + Math.min(7, (params?.data?.count || 1) * 1.6),
        animation: false,
        z: 10,
        itemStyle: { color: '#fbbf24', borderColor: '#111827', borderWidth: 1 },
        data: tradeSeriesData,
      }]
    : []
  const benchmarkLine = hasBenchmark
    ? [{
        id: 'position-review-benchmark',
        name: `${benchmarkName} ${prtoText(benchmarkPayload.code) || '510210'}`,
        type: 'line',
        showSymbol: false,
        smooth: false,
        sampling: 'lttb',
        lineStyle: { color: '#7c3aed', width: 1.6, type: 'dashed' },
        data: benchmarkData,
      }]
    : []
  // 有基准时两条曲线归一化到同一 Y 轴（各自可见区间首点=100），才能直接
  // 对比是否跑赢；无基准时保持原始金额轴。
  if (hasBenchmark) {
    primarySeries[0].data = primaryData.map((value) => prnormalizeTo100(value, accountBase))
    benchmarkLine[0].data = benchmarkData.map((value) => prnormalizeTo100(value, benchmarkBase))
  }
  const primaryYAxis = {
    type: 'value',
    scale: true,
    min: 'dataMin',
    max: 'dataMax',
    splitNumber: 6,
    axisLabel: {
      color: '#6b7280',
      formatter: (value) => (
        hasBenchmark
          ? Number(value).toFixed(1)
          : `${(Number(value) / 10000).toFixed(2)}万`
      ),
    },
    splitLine: { lineStyle: { color: positionReviewChartColors.grid } },
  }
  return {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: {
      show: tooltipEnabled,
      trigger: 'axis',
      triggerOn: 'mousemove',
      className: 'prt-tooltip',
      confine: true,
      extraCssText: PR_TOOLTIP_CSS,
      ...(hasBenchmark
        ? {
            formatter: (params) => prportfolioBenchmarkTooltip(
              params,
              labels,
              primarySeries[0].name,
              primaryData,
              benchmarkName,
              benchmarkData,
              series,
              equityBasis,
            ),
          }
        : {
            formatter: (params) => prportfolioAccountTooltip(
              params,
              labels,
              primarySeries[0].name,
              primaryData,
              series,
              equityBasis,
            ),
          }),
    },
    legend: {
      top: 4,
      textStyle: { color: positionReviewChartColors.text },
      data: [
        ...(primarySeries.length ? [primarySeries[0].name] : []),
        ...(hasBenchmark ? [`${benchmarkName} ${prtoText(benchmarkPayload.code) || '510210'}`] : []),
        ...(tradeSeries.length ? ['交易点'] : []),
      ],
    },
    grid: { left: 70, right: 24, top: 44, bottom: 30 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: hasBenchmark
      ? { ...primaryYAxis, name: '起点=100' }
      : primaryYAxis,
    series: [...primarySeries, ...benchmarkLine, ...tradeSeries],
  }
}

export const normalizePortfolioContributions = (payload = {}) => prtoArray(payload.top).map((row) => ({
  symbol: prtoText(row.symbol),
  name: prtoText(row.name),
  isHolding: Boolean(row.is_holding),
  realizedPnl: prround2(row.realized_pnl),
  floatingPnl: prround2(row.floating_pnl),
  totalPnl: prround2(row.total_pnl),
  marketValue: prround2(row.market_value),
  quantity: prtoInteger(row.quantity),
  costBasisSource: prtoText(row.cost_basis_source),
  verdictCounts: row.verdict_counts || {},
}))

const prparseBarTimeMs = (text) => {
  const value = prtoText(text)
  if (!value) return NaN
  if (/Z$|[+-]\d{2}:?\d{2}$/.test(value)) {
    return Date.parse(value)
  }
  const normalized = value.replace(' ', 'T').replace(/\//g, '-')
  const withTimezone = normalized.length === 10
    ? `${normalized}T00:00:00+08:00`
    : `${normalized}+08:00`
  return Date.parse(withTimezone)
}

const prresolveBarIndex = (targetMs, bars) => {
  if (!Number.isFinite(targetMs) || !bars.length) return null
  let best = -1
  bars.forEach((bar, index) => {
    if (bar.startMs <= targetMs) {
      best = index
    }
  })
  return best >= 0 ? best : null
}

export const normalizeSymbolChart = (payload = {}) => {
  const events = prtoArray(payload.order_events)
  const costSeries = prtoArray(payload.cost_basis_series)
  const positionSeries = prtoArray(payload.position_series)
  const holdingCycles = prtoArray(payload.holding_cycles)
  const registry = payload.signal_type_registry || {}
  return {
    symbol: payload.symbol || {},
    events,
    holdingCycles,
    costBasis: payload.cost_basis || {},
    positionSeries,
    costSeries,
    registry,
    hasEvents: Boolean(events.length),
  }
}

const prbuildBarSlots = (kline) => {
  const dates = prtoArray(kline?.date)
  return dates.map((date) => ({ label: prtoText(date), startMs: prparseBarTimeMs(date) }))
}

const prbuildMarkers = (events, bars) => events
  .map((event) => {
    const marker = event.marker || {}
    const execution = event.execution || {}
    const targetMs = prparseBarTimeMs(marker.bar_time || execution.first_fill_time)
    const barIndex = prresolveBarIndex(targetMs, bars)
    const price = prtoFiniteNumber(marker.price)
    if (barIndex === null || price === null) return null
    return {
      event,
      eventId: prtoText(event.event_id),
      side: prtoText(event.side).toLowerCase() === 'sell' ? 'sell' : 'buy',
      barIndex,
      price,
      symbol: prtoText(marker.symbol) || 'circle',
      verdict: prtoText((event.review || {}).verdict).toUpperCase() || null,
    }
  })
  .filter(Boolean)

const prbuildSpanSegments = (events, bars) => events
  .map((event) => {
    const execution = event.execution || {}
    const startMs = prparseBarTimeMs(execution.first_fill_time)
    const endMs = prparseBarTimeMs(execution.last_fill_time)
    const startIndex = prresolveBarIndex(startMs, bars)
    const endIndex = prresolveBarIndex(endMs, bars)
    const price = prtoFiniteNumber((event.marker || {}).price)
    if (startIndex === null || endIndex === null || startIndex === endIndex || price === null) {
      return null
    }
    return {
      eventId: prtoText(event.event_id),
      side: prtoText(event.side).toLowerCase() === 'sell' ? 'sell' : 'buy',
      startIndex,
      endIndex,
      price,
    }
  })
  .filter(Boolean)

const prbuildCostPoints = (costSeries, bars) => costSeries
  .map((point) => {
    const rawCost = point.average_cost
    if (rawCost === null || rawCost === undefined || rawCost === '') return null
    const barIndex = prresolveBarIndex(prparseBarTimeMs(point.time), bars)
    const value = prtoFiniteNumber(rawCost)
    if (barIndex === null || value === null) return null
    return { barIndex, value }
  })
  .filter(Boolean)
  .sort((left, right) => left.barIndex - right.barIndex)

const prassignMarkerOffsets = (markers) => {
  const buckets = new Map()
  markers.forEach((marker) => {
    const key = marker.barIndex
    const bucket = buckets.get(key) || []
    bucket.push(marker)
    buckets.set(key, bucket)
  })
  const offsets = new Map()
  buckets.forEach((bucket) => {
    const spacing = Math.min(0.18, 0.5 / Math.max(1, bucket.length))
    bucket.forEach((marker, index) => {
      offsets.set(marker.eventId, (index - (bucket.length - 1) / 2) * spacing)
    })
  })
  return offsets
}

export const buildSymbolReviewChartOption = ({
  kline,
  chart,
  conditionsResolver = () => null,
} = {}) => {
  const bars = prbuildBarSlots(kline)
  if (!bars.length) return null
  const normalized = normalizeSymbolChart(chart || {})
  const events = normalized.events
  const markers = prbuildMarkers(events, bars)
  const spans = prbuildSpanSegments(events, bars)
  const costPoints = prbuildCostPoints(normalized.costSeries, bars)
  const offsets = prassignMarkerOffsets(markers)

  const markerSeries = markers.length
    ? [{
        id: 'position-review-symbol-markers',
        name: '订单成交',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: (value, params) => params?.data?.symbol || 'circle',
        symbolSize: 13,
        animation: false,
        z: 12,
        label: {
          show: true,
          position: 'top',
          distance: 2,
          formatter: (params) => {
            if (params?.data?.mark) return '!'
            return params?.data?.sideText || ''
          },
          color: '#1f2937',
          fontSize: 9,
          fontWeight: 'bold',
        },
        data: markers.map((marker) => {
          const style = prverdictMarkerStyle(marker.verdict)
          return {
            value: [marker.barIndex + (offsets.get(marker.eventId) || 0), marker.price],
            event: marker.event,
            symbol: marker.symbol,
            sideText: marker.side === 'buy' ? 'B' : 'S',
            mark: style.mark,
            itemStyle: {
              color: marker.side === 'buy'
                ? positionReviewChartColors.buy
                : positionReviewChartColors.sell,
              borderColor: style.borderColor,
              borderWidth: style.borderWidth,
              opacity: style.opacity,
            },
          }
        }),
        tooltip: {
          show: true,
          className: 'prt-tooltip',
          confine: true,
          extraCssText: PR_TOOLTIP_CSS,
          formatter: (params) => {
            const event = params?.data?.event
            if (!event) return ''
            return buildFullMarkerTooltip(event, conditionsResolver(event.event_id))
          },
        },
      }]
    : []

  const spanSeries = spans.length
    ? [{
        id: 'position-review-symbol-fill-spans',
        name: '成交跨度',
        type: 'custom',
        coordinateSystem: 'cartesian2d',
        xAxisIndex: 0,
        yAxisIndex: 0,
        silent: true,
        animation: false,
        z: 8,
        data: spans,
        renderItem(params, api) {
          const item = spans[params.dataIndex]
          const start = api.coord([item.startIndex, item.price])
          const end = api.coord([item.endIndex, item.price])
          if (!start?.every(Number.isFinite) || !end?.every(Number.isFinite)) return null
          return {
            type: 'line',
            shape: { x1: start[0], y1: start[1], x2: end[0], y2: end[1] },
            style: {
              stroke: item.side === 'sell'
                ? positionReviewChartColors.sell
                : positionReviewChartColors.buy,
              lineWidth: 1.2,
              opacity: 0.85,
            },
          }
        },
      }]
    : []

  const costSeries = costPoints.length
    ? [{
        id: 'position-review-symbol-cost',
        name: '持仓均价',
        type: 'line',
        step: 'end',
        showSymbol: false,
        animation: false,
        z: 6,
        silent: true,
        lineStyle: { color: positionReviewChartColors.cost, width: 1.4, opacity: 0.85 },
        data: costPoints.map((point) => ({ value: [point.barIndex, point.value] })),
      }]
    : []

  return {
    backgroundColor: 'transparent',
    animation: false,
    title: {
      text: `${prtoText(normalized.symbol.code)} ${prtoText(normalized.symbol.name)}`.trim(),
      left: 8,
      top: 6,
      textStyle: { color: '#1f2937', fontSize: 14, fontWeight: 'normal' },
    },
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove|click',
      confine: true,
    },
    legend: {
      top: 8,
      right: 12,
      textStyle: { color: '#374151' },
      data: [
        ...(markerSeries.length ? ['订单成交'] : []),
        ...(costSeries.length ? ['持仓均价'] : []),
      ],
    },
    grid: { left: 58, right: 20, top: 44, bottom: 58 },
    xAxis: {
      type: 'category',
      data: bars.map((bar) => bar.label),
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: positionReviewChartColors.grid } },
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100, bottom: 8, height: 18 },
    ],
    series: [
      {
        id: 'position-review-symbol-candles',
        name: 'K线',
        type: 'candlestick',
        data: prtoArray(kline?.open).map((_, index) => [
          prtoFiniteNumber(kline?.open?.[index]),
          prtoFiniteNumber(kline?.close?.[index]),
          prtoFiniteNumber(kline?.low?.[index]),
          prtoFiniteNumber(kline?.high?.[index]),
        ]),
        animation: false,
        itemStyle: {
          color: positionReviewChartColors.up,
          color0: positionReviewChartColors.down,
          borderColor: positionReviewChartColors.up,
          borderColor0: positionReviewChartColors.down,
        },
      },
      ...spanSeries,
      ...costSeries,
      ...markerSeries,
    ],
  }
}

const prresolveCostIndex = (targetMs, points) => {
  if (!Number.isFinite(targetMs) || !points.length) return null
  let best = -1
  points.forEach((point, index) => {
    if (prparseBarTimeMs(point.time) <= targetMs) {
      best = index
    }
  })
  return best >= 0 ? best : 0
}

export const buildSymbolCostChartOption = ({
  chart,
  conditionsResolver = () => null,
} = {}) => {
  const normalized = normalizeSymbolChart(chart || {})
  const points = normalized.costSeries
    .map((point, index) => ({
      index,
      time: prtoText(point.time),
      timeMs: prparseBarTimeMs(point.time),
      averageCost: prtoFiniteNumber(point.average_cost),
      quantity: prtoInteger(point.position_quantity),
      pointType: prtoText(point.point_type),
      costBasisSource: prtoText(point.cost_basis_source),
    }))
    .filter((point) => point.timeMs != null && Number.isFinite(point.timeMs))
  const events = normalized.events
  if (!points.length && !events.length) {
    return null
  }
  const times = points.map((point) => point.time)

  const markers = events
    .map((event) => {
      const execution = event.execution || {}
      const marker = event.marker || {}
      const targetMs = prparseBarTimeMs(
        marker.bar_time
        || execution.first_fill_time
        || event.occurred_at,
      )
      const index = prresolveCostIndex(targetMs, points)
      if (index === null) return null
      const costValue = points[index]?.averageCost ?? null
      const price = prtoFiniteNumber(marker.price)
        ?? prtoFiniteNumber(execution.avg_filled_price)
        ?? costValue
      if (price === null) return null
      return {
        event,
        eventId: prtoText(event.event_id),
        side: prtoText(event.side).toLowerCase() === 'sell' ? 'sell' : 'buy',
        index,
        price,
        symbol: prtoText(marker.symbol) || 'circle',
        verdict: prtoText((event.review || {}).verdict).toUpperCase() || null,
        rebuilt: Boolean(event.rebuilt),
      }
    })
    .filter(Boolean)
  const offsets = prassignMarkerOffsets(markers.map((marker) => ({
    eventId: marker.eventId,
    barIndex: marker.index,
  })))

  const markerSeries = markers.length
    ? [{
        id: 'position-review-symbol-cost-markers',
        name: '订单事件',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: (value, params) => params?.data?.symbol || 'circle',
        symbolSize: (value, params) => (params?.data?.rebuilt ? 10 : 13),
        animation: false,
        z: 12,
        label: {
          show: true,
          position: 'top',
          distance: 2,
          formatter: (params) => {
            if (params?.data?.mark) return '!'
            if (params?.data?.rebuilt) return '账'
            return params?.data?.sideText || ''
          },
          color: '#1f2937',
          fontSize: 9,
          fontWeight: 'bold',
        },
        data: markers.map((marker) => {
          const style = prverdictMarkerStyle(marker.verdict)
          return {
            value: [marker.index + (offsets.get(marker.eventId) || 0), marker.price],
            event: marker.event,
            symbol: marker.symbol,
            sideText: marker.side === 'buy' ? 'B' : 'S',
            mark: style.mark,
            rebuilt: marker.rebuilt,
            itemStyle: {
              color: marker.side === 'buy'
                ? positionReviewChartColors.buy
                : positionReviewChartColors.sell,
              borderColor: style.borderColor,
              borderWidth: style.borderWidth,
              opacity: style.opacity,
            },
          }
        }),
        tooltip: {
          show: true,
          className: 'prt-tooltip',
          confine: true,
          extraCssText: PR_TOOLTIP_CSS,
          formatter: (params) => {
            const event = params?.data?.event
            if (!event) return ''
            return buildFullMarkerTooltip(event, conditionsResolver(event.event_id))
          },
        },
      }]
    : []

  const markAreas = []
  for (const cycle of normalized.holdingCycles) {
    const startIndex = cycle.open_time == null
      ? 0
      : prresolveCostIndex(prparseBarTimeMs(cycle.open_time), points)
    const endIndex = cycle.close_time == null
      ? points.length - 1
      : prresolveCostIndex(prparseBarTimeMs(cycle.close_time), points)
    if (startIndex === null || endIndex === null || startIndex > endIndex) {
      continue
    }
    markAreas.push([
      {
        coord: [startIndex, 'min'],
        name: cycle.cycle_id,
        itemStyle: {
          color: cycle.status === 'open'
            ? 'rgba(96,165,250,0.06)'
            : 'rgba(156,163,175,0.05)',
        },
        label: {
          show: true,
          position: 'insideTop',
          color: '#6b7280',
          fontSize: 9,
          formatter: `持仓周期 ${startIndex === endIndex ? startIndex + 1 : `${startIndex + 1}–${endIndex + 1}`}`,
        },
      },
      { coord: [endIndex, 'max'] },
    ])
  }

  const costLineSeries = points.length
    ? [{
        id: 'position-review-symbol-cost-line',
        name: '持仓成本价',
        type: 'line',
        step: 'end',
        showSymbol: points.length <= 1,
        animation: false,
        z: 6,
        lineStyle: { color: positionReviewChartColors.cost, width: 2 },
        markArea: markAreas.length ? { silent: true, data: markAreas } : undefined,
        data: points.map((point) => point.averageCost),
      }]
    : []

  const costPointSeries = points.length
    ? [{
        id: 'position-review-symbol-cost-points',
        name: '成本采样点',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'circle',
        symbolSize: 5,
        animation: false,
        z: 7,
        silent: true,
        itemStyle: { color: positionReviewChartColors.cost, opacity: 0.9 },
        data: points.map((point, index) => (
          point.averageCost === null ? null : [index, point.averageCost]
        )).filter(Boolean),
      }]
    : []

  return {
    backgroundColor: 'transparent',
    animation: false,
    title: {
      text: `${prtoText(normalized.symbol.code)} ${prtoText(normalized.symbol.name)}`.trim(),
      left: 8,
      top: 6,
      textStyle: { color: '#1f2937', fontSize: 14, fontWeight: 'normal' },
    },
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove|click',
      confine: true,
    },
    legend: {
      top: 8,
      right: 12,
      textStyle: { color: '#374151' },
      data: [
        ...(costLineSeries.length ? ['持仓成本价'] : []),
        ...(markerSeries.length ? ['订单事件'] : []),
      ],
    },
    grid: { left: 58, right: 20, top: 44, bottom: 40 },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#6b7280', formatter: (value) => Number(value).toFixed(2) },
      splitLine: { lineStyle: { color: positionReviewChartColors.grid } },
      name: '成本价',
      nameTextStyle: { color: '#6b7280' },
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100, bottom: 8, height: 18 },
    ],
    series: [...costLineSeries, ...costPointSeries, ...markerSeries],
  }
}

const prverdictMarkerStyle = (verdict) => {
  if (verdict === 'FAIL') {
    return { borderColor: '#111827', borderWidth: 2.5, opacity: 1, mark: true }
  }
  if (verdict === 'INSUFFICIENT_EVIDENCE') {
    return { borderColor: '#9ca3af', borderWidth: 1, opacity: 0.72, mark: false }
  }
  if (verdict === 'NOT_APPLICABLE') {
    return { borderColor: '#9ca3af', borderWidth: 1, opacity: 0.45, mark: false }
  }
  return { borderColor: '#111827', borderWidth: 1, opacity: 1, mark: false }
}

const prescapeTooltipHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const prtooltipValue = (value, fallback = '—') => (
  value === null || value === undefined || value === ''
    ? fallback
    : prescapeTooltipHtml(value)
)

const prtooltipRow = (label, value, fallback = '—') => (
  `<div class="prt-row"><span class="prt-label">${prescapeTooltipHtml(label)}</span><span class="prt-value">${prtooltipValue(value, fallback)}</span></div>`
)

const prtooltipSection = (title, body) => (
  `<div class="prt-section"><div class="prt-section-title">${prescapeTooltipHtml(title)}</div>${body}</div>`
)

const prconditionStatusLabel = (event) => {
  const conditions = event.conditions || {}
  if (conditions.condition_snapshot_status === 'complete') return '条件完整'
  if (conditions.condition_snapshot_status === 'missing') return '历史阈值证据缺失'
  if (conditions.condition_snapshot_status === 'partial') return '条件部分缺失'
  return '条件待加载'
}

const prbuildConditionsTooltipTable = (payload) => {
  const normalized = normalizeConditions(payload || {})
  if (!normalized.conditions.length) {
    return '<div class="prt-muted">该订单暂无可用条件证据</div>'
  }
  const rows = normalized.conditions.map((condition) => {
    const thresholdCell = condition.thresholdMissing
      ? '<span class="prt-missing">缺失</span>'
      : prtooltipValue(condition.thresholdDisplay)
    const passedCell = condition.passed === null
      ? '—'
      : `<span class="prt-${condition.passed ? 'ok' : 'bad'}">${condition.passed ? '是' : '否'}</span>`
    const sourceLabel = condition.source === 'runtime_event'
      ? '运行事件'
      : condition.source === 'request_snapshot'
        ? '请求快照'
        : condition.source === 'missing'
          ? '缺失'
          : prtooltipValue(condition.source)
    return `<tr>
      <td class="prt-key" title="${prescapeTooltipHtml(condition.key)}">${prescapeTooltipHtml(condition.label || condition.key)}</td>
      <td>${prtooltipValue(condition.actualDisplay)}</td>
      <td>${prescapeTooltipHtml(condition.operator || '—')}</td>
      <td>${thresholdCell}</td>
      <td>${passedCell}</td>
      <td>${sourceLabel}</td>
    </tr>`
  }).join('')
  return `<div class="prt-table-wrap"><table class="prt-table"><thead><tr>
    <th>条件</th><th>实际值</th><th>操作符</th><th>阈值</th><th>通过</th><th>来源</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`
}

export const buildFullMarkerTooltip = (event = {}, conditions = null) => {
  if (!event || !event.event_id) return ''
  const side = event.side === 'buy' ? '买入' : event.side === 'sell' ? '卖出' : '订单'
  const review = event.review || {}
  const signal = event.signal || {}
  const execution = event.execution || {}
  const order = event.order || {}
  const position = event.position_impact || {}
  const dataQuality = event.data_quality || {}
  const positionText = position.position_before == null || position.position_after == null
    ? '待持仓证据'
    : `${position.position_before} → ${position.position_after}`

  const header = `<div class="prt-header">
    <span class="prt-side prt-side-${event.side === 'sell' ? 'sell' : 'buy'}">${side}</span>
    <span class="prt-id">${prescapeTooltipHtml(event.event_id)}</span>
    <span class="prt-verdict">${prtooltipValue(review.verdict || '未判定')}</span>
  </div>`

  const signalBody = signal.id || signal.label
    ? [
        prtooltipRow('信号类型', signal.type),
        prtooltipRow('信号族', signal.family),
        prtooltipRow('信号名称', signal.label),
        prtooltipRow('信号时间', signal.time),
        prtooltipRow('信号价格', signal.price),
        prtooltipRow('信号数量', signal.quantity),
        prtooltipRow('信号方向', signal.direction),
        prtooltipRow('信号来源', signal.source),
        prtooltipRow('关联方式', signal.association_method),
        prtooltipRow('trace_id', signal.trace_id),
        prtooltipRow('intent_id', signal.intent_id),
        ...(signal.remark ? [prtooltipRow('信号备注', signal.remark)] : []),
      ].join('')
    : '<div class="prt-muted">未关联信号（不按时间邻近补配）</div>'

  const conditionsBody = conditions === null
    ? '<div class="prt-muted">条件证据加载中…</div>'
    : prbuildConditionsTooltipTable(conditions)

  const executionBody = [
    prtooltipRow('请求数量', order.request_quantity),
    prtooltipRow('策略应有量', order.expected_quantity, '证据不足'),
    prtooltipRow('实际成交量', execution.actual_quantity),
    prtooltipRow('加权成交均价', execution.avg_filled_price),
    prtooltipRow('成交笔数', execution.fill_count),
    prtooltipRow('首笔成交', execution.first_fill_time),
    prtooltipRow('末笔成交', execution.last_fill_time),
  ].join('')

  const positionBody = [
    prtooltipRow('持仓前后', positionText),
    prtooltipRow('均价前后', `${position.cost_basis_before ?? '—'} → ${position.cost_basis_after ?? '—'}`),
    prtooltipRow('已实现盈亏影响', position.realized_pnl_impact),
    prtooltipRow('持仓周期', position.holding_cycle_id),
    prtooltipRow('成本口径', position.cost_basis_source),
    prtooltipRow('费用口径', `fees_included: ${position.fees_included ? 'true' : 'false'}`),
  ].join('')

  const warnings = Array.isArray(dataQuality.warnings)
    ? dataQuality.warnings.map((warning) => warning?.message || warning?.code || '').filter(Boolean)
    : []
  const qualityBody = [
    prtooltipRow('关联质量', dataQuality.association_quality),
    prtooltipRow('条件状态', prconditionStatusLabel(event)),
    prtooltipRow('证据置信度', review.confidence),
    ...(warnings.length
      ? [prtooltipRow('数据质量提示', warnings.join('；'))]
      : []),
  ].join('')

  return `<div class="prt">
    ${header}
    ${prtooltipSection('触发信号', signalBody)}
    ${prtooltipSection('触发条件与全部阈值', conditionsBody)}
    ${prtooltipSection('订单与成交', executionBody)}
    ${prtooltipSection('仓位与成本影响', positionBody)}
    ${prtooltipSection('数据质量', qualityBody)}
  </div>`
}

export const buildMarkerTooltip = (event = {}) => buildFullMarkerTooltip(event, null)

export const normalizeConditions = (payload = {}) => {
  const conditions = prtoArray(payload.conditions).map((condition) => ({
    key: prtoText(condition.condition_key),
    label: prtoText(condition.label),
    actualValue: condition.actual_value,
    actualDisplay: prtoText(condition.actual_display),
    operator: prtoText(condition.operator),
    thresholdValue: condition.threshold_value,
    thresholdDisplay: prtoText(condition.threshold_display),
    unit: prtoText(condition.unit),
    passed: condition.passed,
    source: prtoText(condition.source),
    observedAt: prtoText(condition.observed_at),
    evidenceId: prtoText(condition.evidence_id),
    thresholdMissing: condition.threshold_value === null || condition.threshold_value === undefined,
  }))
  return {
    conditions,
    expression: prtoText(payload.expression),
    strategyVersion: prtoText(payload.strategy_version),
    configSnapshotHash: prtoText(payload.config_snapshot_hash),
    triggerSnapshot: payload.trigger_snapshot || null,
    evidence: payload.evidence || {},
    dataQuality: payload.data_quality || {},
    thresholdMissingCount: prtoInteger(
      (payload.data_quality || {}).threshold_missing_count,
      conditions.filter((condition) => condition.thresholdMissing).length,
    ),
  }
}

export const positionReviewRefactorFormatters = Object.freeze({
  amount: (value) => (value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })),
  signedAmount: (value) => {
    if (value == null) return '—'
    const numeric = Number(value)
    const sign = numeric > 0 ? '+' : ''
    return `${sign}${numeric.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
  },
  ratio: (value) => (value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`),
})

export const positionReviewRefactorConstants = Object.freeze({
  VERDICT_ORDER: prVERDICT_ORDER,
  SIGNAL_TYPE_LABELS: prSIGNAL_TYPE_LABELS,
})
