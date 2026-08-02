import http from '@/http'

const encodePath = (value) => encodeURIComponent(String(value ?? '').trim())

export const clxDailySelectionApi = {
  getModelCatalog (config = {}) {
    return http({
      url: '/api/clx-daily-selection/model-catalog',
      method: 'get',
      ...config,
    })
  },
  getBatches ({ limit = 30, includePartial = true } = {}, config = {}) {
    return http({
      url: '/api/clx-daily-selection/batches',
      method: 'get',
      params: {
        limit,
        include_partial: includePartial ? 1 : 0,
      },
      ...config,
    })
  },
  getLatestBatch ({ includePartial = false } = {}, config = {}) {
    return http({
      url: '/api/clx-daily-selection/batches/latest',
      method: 'get',
      params: includePartial ? { include_partial: 1 } : {},
      ...config,
    })
  },
  getBatchSummary (batchId, config = {}) {
    return http({
      url: `/api/clx-daily-selection/batches/${encodePath(batchId)}/summary`,
      method: 'get',
      ...config,
    })
  },
  queryBatchResults (batchId, data, config = {}) {
    return http({
      url: `/api/clx-daily-selection/batches/${encodePath(batchId)}/results`,
      method: 'post',
      data,
      ...config,
    })
  },
  syncSelectedBatchResultsToTdx (batchId, data, config = {}) {
    return http({
      url: `/api/clx-daily-selection/batches/${encodePath(batchId)}/results/sync-selected-to-tdx`,
      method: 'post',
      data,
      ...config,
    })
  },
  getBatchResultDetail (batchId, assetType, symbol, config = {}) {
    return http({
      url: `/api/clx-daily-selection/batches/${encodePath(batchId)}/results/${encodePath(assetType)}/${encodePath(symbol)}`,
      method: 'get',
      ...config,
    })
  },
  getBatchStatistics (batchId, config = {}) {
    return http({
      url: `/api/clx-daily-selection/batches/${encodePath(batchId)}/statistics`,
      method: 'get',
      ...config,
    })
  },
  getSignalHistory ({
    symbol,
    assetType = 'stock',
    period = '1d',
    endDate = '',
    barCount = 250,
    modelKeys = [],
    conditionKeys = [],
    includeRaw = true,
  } = {}, config = {}) {
    return http({
      url: '/api/clx-daily-selection/history/signals',
      method: 'get',
      params: {
        symbol,
        assetType,
        period,
        endDate: endDate || undefined,
        barCount,
        modelKeys: Array.isArray(modelKeys) ? modelKeys.join(',') : modelKeys,
        conditionKeys: Array.isArray(conditionKeys) ? conditionKeys.join(',') : conditionKeys,
        includeRaw: includeRaw ? 1 : 0,
      },
      ...config,
    })
  },
}
