import { formatBeijingTimestamp, parseTimestampMs } from '../tool/beijingTime.mjs'
import {
  getPositionReviewStatusMeta,
  normalizePositionReviewStatus,
} from './positionReviewStateMeta.mjs'

/**
 * Shared order-level review timeline contract.
 *
 * Preferred API input:
 * {
 *   orders: [{
 *     internal_order_id, request_id, account_partition, signal_id, signal_time,
 *     signal_price, time, side, expected_quantity, filled_quantity,
 *     avg_filled_price, position_before, position_after, verdict
 *   }],
 *   position_points: [{ time, quantity, point_type }]
 * }
 *
 * The normalizer also accepts the current position-review detail payload
 * (`reviews`, `executions`, and `charts.cumulative_quantity`) so the UI can
 * ship before the order projection endpoint is available everywhere.
 */

export const ORDER_REVIEW_TIMELINE_COLORS = Object.freeze({
  buy: '#dc2626',
  sell: '#15803d',
  expected: '#b45309',
  actual: '#2563eb',
  position: '#35506c',
  signal: '#7c3aed',
  compliant: '#15803d',
  anomaly: '#dc2626',
  unverifiable: '#b45309',
  notApplicable: '#94a3b8',
  text: '#303133',
  muted: '#909399',
  border: '#ebeef5',
  grid: '#eef2f7',
})

const MISSING = Symbol('missing')
const toArray = (value) => (Array.isArray(value) ? value : [])
const toText = (value) => String(value ?? '').trim()

