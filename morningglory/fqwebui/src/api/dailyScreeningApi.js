import axios from 'axios'

export const dailyScreeningApi = {
  getSchema () {
    return axios({
      url: '/api/daily-screening/schema',
      method: 'get',
    })
  },
  startRun (data) {
    return axios({
      url: '/api/daily-screening/runs',
      method: 'post',
      data,
    })
  },
  getRun (runId) {
    return axios({
      url: `/api/daily-screening/runs/${runId}`,
      method: 'get',
    })
  },
  getPrePools (params = {}) {
    return axios({
      url: '/api/daily-screening/pre-pools',
      method: 'get',
      params,
    })
  },
  addPrePoolToStockPool (data) {
    return axios({
      url: '/api/daily-screening/pre-pools/stock-pools',
      method: 'post',
      data,
    })
  },
  deletePrePool (data) {
    return axios({
      url: '/api/daily-screening/pre-pools/delete',
      method: 'post',
      data,
    })
  },
}

export const createDailyScreeningStream = (
  runId,
  { after = 0, once = false } = {},
) => {
  const params = new URLSearchParams()
  if (after) params.set('after', String(after))
  if (once) params.set('once', '1')
  const query = params.toString()
  const suffix = query ? `?${query}` : ''
  return new EventSource(`/api/daily-screening/runs/${runId}/stream${suffix}`)
}
