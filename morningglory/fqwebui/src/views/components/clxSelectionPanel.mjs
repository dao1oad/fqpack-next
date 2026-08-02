const toText = (value) => String(value ?? '').trim()

const toArray = (value) => Array.isArray(value) ? [...value] : []

const stableValue = (value) => {
  if (Array.isArray(value)) return value.map(stableValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, stableValue(value[key])]),
  )
}

const symbolIdentity = (value) => {
  const symbol = toText(value).toLowerCase()
  const code = symbol.replace(/\D/g, '').slice(-6)
  const exchange = symbol.match(/^(sh|sz|bj)/)?.[1] || ''
  return { symbol, code, exchange }
}

export const isSameClxPanelSymbol = (left, right) => {
  const leftIdentity = symbolIdentity(left)
  const rightIdentity = symbolIdentity(right)
  if (!leftIdentity.code || !rightIdentity.code || leftIdentity.code !== rightIdentity.code) return false
  return !leftIdentity.exchange ||
    !rightIdentity.exchange ||
    leftIdentity.exchange === rightIdentity.exchange
}

export const buildClxPanelRequestKey = ({ phase = 'results', scopeId = '', payload = {} } = {}) => {
  return JSON.stringify(stableValue({
    phase: toText(phase),
    scopeId: toText(scopeId),
    payload: payload && typeof payload === 'object' ? payload : {},
  }))
}

export const applyClxPanelScopeDate = (query = {}, { tradeDate = '', force = false } = {}) => {
  const next = { ...(query || {}) }
  const normalizedTradeDate = toText(tradeDate)
  if (normalizedTradeDate && (force || !toText(next.endDate))) {
    next.endDate = normalizedTradeDate
  }
  return next
}

export const resolveClxPanelRouteEntry = (routeState = {}, routeQuery = {}) => {
  const shouldBootstrap = routeState?.screeningOpen === true && !toText(routeState?.scopeId)
  return {
    shouldBootstrap,
    resetAutoSelection: shouldBootstrap && !toText(routeQuery?.symbol),
  }
}

export const appendClxPanelRows = (currentRows = [], incomingRows = []) => {
  const merged = []
  const seenExact = new Set()
  const seenBare = new Set()
  const seenCode = new Set()
  ;[...(Array.isArray(currentRows) ? currentRows : []), ...(Array.isArray(incomingRows) ? incomingRows : [])]
    .forEach((row) => {
      const identity = symbolIdentity(row?.symbol || row?.code)
      const assetType = toText(row?.assetType).toLowerCase()
      const value = identity.code || identity.symbol
      const exactKey = `${assetType}|${identity.exchange}|${value}`
      const bareKey = `${assetType}|${value}`
      if (!identity.code && !identity.symbol) return
      if (identity.exchange) {
        if (seenExact.has(exactKey) || seenBare.has(bareKey)) return
        seenExact.add(exactKey)
        seenCode.add(bareKey)
      } else {
        if (seenCode.has(bareKey)) return
        seenBare.add(bareKey)
        seenCode.add(bareKey)
      }
      merged.push(row)
    })
  return merged
}

export const resolveClxPanelAutoSelection = ({
  rows = [],
  append = false,
  activeSymbol = '',
  requestKey = '',
  currentRequestKey = '',
  selectedRequestKey = '',
} = {}) => {
  if (
    append ||
    toText(activeSymbol) ||
    !toText(requestKey) ||
    requestKey !== currentRequestKey ||
    requestKey === selectedRequestKey
  ) return null
  return Array.isArray(rows) ? rows[0] || null : null
}

const normalizeClxTdxBasketItem = (value = {}) => {
  const assetType = toText(value?.asset_type || value?.assetType).toLowerCase()
  const symbol = toText(value?.symbol)
  if (!['stock', 'etf'].includes(assetType) || !symbol) return null
  return { asset_type: assetType, symbol }
}

export const buildClxTdxBasketKey = (value = {}) => {
  const item = normalizeClxTdxBasketItem(value)
  return item ? `${item.asset_type}:${item.symbol.toLowerCase()}` : ''
}

export const mergeClxTdxBasketItems = (currentItems = [], incomingItems = []) => {
  const byKey = new Map()
  ;[...toArray(currentItems), ...toArray(incomingItems)].forEach((value) => {
    const item = normalizeClxTdxBasketItem(value)
    const key = buildClxTdxBasketKey(item)
    if (key && !byKey.has(key)) byKey.set(key, item)
  })
  return [...byKey.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([, item]) => item)
}

