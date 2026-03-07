import http from '@/http'

const normalizeProvider = (provider) => {
  return String(provider || '').trim() === 'jygs' ? 'jygs' : 'xgb'
}

const normalizeDays = (days, fallback = 30) => {
  const parsed = Number(days)
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return Math.min(90, Math.max(1, Math.floor(parsed)))
}

export const getGanttPlates = ({ provider = 'xgb', days = 30, endDate } = {}) => {
  const params = {
    provider: normalizeProvider(provider),
    days: normalizeDays(days)
  }
  if (endDate) params.end_date = endDate
  return http({
    url: '/api/gantt/plates',
    method: 'get',
    params
  })
}

export const getGanttStocks = ({
  provider = 'xgb',
  plateKey,
  days = 30,
  endDate
} = {}) => {
  const params = {
    provider: normalizeProvider(provider),
    plate_key: String(plateKey || '').trim(),
    days: normalizeDays(days)
  }
  if (endDate) params.end_date = endDate
  return http({
    url: '/api/gantt/stocks',
    method: 'get',
    params
  })
}
