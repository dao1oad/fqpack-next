import { formatBeijingTimestamp } from '../tool/beijingTime.mjs'

const toText = (value) => String(value || '').trim()

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const toFiniteNumber = (value) => {
  if (value === null || value === undefined) return null
  if (typeof value === 'string' && value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const readApiPayload = (response, key, fallback = null) => {
  if (response && typeof response === 'object') {
    if (response[key] !== undefined) return response[key]
    if (response.data && typeof response.data === 'object' && response.data[key] !== undefined) {
      return response.data[key]
    }
  }
  return fallback
}

const sortByCountAndLabel = (entries = []) => {
  return [...entries].sort((left, right) => {
    const countDiff = Number(right[1] || 0) - Number(left[1] || 0)
    if (countDiff !== 0) return countDiff
    return String(left[0]).localeCompare(String(right[0]))
  })
}

export const buildOrderRows = (rows = []) => {
  return [...(Array.isArray(rows) ? rows : [])]
    .map((row) => ({
      ...row,
      internal_order_id: toText(row?.internal_order_id),
      request_id: toText(row?.request_id),
      broker_order_id: toText(row?.broker_order_id),
      symbol: toText(row?.symbol),
      name: toText(row?.name),
      side: toText(row?.side),
      state: toText(row?.state),
      source: toText(row?.source),
      source_type: toText(row?.source_type),
      strategy_name: toText(row?.strategy_name),
      account_type: toText(row?.account_type),
      created_at: toText(row?.created_at),
      submitted_at: toText(row?.submitted_at),
      updated_at: toText(row?.updated_at),
      filled_quantity: toNumber(row?.filled_quantity),
      avg_filled_price: row?.avg_filled_price,
      quantity: row?.quantity,
      price: row?.price,
      summaryLabel: [
        toText(row?.symbol) || '-',
        toText(row?.side) || '-',
        toText(row?.state) || '-',
      ].join(' · '),
    }))
    .sort((left, right) => {
      const updatedDiff = right.updated_at.localeCompare(left.updated_at)
      if (updatedDiff !== 0) return updatedDiff
      const createdDiff = right.created_at.localeCompare(left.created_at)
      if (createdDiff !== 0) return createdDiff
      return right.internal_order_id.localeCompare(left.internal_order_id)
    })
}

export const buildOrderStats = (stats = {}) => {
  const sideDistribution = stats?.side_distribution || {}
  const stateDistribution = stats?.state_distribution || {}
  return {
    ...stats,
    total: toNumber(stats?.total),
    missing_broker_order_count: toNumber(stats?.missing_broker_order_count),
    latest_updated_at: formatBeijingTimestamp(stats?.latest_updated_at),
    filled_count: toNumber(stats?.filled_count),
    partial_filled_count: toNumber(stats?.partial_filled_count),
    canceled_count: toNumber(stats?.canceled_count),
    failed_count: toNumber(stats?.failed_count),
    sideCards: [
      { key: 'buy', label: '买单', value: toNumber(sideDistribution.buy) },
      { key: 'sell', label: '卖单', value: toNumber(sideDistribution.sell) },
    ],
    stateCards: sortByCountAndLabel(Object.entries(stateDistribution)).map(([label, value]) => ({
      key: label,
      label,
      value: toNumber(value),
    })),
  }
}

export const buildOrderDetailViewModel = (detail = {}) => {
  const order = {
    ...(detail?.order || {}),
    internal_order_id: toText(detail?.order?.internal_order_id),
    request_id: toText(detail?.order?.request_id),
    broker_order_id: toText(detail?.order?.broker_order_id),
    symbol: toText(detail?.order?.symbol),
    name: toText(detail?.order?.name),
    side: toText(detail?.order?.side),
    state: toText(detail?.order?.state),
    trace_id: toText(detail?.order?.trace_id),
    intent_id: toText(detail?.order?.intent_id),
  }
  const request = {
    ...(detail?.request || {}),
    request_id: toText(detail?.request?.request_id),
    source: toText(detail?.request?.source),
    strategy_name: toText(detail?.request?.strategy_name),
    scope_type: toText(detail?.request?.scope_type),
    scope_ref_id: toText(detail?.request?.scope_ref_id),
    remark: toText(detail?.request?.remark),
    created_at: toText(detail?.request?.created_at),
  }
  const timelineRows = (Array.isArray(detail?.events) ? detail.events : []).map((row) => ({
    ...row,
    event_id: toText(row?.event_id),
    event_type: toText(row?.event_type),
    state: toText(row?.state),
    created_at: toText(row?.created_at),
  }))
  const tradeRows = (Array.isArray(detail?.trades) ? detail.trades : []).map((row) => ({
    ...row,
    trade_fact_id: toText(row?.trade_fact_id),
    trade_time_label: formatBeijingTimestamp(row?.trade_time),
  }))
  const identifiers = {
    ...(detail?.identifiers || {}),
    trace_id: toText(detail?.identifiers?.trace_id),
    intent_id: toText(detail?.identifiers?.intent_id),
    request_id: toText(detail?.identifiers?.request_id),
    internal_order_id: toText(detail?.identifiers?.internal_order_id),
    broker_order_id: toText(detail?.identifiers?.broker_order_id),
  }
  const identifierRows = Object.entries(identifiers)
    .map(([key, value]) => ({ key, value: toText(value) }))
    .filter((item) => item.value)
  return {
    ...detail,
    order,
    request,
    timelineRows,
    tradeRows,
    identifiers,
    identifierRows,
    headerTitle: `${order.symbol || '-'} · ${order.internal_order_id || '-'}`,
    requestSummary: [request.source, request.strategy_name].filter(Boolean).join(' · ') || '-',
    tradeSummary: `${tradeRows.length} 笔成交`,
  }
}

export const createOrderManagementActions = (api) => ({
  async loadOrders (filters = {}) {
    const response = await api.listOrders(filters)
    return {
      rows: buildOrderRows(readApiPayload(response, 'rows', [])),
      total: toNumber(readApiPayload(response, 'total', 0)),
      page: toNumber(readApiPayload(response, 'page', filters.page || 1), filters.page || 1),
      size: toNumber(readApiPayload(response, 'size', filters.size || 20), filters.size || 20),
    }
  },
  async loadOrderDetail (internalOrderId) {
    const response = await api.getOrderDetail(internalOrderId)
    return buildOrderDetailViewModel(response)
  },
  async loadStats (filters = {}) {
    const response = await api.getStats(filters)
    return buildOrderStats(response)
  },
})

export const formatOrderPrice = (value) => {
  const parsed = toFiniteNumber(value)
  if (parsed === null) return toText(value) || '-'
  return parsed.toFixed(3)
}

export const formatOrderQuantity = (value) => {
  const parsed = toFiniteNumber(value)
  if (parsed === null) return toText(value) || '-'
  return Number.isInteger(parsed) ? String(parsed) : String(parsed)
}

export const formatOrderTimestamp = (value) => {
  return formatBeijingTimestamp(value)
}
