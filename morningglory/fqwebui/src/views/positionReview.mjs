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
  execution_history_archive_then_current_xt_om_union: '历史成交档案 + 当前 XT/OM',
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
      const status = resolvePrimaryStatus(row, counts)
      const statusMeta = getPositionReviewStatusMeta(status)
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
      const severityOrder = { ANOMALY: 0, UNVERIFIABLE: 1, COMPLIANT: 2, NOT_APPLICABLE: 3 }
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
    lowestGuardianPrice: toFiniteNumber(pickFirst(
      expected.lowest_guardian_price,
      expected.guardian_price,
      review.lowest_guardian_price,
    )),
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

const normalizeTimelineRows = (timeline = []) => {
  const seenIds = new Map()
  return toArray(timeline)
    .map((item, index) => {
      const status = normalizePositionReviewStatus(item.verdict || item.status)
      const meta = getPositionReviewStatusMeta(status)
      const time = toText(item.time || item.ts)
      const baseId = toText(item.id) || [
        item.type || 'timeline',
        time || 'no-time',
        normalizeSide(item.side) || 'no-side',
        item.quantity ?? 'no-quantity',
        item.price ?? 'no-price',
      ].join(':')
      const occurrence = seenIds.get(baseId) || 0
      seenIds.set(baseId, occurrence + 1)
      return {
        ...item,
        id: occurrence > 0 ? `${baseId}:${occurrence}:${index}` : baseId,
        time,
        timeLabel: time ? formatBeijingTimestamp(time) : '-',
        side: normalizeSide(item.side),
        status,
        statusLabel: meta.label,
        statusChipVariant: meta.chipVariant,
        price: toFiniteNumber(item.price),
        quantity: toInteger(item.quantity),
      }
    })
    .sort((left, right) => (parseTimestampMs(left.time) || 0) - (parseTimestampMs(right.time) || 0))
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
  const orderTimeline = (
    payload.order_timeline ||
    payload.orderTimeline ||
    payload.timeline_projection ||
    payload.timelineProjection ||
    (!Array.isArray(payload.timeline) && payload.timeline && typeof payload.timeline === 'object'
      ? payload.timeline
      : {})
  )
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
    orderTimeline,
    timeline: normalizeTimelineRows(Array.isArray(payload.timeline) ? payload.timeline : []),
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
