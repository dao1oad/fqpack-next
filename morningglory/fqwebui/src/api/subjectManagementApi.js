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
