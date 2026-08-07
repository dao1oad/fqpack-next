import http from '@/http'

const toText = (value) => String(value ?? '').trim()

const compactParams = (params = {}) => Object.fromEntries(
  Object.entries(params).filter(([, value]) => (
    value !== '' && value !== null && value !== undefined
  )),
)

export const positionReviewApi = {
  getSummary (params = {}) {
    return http({
      url: '/api/position-review/summary',
      method: 'get',
      params: compactParams(params),
    })
  },

  listSymbols (params = {}) {
    return http({
      url: '/api/position-review/symbols',
      method: 'get',
      params: compactParams(params),
    })
  },

  getSymbolReview (symbol, params = {}) {
    return http({
      url: `/api/position-review/symbols/${encodeURIComponent(toText(symbol))}`,
      method: 'get',
      params: compactParams(params),
    })
  },

  getSymbolTimeline (symbol, params = {}) {
    return http({
      url: `/api/position-review/symbols/${encodeURIComponent(toText(symbol))}/timeline`,
      method: 'get',
      params: compactParams(params),
    })
  },

  getSymbolChart (symbol, params = {}) {
    return http({
      url: `/api/position-review/symbols/${encodeURIComponent(toText(symbol))}/chart`,
      method: 'get',
      params: compactParams(params),
    })
  },

  getEventConditions (eventId, params = {}) {
    return http({
      url: `/api/position-review/events/${encodeURIComponent(toText(eventId))}/conditions`,
      method: 'get',
      params: compactParams(params),
    })
  },

  getPortfolioSummary (params = {}) {
    return http({
      url: '/api/position-review/portfolio/summary',
      method: 'get',
      params: compactParams(params),
    })
  },

  getPortfolioSeries (params = {}) {
    return http({
      url: '/api/position-review/portfolio/series',
      method: 'get',
      params: compactParams(params),
    })
  },

  getPortfolioContributions (params = {}) {
    return http({
      url: '/api/position-review/portfolio/contributions',
      method: 'get',
      params: compactParams(params),
    })
  },
}
