import http from '@/http'

export const runtimeObservabilityApi = {
  listComponents () {
    return http({
      url: '/api/runtime/components',
      method: 'get'
    })
  },
  getHealthSummary (params = {}) {
    return http({
      url: '/api/runtime/health/summary',
      method: 'get',
      params
    })
  },
  listTraces (params = {}) {
    return http({
      url: '/api/runtime/traces',
      method: 'get',
      params
    })
  },
  getTraceDetail (traceId, params = {}) {
    return http({
      url: `/api/runtime/traces/${traceId}`,
      method: 'get',
      params
    })
  },
  listTraceSteps (traceId, params = {}) {
    return http({
      url: `/api/runtime/traces/${traceId}/steps`,
      method: 'get',
      params
    })
  },
  listEvents (params = {}) {
    return http({
      url: '/api/runtime/events',
      method: 'get',
      params
    })
  },
  listRawFiles (params = {}) {
    return http({
      url: '/api/runtime/raw-files/files',
      method: 'get',
      params
    })
  },
  tailRawFile (params = {}) {
    return http({
      url: '/api/runtime/raw-files/tail',
      method: 'get',
      params
    })
  }
}
