import http from '@/http'

export const opsApi = {
  fetchOpsOverview (params = {}) {
    return http({
      url: '/api/ops/overview',
      method: 'get',
      params
    })
  },
  fetchKlineHealth (params = {}) {
    return http({
      url: '/api/ops/kline-health',
      method: 'get',
      params
    })
  }
}

export default opsApi
