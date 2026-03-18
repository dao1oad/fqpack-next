import http from '@/http'

export const dailyScreeningApi = {
  getSchema () {
    return http({
      url: '/api/daily-screening/schema',
      method: 'get',
    })
  },
  startRun (data) {
    return http({
      url: '/api/daily-screening/runs',
      method: 'post',
      data,
    })
  },
  getRun (runId) {
    return http({
      url: `/api/daily-screening/runs/${runId}`,
      method: 'get',
    })
  },
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
  getScopeSummary (runId) {
    return http({
      url: `/api/daily-screening/scopes/${runId}/summary`,
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
  getStockDetail (runId, code) {
    return http({
      url: `/api/daily-screening/stocks/${code}/detail`,
      method: 'get',
      params: {
        run_id: runId,
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
