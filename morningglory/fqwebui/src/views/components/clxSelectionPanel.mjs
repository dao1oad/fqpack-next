const toText = (value) => String(value ?? '').trim()

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
