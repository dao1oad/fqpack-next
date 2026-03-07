import http from '@/http'

export const SHOUBAN30_STOCK_WINDOW_OPTIONS = [30, 45, 60, 90]

export const normalizeShouban30Provider = (provider) => {
  return String(provider || '').trim() === 'jygs' ? 'jygs' : 'xgb'
}

export const normalizeShouban30StockWindowDays = (value, fallback = 30) => {
  const parsed = Number(value)
  if (SHOUBAN30_STOCK_WINDOW_OPTIONS.includes(parsed)) return parsed
  return fallback
}

const buildCommonParams = ({
  provider = 'xgb',
  stockWindowDays = 30,
  asOfDate
} = {}) => {
  const params = {
    provider: normalizeShouban30Provider(provider),
    stock_window_days: normalizeShouban30StockWindowDays(stockWindowDays)
  }
  if (String(asOfDate || '').trim()) {
    params.as_of_date = String(asOfDate).trim()
  }
  return params
}

export const getShouban30Plates = ({
  provider = 'xgb',
  stockWindowDays = 30,
  asOfDate
} = {}) => {
  return http({
    url: '/api/gantt/shouban30/plates',
    method: 'get',
    params: buildCommonParams({ provider, stockWindowDays, asOfDate })
  })
}

export const getShouban30Stocks = ({
  provider = 'xgb',
  plateKey,
  stockWindowDays = 30,
  asOfDate
} = {}) => {
  return http({
    url: '/api/gantt/shouban30/stocks',
    method: 'get',
    params: {
      ...buildCommonParams({ provider, stockWindowDays, asOfDate }),
      plate_key: String(plateKey || '').trim()
    }
  })
}
