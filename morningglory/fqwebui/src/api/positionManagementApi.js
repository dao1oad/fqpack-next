import http from '@/http'

export const positionManagementApi = {
  getDashboard () {
    return http({
      url: '/api/position-management/dashboard',
      method: 'get'
    })
  },
  getReconciliation () {
    return http({
      url: '/api/position-management/reconciliation',
      method: 'get'
    })
  },
  getConfig () {
    return http({
      url: '/api/position-management/config',
      method: 'get'
    })
  },
  updateConfig (data) {
    return http({
      url: '/api/position-management/config',
      method: 'post',
      data
    })
  },
  updateSymbolLimit (symbol, data) {
    return http({
      url: `/api/position-management/symbol-limits/${String(symbol || '').trim()}`,
      method: 'post',
      data
    })
  }
}
