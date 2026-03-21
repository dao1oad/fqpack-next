import http from '@/http'

const normalizeSymbol = (symbol) => String(symbol || '').trim()

export const subjectManagementApi = {
  getOverview () {
    return http({
      url: '/api/subject-management/overview',
      method: 'get',
    })
  },
  getDetail (symbol) {
    return http({
      url: `/api/subject-management/${normalizeSymbol(symbol)}`,
      method: 'get',
    })
  },
  saveMustPool (symbol, payload) {
    return http({
      url: `/api/subject-management/${normalizeSymbol(symbol)}/must-pool`,
      method: 'post',
      data: {
        ...payload,
        updated_by: 'web',
      },
    })
  },
  saveSymbolPositionLimit (symbol, payload) {
    return http({
      url: `/api/position-management/symbol-limits/${normalizeSymbol(symbol)}`,
      method: 'post',
      data: {
        ...payload,
        updated_by: 'web',
      },
    })
  },
  saveGuardianBuyGrid (symbol, payload) {
    return http({
      url: `/api/subject-management/${normalizeSymbol(symbol)}/guardian-buy-grid`,
      method: 'post',
      data: {
        ...payload,
        updated_by: 'web',
      },
    })
  },
  saveGuardianBuyGridState (symbol, payload) {
    return http({
      url: '/api/guardian_buy_grid_state',
      method: 'post',
      data: {
        code: normalizeSymbol(symbol),
        ...payload,
        updated_by: 'web',
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
}
