import http from '@/http'

const toText = (value) => String(value || '').trim()

const toPositiveInt = (value, fallback) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return Math.floor(parsed)
}

const buildFilterParams = (params = {}, { includePagination = false } = {}) => {
  const payload = {
    symbol: toText(params.symbol),
    side: toText(params.side),
    state: toText(params.state),
    source: toText(params.source),
    strategy_name: toText(params.strategy_name),
    account_type: toText(params.account_type),
    internal_order_id: toText(params.internal_order_id),
    request_id: toText(params.request_id),
    broker_order_id: toText(params.broker_order_id),
    date_from: toText(params.date_from),
    date_to: toText(params.date_to),
    time_field: toText(params.time_field) || 'updated_at',
    missing_broker_only: Boolean(params.missing_broker_only),
  }
  if (includePagination) {
    payload.page = toPositiveInt(params.page, 1)
    payload.size = toPositiveInt(params.size, 20)
  }
  return payload
}

export const orderManagementApi = {
  listOrders (params = {}) {
    return http({
      url: '/api/order-management/orders',
      method: 'get',
      params: buildFilterParams(params, { includePagination: true }),
    })
  },
  getOrderDetail (internalOrderId) {
    return http({
      url: `/api/order-management/orders/${toText(internalOrderId)}`,
      method: 'get',
    })
  },
  getStats (params = {}) {
    return http({
      url: '/api/order-management/stats',
      method: 'get',
      params: buildFilterParams(params),
    })
  },
}
