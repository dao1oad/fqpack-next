import http from '@/http'

export const dailyScreeningApi = {
  getScopes () {
    return http({
      url: '/api/daily-screening/scopes',
      method: 'get',
    })
  },
  getLatestScope () {
    return http({
      url: '/api/daily-screening/scopes/latest',
      method: 'get',
    })
  },
  getFilters (scopeId) {
    return http({
      url: '/api/daily-screening/filters',
      method: 'get',
      params: {
        scope_id: scopeId,
      },
    })
  },
  getScopeSummary (scopeId) {
    return http({
      url: `/api/daily-screening/scopes/${scopeId}/summary`,
      method: 'get',
    })
  },
  queryStocks (data) {
    return http({
      url: '/api/daily-screening/query',
      method: 'post',
      data,
    })
  },
  getStockDetail (scopeId, code) {
    return http({
      url: `/api/daily-screening/stocks/${code}/detail`,
      method: 'get',
      params: {
        scope_id: scopeId,
      },
    })
  },
  addToPrePool (data) {
    return http({
      url: '/api/daily-screening/actions/add-to-pre-pool',
      method: 'post',
      data,
    })
  },
  addBatchToPrePool (data) {
    return http({
      url: '/api/daily-screening/actions/add-batch-to-pre-pool',
      method: 'post',
      data,
    })
  },
}