const toFiniteNumber = (value) => {
  if (value === MISSING || value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const toInteger = (value, fallback = 0) => {
  const parsed = toFiniteNumber(value)
  return parsed === null ? fallback : Math.trunc(parsed)
}

const ownValue = (source, key) => (
  source && typeof source === 'object' && Object.prototype.hasOwnProperty.call(source, key)
    ? source[key]
    : MISSING
)

const firstPresent = (...values) => {
  for (const value of values) {
    if (value !== MISSING && value !== undefined && value !== '') return value
  }
  return MISSING
}

const firstText = (...values) => {
  for (const value of values) {
    const text = toText(value === MISSING ? '' : value)
    if (text) return text
  }
  return ''
}

const firstArray = (...values) => {
  const populated = values.find((value) => Array.isArray(value) && value.length)
  return populated || values.find(Array.isArray) || []
}

const normalizeSide = (value) => {
  const text = toText(value).toLowerCase()
  if (['buy', 'buy_long', 'b', '1', 'long'].includes(text)) return 'buy'
  if (['sell', 'sell_short', 's', '2', 'short'].includes(text)) return 'sell'
  return ''
}

const signedQuantity = (side, value) => {
  const quantity = toFiniteNumber(value)
  if (quantity === null) return null
  const absolute = Math.abs(Math.trunc(quantity))
  return side === 'sell' ? -absolute : absolute
}

const statusRank = Object.freeze({
  ANOMALY: 4,
  UNVERIFIABLE: 3,
  COMPLIANT: 2,
  NOT_APPLICABLE: 1,
})

const chooseStatus = (items) => (
  items.reduce((selected, item) => (
    statusRank[item.status] > statusRank[selected.status] ? item : selected
  ), { status: 'NOT_APPLICABLE' }).status
)

const resolvePayload = (source = {}) => {
  if (!source || typeof source !== 'object' || Array.isArray(source)) return {}
  const envelope = source.data
  if (
    envelope &&
    typeof envelope === 'object' &&
    !Array.isArray(envelope) &&
    (
      Array.isArray(envelope.orders) ||
      Array.isArray(envelope.events) ||
      Array.isArray(envelope.order_events) ||
      Array.isArray(envelope.reviews) ||
      Array.isArray(envelope.position_points) ||
      Array.isArray(envelope.position_series) ||
      envelope.charts
    )
  ) {
    return envelope
  }
  return source
}

const resolveTimelineContainer = (payload) => {
  const candidates = [
    payload.order_timeline,
    payload.orderTimeline,
    payload.timeline_projection,
    payload.timelineProjection,
    payload.timeline,
  ]
  return candidates.find((value) => value && typeof value === 'object' && !Array.isArray(value)) || {}
}

const resolveOrderRows = (payload, timeline) => {
  const projected = firstArray(
    timeline.events,
    payload.events,
    timeline.order_events,
    timeline.orderEvents,
    payload.order_events,
    payload.orderEvents,
    payload.review_events,
    payload.reviewEvents,
    payload.orders,
    timeline.orders,
  )
  if (projected.length) return { rows: projected, origin: 'order_projection' }

  const reviews = firstArray(payload.reviews, payload.review_rows, payload.reviewRows)
  if (reviews.length) return { rows: reviews, origin: 'reviews_fallback' }

  const executions = firstArray(
    payload.executions,
    payload.canonical_executions,
    payload.canonical_trades,
    payload.fills,
  )
  return { rows: executions, origin: 'executions_fallback' }
}

const resolveFills = (source, actual) => firstArray(
  source.fills,
  source.executions,
  source.execution_fills,
  actual.fills,
  actual.executions,
)

const aggregateFillStats = (fills = []) => {
  const rows = toArray(fills)
  let quantity = 0
  let amount = 0
  let knownQuantity = false
  let fillCount = 0
  let lastTime = ''

  for (const fill of rows) {
    const fillQuantity = toFiniteNumber(firstPresent(
      ownValue(fill, 'quantity'),
      ownValue(fill, 'filled_quantity'),
      ownValue(fill, 'traded_volume'),
    ))
    const fillPrice = toFiniteNumber(firstPresent(
      ownValue(fill, 'price'),
      ownValue(fill, 'avg_filled_price'),
      ownValue(fill, 'traded_price'),
    ))
    const fillTime = firstText(
      fill?.time,
      fill?.trade_time,
      fill?.filled_at,
      fill?.created_at,
    )
    if (fillQuantity !== null) {
      quantity += Math.trunc(fillQuantity)
      knownQuantity = true
      fillCount += 1
      if (fillPrice !== null) amount += fillQuantity * fillPrice
    }
    if (fillTime && compareTime(fillTime, lastTime) > 0) lastTime = fillTime
  }

  return {
    quantity,
    knownQuantity,
    fillCount,
    avgPrice: quantity > 0 && amount > 0 ? amount / quantity : null,
    lastTime,
  }
}

const compareTime = (left, right) => {
  const leftMs = parseTimestampMs(left)
  const rightMs = parseTimestampMs(right)
  if (leftMs !== null && rightMs !== null) return leftMs - rightMs
  if (leftMs !== null) return -1
  if (rightMs !== null) return 1
  return String(left || '').localeCompare(String(right || ''))
}

const sortByTime = (items = []) => (
  [...items].sort((left, right) => {
    const timeResult = compareTime(left.time, right.time)
    if (timeResult) return timeResult
    const keyResult = String(left.orderKey || left.id || '').localeCompare(String(right.orderKey || right.id || ''))
    if (keyResult) return keyResult
    return Number(left.sourceIndex || 0) - Number(right.sourceIndex || 0)
  })
)

const firstNumeric = (...values) => {
  for (const value of values) {
    if (value === MISSING || value === undefined || value === '') continue
    const parsed = toFiniteNumber(value)
    if (parsed !== null) return parsed
  }
  return null
}

const firstNullableNumeric = (...values) => {
  for (const value of values) {
    if (value === MISSING || value === undefined || value === '') continue
    return toFiniteNumber(value)
  }
  return null
}

const normalizeOrderRow = (source = {}, index, origin) => {
  const request = source.request && typeof source.request === 'object' ? source.request : {}
  const expected = source.expected && typeof source.expected === 'object' ? source.expected : {}
  const actual = source.actual && typeof source.actual === 'object' ? source.actual : {}
  const signal = source.signal && typeof source.signal === 'object' ? source.signal : {}
  const order = source.order && typeof source.order === 'object' ? source.order : {}
  const fillStats = aggregateFillStats(resolveFills(source, actual))
  const isExecutionFallback = origin === 'executions_fallback'

  const accountPartition = firstText(
    source.account_partition,
    source.accountPartition,
    order.account_partition,
    order.accountPartition,
  )
  const requestId = firstText(
    source.request_id,
    source.requestId,
    request.request_id,
    request.id,
    order.request_id,
  )
  const internalOrderId = firstText(
    source.internal_order_id,
    source.internalOrderId,
    source.order_id,
    source.orderId,
    order.internal_order_id,
    order.internalOrderId,
    order.id,
  )
  const reviewId = firstText(source.review_id, source.reviewId)
  const brokerOrderId = firstText(
    source.broker_order_id,
    source.brokerOrderId,
    order.broker_order_id,
    order.brokerOrderId,
  )
  const executionId = firstText(
    source.execution_id,
    source.executionId,
    source.execution_fill_id,
    source.executionFillId,
    source.broker_trade_id,
    source.brokerTradeId,
  )
  const eventId = firstText(
    source.id,
    source.order_event_id,
    source.orderEventId,
  )
  const stableId = firstText(
    internalOrderId,
    eventId,
    requestId,
    reviewId,
    executionId,
    `order-${index + 1}`,
  )
  const orderKey = accountPartition ? `${accountPartition}:${stableId}` : stableId

  const expectedCandidate = firstPresent(
    ownValue(source, 'expected_quantity'),
    ownValue(source, 'expectedQuantity'),
    ownValue(source, 'strategy_expected_quantity'),
    ownValue(source, 'strategyExpectedQuantity'),
    ownValue(expected, 'quantity'),
    ownValue(expected, 'expected_quantity'),
    ownValue(order, 'expected_quantity'),
  )
  const expectedQuantity = firstNullableNumeric(expectedCandidate)
  const expectedKnown = expectedCandidate !== MISSING && expectedQuantity !== null

  const directFilledCandidate = firstPresent(
    ownValue(source, 'filled_quantity'),
    ownValue(source, 'filledQuantity'),
    ownValue(source, 'actual_quantity'),
    ownValue(source, 'actualQuantity'),
    ownValue(source, 'executed_quantity'),
    ownValue(source, 'executedQuantity'),
    ownValue(actual, 'filled_quantity'),
    ownValue(actual, 'quantity'),
    ownValue(order, 'filled_quantity'),
    isExecutionFallback ? ownValue(source, 'quantity') : MISSING,
  )
  const directFilled = firstNumeric(directFilledCandidate)
  const actualKnown = directFilled !== null || fillStats.knownQuantity
  const actualQuantity = Math.max(0, Math.trunc(
    directFilled ?? (fillStats.knownQuantity ? fillStats.quantity : 0),
  ))
  const fillCount = toInteger(firstPresent(
    ownValue(source, 'fill_count'),
    ownValue(source, 'fillCount'),
    ownValue(actual, 'fill_count'),
    ownValue(order, 'fill_count'),
    fillStats.fillCount || MISSING,
  ), actualKnown && actualQuantity > 0 ? 1 : 0)

  const requestQuantity = Math.max(0, toInteger(firstPresent(
    ownValue(source, 'requested_quantity'),
    ownValue(source, 'requestedQuantity'),
    ownValue(source, 'request_quantity'),
    ownValue(source, 'requestQuantity'),
    ownValue(request, 'quantity'),
    ownValue(order, 'quantity'),
  )))
  const avgFilledPrice = firstNumeric(
    ownValue(source, 'avg_filled_price'),
    ownValue(source, 'avgFilledPrice'),
    ownValue(source, 'average_filled_price'),
    ownValue(source, 'averageFilledPrice'),
    ownValue(actual, 'avg_filled_price'),
    ownValue(actual, 'weighted_average_price'),
    ownValue(actual, 'weightedAveragePrice'),
    ownValue(actual, 'price'),
    ownValue(order, 'avg_filled_price'),
    fillStats.avgPrice,
    isExecutionFallback ? ownValue(source, 'price') : MISSING,
  )
  const signalId = firstText(
    source.signal_id,
    source.signalId,
    signal.signal_id,
    signal.id,
  )
  const signalTime = firstText(
    source.signal_time,
    source.signalTime,
    signal.occurred_at,
    signal.time,
    signal.fire_time,
  )
  const signalPrice = firstNumeric(
    ownValue(source, 'signal_price'),
    ownValue(source, 'signalPrice'),
    ownValue(signal, 'price'),
  )
  const signalSide = normalizeSide(firstPresent(
    ownValue(signal, 'side'),
    ownValue(source, 'signal_side'),
    ownValue(source, 'signalSide'),
  ))
  const signalQuantity = firstNullableNumeric(
    ownValue(signal, 'quantity'),
    ownValue(source, 'signal_quantity'),
    ownValue(source, 'signalQuantity'),
  )
  const signalLabel = firstText(signal.label, source.signal_label, source.signalLabel)
  const signalStrategy = firstText(signal.strategy, source.signal_strategy, source.signalStrategy)
  const signalRemark = firstText(signal.remark, source.signal_remark, source.signalRemark)
  const orderTime = firstText(
    source.occurred_at,
    source.occurredAt,
    source.order_time,
    source.orderTime,
    source.request_time,
    source.requestTime,
    source.created_at,
    source.createdAt,
    request.created_at,
    order.created_at,
    order.time,
  )
  const filledAt = firstText(
    source.filled_at,
    source.filledAt,
    source.last_fill_at,
    source.lastFillAt,
    source.execution_time,
    source.executionTime,
    actual.filled_at,
    actual.last_fill_at,
    actual.lastFillAt,
    actual.first_fill_at,
    actual.firstFillAt,
    fillStats.lastTime,
    isExecutionFallback ? source.time : '',
    isExecutionFallback ? source.trade_time : '',
  )
  const time = firstText(filledAt, source.time, source.trade_time, orderTime, signalTime)
  const positionBefore = firstNumeric(
    ownValue(source, 'position_before'),
    ownValue(source, 'positionBefore'),
    ownValue(source, 'before_position_quantity'),
    ownValue(source, 'beforePositionQuantity'),
  )
  const positionAfter = firstNumeric(
    ownValue(source, 'position_after'),
    ownValue(source, 'positionAfter'),
    ownValue(source, 'after_position_quantity'),
    ownValue(source, 'afterPositionQuantity'),
  )
  const status = normalizePositionReviewStatus(firstPresent(
    ownValue(source, 'verdict'),
    ownValue(source, 'review_status'),
    ownValue(source, 'status'),
  ))
  const statusMeta = getPositionReviewStatusMeta(status)
  const eventType = firstText(source.type, source.event_type, source.eventType) || 'order'
  const actualScope = firstText(
    source.data_quality?.actual_scope,
    source.dataQuality?.actualScope,
    source.actual_scope,
    source.actualScope,
  ) || 'order'
  const side = normalizeSide(firstPresent(
    ownValue(source, 'side'),
    ownValue(request, 'side'),
    ownValue(order, 'side'),
  ))
  const reasonCodes = toArray(source.reason_codes || source.reasonCodes)
    .map(toText)
    .filter(Boolean)

  return {
    id: orderKey,
    orderKey,
    sourceIndex: index,
    eventId,
    type: eventType,
    requestId,
    internalOrderId,
    reviewId,
    brokerOrderId,
    executionId,
    originalOrderId: firstText(
      source.original_order_id,
      source.originalOrderId,
      order.original_order_id,
      order.originalOrderId,
      order.id,
    ),
    accountPartition,
    time,
    orderTime,
    filledAt,
    side,
    sideLabel: side === 'buy' ? '买入' : side === 'sell' ? '卖出' : '未知方向',
    signalId,
    signalTime,
    signalPrice,
    signalSide,
    signalQuantity,
    signalLabel,
    signalStrategy,
    signalRemark,
    signalAssociation: firstText(
      source.data_quality?.signal_association,
      source.dataQuality?.signalAssociation,
      source.signal_association,
      source.signalAssociation,
      signalId ? 'explicit-order-event' : 'none',
    ),
    hasSignalLink: eventType !== 'unassociated_execution' && Boolean(signalId),
    requestPrice: firstNumeric(
      ownValue(source, 'request_price'),
      ownValue(source, 'requestPrice'),
      ownValue(request, 'price'),
      ownValue(order, 'price'),
    ),
    requestQuantity,
    expectedQuantity,
    expectedKnown,
    actualQuantity,
    actualKnown,
    fillCount,
    avgFilledPrice,
    actualScope,
    positionBefore,
    positionAfter,
    status,
    statusLabel: statusMeta.label,
    statusChipVariant: statusMeta.chipVariant,
    reasonCodes,
    dataQuality: source.data_quality || source.dataQuality || {},
    slot: firstText(source.slot, source.time, source.occurred_at),
    plotSlot: firstNumeric(ownValue(source, 'plot_slot'), ownValue(source, 'plotSlot')),
    plotOffset: firstNumeric(ownValue(source, 'plot_offset'), ownValue(source, 'plotOffset')) ?? 0,
    origin,
    raw: source,
  }
}

const mergeOrderRows = (rows = []) => {
  if (rows.length === 1) return rows[0]
  const sorted = sortByTime(rows)
  // `events` is already an order-level projection. Repeated snapshots must
  // resolve to one canonical event rather than double-counting its aggregate.
  if (sorted.every((item) => item.origin !== 'executions_fallback')) {
    return sorted.at(-1)
  }
  const first = sorted[0]
  const actualRows = sorted.filter((item) => item.actualKnown)
  const actualQuantity = actualRows.reduce((sum, item) => sum + item.actualQuantity, 0)
  const weightedPriceAmount = actualRows.reduce((sum, item) => (
    item.avgFilledPrice === null ? sum : sum + item.actualQuantity * item.avgFilledPrice
  ), 0)
  const weightedQuantity = actualRows.reduce((sum, item) => (
    item.avgFilledPrice === null ? sum : sum + item.actualQuantity
  ), 0)
  const expectedRow = sorted.find((item) => item.expectedKnown)
  const requestRow = sorted.find((item) => item.requestQuantity > 0) || first
  const beforeRow = sorted.find((item) => item.positionBefore !== null)
  const afterRow = [...sorted].reverse().find((item) => item.positionAfter !== null)
  const signalRow = sorted.find((item) => item.hasSignalLink) || first
  const latestFillRow = [...sorted].reverse().find((item) => item.filledAt) || first
  const status = chooseStatus(sorted)
  const statusMeta = getPositionReviewStatusMeta(status)

  return {
    ...first,
    time: latestFillRow.time || first.time,
    filledAt: latestFillRow.filledAt,
    requestQuantity: requestRow.requestQuantity,
    expectedQuantity: expectedRow?.expectedQuantity ?? null,
    expectedKnown: Boolean(expectedRow),
    actualQuantity,
    actualKnown: actualRows.length > 0,
    fillCount: actualRows.reduce((sum, item) => sum + item.fillCount, 0),
    avgFilledPrice: weightedQuantity > 0 ? weightedPriceAmount / weightedQuantity : first.avgFilledPrice,
    positionBefore: beforeRow?.positionBefore ?? null,
    positionAfter: afterRow?.positionAfter ?? null,
    signalId: signalRow.signalId,
    signalTime: signalRow.signalTime,
    signalPrice: signalRow.signalPrice,
    hasSignalLink: signalRow.hasSignalLink,
    status,
    statusLabel: statusMeta.label,
    statusChipVariant: statusMeta.chipVariant,
    reasonCodes: [...new Set(sorted.flatMap((item) => item.reasonCodes))],
    raw: sorted.map((item) => item.raw),
  }
}

const normalizeOrders = (rows, origin) => {
  const groups = new Map()
  toArray(rows).forEach((item, index) => {
    const normalized = normalizeOrderRow(item || {}, index, origin)
    const group = groups.get(normalized.orderKey) || []
    group.push(normalized)
    groups.set(normalized.orderKey, group)
  })
  return sortByTime([...groups.values()].map(mergeOrderRows))
}

const normalizePositionPoint = (source = {}, index) => {
  const time = firstText(source.time, source.ts, source.date, source.at)
  const value = firstNumeric(
    ownValue(source, 'quantity'),
    ownValue(source, 'position_quantity'),
    ownValue(source, 'positionQuantity'),
    ownValue(source, 'value'),
    ownValue(source, 'position'),
  )
  const pointType = firstText(source.point_type, source.pointType)
  return {
    id: firstText(source.position_point_id, source.positionPointId, source.id, `position-${index + 1}`),
    orderEventId: firstText(source.order_event_id, source.orderEventId),
    time,
    value,
    pointType,
    assumption: Boolean(source.assumption || pointType === 'derived_initial'),
    initial: pointType === 'derived_initial' || Boolean(source.initial),
    source: firstText(source.source, source.position_source, source.positionSource),
    sequence: toInteger(
      firstPresent(
        ownValue(source, 'sequence'),
        ownValue(source, 'sort_order'),
        pointType === 'derived_initial' ? -1 : MISSING,
      ),
      pointType === 'derived_initial' ? -1 : 2,
    ),
    raw: source,
  }
}

const initialPositionQuantity = (payload) => firstNumeric(
  ownValue(payload, 'initial_position_quantity'),
  ownValue(payload, 'initialPositionQuantity'),
  ownValue(payload.summary || {}, 'initial_position_quantity'),
  ownValue(payload.summary || {}, 'initialPositionQuantity'),
  ownValue(payload.data_quality || {}, 'initial_position_quantity'),
  ownValue(payload.data_quality || {}, 'initialPositionQuantity'),
)

const buildDerivedPositionPoints = (orders, initialQuantity) => {
  const points = []
  let current = initialQuantity
  let initialAdded = false

  for (const order of orders) {
    if (!order.time) continue
    const before = order.positionBefore ?? current
    if (before !== null && !initialAdded) {
      points.push({
        id: `position-before:${order.orderKey}`,
        time: order.time,
        value: before,
        pointType: initialQuantity !== null ? 'derived_initial' : 'order_position_before',
        assumption: initialQuantity !== null,
        initial: true,
        sequence: -1,
        source: 'derived_fallback',
        orderEventId: order.eventId,
        raw: order,
      })
      initialAdded = true
    }
    const delta = order.side === 'buy'
      ? order.actualQuantity
      : order.side === 'sell'
        ? -order.actualQuantity
        : 0
    const after = order.positionAfter ?? (
      before !== null && order.actualKnown ? before + delta : null
    )
    if (after !== null) {
      points.push({
        id: `position-after:${order.orderKey}`,
        time: order.time,
        value: after,
        pointType: 'derived_order_position',
        assumption: order.positionAfter === null,
        initial: false,
        sequence: 2,
        source: 'derived_fallback',
        orderEventId: order.eventId,
        raw: order,
      })
      current = after
    }
  }
  return points
}

const normalizePositionPoints = (payload, timeline, orders, origin) => {
  const projectionSeries = [
    timeline.position_series,
    timeline.positionSeries,
    payload.position_series,
    payload.positionSeries,
  ]
  const hasProjectionSeries = projectionSeries.some(Array.isArray)
  const raw = firstArray(
    ...projectionSeries,
    timeline.position_points,
    timeline.positionPoints,
    payload.position_points,
    payload.positionPoints,
    payload.charts?.position_quantity,
    payload.charts?.cumulative_quantity,
  )
  const points = raw
    .map(normalizePositionPoint)
    .filter((item) => item.time && parseTimestampMs(item.time) !== null && item.value !== null)
    .sort((left, right) => compareTime(left.time, right.time) || left.sequence - right.sequence)
  if (points.length) {
    return {
      points,
      source: hasProjectionSeries ? 'projection' : 'detail_fallback',
    }
  }
  if (hasProjectionSeries || origin === 'order_projection') {
    return { points: [], source: 'projection_unavailable' }
  }
  return {
    points: buildDerivedPositionPoints(orders, initialPositionQuantity(payload)),
    source: 'derived_fallback',
  }
}

const buildCategories = (orders, positionPoints) => {
  const categories = []

  for (const order of orders) {
    if (!order.time) continue
    if (order.hasSignalLink && order.signalTime && order.signalTime !== order.time) {
      const key = `signal:${order.orderKey}`
      categories.push({
        key,
        time: order.signalTime,
        rank: 0,
        type: 'signal',
        order,
      })
    }
    categories.push({
      key: `order:${order.orderKey}`,
      time: order.time,
      rank: 1,
      type: 'order',
      order,
    })
  }

  for (const point of positionPoints) {
    if (!point.time) continue
    categories.push({
      key: `position:${point.id}`,
      time: point.time,
      rank: point.sequence,
      type: 'position',
      position: point,
    })
  }

  return categories
    .sort((left, right) => {
      const timeResult = compareTime(left.time, right.time)
      if (timeResult) return timeResult
      if (left.rank !== right.rank) return left.rank - right.rank
      return left.key.localeCompare(right.key)
    })
    .map((item, index) => ({
      ...item,
      index,
      label: formatBeijingTimestamp(item.time, item.time || '时间未知'),
      signalKey: item.type === 'signal' ? item.key : `signal:${item.order?.orderKey || ''}`,
    }))
}

const assignPlotSlots = (orders, positionPoints, categories) => {
  const ordersBySlot = new Map()
  orders.forEach((order, index) => {
    order.slot = order.slot || order.time || `unknown:${index}`
    if (order.plotSlot === null) order.plotSlot = index
    const group = ordersBySlot.get(order.slot) || []
    group.push(order)
    ordersBySlot.set(order.slot, group)
  })
  for (const group of ordersBySlot.values()) {
    group.sort((left, right) => (
      left.orderKey.localeCompare(right.orderKey) || left.sourceIndex - right.sourceIndex
    ))
    const center = (group.length - 1) / 2
    group.forEach((order, index) => {
      if (!order.plotOffset) order.plotOffset = (index - center) * 0.18
    })
  }
  for (const category of categories) {
    if (category.type === 'order') category.order.orderAxisSlot = category.index
    if (category.type === 'signal') category.order.signalAxisSlot = category.index
    if (category.type === 'position') category.position.plotSlot = category.index
  }
  return { orders, positionPoints, categories }
}

export const normalizeOrderReviewTimeline = (source = {}) => {
  if (source?.kind === 'order-review-timeline' && Array.isArray(source.categories)) return source

  const payload = resolvePayload(source)
  const timeline = resolveTimelineContainer(payload)
  const { rows, origin } = resolveOrderRows(payload, timeline)
  const orders = normalizeOrders(rows, origin)
  const positionResult = normalizePositionPoints(payload, timeline, orders, origin)
  const positionPoints = positionResult.points
  const categories = buildCategories(orders, positionPoints)
  assignPlotSlots(orders, positionPoints, categories)

  return {
    kind: 'order-review-timeline',
    source: origin,
    positionSource: positionResult.source,
    orders,
    positionPoints,
    categories,
    hasData: Boolean(orders.length || positionPoints.length),
    hasOrderData: Boolean(orders.length),
    hasPositionData: Boolean(positionPoints.length),
  }
}

const buildOrderData = (order, index, value) => ({
  id: `order:${order.orderKey}`,
  eventId: order.eventId || order.reviewId || order.requestId || order.internalOrderId || order.orderKey,
  orderKey: order.orderKey,
  requestId: order.requestId,
  internalOrderId: order.internalOrderId,
  originalOrderId: order.originalOrderId,
  signalId: order.signalId,
  signalTime: order.signalTime,
  plotSlot: order.plotSlot,
  slot: order.slot,
  plotOffset: order.plotOffset,
  orderAxisSlot: order.orderAxisSlot,
  signalAxisSlot: order.signalAxisSlot,
  expectedQuantity: order.expectedQuantity,
  actualQuantity: order.actualQuantity,
  expectedSignedQuantity: signedQuantity(order.side, order.expectedQuantity),
  actualSignedQuantity: signedQuantity(order.side, order.actualQuantity),
  positionBefore: order.positionBefore,
  positionAfter: order.positionAfter,
  status: order.status,
  order,
  value: [index, value],
})

const buildPositionSeriesData = (categories) => {
  let current = null
  return categories.map((category) => {
    if (category.type === 'position') current = category.position.value
    if (current === null) return null
    return {
      value: current,
      eventId: category.order?.reviewId || category.order?.requestId || category.order?.internalOrderId || '',
      pointType: category.position?.pointType || '',
      assumption: Boolean(category.position?.assumption),
    }
  })
}

const escapeHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const formatQuantity = (value, unknown = '证据不足') => (
  value === null || value === undefined ? unknown : Number(value).toLocaleString('zh-CN')
)

const buildTooltipFormatter = (categories) => (params) => {
  const rows = Array.isArray(params) ? params : [params]
  const index = Number(rows[0]?.dataIndex)
  const category = categories[index]
  const order = category?.order || rows.map((item) => item?.data?.order).find(Boolean)
  const header = escapeHtml(category?.label || rows[0]?.axisValueLabel || '')
  if (!order) {
    const body = rows.map((item) => (
      `${item?.marker || ''}${escapeHtml(item?.seriesName || '')}: ${escapeHtml(item?.value ?? '-')}`
    ))
    return [header, ...body].filter(Boolean).join('<br/>')
  }

  const orderId = order.internalOrderId || order.requestId || order.orderKey
  const signal = order.hasSignalLink
    ? order.signalId || formatBeijingTimestamp(order.signalTime, order.signalTime)
    : '未关联信号（证据不足）'
  const position = order.positionBefore !== null || order.positionAfter !== null
    ? `${formatQuantity(order.positionBefore, '-') } -> ${formatQuantity(order.positionAfter, '-')}`
    : '待持仓证据'
  const eventLabel = order.type === 'unassociated_execution'
    ? '未关联成交（订单证据不足）'
    : `${order.sideLabel}订单`
  const actualLabel = order.actualScope === 'window' ? '实际成交量（窗口内）' : '实际成交量'
  return [
    header,
    `${eventLabel}: ${escapeHtml(orderId)}`,
    `关联信号: ${escapeHtml(signal)}`,
    `策略应有量: ${formatQuantity(order.expectedQuantity)}`,
    `${actualLabel}: ${formatQuantity(order.actualQuantity, '0')}`,
    `持仓: ${position}`,
    `复盘结论: ${escapeHtml(order.statusLabel)}`,
  ].join('<br/>')
}

const statusColor = (status) => ({
  COMPLIANT: ORDER_REVIEW_TIMELINE_COLORS.compliant,
  ANOMALY: ORDER_REVIEW_TIMELINE_COLORS.anomaly,
  UNVERIFIABLE: ORDER_REVIEW_TIMELINE_COLORS.unverifiable,
  NOT_APPLICABLE: ORDER_REVIEW_TIMELINE_COLORS.notApplicable,
}[status] || ORDER_REVIEW_TIMELINE_COLORS.notApplicable)

const eventReference = (order) => (
  order.eventId || order.reviewId || order.requestId || order.internalOrderId || order.orderKey
)

const shortHash = (value) => {
  let hash = 2166136261
  for (const character of String(value || 'order')) {
    hash = Math.imul(hash ^ character.charCodeAt(0), 16777619)
  }
  return (hash >>> 0).toString(36).padStart(6, '0').slice(-6)
}

const toOverlayOrder = (order) => {
  const tooltipId = `order-${shortHash(order.orderKey)}`
  return {
    id: eventReference(order),
    tooltipId,
    shortId: tooltipId,
    orderKey: order.orderKey,
    originalOrderId: order.originalOrderId,
    internalOrderId: order.internalOrderId,
    requestId: order.requestId,
    accountPartition: order.accountPartition,
    type: order.type,
    time: order.time,
    slot: order.slot,
    plotSlot: order.plotSlot,
    plotOffset: order.plotOffset,
    side: order.side,
    sideLabel: order.sideLabel,
    requestPrice: order.requestPrice,
    requestQuantity: order.requestQuantity,
    expectedQuantity: order.expectedQuantity,
    expectedSignedQuantity: signedQuantity(order.side, order.expectedQuantity),
    actualQuantity: order.actualQuantity,
    actualSignedQuantity: signedQuantity(order.side, order.actualQuantity),
    avgFilledPrice: order.avgFilledPrice,
    fillCount: order.fillCount,
    actualScope: order.actualScope,
    positionBefore: order.positionBefore,
    positionAfter: order.positionAfter,
    status: order.status,
    statusLabel: order.statusLabel,
    signal: order.hasSignalLink
      ? {
          id: order.signalId,
          time: order.signalTime,
          price: order.signalPrice,
          side: order.signalSide,
          quantity: order.signalQuantity,
          label: order.signalLabel,
          strategy: order.signalStrategy,
          remark: order.signalRemark,
          association: order.signalAssociation,
        }
      : null,
    dataQuality: {
      associationQuality: order.dataQuality?.association_quality || order.dataQuality?.associationQuality || '',
      associationMethods: toArray(order.dataQuality?.association_methods || order.dataQuality?.associationMethods),
      signalAssociation: order.signalAssociation,
      evidenceConfidence: order.dataQuality?.evidence_confidence || order.dataQuality?.evidenceConfidence || '',
      actualScope: order.actualScope,
      warnings: toArray(order.dataQuality?.warnings).map((item) => (
        typeof item === 'string' ? item : {
          code: toText(item?.code),
          message: toText(item?.message),
        }
      )),
    },
  }
}

export const buildOrderReviewOverlayData = (source = {}) => {
  const model = normalizeOrderReviewTimeline(source)
  const overlayOrders = model.orders.map(toOverlayOrder)
  const orderByKey = new Map(overlayOrders.map((order) => [order.orderKey, order]))
  const tooltipById = Object.fromEntries(overlayOrders.map((order) => [order.tooltipId, order]))
  const overlayPositionPoints = model.positionPoints.map((point) => ({
    time: point.time,
    value: point.value,
    pointType: point.pointType,
    assumption: point.assumption,
    source: point.source,
    orderEventId: point.orderEventId,
    plotSlot: point.plotSlot,
  }))
  const publicModel = {
    kind: model.kind,
    source: model.source,
    positionSource: model.positionSource,
    orders: overlayOrders,
    positionPoints: overlayPositionPoints,
    hasData: model.hasData,
    hasOrderData: model.hasOrderData,
    hasPositionData: model.hasPositionData,
  }
  return {
    model: publicModel,
    orders: overlayOrders,
    tooltipById,
    positionSource: model.positionSource,
    signalMarkers: model.orders
      .filter((order) => (
        order.type !== 'unassociated_execution' && order.hasSignalLink && order.signalPrice !== null
      ))
      .map((order) => ({
        time: order.signalTime || order.time,
        price: order.signalPrice,
        eventId: eventReference(order),
        orderKey: order.orderKey,
        internalOrderId: order.internalOrderId,
        requestId: order.requestId,
        originalOrderId: order.originalOrderId,
        slot: order.slot,
        plotSlot: order.plotSlot,
        plotOffset: order.plotOffset,
        tooltipId: orderByKey.get(order.orderKey)?.tooltipId,
        order: orderByKey.get(order.orderKey),
      })),
    orderFillMarkers: model.orders
      .filter((order) => order.actualQuantity > 0 && order.avgFilledPrice !== null)
      .map((order) => ({
        time: order.time,
        price: order.avgFilledPrice,
        quantity: order.actualQuantity,
        signedQuantity: signedQuantity(order.side, order.actualQuantity),
        side: order.side,
        eventId: eventReference(order),
        orderKey: order.orderKey,
        internalOrderId: order.internalOrderId,
        requestId: order.requestId,
        originalOrderId: order.originalOrderId,
        slot: order.slot,
        plotSlot: order.plotSlot,
        plotOffset: order.plotOffset,
        tooltipId: orderByKey.get(order.orderKey)?.tooltipId,
        order: orderByKey.get(order.orderKey),
      })),
    quantityEvents: model.orders.map((order) => ({
      time: order.time,
      expectedQuantity: order.expectedQuantity,
      expectedSignedQuantity: signedQuantity(order.side, order.expectedQuantity),
      requestQuantity: order.requestQuantity,
      requestSignedQuantity: signedQuantity(order.side, order.requestQuantity),
      actualQuantity: order.actualQuantity,
      actualSignedQuantity: signedQuantity(order.side, order.actualQuantity),
      side: order.side,
      eventId: eventReference(order),
      orderKey: order.orderKey,
      internalOrderId: order.internalOrderId,
      requestId: order.requestId,
      originalOrderId: order.originalOrderId,
      slot: order.slot,
      plotSlot: order.plotSlot,
      plotOffset: order.plotOffset,
      tooltipId: orderByKey.get(order.orderKey)?.tooltipId,
      order: orderByKey.get(order.orderKey),
    })),
    positionPoints: overlayPositionPoints,
  }
}

/**
 * Builds the standalone, three-track ECharts option used by PositionReview.
 * It deliberately has no signal/request price line: signals and executions are
 * discrete order-level markers, while quantities and holdings share the time
 * axis below them.
 */
export const buildOrderReviewTimelineOption = (source = {}) => {
  const model = normalizeOrderReviewTimeline(source)
  const categories = model.categories
  const labels = categories.map((item) => item.label)
  const orderCategoryIndex = new Map(
    categories
      .filter((item) => item.type === 'order')
      .map((item) => [item.order.orderKey, item.index]),
  )
  const signalCategoryIndex = new Map(
    categories
      .filter((item) => item.type === 'signal')
      .map((item) => [item.order.orderKey, item.index]),
  )
  const signalMarkers = model.orders
    .filter((order) => order.hasSignalLink && order.signalPrice !== null)
    .map((order) => {
      const index = signalCategoryIndex.get(order.orderKey) ?? orderCategoryIndex.get(order.orderKey)
      return index === undefined ? null : buildOrderData(
        order,
        index,
        order.signalPrice,
      )
    })
    .filter(Boolean)
  const buyFillMarkers = model.orders
    .filter((order) => order.side === 'buy' && order.actualQuantity > 0 && order.avgFilledPrice !== null)
    .map((order) => buildOrderData(order, orderCategoryIndex.get(order.orderKey), order.avgFilledPrice))
    .filter((item) => item.value[0] !== undefined)
  const sellFillMarkers = model.orders
    .filter((order) => order.side === 'sell' && order.actualQuantity > 0 && order.avgFilledPrice !== null)
    .map((order) => buildOrderData(order, orderCategoryIndex.get(order.orderKey), order.avgFilledPrice))
    .filter((item) => item.value[0] !== undefined)
  const signalOrderLinks = model.orders
    .filter((order) => (
      order.hasSignalLink &&
      order.signalPrice !== null &&
      order.avgFilledPrice !== null &&
      signalCategoryIndex.has(order.orderKey) &&
      orderCategoryIndex.has(order.orderKey)
    ))
    .map((order) => ({
      eventId: order.reviewId || order.requestId || order.internalOrderId || order.orderKey,
      signalIndex: signalCategoryIndex.get(order.orderKey),
      signalPrice: order.signalPrice,
      orderIndex: orderCategoryIndex.get(order.orderKey),
      fillPrice: order.avgFilledPrice,
    }))
    .filter((item) => item.signalIndex !== item.orderIndex)
  const expectedQuantityData = categories.map((category) => {
    if (category.type !== 'order') return null
    const order = category.order
    return {
      ...buildOrderData(order, category.index, signedQuantity(order.side, order.expectedQuantity)),
      value: signedQuantity(order.side, order.expectedQuantity),
      evidenceInsufficient: !order.expectedKnown,
    }
  })
  const actualQuantityData = categories.map((category) => {
    if (category.type !== 'order') return null
    const order = category.order
    return {
      ...buildOrderData(order, category.index, signedQuantity(order.side, order.actualQuantity)),
      value: signedQuantity(order.side, order.actualQuantity),
      evidenceInsufficient: !order.actualKnown,
    }
  })
  const derivedInitial = categories.find((item) => (
    item.type === 'position' && item.position.initial && item.position.assumption
  ))
  const visibleWindowStart = categories.length > 36
    ? Math.max(0, 100 - (36 / categories.length) * 100)
    : 0

  return {
    animation: false,
    textStyle: {
      color: ORDER_REVIEW_TIMELINE_COLORS.text,
      fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
    },
    aria: {
      enabled: true,
      decal: { show: true },
      description: `订单级持仓复盘，共 ${model.orders.length} 个订单聚合节点、${model.positionPoints.length} 个持仓变化点。信号只显示已关联订单，不展示逐笔成交明细。`,
    },
    color: [
      ORDER_REVIEW_TIMELINE_COLORS.signal,
      ORDER_REVIEW_TIMELINE_COLORS.buy,
      ORDER_REVIEW_TIMELINE_COLORS.sell,
      ORDER_REVIEW_TIMELINE_COLORS.expected,
      ORDER_REVIEW_TIMELINE_COLORS.actual,
      ORDER_REVIEW_TIMELINE_COLORS.position,
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: buildTooltipFormatter(categories),
    },
    legend: {
      type: 'scroll',
      top: 0,
      left: 8,
      right: 8,
      data: ['关联信号', '买入订单成交均价', '卖出订单成交均价', '策略应有量', '实际成交量', '持仓数量'],
    },
    axisPointer: {
      link: [{ xAxisIndex: [0, 1, 2] }],
    },
    grid: [
      { left: 64, right: 28, top: 56, height: '35%' },
      { left: 64, right: 28, top: '51%', height: '17%' },
      { left: 64, right: 28, top: '75%', height: '12%' },
    ],
    xAxis: [0, 1, 2].map((index) => ({
      type: 'category',
      gridIndex: index,
      boundaryGap: index === 1,
      data: labels,
      axisLabel: { show: index === 2, hideOverlap: true },
      axisTick: { show: index === 2 },
      axisLine: { lineStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.border } },
    })),
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        name: '价格',
        scale: true,
        splitLine: { lineStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.grid } },
      },
      {
        type: 'value',
        gridIndex: 1,
        name: '数量（买+/卖-）',
        minInterval: 100,
        splitLine: { lineStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.grid } },
      },
      {
        type: 'value',
        gridIndex: 2,
        name: '持仓',
        minInterval: 100,
        splitLine: { lineStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.grid } },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, 2], start: visibleWindowStart, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1, 2], height: 18, bottom: 8, start: visibleWindowStart, end: 100 },
    ],
    series: [
      {
        id: 'order-signal-anchor',
        name: '关联信号',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'diamond',
        symbolSize: 10,
        itemStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.signal },
        data: signalMarkers,
        markLine: signalOrderLinks.length
          ? {
              silent: true,
              symbol: ['none', 'arrow'],
              symbolSize: 7,
              label: { show: false },
              lineStyle: {
                color: ORDER_REVIEW_TIMELINE_COLORS.signal,
                type: 'dashed',
                width: 1.25,
                opacity: 0.78,
              },
              data: signalOrderLinks.map((link) => ([
                { coord: [link.signalIndex, link.signalPrice] },
                { coord: [link.orderIndex, link.fillPrice], eventId: link.eventId },
              ])),
            }
          : undefined,
      },
      {
        id: 'buy-order-fill-price',
        name: '买入订单成交均价',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'triangle',
        symbolSize: 13,
        itemStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.buy },
        data: buyFillMarkers,
      },
      {
        id: 'sell-order-fill-price',
        name: '卖出订单成交均价',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'pin',
        symbolSize: 16,
        itemStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.sell },
        data: sellFillMarkers,
      },
      {
        id: 'order-expected-quantity',
        name: '策略应有量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 22,
        data: expectedQuantityData,
      },
      {
        id: 'order-actual-quantity',
        name: '实际成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 22,
        data: actualQuantityData,
        itemStyle: {
          color: (params) => statusColor(params?.data?.status),
        },
      },
      {
        id: 'position-quantity',
        name: '持仓数量',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        step: 'end',
        showSymbol: false,
        lineStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.position },
        areaStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.position, opacity: 0.12 },
        data: buildPositionSeriesData(categories),
        markPoint: derivedInitial
          ? {
              symbol: 'pin',
              symbolSize: 44,
              itemStyle: { color: ORDER_REVIEW_TIMELINE_COLORS.expected },
              label: { show: true, formatter: '期初仓（推导）\n{c}', fontSize: 10 },
              data: [{
                name: '期初仓（推导）',
                coord: [derivedInitial.index, derivedInitial.position.value],
                value: derivedInitial.position.value,
              }],
            }
          : undefined,
      },
    ],
  }
}
