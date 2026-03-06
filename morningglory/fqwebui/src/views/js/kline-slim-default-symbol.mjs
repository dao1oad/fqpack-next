export function shouldResolveDefaultSymbol(query) {
  return !String(query?.symbol || '').trim()
}

export function pickFirstHoldingSymbol(positions) {
  if (!Array.isArray(positions)) {
    return ''
  }
  const first = positions.find((item) => String(item?.symbol || '').trim())
  return String(first?.symbol || '').trim()
}

export function buildResolvedKlineSlimQuery({ currentQuery, symbol, period }) {
  return {
    ...(currentQuery || {}),
    symbol,
    period
  }
}

export function getKlineSlimEmptyMessage({
  resolvingDefaultSymbol,
  resolveError
}) {
  if (resolveError) {
    return resolveError
  }
  if (resolvingDefaultSymbol) {
    return '正在读取持仓，准备默认标的...'
  }
  return '请输入或通过 query 传入 `symbol`，例如 `/kline-slim?symbol=sh510050`'
}
