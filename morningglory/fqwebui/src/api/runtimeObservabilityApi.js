import axios from 'axios'

export const runtimeObservabilityApi = {
  listComponents () {
    return axios({
      url: '/api/runtime/components',
      method: 'get'
    })
  },
  getHealthSummary (params = {}) {
    return axios({
      url: '/api/runtime/health/summary',
      method: 'get',
      params
    })
  },
  listTraces (params = {}) {
    return axios({
      url: '/api/runtime/traces',
      method: 'get',
      params
    })
  },
  getTraceDetail (traceId, params = {}) {
    return axios({
      url: `/api/runtime/traces/${traceId}`,
      method: 'get',
      params
    })
  },
  listTraceSteps (traceId, params = {}) {
    return axios({
      url: `/api/runtime/traces/${traceId}/steps`,
      method: 'get',
      params
    })
  },
  listEvents (params = {}) {
    return axios({
      url: '/api/runtime/events',
      method: 'get',
      params
    })
  },
  listRawFiles (params = {}) {
    return axios({
      url: '/api/runtime/raw-files/files',
      method: 'get',
      params
    })
  },
  tailRawFile (params = {}) {
    return axios({
      url: '/api/runtime/raw-files/tail',
      method: 'get',
      params
    })
  }
}
