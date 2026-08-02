import { sortHoldingItemsByAmountDesc } from './kline-slim-sidebar.mjs'

export function shouldResolveDefaultSymbol(query) {
  const hasSymbol = Boolean(String(query?.symbol || '').trim())
  const opensClxWorkspace = ['1', 'true', 'open'].includes(
    String(query?.clxScreening || query?.clxWorkbench || '').trim().toLowerCase()
  )
  return !hasSymbol && !opensClxWorkspace
}

export function pickFirstHoldingSymbol(positions) {
  if (!Array.isArray(positions)) {
    return ''
  }
  const first = sortHoldingItemsByAmountDesc(positions).find((item) => String(item?.symbol || '').trim())
  return String(first?.symbol || '').trim()
}

export function buildResolvedKlineSlimQuery({ currentQuery, symbol, period }) {
  return {
    ...(currentQuery || {}),
    symbol,
    period
  }
}

export function canApplyResolvedKlineSlimRoute({
  token,
  routeToken,
  routePath
}) {
  return token === routeToken && routePath === '/kline-slim'
}

export function getKlineSlimEmptyMessage({
  resolvingDefaultSymbol,
  resolveError,
  clxScreening = false
}) {
  if (resolveError) {
    return resolveError
  }
  if (resolvingDefaultSymbol) {
    return '正在读取持仓，准备默认标的...'
  }
  return clxScreening
    ? '请从左侧 CLX 筛选结果选择标的'
    : '请在顶部输入代码，或从左侧持仓股/股票池选择标的'
}
