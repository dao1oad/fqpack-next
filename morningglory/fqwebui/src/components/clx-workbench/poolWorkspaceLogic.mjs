const toText = (value) => String(value ?? '').trim()

export const SYNC_STOCK_ENDPOINT = '/api/pools/stock/sync-from-tdx'
export const SYNC_MUST_ENDPOINT = '/api/pools/must/sync-from-tdx'

export const PRE_POOL_SOURCE = 'clx_daily_selection'

const loadHttp = async () => (await import('@/http')).default

export const normalizePoolRows = (rows = [], poolKind = '') =>
  (Array.isArray(rows) ? rows : [])
    .map((row) => ({
      code: toText(row.code),
      name: toText(row.name || row.code),
      symbol: toText(row.symbol),
      assetType: toText(row.asset_type || row.extra?.asset_type || ''),
      syncedAt: toText(
        row.synced_at ||
          row.updated_at ||
          row.datetime ||
          (poolKind === 'pre' ? row.memberships?.[0]?.added_at : ''),
      ),
      stopLossPrice: row.stop_loss_price ?? null,
      lotAmount: row.lot_amount ?? null,
      initialLotAmount: row.initial_lot_amount ?? null,
    }))
    .filter((row) => row.code)

export const fetchPoolRows = async ({ poolKind = 'pre', page = 1 } = {}, fetcher = null) => {
  const doFetch =
    fetcher ||
    (async (url, params) => {
      const http = await loadHttp()
      const response = await http({ url, method: 'get', params })
      return response?.data ?? response ?? []
    })
  if (poolKind === 'pre') {
    const payload = await doFetch('/api/get_stock_pre_pools_list', { page, size: 1000 })
    const rows = Array.isArray(payload) ? payload : payload?.data ?? []
    return normalizePoolRows(rows, 'pre')
  }
  if (poolKind === 'stock') {
    const payload = await doFetch('/api/get_stock_pools_list', { page })
    const rows = Array.isArray(payload) ? payload : payload?.data ?? []
    return normalizePoolRows(rows, 'stock')
  }
  const payload = await doFetch('/api/get_stock_must_pools_list', { page, size: 1000 })
  const rows = Array.isArray(payload) ? payload : payload?.data ?? []
  return normalizePoolRows(rows, 'must')
}

export const syncPoolFromTdx = async ({ poolKind = 'stock' } = {}, fetcher = null) => {
  const doFetch =
    fetcher ||
    (async (url, params) => {
      const http = await loadHttp()
      const response = await http({ url, method: 'post', params })
      return response?.data ?? response ?? {}
    })
  const url = poolKind === 'stock' ? SYNC_STOCK_ENDPOINT : SYNC_MUST_ENDPOINT
  const payload = await doFetch(url, { days: 30 })
  return normalizeSyncResult(payload, poolKind)
}

export const normalizeSyncResult = (payload = {}, poolKind = '') => {
  const data = payload?.data ?? payload ?? {}
  return {
    code: toText(payload.code ?? data.code ?? ''),
    msg: toText(payload.msg ?? data.msg ?? ''),
    sourceCount: Number(data.source_count ?? data.read_count ?? 0),
    syncedCount: Number(data.synced_count ?? 0),
    removedCount: Number(data.removed_count ?? 0),
    holdingExcludedCount: Number(
      data.holding_excluded_count ?? data.skipped_holding_count ?? 0,
    ),
    invalidCount: Number(data.invalid_count ?? data.skipped_invalid_count ?? 0),
    failedCount: Number(data.failed_count ?? 0),
    failedCodes: Array.isArray(data.failed_codes) ? data.failed_codes : [],
    filePath: toText(data.file_path),
    syncedCodes: Array.isArray(data.synced_codes) ? data.synced_codes : [],
    removedCodes: Array.isArray(data.removed_codes) ? data.removed_codes : [],
    holdingExcludedCodes: Array.isArray(data.holding_excluded_codes)
      ? data.holding_excluded_codes
      : [],
    invalidCodes: Array.isArray(data.invalid_codes) ? data.invalid_codes : [],
    poolKind,
  }
}

export const buildSyncSummaryText = (result = {}) => {
  const parts = [
    `源 ${result.sourceCount} 个代码`,
    `同步 ${result.syncedCount}`,
    `删除 ${result.removedCount}`,
    `持仓排除 ${result.holdingExcludedCount}`,
    `无效 ${result.invalidCount}`,
  ]
  if (result.failedCount > 0) {
    parts.push(
      `失败 ${result.failedCount}: ${result.failedCodes
        .map((item) => `${toText(item.code)}(${toText(item.reason)})`)
        .join('、')}`,
    )
  }
  return parts.join('；')
}

export const buildSyncConfirmMessage = (poolKind = 'stock') =>
  poolKind === 'stock'
    ? '将使用通达信“自选股”覆盖当前监控池，并自动排除持仓股。是否继续？'
    : '将使用通达信“待买组”覆盖当前待买池，并自动排除持仓股；新代码自动使用系统默认参数。是否继续？'
