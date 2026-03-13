import http from '@/http'

const normalizeSymbol = (symbol) => String(symbol || '').trim()

const normalizeLimit = (value, fallback = 20) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return Math.floor(parsed)
}

export const tpslApi = {
  getManagementOverview () {
    return http({
      url: '/api/tpsl/management/overview',
      method: 'get',
    })
  },
  getManagementDetail (symbol, { historyLimit = 20 } = {}) {
    return http({
      url: `/api/tpsl/management/${normalizeSymbol(symbol)}`,
      method: 'get',
      params: {
        history_limit: normalizeLimit(historyLimit, 20),
      },
    })
  },
  saveTakeprofitProfile (symbol, payload) {
    return http({
      url: `/api/tpsl/takeprofit/${normalizeSymbol(symbol)}`,
      method: 'post',
      data: {
        ...payload,
        updated_by: 'web',
      },
    })
  },
  setTakeprofitTierEnabled (symbol, level, enabled) {
    return http({
      url: `/api/tpsl/takeprofit/${normalizeSymbol(symbol)}/tiers/${Number(level)}/${enabled ? 'enable' : 'disable'}`,
      method: 'post',
      data: {
        updated_by: 'web',
      },
    })
  },
  rearmTakeprofit (symbol) {
    return http({
      url: `/api/tpsl/takeprofit/${normalizeSymbol(symbol)}/rearm`,
      method: 'post',
      data: {
        updated_by: 'web',
      },
    })
  },
  bindStoploss (payload) {
    return http({
      url: '/api/order-management/stoploss/bind',
      method: 'post',
      data: {
        ...payload,
        updated_by: 'web',
      },
    })
  },
  listHistory ({ symbol, kind, buy_lot_id, batch_id, limit = 20 } = {}) {
    return http({
      url: '/api/tpsl/history',
      method: 'get',
      params: {
        symbol: normalizeSymbol(symbol),
        kind: String(kind || '').trim(),
        buy_lot_id: String(buy_lot_id || '').trim(),
        batch_id: String(batch_id || '').trim(),
        limit: normalizeLimit(limit, 20),
      },
    })
  },
}
