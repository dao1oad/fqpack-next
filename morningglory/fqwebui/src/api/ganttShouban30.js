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

export const replaceShouban30PrePool = (payload = {}) => {
  return http({
    url: '/api/gantt/shouban30/pre-pool/replace',
    method: 'post',
    data: payload
  })
}

export const getShouban30PrePool = () => {
  return http({
    url: '/api/gantt/shouban30/pre-pool',
    method: 'get'
  })
}

export const addShouban30PrePoolToStockPool = ({ code6 } = {}) => {
  return http({
    url: '/api/gantt/shouban30/pre-pool/add-to-stock-pools',
    method: 'post',
    data: {
      code6: String(code6 || '').trim()
    }
  })
}

export const deleteShouban30PrePoolItem = ({ code6 } = {}) => {
  return http({
    url: '/api/gantt/shouban30/pre-pool/delete',
    method: 'post',
    data: {
      code6: String(code6 || '').trim()
    }
  })
}

export const getShouban30StockPool = () => {
  return http({
    url: '/api/gantt/shouban30/stock-pool',
    method: 'get'
  })
}

export const addShouban30StockPoolToMustPool = ({ code6 } = {}) => {
  return http({
    url: '/api/gantt/shouban30/stock-pool/add-to-must-pool',
    method: 'post',
    data: {
      code6: String(code6 || '').trim()
    }
  })
}

export const deleteShouban30StockPoolItem = ({ code6 } = {}) => {
  return http({
    url: '/api/gantt/shouban30/stock-pool/delete',
    method: 'post',
    data: {
      code6: String(code6 || '').trim()
    }
  })
}
