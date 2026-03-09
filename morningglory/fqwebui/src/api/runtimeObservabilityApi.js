import axios from 'axios'

export const runtimeObservabilityApi = {
  listComponents () {
    return axios({
      url: '/api/runtime/components',
      method: 'get'
    })
  },
  getHealthSummary () {
    return axios({
      url: '/api/runtime/health/summary',
      method: 'get'
    })
  },
  listTraces (params = {}) {
    return axios({
      url: '/api/runtime/traces',
      method: 'get',
      params
    })
  },
  getTraceDetail (traceId) {
    return axios({
      url: `/api/runtime/traces/${traceId}`,
      method: 'get'
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
