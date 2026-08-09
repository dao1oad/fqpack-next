const toText = (value) => String(value ?? '').trim()

export const OFFICIAL_RESULT_ENDPOINT = '/api/clx-daily-selection/official'

const loadHttp = async () => (await import('@/http')).default

export const normalizeOfficialResult = (payload = {}) => {
  const counts = payload.counts || {}
  return {
    status: toText(payload.status) || 'no_ready',
    tradeDate: toText(payload.trade_date || payload.tradeDate),
    batchId: toText(payload.batch_id || payload.batchId),
    generationId: toText(payload.generation_id || payload.generationId),
    publicationId: toText(payload.publication_id || payload.publicationId),
    contentHash: toText(payload.content_hash || payload.contentHash),
    resultTime: toText(payload.result_time || payload.resultTime),
    readyMarkerUpdatedAt: toText(
      payload.ready_marker_updated_at || payload.readyMarkerUpdatedAt,
    ),
    releaseStatus: toText(payload.release_status || payload.releaseStatus),
    isFinal: Boolean(payload.is_final ?? payload.isFinal),
    counts: {
      pureBuyTotal: Number(counts.pure_buy_total ?? counts.pureBuyTotal ?? 0),
      stock: Number(counts.stock ?? 0),
      etf: Number(counts.etf ?? 0),
    },
    rows: Array.isArray(payload.rows) ? payload.rows : [],
    total: Number(payload.total ?? 0),
    nextCursor: toText(payload.next_cursor ?? payload.nextCursor) || null,
  }
}

export const buildResultQuery = ({
  tradeDate = '',
  q = '',
  assetTypes = [],
  cursor = '',
  limit = 100,
} = {}) => {
  const params = {
    direction_mode: 'pure_buy',
    limit,
  }
  if (toText(tradeDate)) params.trade_date = toText(tradeDate)
  if (toText(q)) params.q = toText(q)
  if (Array.isArray(assetTypes) && assetTypes.length) {
    params.asset_types = assetTypes.join(',')
  }
  if (toText(cursor)) params.cursor = toText(cursor)
  return params
}

export const fetchOfficialResult = async ({
  tradeDate = '',
  q = '',
  assetTypes = [],
  cursor = '',
  limit = 100,
  fetcher = null,
} = {}) => {
  const doFetch = fetcher || (async (params) => {
    const http = await loadHttp()
    const response = await http({
      url: OFFICIAL_RESULT_ENDPOINT,
      method: 'get',
      params,
    })
    return response?.data ?? response ?? {}
  })
  const payload = await doFetch(
    buildResultQuery({ tradeDate, q, assetTypes, cursor, limit }),
  )
  return normalizeOfficialResult(payload)
}

export const buildTdxExportItems = (rows = []) =>
  rows
    .map((row) => {
      const symbol = toText(row.symbol || row.code)
      const assetType = toText(row.asset_type) || 'stock'
      if (!symbol) return null
      return { asset_type: assetType, symbol }
    })
    .filter(Boolean)

export const buildResultExportPayload = (result = {}) => {
  const batchId = toText(result.batchId)
  if (!batchId) return null
  return {
    batchId,
    items: buildTdxExportItems(result.rows),
  }
}

export const formatResultTime = (value) => {
  const text = toText(value)
  if (!text) return '—'
  return text
}