export const toggleClxTdxBasketItem = (items = [], value = {}) => {
  const item = normalizeClxTdxBasketItem(value)
  const key = buildClxTdxBasketKey(item)
  if (!key) return mergeClxTdxBasketItems(items)
  const normalized = mergeClxTdxBasketItems(items)
  if (normalized.some((candidate) => buildClxTdxBasketKey(candidate) === key)) {
    return normalized.filter((candidate) => buildClxTdxBasketKey(candidate) !== key)
  }
  return mergeClxTdxBasketItems(normalized, [item])
}

const buildClxTdxBasketStorageKey = (batchId) => (
  `freshquant:clx-tdx-basket:v1:${toText(batchId)}`
)

export const readClxTdxBasket = (storage, batchId) => {
  if (!storage || !toText(batchId)) return []
  try {
    const raw = storage.getItem(buildClxTdxBasketStorageKey(batchId))
    return mergeClxTdxBasketItems([], raw ? JSON.parse(raw) : [])
  } catch {
    return []
  }
}

export const writeClxTdxBasket = (storage, batchId, items = []) => {
  if (!storage || !toText(batchId)) return false
  try {
    const normalized = mergeClxTdxBasketItems([], items)
    const key = buildClxTdxBasketStorageKey(batchId)
    if (normalized.length) storage.setItem(key, JSON.stringify(normalized))
    else storage.removeItem(key)
    return true
  } catch {
    return false
  }
}

export const freezeClxTdxSelectionPayload = (payload = {}) => ({
  scope_id: toText(payload?.scope_id),
  q: toText(payload?.q),
  asset_types: toArray(payload?.asset_types),
  model_keys: toArray(payload?.model_keys),
  condition_keys: toArray(payload?.condition_keys),
  directions: toArray(payload?.directions),
  min_model_count: Math.max(1, Number(payload?.min_model_count) || 1),
  line_flags: payload?.line_flags && typeof payload.line_flags === 'object'
    ? { ...payload.line_flags }
    : {},
  sort: toText(payload?.sort),
  cursor: '',
  limit: 200,
})

export const buildClxTdxSelectionPagePayload = (frozenPayload = {}, cursor = '') => ({
  ...freezeClxTdxSelectionPayload(frozenPayload),
  cursor: toText(cursor),
})

export const assertClxTdxSelectionProgress = ({
  expectedTotal,
  responseTotal,
  selectedCount,
  nextCursor = '',
} = {}) => {
  const expected = Number(expectedTotal)
  const response = Number(responseTotal)
  const selected = Number(selectedCount)
  const next = toText(nextCursor)

  if (!Number.isInteger(expected) || expected <= 0) {
    throw new Error('全选结果总数无效，待导入篮子保持不变')
  }
  if (!Number.isInteger(response) || response !== expected) {
    throw new Error('全选结果总数在分页期间发生变化，待导入篮子保持不变')
  }
  if (!Number.isInteger(selected) || selected < 0 || selected > expected) {
    throw new Error('全选结果数量异常，待导入篮子保持不变')
  }
  if (!next && selected !== expected) {
    throw new Error('全选结果分页提前结束，待导入篮子保持不变')
  }
  if (next && selected >= expected) {
    throw new Error('全选结果分页游标异常，待导入篮子保持不变')
  }
  return true
}

export const buildClxTdxSelectedPayload = (items = []) => ({
  items: mergeClxTdxBasketItems([], items),
})

export const isClxTdxBasketEligible = (scope = null) => Boolean(
  scope?.isFinal === true &&
  scope?.releaseStatus === 'final' &&
  scope?.publicationLifecycleStatus === 'published' &&
  scope?.partitions?.stock?.isComplete === true &&
  scope?.partitions?.etf?.isComplete === true
)

const isActionLoading = (loading, keys) => keys.some((key) => loading?.[key] === true)

export const isClxTdxSelectAllEnabled = ({
  scope = null,
  hasLoaded = false,
  total = 0,
  loading = {},
  pageError = '',
} = {}) => Boolean(
  isClxTdxBasketEligible(scope) &&
  hasLoaded &&
  Number(total) > 0 &&
  !toText(pageError) &&
  !isActionLoading(loading, ['bootstrap', 'results', 'more', 'selectAll', 'importToTdx'])
)

export const isClxTdxImportEnabled = ({
  scope = null,
  basketCount = 0,
  loading = {},
} = {}) => Boolean(
  isClxTdxBasketEligible(scope) &&
  Number(basketCount) > 0 &&
  !isActionLoading(loading, ['bootstrap', 'selectAll', 'importToTdx'])
)

export const formatClxTdxImportSuccessMessage = (writtenCount) => (
  `已导入通达信分组 clx_18，共 ${Math.max(0, Number(writtenCount) || 0)} 只（已覆盖原分组）`
)

export const formatClxTdxImportErrorMessage = (message) => {
  const text = toText(message) || '导入通达信失败'
  return text.includes('旧分组已保留') ? text : `${text}；旧分组已保留`
}
